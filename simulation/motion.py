"""
simulation/motion.py — 3D motion trajectories for Terminal B.

Provides four selectable motion modes:
  - straight:      Linear flyby through space.
  - circle:        Circular orbit around a reference center in the XZ plane.
  - figure_eight:  Lissajous figure-eight trajectory (3D).
  - random:        Smooth spline walk with configurable random seed.

All modes operate in the 3D world coordinate frame:
  +X = Right, +Y = Up, +Z = Forward (into scene / increasing range)
"""

import math
import numpy as np
from collections import deque
from typing import List, Tuple


# Default starting position for Terminal B: centered at range 1000m along optical axis
DEFAULT_CENTER = np.array([0.0, 0.0, 1000.0], dtype=float)

# Base angular speed (rad/s) at speed multiplier 1.0
BASE_OMEGA = 0.25


class TargetMotion:
    """3D motion controller for Terminal B.

    Manages the trajectory of Terminal B in the 3D world.
    `step(dt)` advances time and returns the new 3D position as a numpy array.
    """

    MODES = ("straight", "circle", "figure_eight", "random")

    def __init__(self, mode: str = "circle", speed: float = 1.0, seed: int = 42) -> None:
        self.mode: str = mode
        self.speed: float = speed
        self.seed: int = seed

        self._theta: float = 0.0       # Phase angle for periodic motions
        self._sim_time: float = 0.0    # Internal sim time tracker for motions

        # Trail buffer for visualization (keep last 200 positions)
        self.trail: deque = deque(maxlen=200)

        # Pre-generate random waypoints for "random" mode
        self._random_waypoints: List[np.ndarray] = []
        self._random_t: float = 0.0
        self._random_seg_idx: int = 0
        self._random_seg_dur: float = 4.0  # seconds per segment
        self._init_random_waypoints()

        # Compute and record initial position
        self._position: np.ndarray = self._compute_position()
        self.trail.append(self._position.copy())

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    @property
    def position(self) -> np.ndarray:
        return self._position.copy()

    def step(self, dt: float) -> np.ndarray:
        """Advance motion by dt seconds, return new 3D world position."""
        if dt <= 0:
            return self._position.copy()

        dt_clamped = min(dt, 0.05)
        self._theta += BASE_OMEGA * self.speed * dt_clamped
        self._theta = math.fmod(self._theta, 2.0 * math.pi)
        self._sim_time += dt_clamped

        # Update random motion time tracker
        self._random_t += dt_clamped

        self._position = self._compute_position()
        self.trail.append(self._position.copy())
        return self._position.copy()

    def reset(self, seed: Optional[int] = None) -> None:
        """Reset trajectory to initial state, optionally updating random seed."""
        if seed is not None:
            self.seed = int(seed)
        self._theta = 0.0
        self._sim_time = 0.0
        self._random_t = 0.0
        self._random_seg_idx = 0
        self.trail.clear()
        self._init_random_waypoints()
        self._position = self._compute_position()
        self.trail.append(self._position.copy())

    def set_seed(self, seed: int) -> None:
        """Set random seed and reset trajectory."""
        self.reset(seed=seed)

    def set_mode(self, mode: str) -> None:
        """Change motion mode. Accepts 'straight', 'circle', 'figure_eight', 'random'."""
        normalized = mode.lower().replace(" ", "_")
        if normalized in self.MODES:
            self.mode = normalized
            self.trail.clear()
            self._position = self._compute_position()
            self.trail.append(self._position.copy())

    def set_speed(self, speed: float) -> None:
        """Set speed multiplier (0.1–5.0)."""
        self.speed = max(0.1, min(5.0, float(speed)))

    def get_preview_path(self, num_points: int = 120) -> List[np.ndarray]:
        """Return preview path for current motion mode (for world map overlay).

        For 'random' mode, returns the current trail instead.
        """
        if self.mode == "random":
            return list(self.trail)

        path = []
        saved_theta = self._theta
        saved_time = self._sim_time
        saved_random_t = self._random_t

        # Sample the trajectory over one full period
        for i in range(num_points + 1):
            frac = i / num_points
            self._theta = frac * 2.0 * math.pi
            self._sim_time = frac * (2.0 * math.pi / (BASE_OMEGA * max(0.1, self.speed)))
            path.append(self._compute_position())

        # Restore state
        self._theta = saved_theta
        self._sim_time = saved_time
        self._random_t = saved_random_t
        return path

    # ------------------------------------------------------------------ #
    # Internal trajectory computation
    # ------------------------------------------------------------------ #

    def _compute_position(self) -> np.ndarray:
        if self.mode == "straight":
            return self._straight_position()
        elif self.mode == "circle":
            return self._circle_position()
        elif self.mode == "figure_eight":
            return self._figure_eight_position()
        elif self.mode == "random":
            return self._random_position()
        return DEFAULT_CENTER.copy()

    def _straight_position(self) -> np.ndarray:
        """Linear flyby: moves across X axis at constant Z and Y."""
        x = 400.0 * math.sin(self._theta)
        y = DEFAULT_CENTER[1] + 20.0 * math.sin(self._theta * 0.5)
        z = DEFAULT_CENTER[2] + 40.0 * (1.0 - math.cos(self._theta * 0.3))
        return np.array([x, y, z], dtype=float)

    def _circle_position(self) -> np.ndarray:
        """Circular orbit centered along the optical line of sight."""
        r = 300.0   # orbit radius (world units)
        x = r * math.sin(self._theta)
        y = DEFAULT_CENTER[1] + 25.0 * math.sin(self._theta)
        z = DEFAULT_CENTER[2] + r * (math.cos(self._theta) - 1.0)
        return np.array([x, y, z], dtype=float)

    def _figure_eight_position(self) -> np.ndarray:
        """Lissajous figure-eight starting at optical bore-sight."""
        amp_x = 350.0
        amp_z = 150.0
        x = amp_x * math.sin(self._theta)
        y = DEFAULT_CENTER[1] + 25.0 * math.sin(2.0 * self._theta)
        z = DEFAULT_CENTER[2] + amp_z * math.sin(2.0 * self._theta)
        return np.array([x, y, z], dtype=float)

    def _random_position(self) -> np.ndarray:
        """Smooth cubic spline interpolation between random waypoints."""
        if len(self._random_waypoints) < 2:
            return DEFAULT_CENTER.copy()

        total_segs = len(self._random_waypoints) - 1

        # Advance segment index based on time
        seg_idx = int(self._random_t / self._random_seg_dur) % total_segs
        t_local = (self._random_t % self._random_seg_dur) / self._random_seg_dur  # 0..1

        p0 = self._random_waypoints[seg_idx]
        p1 = self._random_waypoints[(seg_idx + 1) % len(self._random_waypoints)]

        # Catmull-Rom tangent points
        pm1 = self._random_waypoints[(seg_idx - 1) % len(self._random_waypoints)]
        p2 = self._random_waypoints[(seg_idx + 2) % len(self._random_waypoints)]

        return self._catmull_rom(pm1, p0, p1, p2, t_local)

    def _init_random_waypoints(self) -> None:
        """Pre-generate smooth random waypoints (closed loop)."""
        rng = np.random.default_rng(self.seed)
        n = 14  # number of waypoints in the loop
        self._random_waypoints = []
        for i in range(n):
            x = rng.uniform(-700.0, 700.0)
            y = rng.uniform(50.0, 250.0)
            z = rng.uniform(600.0, 1400.0)
            self._random_waypoints.append(np.array([x, y, z], dtype=float))
        # Close the loop by appending first 3 waypoints at end for Catmull-Rom continuity
        self._random_waypoints += self._random_waypoints[:3]

    @staticmethod
    def _catmull_rom(p0: np.ndarray, p1: np.ndarray,
                     p2: np.ndarray, p3: np.ndarray, t: float) -> np.ndarray:
        """Catmull-Rom spline interpolation between p1 and p2 at parameter t (0..1)."""
        t2 = t * t
        t3 = t2 * t
        return 0.5 * (
            (2.0 * p1) +
            (-p0 + p2) * t +
            (2.0 * p0 - 5.0 * p1 + 4.0 * p2 - p3) * t2 +
            (-p0 + 3.0 * p1 - 3.0 * p2 + p3) * t3
        )
