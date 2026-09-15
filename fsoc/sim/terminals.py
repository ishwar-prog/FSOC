"""Terminal models: remote terminal B (drone, aircraft, ship, satellite, space station) and
ground terminal A (fixed station, vehicle, ship deck).

Everything the operator can change live — speed, distance, bearing, altitude, variation,
orbit parameters, waypoints, ground position — is stored as a *time history* rather
than a single value. Positions therefore stay analytic functions of time: every thread
(renderer, cue, evaluator, world view trails) can ask "where was it at t?" and changes
ramp smoothly instead of teleporting the terminal.
"""

import math
import threading
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

from . import patterns as pat

Vec = Tuple[float, float, float]
DEG = math.pi / 180.0
TAU = 2 * math.pi
RE = 6_371_000.0
MU = 3.986004418e14


def _smoothstep(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


# =============================================================================== platforms
@dataclass(frozen=True)
class PlatformInfo:
    key: str
    name: str
    domain: str             # aerial | sea | space
    summary: str
    ref_range_km: float     # range at which the beacon has its nominal brightness
    max_speed: float        # m/s (aerial / sea manual drive)


PLATFORMS: List[PlatformInfo] = [
    PlatformInfo("quad", "Drone", "aerial", "Multirotor UAV relay — hovers, weaves, climbs.", 1.8, 18.0),
    PlatformInfo("fixedwing", "Aircraft", "aerial", "Fixed-wing UAV / aircraft — cannot hover, flies patterns.", 2.2, 45.0),
    PlatformInfo("ship", "Ship", "sea", "Mast-top terminal on a vessel rolling in a sea state.", 2.6, 9.0),
    PlatformInfo("satellite", "Satellite", "space", "Low-Earth-orbit smallsat or geostationary relay.", 900.0, 0.0),
    PlatformInfo("station", "Space station", "space", "ISS-class station — large, bright, 420 km orbit.", 650.0, 0.0),
]
PLATFORM_BY_KEY = {p.key: p for p in PLATFORMS}


# ============================================================================ smooth params
class SmoothParam:
    """Value with a history of smooth (smoothstep) transitions."""

    def __init__(self, value: float, ramp_s: float = 2.5) -> None:
        self.ramp = ramp_s
        self._hist: List[Tuple[float, float, float]] = [(-1e9, value, value)]

    def value(self, t: float) -> float:
        h = self._hist
        for i in range(len(h) - 1, -1, -1):
            t0, a, b = h[i]
            if t >= t0:
                return a + (b - a) * _smoothstep((t - t0) / self.ramp)
        return h[0][1]

    def target(self) -> float:
        return self._hist[-1][2]

    def set(self, t: float, v: float) -> None:
        cur = self.value(t)
        h = self._hist + [(t, cur, float(v))]
        self._hist = h[-24:]

    def reset(self, v: Optional[float] = None) -> None:
        self._hist = [(-1e9, self.target() if v is None else v, self.target() if v is None else v)]


class TimeWarp:
    """Pattern time τ(t) = ∫ speed dt with linear speed ramps (no jumps when speed changes)."""

    def __init__(self, speed: float = 1.0, ramp_s: float = 1.5) -> None:
        self.ramp = ramp_s
        self._seg = [(0.0, 0.0, speed, speed)]

    def _find(self, t: float):
        seg = self._seg
        for i in range(len(seg) - 1, -1, -1):
            if t >= seg[i][0]:
                return seg[i]
        return seg[0]

    def speed(self, t: float) -> float:
        t0, _, s0, s1 = self._find(t)
        return s0 + (s1 - s0) * max(0.0, min(1.0, (t - t0) / self.ramp))

    def tau(self, t: float) -> float:
        t0, tau0, s0, s1 = self._find(t)
        dt = t - t0
        T = self.ramp
        if dt < 0:
            return tau0 + s0 * dt
        if dt < T:
            return tau0 + s0 * dt + (s1 - s0) * dt * dt / (2 * T)
        return tau0 + (s0 + s1) * T / 2 + s1 * (dt - T)

    def set(self, t: float, speed: float) -> None:
        seg = self._seg + [(t, self.tau(t), self.speed(t), float(speed))]
        self._seg = seg[-32:]

    def reset(self) -> None:
        s = self._seg[-1][3]
        self._seg = [(0.0, 0.0, s, s)]


# ============================================================================== manual drive
class ManualPath:
    """Waypoint driving with platform-limited speed: smooth Hermite legs; aircraft loiter
    around the waypoint (they cannot hover), drones hover, ships hold station."""

    def __init__(self, start: Vec, kind: str) -> None:
        self.kind = kind
        self._legs: List[tuple] = [(-1e9, start, (0.0, 0.0, 0.0), start, 1.0)]

    def _leg(self, t: float):
        legs = self._legs
        for i in range(len(legs) - 1, -1, -1):
            if t >= legs[i][0]:
                return legs[i]
        return legs[0]

    def position(self, t: float) -> Vec:
        t0, p0, v0, p1, T = self._leg(t)
        dt = t - t0
        if dt < T:
            s = dt / T
            h00, h10, h01 = 2 * s ** 3 - 3 * s ** 2 + 1, s ** 3 - 2 * s ** 2 + s, -2 * s ** 3 + 3 * s ** 2
            h11 = s ** 3 - s ** 2
            v1 = self._arrival_velocity(p0, p1)
            return tuple(h00 * p0[i] + h10 * v0[i] * T + h01 * p1[i] + h11 * v1[i] * T for i in range(3))
        return self._hold(p1, p0, dt - T)

    def _arrival_velocity(self, p0: Vec, p1: Vec) -> Vec:
        if self.kind != "fixedwing":
            return (0.0, 0.0, 0.0)
        dx, dz = p1[0] - p0[0], p1[2] - p0[2]
        n = math.hypot(dx, dz) or 1.0
        v = 32.0
        return (dx / n * v, 0.0, dz / n * v)

    def _hold(self, p1: Vec, p0: Vec, dt: float) -> Vec:
        if self.kind == "fixedwing":
            v, R = 32.0, 260.0
            dx, dz = p1[0] - p0[0], p1[2] - p0[2]
            n = math.hypot(dx, dz) or 1.0
            hx, hz = dx / n, dz / n                          # arrival heading
            cx, cz = p1[0] + hz * R, p1[2] - hx * R          # loiter centre to the right
            a0 = math.atan2(p1[0] - cx, p1[2] - cz)
            a = a0 + v / R * dt
            return (cx + R * math.sin(a), p1[1] + 6 * math.sin(dt * 0.3), cz + R * math.cos(a))
        if self.kind == "ship":
            return (p1[0] + 3 * math.sin(dt * 0.07), p1[1], p1[2] + 3 * math.cos(dt * 0.05))
        return (p1[0] + 2.5 * math.sin(dt * 0.19), p1[1] + 1.2 * math.sin(dt * 0.23), p1[2] + 2.0 * math.cos(dt * 0.13))

    def goto(self, t: float, target: Vec, max_speed: float) -> None:
        p = self.position(t)
        q = self.position(t + 0.05)
        v0 = tuple((q[i] - p[i]) / 0.05 for i in range(3))
        dist = math.dist(p, target)
        T = max(2.5, 1.35 * dist / max(1.0, max_speed))
        self._legs = (self._legs + [(t, p, v0, target, T)])[-16:]


# ================================================================================== orbits
class OrbitPass:
    """Circular-orbit pass over the ground station (spherical Earth, station at origin).

    The orbit plane is placed so the pass culminates at `max_el_deg`, travelling along
    `heading_deg`. Pass geometry follows the standard slant-range / elevation relations,
    so angular rates near culmination are the real ~0.5–1.2 °/s a LEO tracker must follow.
    """

    def __init__(self, alt_km: float, max_el_deg: float, heading_deg: float, start_el_deg: float = 12.0) -> None:
        self.r = RE + alt_km * 1000.0
        self.omega = math.sqrt(MU / self.r ** 3)
        gmin = self._gamma_for_el(max_el_deg * DEG)
        a = heading_deg * DEG
        z = (0.0, 1.0, 0.0)
        w = (math.cos(a), 0.0, -math.sin(a))
        self.u = tuple(math.cos(gmin) * z[i] + math.sin(gmin) * w[i] for i in range(3))
        self.v = (math.sin(a), 0.0, math.cos(a))
        lo, hi = -math.pi / 2, 0.0
        target = start_el_deg * DEG
        for _ in range(60):
            mid = 0.5 * (lo + hi)
            if self.elevation(self._pos(mid)) < target:
                lo = mid
            else:
                hi = mid
        self.theta0 = hi
        self.period = 2 * abs(self.theta0) / self.omega

    def _gamma_for_el(self, el: float) -> float:
        lo, hi = 0.0, math.acos(RE / self.r)
        for _ in range(60):
            mid = 0.5 * (lo + hi)
            e = math.atan2(math.cos(mid) - RE / self.r, math.sin(mid))
            if e > el:
                lo = mid
            else:
                hi = mid
        return 0.5 * (lo + hi)

    def _pos(self, th: float) -> Vec:
        c, s = math.cos(th), math.sin(th)
        return tuple(self.r * (c * self.u[i] + s * self.v[i]) - (RE if i == 1 else 0.0) for i in range(3))

    @staticmethod
    def elevation(p: Vec) -> float:
        return math.atan2(p[1], math.hypot(p[0], p[2]))

    def position(self, tau: float) -> Vec:
        ph = tau % self.period if tau >= 0 else tau      # before the pass: extrapolate, don't wrap
        return self._pos(self.theta0 + self.omega * ph)

    def phase(self, tau: float) -> float:
        return (tau % self.period) / self.period


class GeoRelay:
    """Geostationary relay (LCRD-class): fixed in the sky, 36 000 km slant range, tiny drift."""

    def __init__(self, el_deg: float = 42.0, az_deg: float = 175.0) -> None:
        self.el, self.az = el_deg * DEG, az_deg * DEG
        self.range = 37_600_000.0
        self.period = 1e9

    def position(self, tau: float) -> Vec:
        el = self.el + 0.004 * DEG * math.sin(tau / 900.0)
        az = self.az + 0.004 * DEG * math.cos(tau / 1100.0)
        ce = math.cos(el)
        return (self.range * ce * math.sin(az), self.range * math.sin(el), self.range * ce * math.cos(az))

    def phase(self, tau: float) -> float:
        return 0.5


# ============================================================================ remote terminal
AERIAL_CENTER = {
    "hover": (140.0, 150.0, 1750.0), "flyby": (0.0, 190.0, 1560.0), "orbit": (-120.0, 210.0, 2150.0),
    "figure8": (60.0, 230.0, 2050.0), "zigzag": (0.0, 165.0, 1700.0), "spiral": (0.0, 176.0, 1950.0),
    "maritime": (-350.0, 25.0, 2600.0), "random": (0.0, 170.0, 1900.0), "transit": (0.0, 25.0, 2400.0),
}


class RemoteTerminal:
    """Terminal B. Thread-safe: readers see an immutable state tuple swapped atomically."""

    BLEND_S = 5.0

    def __init__(self, pattern: str = "orbit", seed: int = 42) -> None:
        self.seed = seed
        self._lock = threading.Lock()
        self.warp = TimeWarp(1.0)
        self.range_km = SmoothParam(0.0)          # 0 → pattern's natural distance
        self.bearing = SmoothParam(0.0)           # degrees offset
        self.alt_off = SmoothParam(0.0)           # metres
        self.variation = SmoothParam(0.25)
        self.orbit_alt = 550.0
        self.max_el = 62.0
        self.heading = 30.0
        self.key = pattern
        self._manual: Optional[ManualPath] = None
        self._state = (self._make_fn(pattern), None, -1e9)
        self.pass_serial = 0

    # ----------------------------------------------------------------- info
    @property
    def info(self) -> pat.PatternInfo:
        return pat.INFO_BY_KEY[self.key]

    @property
    def platform(self) -> PlatformInfo:
        return PLATFORM_BY_KEY[self.info.platform]

    @property
    def space(self) -> bool:
        return self.platform.domain == "space"

    # --------------------------------------------------------------- building
    def _orbit_model(self, key: str):
        if key == "geo_relay":
            return GeoRelay()
        if key == "iss_pass":
            return OrbitPass(420.0, self.max_el, self.heading)
        return OrbitPass(self.orbit_alt, self.max_el, self.heading)

    def _make_fn(self, key: str) -> Callable[[float], Vec]:
        if key in ("leo_pass", "iss_pass", "geo_relay"):
            model = self._orbit_model(key)
            self.orbit = model
            warp = self.warp
            return lambda t, m=model, w=warp: m.position(w.tau(t))
        if key.startswith("manual"):
            return lambda t: self._manual.position(t) if self._manual else (0.0, 150.0, 1800.0)
        base = pat.make_pattern(key, self.seed)
        center = AERIAL_CENTER.get(key, (0.0, 170.0, 1900.0))
        sea = pat.INFO_BY_KEY[key].platform == "ship"
        warp, rng, brg, alt, var = self.warp, self.range_km, self.bearing, self.alt_off, self.variation
        cb = math.atan2(center[0], center[2])
        cr = math.hypot(center[0], center[2])
        ph = (self.seed % 97) * 0.37

        def fn(t: float) -> Vec:
            tau = warp.tau(t)
            p = base(tau)
            R = rng.value(t) * 1000.0 or cr
            db = brg.value(t) * DEG
            b = cb + db
            rx, ry, rz = p[0] - center[0], p[1] - center[1], p[2] - center[2]
            cdb, sdb = math.cos(db), math.sin(db)
            x = R * math.sin(b) + cdb * rx + sdb * rz
            z = R * math.cos(b) - sdb * rx + cdb * rz
            y = center[1] + ry + (0.0 if sea else alt.value(t))
            v = var.value(t)
            if v > 0.001:
                x += v * (14 * math.sin(0.11 * t + ph) + 6 * math.sin(0.37 * t + 2 * ph))
                z += v * (10 * math.sin(0.07 * t + 3 * ph) + 5 * math.sin(0.29 * t + ph))
                if not sea:
                    y += v * (6 * math.sin(0.23 * t + ph) + 2.5 * math.sin(0.9 * t + 4 * ph))
            return (x, max(y, 3.0), z)
        return fn

    # --------------------------------------------------------------- control
    def set_pattern(self, key: str, t: float) -> None:
        if key == self.key or key not in pat.INFO_BY_KEY:
            return
        with self._lock:
            old_space = self.space
            fn, prev, sw = self._state
            if key.startswith("manual"):
                start = self.position(t)
                self._manual = ManualPath(start, pat.INFO_BY_KEY[key].platform)
            new_fn = self._make_fn(key)
            self.key = key
            if old_space or self.space:
                self._state = (new_fn, None, -1e9)
                self.pass_serial += 1
            else:
                def frozen(tt: float, fn=fn, prev=prev, sw=sw) -> Vec:
                    return self._blend(fn, prev, sw, tt)
                self._state = (new_fn, (frozen, t), t)

    def goto(self, t: float, x: float, z: float, y: Optional[float] = None) -> None:
        """Manual drive: switches the platform to its manual mode and steers to (x, z)."""
        plat = self.info.platform
        if plat not in ("quad", "fixedwing", "ship"):
            return
        if not self.key.startswith("manual"):
            self.set_pattern("manual_" + plat, t)
        cur = self.position(t)
        yy = cur[1] if y is None else y
        if plat == "ship":
            yy = 25.0
        self._manual.goto(t, (x, yy, z), self.platform.max_speed * max(0.3, self.warp.speed(t)))

    def set_speed(self, t: float, speed: float) -> None:
        self.warp.set(t, speed)

    def set_orbit(self, t: float, alt_km: Optional[float] = None, max_el: Optional[float] = None,
                  heading: Optional[float] = None) -> None:
        if alt_km is not None:
            self.orbit_alt = alt_km
        if max_el is not None:
            self.max_el = max_el
        if heading is not None:
            self.heading = heading
        if self.key in ("leo_pass", "iss_pass"):
            with self._lock:
                self._state = (self._make_fn(self.key), None, -1e9)
                self.pass_serial += 1

    def reseed(self, seed: int) -> None:
        self.seed = seed
        self.warp.reset()
        with self._lock:
            if self.key.startswith("manual"):
                self._manual = ManualPath((0.0, 150.0, 1800.0), self.info.platform)
            self._state = (self._make_fn(self.key), None, -1e9)

    # ------------------------------------------------------------- queries
    def _blend(self, fn, prev, sw, t: float) -> Vec:
        p = fn(t)
        if prev is None:
            return p
        w = (t - sw) / self.BLEND_S
        if w >= 1.0:
            return p
        w = _smoothstep(w)
        q = prev[0](t)
        return (q[0] + (p[0] - q[0]) * w, q[1] + (p[1] - q[1]) * w, q[2] + (p[2] - q[2]) * w)

    def position(self, t: float) -> Vec:
        fn, prev, sw = self._state
        return self._blend(fn, prev, sw, t)

    def velocity(self, t: float) -> Vec:
        h = 0.01
        a, b = self.position(t - h), self.position(t + h)
        return ((b[0] - a[0]) / (2 * h), (b[1] - a[1]) / (2 * h), (b[2] - a[2]) / (2 * h))

    def ship_roll(self, t: float) -> float:
        return pat.ship_motion(self.warp.tau(t))[3] if self.info.platform == "ship" else 0.0

    def orbit_phase(self, t: float) -> float:
        return self.orbit.phase(self.warp.tau(t)) if self.space else 0.0

    def waypoint(self) -> Optional[Vec]:
        if self.key.startswith("manual") and self._manual is not None:
            return self._manual._legs[-1][3]
        return None


# ============================================================================ ground terminal
@dataclass(frozen=True)
class MountInfo:
    key: str
    name: str
    summary: str


MOUNTS: List[MountInfo] = [
    MountInfo("fixed", "Fixed station", "Tripod / observatory pier — no platform motion."),
    MountInfo("vehicle", "Vehicle", "Terminal on a truck driving a road; INS keeps pointing stable."),
    MountInfo("ship", "Ship deck", "Stabilised deck mount on a vessel in a seaway."),
]


class GroundTerminal:
    def __init__(self) -> None:
        self.mount = "fixed"
        self.x = SmoothParam(0.0, 3.0)
        self.z = SmoothParam(0.0, 3.0)
        self.height = SmoothParam(6.0, 2.0)
        self._mount_t = -1e9

    def set_mount(self, t: float, mount: str) -> None:
        self.mount = mount
        self._mount_t = t

    def set_position(self, t: float, x: Optional[float] = None, z: Optional[float] = None,
                     height: Optional[float] = None) -> None:
        if x is not None:
            self.x.set(t, x)
        if z is not None:
            self.z.set(t, z)
        if height is not None:
            self.height.set(t, height)

    def position(self, t: float) -> Vec:
        x, y, z = self.x.value(t), self.height.value(t), self.z.value(t)
        w = _smoothstep((t - self._mount_t) / 3.0)
        if self.mount == "vehicle":
            x += w * 260.0 * math.sin(TAU * t / 110.0)
            y += w * 0.05 * math.sin(t * 9.1)
        elif self.mount == "ship":
            x += w * 1.3 * math.sin(TAU * t / 9.2)
            z += w * 0.8 * math.sin(TAU * t / 7.1)
            y += w * 0.9 * math.sin(TAU * t / 8.3)
        return (x, y, z)

    def residual_jitter(self, t: float) -> Tuple[float, float]:
        """Residual line-of-sight error the inertial stabilisation cannot remove (rad)."""
        if self.mount == "vehicle":
            a = 0.015 * DEG
            return a * math.sin(TAU * 7.3 * t), a * 0.8 * math.sin(TAU * 5.9 * t + 1.0)
        if self.mount == "ship":
            a = 0.03 * DEG
            return a * math.sin(TAU * 0.21 * t), a * math.sin(TAU * 0.17 * t + 0.6)
        return 0.0, 0.0
