import math
import random
from collections import deque
from typing import Dict, Any, List, Tuple


class BeaconSimulation:
    """Physics, atmospheric/space channel, PAT state machine, and sensor detection
    simulation for FSOC optical tracking systems.
    
    PAT Stages:
      1. SEARCH / SCANNING (Finding beacon via uncertainty cone search)
      2. ACQUISITION (Detecting photon flux, centroid verification)
      3. COARSE POINTING (Gimbal/steering mirror slewing bore-sight toward target)
      4. FINE TRACKING (Closed-loop tracking locked with Fast Steering Mirror)
    """

    WORLD_WIDTH: float = 1000.0
    WORLD_HEIGHT: float = 600.0
    CENTER_X: float = 500.0
    CENTER_Y: float = 300.0

    CIRCLE_RADIUS: float = 200.0
    FIGURE_EIGHT_AMP_X: float = 320.0
    FIGURE_EIGHT_AMP_Y: float = 180.0
    BASE_OMEGA: float = 1.0

    def __init__(self) -> None:
        self.is_running: bool = True
        self.sim_time: float = 0.0
        self.theta: float = 0.0
        self.speed_multiplier: float = 1.0
        self.motion_type: str = "circle"

        # Atmospheric & Space channel parameters
        self.fog_density: float = 0.15          # Space/atmospheric haze
        self.sensor_noise: float = 0.18         # Sensor readout/thermal noise
        self.turbulence_enabled: bool = True    # Atmospheric/gimbal micro-jitter
        self.dust_density: float = 0.35         # Cosmic dust & debris density
        self.fog_drift: float = 0.0

        # PAT State Machine: "search", "acquisition", "pointing", "fine_tracking", "lost"
        self.pat_mode: str = "auto"             # "auto" or "manual"
        self.pat_stage: str = "search"
        self.stage_time: float = 0.0

        # Search / Scan parameters
        self.scan_angle: float = 0.0
        self.scan_radius: float = 40.0
        self.pointing_progress: float = 0.0     # 0.0 to 1.0 during pointing slew

        # True beacon coordinates
        self.true_x: float = self.CENTER_X + self.CIRCLE_RADIUS
        self.true_y: float = self.CENTER_Y

        # Detected / estimated centroid coordinates
        self.detected_x: float = self.true_x
        self.detected_y: float = self.true_y
        self.distance: float = self.CIRCLE_RADIUS
        self.snr_db: float = 27.0

        # Effective camera bore-sight (slews toward beacon in Pointing stage)
        self.boresight_x: float = self.CENTER_X
        self.boresight_y: float = self.CENTER_Y

        # Deep-space background stars (x, y, magnitude, twinkle_speed, phase)
        self.stars: List[Tuple[float, float, float, float, float]] = []
        self._init_stars()

        # Cosmic dust / space debris particles [x, y, vx, vy, size, alpha]
        self.dust_particles: List[List[float]] = []
        self._init_dust()

        # Trailing history
        self.trail: deque[Tuple[float, float]] = deque(maxlen=80)
        self._update_telemetry()

    def _init_stars(self) -> None:
        """Generate static deep space starfield with realistic magnitude distribution."""
        random.seed(42)  # Deterministic beautiful starfield
        self.stars.clear()
        for _ in range(160):
            sx = random.uniform(5, self.WORLD_WIDTH - 5)
            sy = random.uniform(5, self.WORLD_HEIGHT - 5)
            mag = random.uniform(0.6, 2.5)  # Radius / brightness
            speed = random.uniform(1.0, 4.0)
            phase = random.uniform(0.0, 2.0 * math.pi)
            self.stars.append((sx, sy, mag, speed, phase))
        random.seed()

    def _init_dust(self) -> None:
        """Initialize floating cosmic dust particles."""
        self.dust_particles.clear()
        num_dust = int(20 + self.dust_density * 60)
        for _ in range(num_dust):
            dx = random.uniform(0, self.WORLD_WIDTH)
            dy = random.uniform(0, self.WORLD_HEIGHT)
            vx = random.uniform(-6.0, 6.0)
            vy = random.uniform(-4.0, 4.0)
            size = random.uniform(1.0, 2.8)
            alpha = random.uniform(0.2, 0.7)
            self.dust_particles.append([dx, dy, vx, vy, size, alpha])

    def _update_dust(self, dt: float) -> None:
        """Update positions of floating cosmic dust particles."""
        for p in self.dust_particles:
            p[0] += p[2] * dt
            p[1] += p[3] * dt
            # Wrap around boundaries
            if p[0] < 0:
                p[0] = self.WORLD_WIDTH
            elif p[0] > self.WORLD_WIDTH:
                p[0] = 0
            if p[1] < 0:
                p[1] = self.WORLD_HEIGHT
            elif p[1] > self.WORLD_HEIGHT:
                p[1] = 0

    def _step_pat_state_machine(self, dt: float) -> None:
        """Advance the Pointing, Acquisition, and Tracking (PAT) state machine."""
        self.stage_time += dt

        # Search sweep dynamics
        self.scan_angle = (self.scan_angle + dt * 3.5) % (2.0 * math.pi)
        self.scan_radius = 50.0 + 280.0 * (0.5 + 0.5 * math.sin(self.stage_time * 1.2))

        if self.pat_mode != "auto":
            return

        # Automatic PAT stage progression
        if self.pat_stage == "search":
            # Check if scan cone has located beacon or search timer elapsed (~3.2s)
            dist_to_scan = math.hypot(
                self.true_x - (self.CENTER_X + self.scan_radius * math.cos(self.scan_angle)),
                self.true_y - (self.CENTER_Y + self.scan_radius * math.sin(self.scan_angle)),
            )
            # If search sweep encounters beacon with good SNR or timeout
            if (dist_to_scan < 120.0 and self.snr_db >= 10.0) or self.stage_time > 3.8:
                if self.snr_db >= 8.5:
                    self.set_pat_stage("acquisition")

        elif self.pat_stage == "acquisition":
            # Integrate optical pulses and verify centroid over 1.6 seconds
            if self.snr_db < 8.0:
                self.set_pat_stage("lost")
            elif self.stage_time >= 1.6:
                self.set_pat_stage("pointing")

        elif self.pat_stage == "pointing":
            # Coarse gimbal steering aligns bore-sight toward beacon over ~2.0 seconds
            self.pointing_progress = min(1.0, self.stage_time / 2.0)
            if self.snr_db < 8.0:
                self.set_pat_stage("lost")
            elif self.pointing_progress >= 1.0:
                self.set_pat_stage("fine_tracking")

        elif self.pat_stage == "fine_tracking":
            # Continuous closed-loop tracking
            if self.snr_db < 8.0:
                self.set_pat_stage("lost")

        elif self.pat_stage == "lost":
            # Signal lost, brief pause before re-initiating search
            if self.stage_time >= 1.5:
                self.set_pat_stage("search")

    def _update_telemetry(self) -> None:
        """Compute true position, micro-jitter, detected centroid, SNR, and pointing error."""
        # 1. True kinematic beacon trajectory
        if self.motion_type == "circle":
            self.true_x = self.CENTER_X + self.CIRCLE_RADIUS * math.cos(self.theta)
            self.true_y = self.CENTER_Y + self.CIRCLE_RADIUS * math.sin(self.theta)
        elif self.motion_type == "figure_eight":
            self.true_x = self.CENTER_X + self.FIGURE_EIGHT_AMP_X * math.sin(self.theta)
            self.true_y = self.CENTER_Y + self.FIGURE_EIGHT_AMP_Y * math.sin(2.0 * self.theta)
        else:
            self.true_x = self.CENTER_X
            self.true_y = self.CENTER_Y

        # 2. Atmospheric & gimbal micro-jitter
        wander_x = 0.0
        wander_y = 0.0
        if self.turbulence_enabled:
            # Micro-jitter scale depends on stage (fine tracking rejects most coarse jitter)
            jitter_scale = 1.0 if self.pat_stage == "fine_tracking" else (2.0 + 3.0 * self.fog_density)
            wander_x = random.gauss(0.0, jitter_scale)
            wander_y = random.gauss(0.0, jitter_scale)

        # 3. Sensor readout noise & dust attenuation
        sensor_jitter_scale = 0.8 + 6.0 * self.sensor_noise
        noise_x = random.gauss(0.0, sensor_jitter_scale)
        noise_y = random.gauss(0.0, sensor_jitter_scale)

        self.detected_x = self.true_x + wander_x + noise_x
        self.detected_y = self.true_y + wander_y + noise_y

        # Distance from camera bore-sight center (500, 300)
        dx = self.detected_x - self.CENTER_X
        dy = self.detected_y - self.CENTER_Y
        self.distance = math.sqrt(dx * dx + dy * dy)

        # 4. Signal-to-Noise Ratio (SNR) in dB
        # Attenuation by fog and space dust/debris
        extinction = (self.fog_density * 2.0) + (self.dust_density * 0.8)
        signal_power = 100.0 * math.exp(-extinction)
        noise_power = (self.sensor_noise * 18.0) + (self.fog_density * 8.0) + 1.0
        linear_snr = max(0.05, signal_power / noise_power)
        self.snr_db = max(2.0, min(36.0, 10.0 * math.log10(linear_snr) + 12.0))

        if self.pat_stage in ("fine_tracking", "pointing"):
            self.trail.append((self.detected_x, self.detected_y))

    def step(self, dt: float) -> None:
        """Advance simulation by dt seconds."""
        if not self.is_running or dt <= 0:
            return

        dt_clamped = min(dt, 0.1)
        self.sim_time += dt_clamped
        self.fog_drift = (self.fog_drift + dt_clamped * 0.25) % (2.0 * math.pi)
        self.theta += self.BASE_OMEGA * dt_clamped * self.speed_multiplier
        self.theta = math.fmod(self.theta, 2.0 * math.pi)

        self._step_pat_state_machine(dt_clamped)
        self._update_dust(dt_clamped)
        self._update_telemetry()

    def start(self) -> None:
        self.is_running = True

    def pause(self) -> None:
        self.is_running = False

    def toggle(self) -> bool:
        self.is_running = not self.is_running
        return self.is_running

    def reset(self) -> None:
        self.sim_time = 0.0
        self.theta = 0.0
        self.fog_drift = 0.0
        self.trail.clear()
        self.set_pat_stage("search")
        self._update_telemetry()

    def restart_pat_cycle(self) -> None:
        """Manually trigger a fresh PAT acquisition cycle."""
        self.set_pat_stage("search")

    def set_pat_mode(self, mode: str) -> None:
        """Set PAT mode: 'auto' or 'manual'."""
        self.pat_mode = mode.lower()

    def set_pat_stage(self, stage: str) -> None:
        """Set or force PAT stage: 'search', 'acquisition', 'pointing', 'fine_tracking', 'lost'."""
        stage_norm = stage.lower().replace(" ", "_")
        if stage_norm in ("search", "acquisition", "pointing", "fine_tracking", "lost"):
            self.pat_stage = stage_norm
            self.stage_time = 0.0
            if stage_norm == "pointing":
                self.pointing_progress = 0.0

    def set_speed(self, speed: float) -> None:
        self.speed_multiplier = max(0.1, float(speed))

    def set_motion(self, motion_type: str) -> None:
        normalized = motion_type.lower().replace(" ", "_")
        if normalized in ("circle", "figure_eight"):
            self.motion_type = normalized
            self.trail.clear()
            self._update_telemetry()

    def set_fog(self, density: float) -> None:
        self.fog_density = max(0.0, min(1.0, float(density)))
        self._update_telemetry()

    def set_noise(self, noise: float) -> None:
        self.sensor_noise = max(0.0, min(1.0, float(noise)))
        self._update_telemetry()

    def set_dust(self, density: float) -> None:
        """Set cosmic dust / space debris density (0.0 to 1.0)."""
        self.dust_density = max(0.0, min(1.0, float(density)))
        self._init_dust()
        self._update_telemetry()

    def set_turbulence(self, enabled: bool) -> None:
        self.turbulence_enabled = bool(enabled)
        self._update_telemetry()

    def get_state(self) -> Dict[str, Any]:
        """Return the current simulation telemetry state."""
        return {
            "x": self.detected_x,
            "y": self.detected_y,
            "true_x": self.true_x,
            "true_y": self.true_y,
            "center_x": self.CENTER_X,
            "center_y": self.CENTER_Y,
            "distance": self.distance,
            "sim_time": self.sim_time,
            "is_running": self.is_running,
            "motion_type": self.motion_type,
            "speed_multiplier": self.speed_multiplier,
            "fog_density": self.fog_density,
            "sensor_noise": self.sensor_noise,
            "dust_density": self.dust_density,
            "turbulence_enabled": self.turbulence_enabled,
            "fog_drift": self.fog_drift,
            "snr_db": self.snr_db,
            "pat_mode": self.pat_mode,
            "pat_stage": self.pat_stage,
            "stage_time": self.stage_time,
            "scan_angle": self.scan_angle,
            "scan_radius": self.scan_radius,
            "pointing_progress": self.pointing_progress,
            "stars": self.stars,
            "dust_particles": self.dust_particles,
            "trail": list(self.trail),
        }
