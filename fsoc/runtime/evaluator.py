"""SIH26169 evaluator — scores the live system against the six reference numbers.

Definitions (ground truth is used here only, never inside the pipeline):
  Acquisition time   cold start -> first confirmed LOCK.                      <= 2 s
  Tracking error     |detected centroid - true beacon centre| on sensor, mean
                     over LOCKED frames with a detection.                      <= 10 px
  Target loss        % of frames after first lock without a valid lock. Valid =
                     LOCKED or COASTING (Kalman prediction) AND the track LOS is
                     within 40 px of the true LOS (a lock on a decoy is a loss). < 5 %
  Re-acquisition     loss of valid lock -> LOCKED again, counted from when the
                     beacon became physically visible again. Worst case scored. <= 1 s
  Processing speed   achieved end-to-end vision pipeline rate (render/capture +
                     detect + track).                                          >= 20 FPS
  Camera update      GUI render rate / gimbal control-loop rate.               >= 30 / 20 Hz
"""

import math
from collections import deque
from typing import Dict, Optional

from ..core.geometry import CameraIntrinsics, angular_separation
from ..core.pipeline import TrackState

KPI_ORDER = ["acquisition", "tracking_error", "target_loss", "reacquisition", "processing", "camera_rate"]

KPI_META = {
    "acquisition":    ("Acquisition time", "≤ 2.0 s", "Cold start → first confirmed lock"),
    "tracking_error": ("Tracking error", "≤ 10 px", "Detected centroid → true beacon centre"),
    "target_loss":    ("Target loss", "< 5 %", "Frames with no valid lock"),
    "reacquisition":  ("Re-acquisition", "≤ 1.0 s", "Recovery after losing the spot"),
    "processing":     ("Processing speed", "≥ 20 FPS", "End-to-end pipeline throughput"),
    "camera_rate":    ("Camera update rate", "≥ 30 / 20 Hz", "Render loop / control loop"),
}


class Evaluator:
    ACQ_MAX = 2.0
    TRACK_ERR_MAX = 10.0
    LOSS_MAX = 5.0
    REACQ_MAX = 1.0
    FPS_MIN = 20.0
    RENDER_MIN = 30.0
    CONTROL_MIN = 20.0
    VALID_LOCK_PX = 40.0

    def __init__(self, K: CameraIntrinsics) -> None:
        self.K = K
        self.reset(0.0)

    def reset(self, t0: float) -> None:
        self.t0 = t0
        self.t = t0
        self.acq_time: Optional[float] = None
        self.err_n = 0
        self.err_sum = 0.0
        self.err_sq = 0.0
        self.err_max = 0.0
        self.err_recent = deque(maxlen=150)
        self.point_n = 0
        self.point_sum = 0.0
        self.frames_after_lock = 0
        self.lost_frames = 0
        self._prev_valid = True
        self._in_loss = False
        self._loss_t = 0.0
        self._clear_t: Optional[float] = None
        self.reacq_times = []
        self.proc_ms = deque(maxlen=90)
        self.stage_ms = (0.0, 0.0, 0.0)
        self.last_centroid_err: Optional[float] = None
        self.last_pointing_err: Optional[float] = None
        self.last_track_sep_px: Optional[float] = None
        self.frames = 0

    def on_frame(self, out, truth, render_ms: float, detect_ms: float, track_ms: float,
                has_truth: bool = True) -> None:
        """`has_truth=False` (a real recorded video, where nothing is known about the true beacon
        position) still measures acquisition, processing speed and camera update rate — the
        ground-truth-dependent numbers (tracking error, target loss, re-acquisition) are left
        alone so they stay "no data" rather than being scored against a meaningless reference."""
        t = out.t
        if t < self.t0:
            return
        self.t = t
        self.frames += 1
        self.proc_ms.append(render_ms + detect_ms + track_ms)
        self.stage_ms = (render_ms, detect_ms, track_ms)
        K = self.K
        st = out.state

        if self.acq_time is None and st == TrackState.LOCKED:
            self.acq_time = t - self.t0

        if not has_truth:
            return

        self.last_centroid_err = None
        if st == TrackState.LOCKED and out.measurement and truth.target_px and not truth.occluded:
            e = math.hypot(out.measurement[0] - truth.target_px[0], out.measurement[1] - truth.target_px[1])
            self.err_n += 1
            self.err_sum += e
            self.err_sq += e * e
            self.err_max = max(self.err_max, e)
            self.err_recent.append(e)
            self.last_centroid_err = e

        self.last_pointing_err = None
        if truth.target_px is not None:
            self.last_pointing_err = math.hypot(truth.target_px[0] - K.cx, truth.target_px[1] - K.cy)
            if st == TrackState.LOCKED:
                self.point_n += 1
                self.point_sum += self.last_pointing_err

        sep_px = None
        if out.track_los is not None:
            sep_px = angular_separation(out.track_los[0], out.track_los[1],
                                        truth.target_los[0], truth.target_los[1]) * K.fx
        self.last_track_sep_px = sep_px

        if self.acq_time is None:
            return
        valid = st in (TrackState.LOCKED, TrackState.COASTING) and sep_px is not None \
            and sep_px <= self.VALID_LOCK_PX
        self.frames_after_lock += 1
        if not valid:
            self.lost_frames += 1

        if self._prev_valid and not valid:
            self._in_loss = True
            self._loss_t = t
            self._clear_t = None if truth.occluded else t
        if self._in_loss:
            if truth.occluded:
                self._clear_t = None
            elif self._clear_t is None:
                self._clear_t = t
            if valid and st == TrackState.LOCKED:
                start = max(self._loss_t, self._clear_t if self._clear_t is not None else t)
                self.reacq_times.append(max(0.0, t - start))
                self._in_loss = False
        self._prev_valid = valid

    # ------------------------------------------------------------------ report
    def metrics(self, vision_hz: float, control_hz: float, render_hz: Optional[float]) -> Dict[str, dict]:
        elapsed = self.t - self.t0
        out: Dict[str, dict] = {}

        def kpi(key, value, text, status, ratio=None, detail=""):
            name, target, meaning = KPI_META[key]
            out[key] = dict(name=name, target=target, meaning=meaning, value=value, text=text,
                            status=status, ratio=ratio, detail=detail)

        # Acquisition
        if self.acq_time is not None:
            ok = self.acq_time <= self.ACQ_MAX
            kpi("acquisition", self.acq_time, f"{self.acq_time:.2f} s", "pass" if ok else "fail",
                self.acq_time / self.ACQ_MAX, "locked")
        elif elapsed > self.ACQ_MAX:
            kpi("acquisition", None, f"> {elapsed:.1f} s", "fail", 1.5, "no lock yet")
        else:
            kpi("acquisition", None, f"{elapsed:.2f} s", "pending", elapsed / self.ACQ_MAX, "searching…")

        # Tracking error
        if self.err_n >= 10:
            mean = self.err_sum / self.err_n
            rmse = math.sqrt(self.err_sq / self.err_n)
            kpi("tracking_error", mean, f"{mean:.2f} px", "pass" if mean <= self.TRACK_ERR_MAX else "fail",
                mean / self.TRACK_ERR_MAX, f"RMSE {rmse:.2f} · max {self.err_max:.1f} px")
        else:
            kpi("tracking_error", None, "—", "pending", 0.0, "waiting for lock")

        # Target loss
        if self.frames_after_lock >= 30:
            pct = 100.0 * self.lost_frames / self.frames_after_lock
            kpi("target_loss", pct, f"{pct:.2f} %", "pass" if pct < self.LOSS_MAX else "fail",
                pct / self.LOSS_MAX, f"{self.lost_frames}/{self.frames_after_lock} frames")
        else:
            kpi("target_loss", None, "—", "pending", 0.0, "waiting for lock")

        # Re-acquisition
        if self.reacq_times:
            worst = max(self.reacq_times)
            last = self.reacq_times[-1]
            kpi("reacquisition", worst, f"{worst:.2f} s", "pass" if worst <= self.REACQ_MAX else "fail",
                worst / self.REACQ_MAX, f"{len(self.reacq_times)} recoveries · last {last:.2f} s")
        elif self._in_loss:
            kpi("reacquisition", None, f"{self.t - self._loss_t:.2f} s", "pending", 0.5, "recovering…")
        else:
            kpi("reacquisition", None, "No losses", "standby", 0.0, "use “Block beacon” to test")

        # Processing speed
        cap = 1000.0 / (sum(self.proc_ms) / len(self.proc_ms)) if self.proc_ms else 0.0
        if self.frames >= 10:
            kpi("processing", vision_hz, f"{vision_hz:.1f} FPS",
                "pass" if vision_hz >= self.FPS_MIN else "fail",
                self.FPS_MIN / max(vision_hz, 1e-3), f"capacity {cap:.0f} FPS")
        else:
            kpi("processing", None, "—", "pending", 0.0, "")

        # Camera update rates
        if render_hz is None:
            ok = control_hz >= self.CONTROL_MIN
            kpi("camera_rate", control_hz, f"— / {control_hz:.0f} Hz", "pass" if ok else "fail",
                self.CONTROL_MIN / max(control_hz, 1e-3), "headless")
        elif self.frames >= 10:
            ok = render_hz >= self.RENDER_MIN and control_hz >= self.CONTROL_MIN
            kpi("camera_rate", render_hz, f"{render_hz:.0f} / {control_hz:.0f} Hz", "pass" if ok else "fail",
                max(self.RENDER_MIN / max(render_hz, 1e-3), self.CONTROL_MIN / max(control_hz, 1e-3)),
                "threads decoupled")
        else:
            kpi("camera_rate", None, "—", "pending", 0.0, "")
        return out

    def summary(self) -> dict:
        mean = self.err_sum / self.err_n if self.err_n else None
        return {
            "elapsed_s": round(self.t - self.t0, 2),
            "acquisition_time_s": None if self.acq_time is None else round(self.acq_time, 3),
            "tracking_error_mean_px": None if mean is None else round(mean, 3),
            "tracking_error_rmse_px": None if not self.err_n else round(math.sqrt(self.err_sq / self.err_n), 3),
            "tracking_error_max_px": round(self.err_max, 2),
            "pointing_error_mean_px": None if not self.point_n else round(self.point_sum / self.point_n, 2),
            "target_loss_pct": None if not self.frames_after_lock else
            round(100.0 * self.lost_frames / self.frames_after_lock, 3),
            "reacquisition_times_s": [round(x, 3) for x in self.reacq_times],
            "reacquisition_worst_s": None if not self.reacq_times else round(max(self.reacq_times), 3),
            "processing_capacity_fps": None if not self.proc_ms else
            round(1000.0 / (sum(self.proc_ms) / len(self.proc_ms)), 1),
            "frames": self.frames,
        }
