"""
simulation/camera.py — Virtual 3D Pan/Tilt Camera (Stage 1 Alpha).

Implements a true pinhole perspective camera with pan (azimuth) and tilt (elevation)
degrees of freedom. Replaces the 2D sliding-window camera from the previous build.

Coordinate frame:
  +X = Right
  +Y = Up
  +Z = Forward (into scene)

Pan (ψ): rotation around Y axis (left/right azimuth)
Tilt (θ): rotation around camera-right axis (up/down elevation)
"""

import math
import numpy as np
from typing import Tuple, Optional


# Camera constants
RESOLUTION_W: int = 640
RESOLUTION_H: int = 480

# Field of view: 4° horizontal × 3° vertical (per SIH26169 spec)
FOV_H_DEG: float = 4.0
FOV_V_DEG: float = 3.0


class VirtualCamera3D:
    """Virtual 3D pan/tilt camera with pinhole perspective projection.

    The camera is always mounted at Terminal A's position (default: world origin).
    Pan and Tilt angles drive the camera look-direction.

    Key methods:
      project_world_point()  — projects a 3D world point onto the 640×480 sensor
      get_look_vectors()     — returns (forward, right, up) unit vectors
    """

    WIDTH: int = RESOLUTION_W
    HEIGHT: int = RESOLUTION_H
    CENTER_X: float = RESOLUTION_W / 2.0   # 320.0
    CENTER_Y: float = RESOLUTION_H / 2.0   # 240.0

    FOV_H: float = math.radians(FOV_H_DEG)  # 0.06981 rad
    FOV_V: float = math.radians(FOV_V_DEG)  # 0.05236 rad

    # Pinhole focal lengths in pixels
    FX: float = RESOLUTION_W / (2.0 * math.tan(FOV_H / 2.0))
    FY: float = RESOLUTION_H / (2.0 * math.tan(FOV_V / 2.0))

    def __init__(
        self,
        position: Optional[np.ndarray] = None,
        pan: float = 0.0,
        tilt: float = 0.0,
    ) -> None:
        """
        Args:
            position: Camera world position (defaults to origin).
            pan:      Initial pan angle in radians.
            tilt:     Initial tilt angle in radians.
        """
        self.position: np.ndarray = (
            np.zeros(3, dtype=float) if position is None else np.array(position, dtype=float)
        )
        self.pan: float = float(pan)    # ψ: azimuth angle (rad)
        self.tilt: float = float(tilt)  # θ: elevation angle (rad)

        # Angle limits (±180° pan, ±60° tilt)
        self.pan_limit: float = math.radians(180.0)
        self.tilt_limit: float = math.radians(60.0)

    def reset(self) -> None:
        """Reset pan and tilt to zero (boresight forward / +Z)."""
        self.pan = 0.0
        self.tilt = 0.0

    def set_pan(self, pan_rad: float) -> None:
        """Set pan angle in radians (clamped to ±180°)."""
        self.pan = max(-self.pan_limit, min(self.pan_limit, float(pan_rad)))

    def set_tilt(self, tilt_rad: float) -> None:
        """Set tilt angle in radians (clamped to ±60°)."""
        self.tilt = max(-self.tilt_limit, min(self.tilt_limit, float(tilt_rad)))

    def get_look_vectors(self) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Compute camera basis vectors (forward, right, up) from current pan/tilt.

        Pan (ψ) rotates around world Y.
        Tilt (θ) rotates around the resulting right vector.

        Returns:
            forward: Unit vector pointing along camera optical axis.
            right:   Unit vector pointing camera-right.
            up:      Unit vector pointing camera-up (= forward × right).
        """
        psi = self.pan
        theta = self.tilt

        # Forward vector after pan & tilt
        fx = math.cos(theta) * math.sin(psi)
        fy = -math.sin(theta)
        fz = math.cos(theta) * math.cos(psi)
        forward = np.array([fx, fy, fz], dtype=float)

        # Right vector (independent of tilt — only depends on pan)
        rx = math.cos(psi)
        ry = 0.0
        rz = -math.sin(psi)
        right = np.array([rx, ry, rz], dtype=float)

        # Up vector = right × forward (note: cross of right × forward gives up)
        up = np.cross(right, forward)
        # Normalize for robustness
        up_norm = np.linalg.norm(up)
        if up_norm > 1e-9:
            up = up / up_norm

        return forward, right, up

    def project_world_point(
        self, world_pos: np.ndarray
    ) -> Tuple[float, float, bool, float]:
        """Project a 3D world point onto the 640×480 sensor plane.

        Args:
            world_pos: 3D world coordinates [X, Y, Z].

        Returns:
            (sx, sy, in_fov, depth)
            sx, sy:  Screen pixel coordinates (may be outside [0,W]×[0,H]).
            in_fov:  True if point projects inside the sensor FOV.
            depth:   Signed depth along camera forward axis (negative = behind camera).
        """
        forward, right, up = self.get_look_vectors()

        # Vector from camera to world point
        v = np.array(world_pos, dtype=float) - self.position

        # Project onto camera axes
        xc = float(np.dot(v, right))    # camera-right component
        yc = float(np.dot(v, up))       # camera-up component
        zc = float(np.dot(v, forward))  # depth along camera axis

        # Reject points behind camera
        if zc <= 1e-3:
            return (self.CENTER_X, self.CENTER_Y, False, zc)

        # Pinhole projection
        sx = self.CENTER_X + self.FX * (xc / zc)
        sy = self.CENTER_Y - self.FY * (yc / zc)  # Y flipped: +cam_y = up = -screen_y

        in_fov = (0.0 <= sx <= self.WIDTH) and (0.0 <= sy <= self.HEIGHT)
        return (sx, sy, in_fov, zc)

    def get_angular_error_to_point(self, world_pos: np.ndarray) -> Tuple[float, float, float]:
        """Compute angular error (in radians) from camera bore-sight to a world point.

        Returns:
            (dpan, dtilt, total_error_rad)
            dpan:           Pan angular error (positive = target is to the right).
            dtilt:          Tilt angular error (positive = target is above bore-sight).
            total_error_rad: Combined magnitude of angular error.
        """
        forward, right, up = self.get_look_vectors()
        v = np.array(world_pos, dtype=float) - self.position
        dist = np.linalg.norm(v)
        if dist < 1e-6:
            return (0.0, 0.0, 0.0)

        v_norm = v / dist

        # Component along right and up axes
        xc = float(np.dot(v_norm, right))
        yc = float(np.dot(v_norm, up))
        zc = float(np.dot(v_norm, forward))

        if zc <= 0:
            # Point behind camera — return large error
            return (math.pi, math.pi, math.pi * math.sqrt(2))

        dpan = math.atan2(xc, zc)
        dtilt = math.atan2(yc, zc)
        total = math.hypot(dpan, dtilt)
        return (dpan, dtilt, total)

    def pixel_error(self, world_pos: np.ndarray) -> Tuple[float, float, float]:
        """Return pixel-space error (ex, ey, magnitude) from bore-sight to projected point."""
        sx, sy, in_fov, depth = self.project_world_point(world_pos)
        ex = sx - self.CENTER_X
        ey = sy - self.CENTER_Y
        return (ex, ey, math.hypot(ex, ey))

    @property
    def pan_deg(self) -> float:
        """Current pan angle in degrees."""
        return math.degrees(self.pan)

    @property
    def tilt_deg(self) -> float:
        """Current tilt angle in degrees."""
        return math.degrees(self.tilt)
