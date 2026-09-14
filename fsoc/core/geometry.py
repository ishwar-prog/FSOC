"""Camera intrinsics and line-of-sight (LOS) geometry.

Conventions (right-handed world frame):
  +X east/right, +Y up, +Z north/forward.
  Gimbal azimuth (az) rotates about +Y, positive towards +X.
  Gimbal elevation (el) is positive upwards.
  Image: u to the right, v downwards, principal point (cx, cy).

All tracking is done in LOS angles (az, el) rather than pixels. A measurement is
  LOS = gimbal encoder angles  (+)  pixel offset converted through the intrinsics
which makes the tracker immune to the camera's own motion. This is what allows the
same algorithm to run on a real gimbal (encoders), on video (static or virtual crop
gimbal) or in simulation.
"""

import math
from dataclasses import dataclass
from typing import Optional, Tuple

TWO_PI = 2.0 * math.pi


def wrap_pi(a: float) -> float:
    """Wrap an angle to [-pi, pi)."""
    return (a + math.pi) % TWO_PI - math.pi


@dataclass(frozen=True)
class CameraIntrinsics:
    width: int
    height: int
    fx: float
    fy: float
    cx: float
    cy: float

    @classmethod
    def from_fov(cls, width: int = 640, height: int = 480,
                 hfov_deg: float = 4.0, vfov_deg: float = 3.0) -> "CameraIntrinsics":
        fx = (width / 2.0) / math.tan(math.radians(hfov_deg) / 2.0)
        fy = (height / 2.0) / math.tan(math.radians(vfov_deg) / 2.0)
        return cls(width, height, fx, fy, width / 2.0, height / 2.0)

    @property
    def hfov_deg(self) -> float:
        return math.degrees(2.0 * math.atan(self.width / 2.0 / self.fx))

    @property
    def vfov_deg(self) -> float:
        return math.degrees(2.0 * math.atan(self.height / 2.0 / self.fy))

    @property
    def rad_per_px(self) -> float:
        return 1.0 / self.fx

    @property
    def px_per_deg(self) -> float:
        return self.fx * math.pi / 180.0


def gimbal_basis(az: float, el: float):
    """Return (forward, right, up) unit vectors of the camera for gimbal angles."""
    ca, sa = math.cos(az), math.sin(az)
    ce, se = math.cos(el), math.sin(el)
    f = (ce * sa, se, ce * ca)
    r = (ca, 0.0, -sa)
    u = (-se * sa, ce, -se * ca)
    return f, r, u


def direction_to_los(dx: float, dy: float, dz: float) -> Tuple[float, float]:
    return math.atan2(dx, dz), math.atan2(dy, math.hypot(dx, dz))


def los_to_direction(az: float, el: float) -> Tuple[float, float, float]:
    ce = math.cos(el)
    return ce * math.sin(az), math.sin(el), ce * math.cos(az)


def pixel_to_los(u: float, v: float, gimbal_az: float, gimbal_el: float,
                 K: CameraIntrinsics) -> Tuple[float, float]:
    """Convert an image point to a world LOS given the camera pointing."""
    f, r, up = gimbal_basis(gimbal_az, gimbal_el)
    x = (u - K.cx) / K.fx
    y = -(v - K.cy) / K.fy
    dx = r[0] * x + up[0] * y + f[0]
    dy = r[1] * x + up[1] * y + f[1]
    dz = r[2] * x + up[2] * y + f[2]
    return direction_to_los(dx, dy, dz)


def los_to_pixel(az: float, el: float, gimbal_az: float, gimbal_el: float,
                 K: CameraIntrinsics) -> Optional[Tuple[float, float]]:
    """Project a world LOS into the image. None if behind the camera."""
    d = los_to_direction(az, el)
    return direction_to_pixel(d, gimbal_az, gimbal_el, K)


def direction_to_pixel(d, gimbal_az: float, gimbal_el: float,
                       K: CameraIntrinsics) -> Optional[Tuple[float, float]]:
    f, r, up = gimbal_basis(gimbal_az, gimbal_el)
    zc = d[0] * f[0] + d[1] * f[1] + d[2] * f[2]
    if zc <= 1e-6:
        return None
    xc = d[0] * r[0] + d[1] * r[1] + d[2] * r[2]
    yc = d[0] * up[0] + d[1] * up[1] + d[2] * up[2]
    return K.cx + K.fx * xc / zc, K.cy - K.fy * yc / zc


def angular_separation(az1: float, el1: float, az2: float, el2: float) -> float:
    """Great-circle angle between two LOS directions (radians)."""
    a = los_to_direction(az1, el1)
    b = los_to_direction(az2, el2)
    dot = max(-1.0, min(1.0, a[0] * b[0] + a[1] * b[1] + a[2] * b[2]))
    return math.acos(dot)
