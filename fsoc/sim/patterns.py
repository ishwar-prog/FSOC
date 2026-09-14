"""Eight beacon (remote terminal) motion patterns.

Every pattern is an analytic, smooth function of time with platform-realistic speeds
and accelerations, so trajectories are exactly reproducible and switching between
patterns can be blended without jumps. World frame: +X right, +Y up, +Z down-range.
"""

import math
from dataclasses import dataclass
from typing import Callable, Dict, List, Tuple

import numpy as np

TAU = 2.0 * math.pi
Vec = Tuple[float, float, float]


@dataclass(frozen=True)
class PatternInfo:
    key: str
    name: str
    platform: str        # quad | fixedwing | ship
    summary: str
    speed: str


PATTERN_INFOS: List[PatternInfo] = [
    PatternInfo("hover", "Hover Hold", "quad",
                "Quadcopter station-keeping at 1.8 km with wind-gust drift.", "0–3 m/s"),
    PatternInfo("flyby", "Linear Flyby", "fixedwing",
                "Fixed-wing racetrack: long straight passes with banked turns.", "34 m/s"),
    PatternInfo("orbit", "Circular Orbit", "fixedwing",
                "Loiter orbit of 380 m radius around a point 2.1 km away.", "24 m/s"),
    PatternInfo("figure8", "Figure-Eight", "fixedwing",
                "Lissajous surveillance pattern with changing range and bearing.", "20–45 m/s"),
    PatternInfo("zigzag", "Zig-Zag Evasive", "quad",
                "Aggressive ~1 g lateral weaving with altitude bobbing.", "up to 20 m/s"),
    PatternInfo("spiral", "Spiral Approach", "quad",
                "Spirals in from 3 km to 0.9 km and back out (large range change).", "15–30 m/s"),
    PatternInfo("maritime", "Maritime Sway", "ship",
                "Ship-mast beacon at 2.6 km rolling and pitching in a sea state.", "5 m/s + roll"),
    PatternInfo("random", "Random Manoeuvre", "quad",
                "Seeded random but smooth manoeuvres — no two runs alike.", "5–30 m/s"),
]
PATTERN_KEYS = [p.key for p in PATTERN_INFOS]
INFO_BY_KEY = {p.key: p for p in PATTERN_INFOS}


def _s(f: float, t: float, ph: float = 0.0) -> float:
    return math.sin(TAU * f * t + ph)


def hover(t: float) -> Vec:
    return (140 + 5.5 * _s(0.071, t) + 2.8 * _s(0.19, t, 1.2) + 0.12 * _s(0.9, t),
            150 + 2.5 * _s(0.11, t, 0.4) + 0.08 * _s(1.3, t),
            1750 + 4.0 * _s(0.053, t, 2.0))


_RT_L, _RT_R, _RT_Z0, _RT_V, _RT_ALT = 1500.0, 260.0, 1300.0, 34.0, 190.0
_RT_P = 2 * _RT_L + TAU * _RT_R


def flyby(t: float) -> Vec:
    s = (_RT_V * t + _RT_L / 2) % _RT_P
    L, R, z0 = _RT_L, _RT_R, _RT_Z0
    if s < L:
        x, z = -L / 2 + s, z0
    elif s < L + math.pi * R:
        a = -math.pi / 2 + (s - L) / R
        x, z = L / 2 + R * math.cos(a), z0 + R + R * math.sin(a)
    elif s < 2 * L + math.pi * R:
        x, z = L / 2 - (s - L - math.pi * R), z0 + 2 * R
    else:
        a = math.pi / 2 + (s - 2 * L - math.pi * R) / R
        x, z = -L / 2 + R * math.cos(a), z0 + R + R * math.sin(a)
    return x, _RT_ALT + 12 * math.sin(TAU * s / _RT_P), z


def orbit(t: float) -> Vec:
    w = 24.0 / 380.0
    return (-120 + 380 * math.sin(w * t), 210 + 15 * math.sin(2 * w * t), 2150 - 380 * math.cos(w * t))


def figure8(t: float) -> Vec:
    w = TAU / 75.0
    return (60 + 520 * math.sin(w * t), 230 + 20 * math.sin(w * t + 0.5), 2050 + 240 * math.sin(2 * w * t))


def zigzag(t: float) -> Vec:
    # ~1 g peak lateral weave: aggressive but within a real quadcopter's envelope
    return (250 * _s(1 / 150, t) + 38 * _s(1 / 14, t) + 1.5 * _s(3 / 14, t),
            165 + 10 * _s(1 / 7.0, t) + 0.8 * _s(0.41, t, 1.0),
            1700 + 300 * _s(1 / 120, t, 1.3))


def spiral(t: float) -> Vec:
    r = 1950 + 1050 * math.cos(TAU * t / 100)
    phi = math.radians(6.0) * _s(1 / 28, t)
    return (r * math.sin(phi) + 60 * math.cos(TAU * t / 20),
            40 + 0.07 * r + 30 * math.sin(TAU * t / 20) + 10 * _s(1 / 19, t),
            r * math.cos(phi))


_SHIP_HDG = math.radians(35.0)


def ship_motion(t: float):
    sx = -350 + 380 * _s(1 / 420, t)
    sz = 2600 + 150 * _s(1 / 400, t, 0.8)
    heave = 1.1 * _s(1 / 7.3, t)
    roll = math.radians(6.5) * _s(1 / 8.7, t) + math.radians(2.2) * _s(1 / 5.3, t, 1.0)
    pitch = math.radians(2.2) * _s(1 / 6.1, t, 0.7)
    return sx, sz, heave, roll, pitch


def maritime(t: float) -> Vec:
    sx, sz, heave, roll, pitch = ship_motion(t)
    mast = 24.0
    lat = (math.cos(_SHIP_HDG), -math.sin(_SHIP_HDG))
    lon = (math.sin(_SHIP_HDG), math.cos(_SHIP_HDG))
    up = mast * math.cos(roll) * math.cos(pitch)
    dl = mast * math.sin(roll)
    dn = mast * math.sin(pitch)
    return (sx + lat[0] * dl + lon[0] * dn, 1.5 + heave + up, sz + lat[1] * dl + lon[1] * dn)


class RandomManoeuvre:
    def __init__(self, seed: int) -> None:
        rng = np.random.default_rng(seed + 9001)
        self.terms = []
        for amp_total in (430.0, 45.0, 300.0):
            f = rng.uniform(0.008, 0.07, 5)
            a = 1.0 / f
            a = a / a.sum() * amp_total
            # keep peak speed platform-realistic (<= ~28 m/s per axis)
            speed = float((a * TAU * f).sum())
            if speed > 28.0:
                a *= 28.0 / speed
            ph = rng.uniform(0, TAU, 5)
            self.terms.append((f, a, ph))

    def __call__(self, t: float) -> Vec:
        c = (0.0, 170.0, 1900.0)
        out = []
        for i, (f, a, ph) in enumerate(self.terms):
            out.append(c[i] + float((a * np.sin(TAU * f * t + ph)).sum()))
        return out[0], out[1], out[2]


def make_pattern(key: str, seed: int) -> Callable[[float], Vec]:
    return {
        "hover": hover, "flyby": flyby, "orbit": orbit, "figure8": figure8,
        "zigzag": zigzag, "spiral": spiral, "maritime": maritime,
    }.get(key) or RandomManoeuvre(seed)


class PatternMixer:
    """Current pattern with a smooth cross-blend when the operator switches pattern."""

    BLEND_S = 5.0

    def __init__(self, key: str = "orbit", seed: int = 42) -> None:
        self.seed = seed
        self.key = key
        # (fn, prev, switch_t) swapped atomically so readers on other threads never
        # see a half-updated blend.
        self._state = (make_pattern(key, seed), None, -1e9)

    @property
    def info(self) -> PatternInfo:
        return INFO_BY_KEY[self.key]

    def set_pattern(self, key: str, t: float) -> None:
        if key == self.key or key not in INFO_BY_KEY:
            return
        fn, prev, sw = self._state

        def frozen(tt: float, fn=fn, prev=prev, sw=sw) -> Vec:
            return self._blend(fn, prev, sw, tt)

        self._state = (make_pattern(key, self.seed), (frozen, t), t)
        self.key = key

    def reseed(self, seed: int) -> None:
        self.seed = seed
        self._state = (make_pattern(self.key, seed), None, -1e9)

    def _blend(self, fn, prev, sw, t: float) -> Vec:
        p = fn(t)
        if prev is None:
            return p
        w = (t - sw) / self.BLEND_S
        if w >= 1.0:
            return p
        w = max(0.0, w)
        w = w * w * (3 - 2 * w)
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
        return ship_motion(t)[3] if self.key == "maritime" else 0.0
