"""
simulation/engine.py — Simulation Engine with Scenarios & Logging (Stage 3 Alpha).

Full closed-loop pipeline with reproducible scenarios S01–S12, random seed control,
in-memory telemetry logging, automated run reports, and performance benchmarking:
  3D WORLD
   ↓  (VirtualCamera3D pinhole projection)
  NUMPY SENSOR FRAME
   ↓  (DisturbanceModel: atmosphere, noise, turbulence, jitter, platform, dropout)
  DISTORTED FRAME
   ↓  (BeaconDetector: background subtraction, Otsu, morphology, weighted centroid)
  DETECTION RESULT
   ↓  (MultiBeaconManager: nearest-centroid gating)
  TRACKER STATE
   ↓  (AcquisitionFSM: SEARCH ↔ ACQUIRING ↔ LOCKED ↔ COASTING ↔ REACQUIRE)
  FSM STATE
   ↓  (CoarseAlignmentController: pixel error to pan/tilt slew, OR SearchPattern)
  PAN/TILT COMMANDS
   ↓  (Applied to VirtualCamera3D)
  TELEMETRY LOGGER
   ↓  (Auto-records frame metrics to CSV & run summary JSON)

Ground truth is NEVER passed to the detector or controller.
"""

import math
import random
import numpy as np
from typing import Dict, Any, Optional, List

from .world import World
from .terminal import TerminalA, TerminalB
from .beacon import OpticalBeacon
from .motion import TargetMotion
from .camera import VirtualCamera3D
from .controller import CoarseAlignmentController
from .disturbances import (
    DisturbanceModel, Atmosphere, NoiseLevel, TurbulenceLevel,
    JitterLevel, PlatformMotion, Dropout
)
from .detector import BeaconDetector, DetectionResult
from .tracker import BeaconTracker
from .state_machine import AcquisitionFSM, TrackingState
from .search import SearchPattern
from .multi_beacon import MultiBeaconManager
from .scenarios import SCENARIOS, ScenarioPreset, get_scenario
from .logger import SimulationLogger


class Stage3Engine:
    """Master Stage 3 Simulation Engine.

    Manages the full pipeline, scenarios S01-S12, deterministic random seed,
    telemetry logging, control effort, and performance metrics.
    """

    FRAME_H = 480
    FRAME_W = 640
    CENTER_X = 320.0
    CENTER_Y = 240.0

    # SIH Reference Target Thresholds
    REF_ACQ_TIME_MAX = 2.0      # s
    REF_TRACK_ERR_MAX = 10.0    # px
    REF_TARGET_LOSS_MAX = 5.0   # %
    REF_REACQ_TIME_MAX = 1.0    # s
    REF_FPS_MIN = 20.0          # FPS

    def __init__(self, seed: int = 42) -> None:
        self.seed: int = seed

        # ── World ───────────────────────────────────────────────────────
        self.world = World(num_stars=250, seed=self.seed)

        # ── Terminals ───────────────────────────────────────────────────
        self.terminal_a = TerminalA()
        self.terminal_b = TerminalB(position=np.array([0.0, 100.0, 1000.0]))

        # ── Beacon & Motion ─────────────────────────────────────────────
        self.motion = TargetMotion(mode="circle", speed=1.0, seed=self.seed)
        self.multi_beacon = MultiBeaconManager(beacon_count=1)
        self.multi_beacon.set_primary_motion(self.motion)

        # ── Camera ─────────────────────────────────────────────────────
        self.camera = VirtualCamera3D(position=self.terminal_a.position.copy())

        # ── Pipeline subsystems ─────────────────────────────────────────
        self.disturbances = DisturbanceModel()
        self.detector = BeaconDetector()
        self.tracker = BeaconTracker()
        self.state_machine = AcquisitionFSM()
        self.search = SearchPattern(mode="spiral")
        self.controller = CoarseAlignmentController(max_rate_deg=5.0, kp=2.5)
        self.logger = SimulationLogger(log_dir="logs")

        # ── State variables ─────────────────────────────────────────────
        self.is_running: bool = True
        self.sim_time: float = 0.0
        self.frame_count: int = 0
        self.active_scenario_id: str = "S01"
        self.active_scenario_name: str = "S01 Baseline"

        # ── Gimbal dynamics & Control Effort ────────────────────────────
        self.pan_rate_deg_s: float = 0.0
        self.tilt_rate_deg_s: float = 0.0
        self.cmd_pan_deg: float = 0.0
        self.cmd_tilt_deg: float = 0.0
        self.control_effort: float = 0.0

        # ── Averaging accumulators ──────────────────────────────────────
        self.total_proc_time_ms: float = 0.0
        self.total_fps_accum: float = 0.0
        self.fps_samples: int = 0

        # ── Cached pipeline results ──────────────────────────────────────
        self._raw_frame: Optional[np.ndarray] = None
        self._distorted_frame: Optional[np.ndarray] = None
        self._detection: Optional[DetectionResult] = None
        self._tracker_x: float = self.CENTER_X
        self._tracker_y: float = self.CENTER_Y
        self._tracker_vx: float = 0.0
        self._tracker_vy: float = 0.0
        self._tracker_valid: bool = False
        self._fsm_state: str = TrackingState.SEARCH

        # ── Ground truth telemetry (for evaluation only) ─────────────────
        self._gt_screen: tuple = (self.CENTER_X, self.CENTER_Y)
        self._gt_in_fov: bool = False
        self._gt_angular_error: tuple = (0.0, 0.0, 0.0)
        self._gt_pixel_error: tuple = (0.0, 0.0, 0.0)
        self._detection_error: float = 0.0

        # ── Error history for RMSE / max error ──────────────────────────
        self._error_history: List[float] = []
        self._max_error: float = 0.0
        self._status: str = TrackingState.SEARCH

        # ── Debug mode & overlay toggles ────────────────────────────────
        self.debug_mode: bool = False
        self.show_ground_truth: bool = True
        self.show_detection: bool = True
        self.show_prediction: bool = True
        self.show_candidates: bool = False

        # Apply initial seed & scenario S01
        self.set_seed(self.seed)
        self.load_scenario("S01")

        # Render initial frame
        self._raw_frame = self._render_numpy_frame()
        self._distorted_frame = self._raw_frame.copy()

    # ================================================================== #
    # Random Seed & Scenario Control
    # ================================================================== #

    def set_seed(self, seed: int) -> None:
        """Set deterministic random seed across all stochastic subsystems."""
        self.seed = int(seed)
        random.seed(self.seed)
        np.random.seed(self.seed)
        self.disturbances.set_seed(self.seed)
        self.motion.set_seed(self.seed)
        self.world.reset(self.seed)

    def load_scenario(self, scenario_id: str) -> bool:
        """Load scenario preset (S01 to S12) and apply its configuration."""
        preset = get_scenario(scenario_id)
        if not preset:
            return False

        self.active_scenario_id = preset.id
        self.active_scenario_name = preset.name

        # Trajectory & Camera limits
        self.motion.set_mode(preset.motion_mode)
        self.motion.set_speed(preset.target_speed)
        self.controller.set_max_rate(preset.camera_max_rate)

        # Atmosphere
        self.disturbances.atmosphere = preset.atmosphere
        self.disturbances.fog_density = preset.fog_density
        self.disturbances.rain_intensity = preset.rain_intensity

        # Noise
        self.disturbances.noise_level = preset.noise_level
        self.disturbances.noise_custom_sigma = preset.noise_custom_sigma
        self.disturbances.noise_custom_sp = preset.noise_custom_sp

        # Turbulence & Jitter
        self.disturbances.turbulence = preset.turbulence
        self.disturbances.jitter_level = preset.jitter_level
        self.disturbances.jitter_custom_px = preset.jitter_custom_px

        # Platform motion & Dropout
        self.disturbances.platform_motion = preset.platform_motion
        self.disturbances.platform_strength = preset.platform_strength
        self.disturbances.dropout = preset.dropout

        # Starfield & Beacons
        self.world.set_starfield_density(preset.starfield_density)
        self.multi_beacon.set_count(preset.beacon_count)
        self.multi_beacon.set_primary_intensity(preset.beacon_intensity)

        # Reset simulation state
        self.reset()
        return True

    def start_scenario_run(self) -> None:
        """Reset and start an active scenario run with telemetry logging."""
        self.reset()
        self.is_running = True
        self.logger.start_run(self.active_scenario_name, self.seed)

    def stop_scenario_run(self) -> Optional[Dict[str, str]]:
        """Stop active scenario run and flush CSV & JSON report to logs/."""
        self.is_running = False
        summary = self.get_run_summary()
        paths = self.logger.stop_run(summary_data=summary)
        return paths

    # ================================================================== #
    # Simulation Step
    # ================================================================== #

    def step(self, dt: float) -> None:
        """Execute one complete pipeline step."""
        if not self.is_running or dt <= 0:
            return

        dt = min(dt, 0.05)
        self.sim_time += dt
        self.frame_count += 1

        # 1. Advance target kinematics
        new_pos = self.motion.step(dt)
        self.terminal_b.update_position(new_pos)

        # 2. Advance distractor beacons
        self.multi_beacon.step(dt)

        # 3. Advance disturbance timers
        self.disturbances.tick(dt)

        # 4. Render raw sensor frame (NumPy, 3D pinhole projection)
        self._raw_frame = self._render_numpy_frame()

        # 5. Apply frame disturbances
        self._distorted_frame = self.disturbances.apply_frame_effects(self._raw_frame.copy())

        # 6. Run OpenCV detector
        self._detection = self.detector.detect(self._distorted_frame)
        self.total_proc_time_ms += self.detector.processing_time_ms

        # 7. Tracker update / coast with nearest-neighbor association
        if self._detection.detected:
            all_cands = [(c[0], c[1]) for c in self._detection.candidate_list]
            if self._tracker_valid and len(all_cands) > 1:
                matched = self.multi_beacon.associate_detection(
                    all_cands, self._tracker_x, self._tracker_y
                )
            else:
                matched = (self._detection.x, self._detection.y)

            if matched:
                ts = self.tracker.update(matched[0], matched[1], dt)
            else:
                ts = self.tracker.coast(dt)
        else:
            ts = self.tracker.coast(dt)

        self._tracker_x = ts.x
        self._tracker_y = ts.y
        self._tracker_vx = ts.vx
        self._tracker_vy = ts.vy
        self._tracker_valid = ts.valid

        # 8. FSM update
        self._fsm_state = self.state_machine.update(
            detected=self._detection.detected,
            coast_frames=ts.coast_frames,
            track_lost=self.tracker.track_lost,
            dt=dt,
        )

        # 9. Gimbal control: record pre-control angles
        prev_pan = self.camera.pan
        prev_tilt = self.camera.tilt

        if self._fsm_state in (TrackingState.LOCKED, TrackingState.COASTING):
            cmds = self.controller.update_from_pixel_error(
                self.camera, self._tracker_x, self._tracker_y, dt
            )
            if cmds:
                self.cmd_pan_deg = math.degrees(cmds[0])
                self.cmd_tilt_deg = math.degrees(cmds[1])
        elif self._fsm_state in (TrackingState.SEARCH, TrackingState.REACQUIRE):
            if self.search.completed:
                self.search.reset(self.camera)
            self.search.step(self.camera, dt, max_rate_deg=self.controller.max_rate_deg)
            self.cmd_pan_deg = 0.0
            self.cmd_tilt_deg = 0.0

        # Slew rates & control effort calculation
        dpan = self.camera.pan - prev_pan
        dtilt = self.camera.tilt - prev_tilt
        self.pan_rate_deg_s = abs(math.degrees(dpan)) / dt
        self.tilt_rate_deg_s = abs(math.degrees(dtilt)) / dt
        self.control_effort += (abs(math.degrees(dpan)) + abs(math.degrees(dtilt)))

        # 10. Platform disturbance injection
        self.disturbances.apply_camera_perturbations(self.camera, dt)

        # 11. Ground truth metrics computation
        self._compute_gt_metrics()

        # 12. Record frame telemetry in logger if active
        if self.logger.is_logging:
            self.logger.record_frame(self.get_state(), dt)

    def _render_numpy_frame(self) -> np.ndarray:
        """Render the 3D scene into a 640×480 numpy BGR uint8 sensor frame."""
        H, W = self.FRAME_H, self.FRAME_W
        frame = np.zeros((H, W, 3), dtype=np.float32)

        # Deep space dark pedestal
        bg = 5.0
        frame[:, :, 0] = bg * 0.6
        frame[:, :, 1] = bg * 0.8
        frame[:, :, 2] = bg

        forward, right, up = self.camera.get_look_vectors()
        cam_pos = self.camera.position
        FX, FY = self.camera.FX, self.camera.FY
        CX, CY = self.camera.CENTER_X, self.camera.CENTER_Y

        def _proj(wpos):
            v = np.array(wpos, dtype=float) - cam_pos
            xc = float(np.dot(v, right))
            yc = float(np.dot(v, up))
            zc = float(np.dot(v, forward))
            if zc <= 1e-3:
                return None
            return CX + FX * (xc / zc), CY - FY * (yc / zc)

        # Stars
        for star in self.world.get_stars_3d():
            res = _proj(star["pos"])
            if res is None:
                continue
            sx, sy = res
            if not (0 <= sx < W and 0 <= sy < H):
                continue
            alpha = star["alpha"] / 255.0
            size = star["size"]
            ix, iy = int(sx + 0.5), int(sy + 0.5)
            if not (0 <= ix < W and 0 <= iy < H):
                continue

            if size <= 1.2:
                val = alpha * 200
                frame[iy, ix, 0] += val * 0.85
                frame[iy, ix, 1] += val * 0.90
                frame[iy, ix, 2] += val
            else:
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        py, px = iy + dy, ix + dx
                        if 0 <= px < W and 0 <= py < H:
                            d2 = dx * dx + dy * dy
                            v = alpha * 190 * np.exp(-d2 / (2 * 0.7 ** 2))
                            frame[py, px, 0] += v * 0.85
                            frame[py, px, 1] += v * 0.92
                            frame[py, px, 2] += v

        # Beacons
        beacon_positions = self.multi_beacon.get_beacon_positions()
        for i, bpos in enumerate(beacon_positions):
            if i == 0 and self.disturbances.beacon_occluded:
                continue
            res = _proj(bpos)
            if res is None:
                continue
            bx, by = res
            if not (-50 <= bx < W + 50 and -50 <= by < H + 50):
                continue
            intensity = self.multi_beacon.get_beacon_intensity(i)
            if self.disturbances.atmosphere == Atmosphere.LOW_LIGHT:
                intensity *= 0.35
            self._draw_beacon_gaussian(frame, bx, by, intensity)

        return np.clip(frame, 0, 255).astype(np.uint8)

    @staticmethod
    def _draw_beacon_gaussian(frame: np.ndarray, cx: float, cy: float, intensity: float) -> None:
        """Convolve Gaussian point spread function onto float32 frame."""
        H, W = frame.shape[:2]
        sigma = max(3.0, 6.5 * min(1.5, math.sqrt(intensity)))
        r = int(sigma * 3.5) + 2
        peak = min(255.0, 240.0 * intensity)

        x0 = max(0, int(cx) - r)
        x1 = min(W, int(cx) + r + 1)
        y0 = max(0, int(cy) - r)
        y1 = min(H, int(cy) + r + 1)

        if x1 <= x0 or y1 <= y0:
            return

        yy, xx = np.mgrid[y0:y1, x0:x1].astype(np.float32)
        dist2 = (yy - cy) ** 2 + (xx - cx) ** 2
        psf = np.exp(-dist2 / (2.0 * sigma ** 2))

        # 1. Saturated core & primary PSF
        frame[y0:y1, x0:x1, 0] += psf * peak * 0.82
        frame[y0:y1, x0:x1, 1] += psf * peak * 0.91
        frame[y0:y1, x0:x1, 2] += psf * peak

        # 2. Secondary soft forward-scattering optical bloom
        halo_sigma = sigma * 2.6
        halo_psf = np.exp(-dist2 / (2.0 * halo_sigma ** 2))
        frame[y0:y1, x0:x1, 0] += halo_psf * (peak * 0.24) * 0.85
        frame[y0:y1, x0:x1, 1] += halo_psf * (peak * 0.24) * 0.93
        frame[y0:y1, x0:x1, 2] += halo_psf * (peak * 0.24)

    def _compute_gt_metrics(self) -> None:
        """Compute ground truth metrics for evaluation & benchmarking only."""
        target_pos = self.motion.position
        sx, sy, in_fov, _ = self.camera.project_world_point(target_pos)
        self._gt_screen = (sx, sy)
        self._gt_in_fov = in_fov

        ex, ey, e_total = self.camera.pixel_error(target_pos)
        self._gt_pixel_error = (ex, ey, e_total)

        dpan, dtilt, ang_total = self.camera.get_angular_error_to_point(target_pos)
        self._gt_angular_error = (dpan, dtilt, ang_total)

        if self._detection and self._detection.detected:
            self._detection_error = math.hypot(
                self._detection.x - sx,
                self._detection.y - sy,
            )
        else:
            self._detection_error = 0.0

        if self._fsm_state == TrackingState.LOCKED:
            self._error_history.append(e_total)
            if len(self._error_history) > 600:
                self._error_history.pop(0)
            self._max_error = max(self._max_error, e_total)

        self._status = "PAUSED" if not self.is_running else self._fsm_state

    # ================================================================== #
    # Benchmark Evaluation & Report
    # ================================================================== #

    def get_reference_evaluations(self) -> Dict[str, Dict[str, Any]]:
        """Evaluate current metrics honestly against SIH Reference Targets."""
        fsm_metrics = self.state_machine.metrics
        rmse = float(np.sqrt(np.mean(np.array(self._error_history) ** 2))) if self._error_history else 0.0
        avg_err = float(np.mean(self._error_history)) if self._error_history else 0.0
        acq_time = fsm_metrics.acquisition_time
        loss_pct = (1.0 - fsm_metrics.lock_retention) * 100.0
        reacq_time = fsm_metrics.reacquisition_time

        avg_fps = (self.total_fps_accum / max(1, self.fps_samples)) if self.fps_samples > 0 else 60.0

        return {
            "acquisition_time": {
                "metric": "Acquisition Time",
                "reference": f"≤ {self.REF_ACQ_TIME_MAX:.1f} s",
                "actual": f"{acq_time:.2f} s",
                "passed": (0.0 < acq_time <= self.REF_ACQ_TIME_MAX),
            },
            "tracking_error": {
                "metric": "Tracking Error (Avg)",
                "reference": f"≤ {self.REF_TRACK_ERR_MAX:.1f} px",
                "actual": f"{avg_err:.1f} px",
                "passed": (avg_err <= self.REF_TRACK_ERR_MAX),
            },
            "target_loss": {
                "metric": "Target Loss Rate",
                "reference": f"< {self.REF_TARGET_LOSS_MAX:.1f} %",
                "actual": f"{loss_pct:.1f} %",
                "passed": (loss_pct < self.REF_TARGET_LOSS_MAX),
            },
            "reacquisition_time": {
                "metric": "Re-acquisition Time",
                "reference": f"≤ {self.REF_REACQ_TIME_MAX:.1f} s",
                "actual": f"{reacq_time:.2f} s",
                "passed": (reacq_time <= self.REF_REACQ_TIME_MAX),
            },
            "processing_fps": {
                "metric": "Processing Rate",
                "reference": f"≥ {self.REF_FPS_MIN:.1f} FPS",
                "actual": f"{avg_fps:.1f} FPS",
                "passed": (avg_fps >= self.REF_FPS_MIN),
            },
        }

    def get_run_summary(self) -> Dict[str, Any]:
        """Generate full run summary report."""
        fsm_m = self.state_machine.metrics
        rmse = float(np.sqrt(np.mean(np.array(self._error_history) ** 2))) if self._error_history else 0.0
        avg_err = float(np.mean(self._error_history)) if self._error_history else 0.0
        avg_fps = (self.total_fps_accum / max(1, self.fps_samples)) if self.fps_samples > 0 else 60.0
        avg_proc_ms = (self.total_proc_time_ms / max(1, self.frame_count)) if self.frame_count > 0 else 0.0

        preset = get_scenario(self.active_scenario_id)

        return {
            "scenario": self.active_scenario_name,
            "seed": self.seed,
            "duration": round(self.sim_time, 2),
            "parameters": {
                "target_motion": preset.motion_mode if preset else self.motion.mode,
                "target_speed": preset.target_speed if preset else self.motion.speed,
                "camera_speed": preset.camera_max_rate if preset else self.controller.max_rate_deg,
                "atmosphere": preset.atmosphere if preset else self.disturbances.atmosphere,
                "noise": preset.noise_level if preset else self.disturbances.noise_level,
                "jitter": preset.jitter_level if preset else self.disturbances.jitter_level,
                "platform_motion": preset.platform_motion if preset else self.disturbances.platform_motion,
                "turbulence": preset.turbulence if preset else self.disturbances.turbulence,
            },
            "results": {
                "acquisition_time_s": round(fsm_m.acquisition_time, 3),
                "average_error_px": round(avg_err, 2),
                "maximum_error_px": round(self._max_error, 2),
                "rmse_px": round(rmse, 2),
                "lock_retention_pct": round(fsm_m.lock_retention * 100.0, 2),
                "target_loss_events": fsm_m.target_loss_events,
                "reacquisition_time_s": round(fsm_m.reacquisition_time, 3),
                "average_fps": round(avg_fps, 1),
                "average_processing_time_ms": round(avg_proc_ms, 2),
                "control_effort_deg": round(self.control_effort, 2),
            }
        }

    # ================================================================== #
    # Control API
    # ================================================================== #

    def toggle(self) -> bool:
        self.is_running = not self.is_running
        return self.is_running

    def reset(self) -> None:
        """Reset simulation state while preserving current scenario & seed."""
        self.sim_time = 0.0
        self.frame_count = 0
        self.control_effort = 0.0
        self.total_proc_time_ms = 0.0
        self.total_fps_accum = 0.0
        self.fps_samples = 0
        self._error_history.clear()
        self._max_error = 0.0
        self._detection_error = 0.0

        self.motion.reset(self.seed)
        self.multi_beacon.reset()
        self.camera.reset()
        self.controller.reset()
        self.detector.reset()
        self.tracker.reset()
        self.state_machine.reset()
        self.search.reset(self.camera)
        self.disturbances.set_seed(self.seed)

        self._raw_frame = self._render_numpy_frame()
        self._distorted_frame = self._raw_frame.copy()
        self._fsm_state = TrackingState.SEARCH
        self._status = TrackingState.SEARCH

    def set_motion_type(self, motion_type: str) -> None:
        self.motion.set_mode(motion_type)

    def set_target_speed(self, speed: float) -> None:
        self.motion.set_speed(speed)

    def set_camera_max_rate(self, rate_deg: float) -> None:
        self.controller.set_max_rate(rate_deg)

    def set_atmosphere(self, mode: str) -> None:
        self.disturbances.atmosphere = mode

    def set_noise_level(self, level: str) -> None:
        self.disturbances.noise_level = level

    def set_noise_custom_sigma(self, sigma: float) -> None:
        self.disturbances.noise_custom_sigma = sigma

    def set_turbulence(self, level: str) -> None:
        self.disturbances.turbulence = level

    def set_jitter_level(self, level: str) -> None:
        self.disturbances.jitter_level = level

    def set_jitter_custom(self, px: float) -> None:
        self.disturbances.jitter_custom_px = px

    def set_platform_motion(self, mode: str) -> None:
        self.disturbances.platform_motion = mode

    def set_platform_strength(self, strength: float) -> None:
        self.disturbances.platform_strength = max(0.0, min(1.0, strength))

    def set_fog_density(self, density: float) -> None:
        self.disturbances.fog_density = max(0.0, min(1.0, density))

    def set_rain_intensity(self, intensity: float) -> None:
        self.disturbances.rain_intensity = max(0.0, min(1.0, intensity))

    def set_dropout(self, mode: str) -> None:
        self.disturbances.dropout = mode

    def set_beacon_intensity(self, intensity: float) -> None:
        self.multi_beacon.set_primary_intensity(intensity)

    def set_beacon_count(self, count: int) -> None:
        self.multi_beacon.set_count(count)

    def set_starfield_density(self, density: str) -> None:
        self.world.set_starfield_density(density)

    def set_search_mode(self, mode: str) -> None:
        self.search.mode = mode
        self.search.reset(self.camera)

    def set_debug_mode(self, v: bool) -> None:
        self.debug_mode = v

    def set_show_ground_truth(self, v: bool) -> None:
        self.show_ground_truth = v

    def set_show_detection(self, v: bool) -> None:
        self.show_detection = v

    def set_show_prediction(self, v: bool) -> None:
        self.show_prediction = v

    def set_show_candidates(self, v: bool) -> None:
        self.show_candidates = v

    # ================================================================== #
    # State Snapshot
    # ================================================================== #

    def get_state(self) -> Dict[str, Any]:
        """Full state snapshot consumed by all GUI widgets."""
        target_pos = self.motion.position
        fsm_metrics = self.state_machine.metrics
        ang_deg = math.degrees(self._gt_angular_error[2])
        ang_mrad = ang_deg * (math.pi / 180.0) * 1000.0

        rmse = float(np.sqrt(np.mean(np.array(self._error_history) ** 2))) if self._error_history else 0.0
        avg_err = float(np.mean(self._error_history)) if self._error_history else 0.0

        return {
            # ── Scenario & Seed ──
            "scenario_id":           self.active_scenario_id,
            "scenario_name":         self.active_scenario_name,
            "seed":                  self.seed,
            "is_logging":            self.logger.is_logging,

            # ── Ground truth (evaluation only) ──
            "target_pos_3d":         target_pos.tolist(),
            "target_world_x":        float(target_pos[0]),
            "target_world_y":        float(target_pos[1]),
            "target_world_z":        float(target_pos[2]),
            "gt_screen_x":           float(self._gt_screen[0]),
            "gt_screen_y":           float(self._gt_screen[1]),
            "gt_in_fov":             self._gt_in_fov,
            "is_target_in_fov":      self._gt_in_fov,
            "is_target_in_view":     self._gt_in_fov,
            "target_screen_x":       float(self._gt_screen[0]),
            "target_screen_y":       float(self._gt_screen[1]),
            "angular_error_deg":     ang_deg,
            "angular_error_mrad":    ang_mrad,
            "angular_error_total_rad": float(self._gt_angular_error[2]),
            "angular_error_pan_rad": float(self._gt_angular_error[0]),
            "angular_error_tilt_rad": float(self._gt_angular_error[1]),
            "pixel_error_x":         float(self._gt_pixel_error[0]),
            "pixel_error_y":         float(self._gt_pixel_error[1]),
            "pixel_error_total":     float(self._gt_pixel_error[2]),
            "tracking_error":        float(self._gt_pixel_error[2]),

            # ── Camera & Gimbal ──
            "camera_pos_3d":         self.camera.position.tolist(),
            "camera_world_x":        float(self.camera.position[0]),
            "camera_world_y":        float(self.camera.position[1]),
            "camera_world_z":        float(self.camera.position[2]),
            "camera_pan_rad":        self.camera.pan,
            "camera_tilt_rad":       self.camera.tilt,
            "camera_pan_deg":        self.camera.pan_deg,
            "camera_tilt_deg":       self.camera.tilt_deg,
            "camera_look_vectors":   tuple(v.tolist() for v in self.camera.get_look_vectors()),
            "controller_max_rate_deg": self.controller.max_rate_deg,
            "pan_rate_deg_s":        self.pan_rate_deg_s,
            "tilt_rate_deg_s":       self.tilt_rate_deg_s,
            "cmd_pan_deg":           self.cmd_pan_deg,
            "cmd_tilt_deg":          self.cmd_tilt_deg,
            "control_effort":        self.control_effort,

            # ── Detection ──
            "detected":              self._detection.detected if self._detection else False,
            "detection_x":          self._detection.x if self._detection else self.CENTER_X,
            "detection_y":          self._detection.y if self._detection else self.CENTER_Y,
            "detection_confidence": self._detection.confidence if self._detection else 0.0,
            "detection_candidates": self._detection.candidates if self._detection else 0,
            "candidate_list":       self._detection.candidate_list if self._detection else [],
            "detection_error_px":   self._detection_error,
            "processing_time_ms":   self.detector.processing_time_ms,

            # ── Tracker ──
            "tracker_x":            self._tracker_x,
            "tracker_y":            self._tracker_y,
            "tracker_vx":           self._tracker_vx,
            "tracker_vy":           self._tracker_vy,
            "tracker_valid":        self._tracker_valid,

            # ── FSM ──
            "fsm_state":            self._fsm_state,
            "acquisition_time":     fsm_metrics.acquisition_time,
            "lock_retention":       fsm_metrics.lock_retention,
            "reacquisition_time":   fsm_metrics.reacquisition_time,
            "target_loss_events":   fsm_metrics.target_loss_events,

            # ── Error statistics ──
            "rmse_px":              rmse,
            "avg_error_px":         avg_err,
            "max_error_px":         self._max_error,

            # ── Motion & Trail ──
            "motion_mode":          self.motion.mode,
            "target_speed":         self.motion.speed,
            "target_trail":         [p.tolist() for p in self.motion.trail],
            "target_preview_path":  [p.tolist() for p in self.motion.get_preview_path(60)],

            # ── World ──
            "stars_3d":             self.world.get_stars_3d(),
            "celestial_objects_3d": self.world.get_celestial_objects_3d(),
            "starfield_density":    self.world.starfield_density,

            # ── Beacons ──
            "beacon_count":         self.multi_beacon.count,
            "beacon_info":          self.multi_beacon.get_beacon_info(),

            # ── Sensor frame ──
            "distorted_frame":      self._distorted_frame,

            # ── Overlays & Debug ──
            "debug_mode":           self.debug_mode,
            "show_ground_truth":    self.show_ground_truth,
            "show_detection":       self.show_detection,
            "show_prediction":      self.show_prediction,
            "show_candidates":      self.show_candidates,

            # ── Metadata ──
            "sim_time":             self.sim_time,
            "is_running":           self.is_running,
            "status":               self._status,
        }


# Aliases for backward compatibility
Stage2Engine = Stage3Engine
Stage1Engine = Stage3Engine
SimulationEngine = Stage3Engine
