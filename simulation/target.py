import math
from collections import deque
from typing import Tuple, List


class Target:
    """Moving optical beacon / target with ground truth world coordinates."""

    CENTER_X: float = 1000.0
    CENTER_Y: float = 1000.0

    # Circle trajectory constants
    CIRCLE_RADIUS: float = 500.0

    # Figure-eight trajectory constants
    FIG8_AMP_X: float = 650.0
    FIG8_AMP_Y: float = 400.0

    BASE_OMEGA: float = 0.5  # Base angular frequency (rad/s)

    def __init__(self) -> None:
        self.motion_type: str = "circle"  # "circle" or "figure_eight"
        self.speed: float = 1.0           # Speed multiplier
        self.theta: float = 0.0
        self.x: float = self.CENTER_X + self.CIRCLE_RADIUS
        self.y: float = self.CENTER_Y

        # Trail of recent positions for visualization
        self.trail: deque[Tuple[float, float]] = deque(maxlen=150)
        self._update_position()

    def _update_position(self) -> None:
        if self.motion_type == "circle":
            self.x = self.CENTER_X + self.CIRCLE_RADIUS * math.cos(self.theta)
            self.y = self.CENTER_Y + self.CIRCLE_RADIUS * math.sin(self.theta)
        elif self.motion_type == "figure_eight":
            self.x = self.CENTER_X + self.FIG8_AMP_X * math.sin(self.theta)
            self.y = self.CENTER_Y + self.FIG8_AMP_Y * math.sin(2.0 * self.theta)
        else:
            self.x = self.CENTER_X
            self.y = self.CENTER_Y

        self.trail.append((self.x, self.y))

    def step(self, dt: float) -> None:
        """Advance target along its trajectory by dt seconds."""
        if dt <= 0:
            return
        dt_clamped = min(dt, 0.1)
        self.theta += self.BASE_OMEGA * self.speed * dt_clamped
        self.theta = math.fmod(self.theta, 2.0 * math.pi)
        self._update_position()

    def reset(self) -> None:
        """Reset target to initial position."""
        self.theta = 0.0
        self.trail.clear()
        self._update_position()

    def set_motion_type(self, motion_type: str) -> None:
        """Set motion: 'circle' or 'figure_eight'."""
        norm = motion_type.lower().replace(" ", "_")
        if norm in ("circle", "figure_eight"):
            self.motion_type = norm
            self.trail.clear()
            self._update_position()

    def set_speed(self, speed: float) -> None:
        """Set target speed multiplier."""
        self.speed = max(0.1, float(speed))

    def get_orbit_path(self, num_points: int = 180) -> List[Tuple[float, float]]:
        """Return the complete orbital trajectory path in world coordinates."""
        path = []
        for i in range(num_points + 1):
            t = (i / num_points) * 2.0 * math.pi
            if self.motion_type == "circle":
                px = self.CENTER_X + self.CIRCLE_RADIUS * math.cos(t)
                py = self.CENTER_Y + self.CIRCLE_RADIUS * math.sin(t)
            else:
                px = self.CENTER_X + self.FIG8_AMP_X * math.sin(t)
                py = self.CENTER_Y + self.FIG8_AMP_Y * math.sin(2.0 * t)
            path.append((px, py))
        return path
