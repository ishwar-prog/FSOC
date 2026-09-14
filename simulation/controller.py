"""
simulation/controller.py — Rate-Limited Proportional Coarse Alignment Controller (Stage 1).

Implements the coarse gimbal alignment control loop:
  1. Compute target azimuth & elevation from 3D relative vector.
  2. Calculate angular errors (Δpan, Δtilt).
  3. Apply proportional control with rate limiting — no teleporting.

Architecture note:
  The controller only takes `target_pos_estimate` as input — in Stage 2 this
  will be replaced by the CV-detected beacon position without changing the
  controller interface.
"""

import math
import numpy as np
from typing import Tuple
from .camera import VirtualCamera3D


class CoarseAlignmentController:
    """Rate-limited proportional pan/tilt coarse alignment controller.

    Drives the virtual camera's pan and tilt angles toward the 3D target
    at a physically believable slew rate (default max 5°/s).

    The controller guarantees:
      - No instantaneous angle jumps (rate-limited).
      - Proportional approach: faster when error is large, slower near target.
      - Configurable max slew rate and proportional gain.
    """

    DEFAULT_MAX_RATE_DEG: float = 5.0   # degrees per second
    DEFAULT_KP: float = 2.0             # proportional gain

    def __init__(
        self,
        max_rate_deg: float = DEFAULT_MAX_RATE_DEG,
        kp: float = DEFAULT_KP,
    ) -> None:
        """
        Args:
            max_rate_deg: Maximum pan/tilt slew rate in degrees per second.
            kp:           Proportional control gain.
        """
        self.max_rate_rad: float = math.radians(max_rate_deg)
        self.kp: float = float(kp)

    def set_max_rate(self, max_rate_deg: float) -> None:
        """Set maximum slew rate in degrees/second (clamped 0.5–30°/s)."""
        self.max_rate_rad = math.radians(max(0.5, min(30.0, float(max_rate_deg))))

    def reset(self) -> None:
        """No persistent velocity state in this controller — no-op for interface compatibility."""
        pass

    def update(
        self,
        camera: VirtualCamera3D,
        target_pos_estimate: np.ndarray,
        dt: float,
    ) -> Tuple[float, float]:
        """Compute one control step: compute angular error → apply rate-limited pan/tilt update.

        Args:
            camera:               The VirtualCamera3D to drive.
            target_pos_estimate:  Estimated 3D world position of the beacon target.
                                  (In Stage 1: ground-truth. In Stage 2: CV-detected.)
            dt:                   Time step in seconds.

        Returns:
            (dpan_applied, dtilt_applied): Angular change applied this step (radians).
        """
        if dt <= 0:
            return (0.0, 0.0)

        dt = min(dt, 0.05)  # Clamp to 50ms for stability

        # 1. Compute relative vector from Terminal A (camera) to target
        rel = np.array(target_pos_estimate, dtype=float) - camera.position

        # 2. Compute desired pan and tilt angles (azimuth & elevation)
        dist_xz = math.hypot(float(rel[0]), float(rel[2]))

        pan_target = math.atan2(float(rel[0]), float(rel[2]))   # azimuth
        tilt_target = math.atan2(-float(rel[1]), dist_xz)       # elevation (−Y = up)

        # 3. Compute angular errors
        dpan = pan_target - camera.pan
        dtilt = tilt_target - camera.tilt

        # Wrap pan error to [-π, +π] for correct shortest-path rotation
        dpan = (dpan + math.pi) % (2.0 * math.pi) - math.pi
        dtilt = (dtilt + math.pi) % (2.0 * math.pi) - math.pi

        # 4. Proportional control command
        cmd_pan = self.kp * dpan
        cmd_tilt = self.kp * dtilt

        # 5. Rate-limit: clamp to max_rate
        max_delta = self.max_rate_rad * dt
        cmd_pan = max(-max_delta, min(max_delta, cmd_pan * dt))
        cmd_tilt = max(-max_delta, min(max_delta, cmd_tilt * dt))

        # 6. Apply to camera angles (also respects camera's own angle limits)
        camera.set_pan(camera.pan + cmd_pan)
        camera.set_tilt(camera.tilt + cmd_tilt)

        return (cmd_pan, cmd_tilt)

    def update_from_pixel_error(
        self,
        camera,
        px_x: float,
        px_y: float,
        dt: float,
    ) -> None:
        """Stage 2: Drive camera from pixel centroid error (no 3D world position needed).

        Converts pixel error from bore-sight to angular error and applies
        the same rate-limited proportional control as update().
        """
        if dt <= 0:
            return
        dt = min(dt, 0.05)
        ex = float(px_x) - camera.CENTER_X
        ey = float(px_y) - camera.CENTER_Y
        dpan  = math.atan2(ex,  camera.FX)
        dtilt = math.atan2(-ey, camera.FY)
        max_delta = self.max_rate_rad * dt
        cmd_pan  = max(-max_delta, min(max_delta, self.kp * dpan  * dt))
        cmd_tilt = max(-max_delta, min(max_delta, self.kp * dtilt * dt))
        camera.set_pan(camera.pan   + cmd_pan)
        camera.set_tilt(camera.tilt + cmd_tilt)
        return (cmd_pan, cmd_tilt)

    @property
    def max_rate_deg(self) -> float:
        """Maximum slew rate in degrees per second."""
        return math.degrees(self.max_rate_rad)
