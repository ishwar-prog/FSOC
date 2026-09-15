"""Night-sky clutter for space targets: stars, other satellites, a planet.

Stars are a seeded catalogue (magnitude distribution following real star counts,
N(<m) ∝ 10^(0.45 m)) that rotates with sidereal time about the celestial pole, so they
drift relative to a GEO relay exactly as in a real telescope. Other resident space
objects cross the field on their own tracks; some tumble and glint periodically, which
is precisely the kind of "blinking" clutter a beacon identifier must reject.
"""

import math
import random
from typing import List, Tuple

import numpy as np

DEG = math.pi / 180.0
OMEGA_EARTH = 7.2921159e-5
LATITUDE = 24.6 * DEG            # e.g. an optical ground station site in western India


class StarCatalog:
    BIN = 2.0                    # degrees

    def __init__(self, seed: int, count: int = 60000, m_min: float = -1.0, m_max: float = 9.0) -> None:
        rng = np.random.default_rng(seed + 5150)
        # uniform over the sphere
        z = rng.uniform(-1.0, 1.0, count)
        phi = rng.uniform(0, 2 * math.pi, count)
        s = np.sqrt(1 - z * z)
        d = np.stack([s * np.sin(phi), z, s * np.cos(phi)], axis=1)       # x east, y up, z north
        # magnitudes: cumulative counts grow ~10^(0.45 m)
        u = rng.uniform(0, 1, count)
        k = 0.45 * math.log(10)
        lo, hi = math.exp(k * m_min), math.exp(k * m_max)
        mags = np.log(lo + u * (hi - lo)) / k
        self.dirs = d
        self.mags = mags
        self.twinkle = rng.uniform(0, 1000, count)
        az = np.degrees(np.arctan2(d[:, 0], d[:, 2])) % 360.0
        el = np.degrees(np.arcsin(np.clip(d[:, 1], -1, 1)))
        self._bins = {}
        bx = (az // self.BIN).astype(int)
        by = ((el + 90) // self.BIN).astype(int)
        for i, key in enumerate(zip(bx.tolist(), by.tolist())):
            self._bins.setdefault(key, []).append(i)
        self._bins = {k: np.array(v) for k, v in self._bins.items()}
        pole = np.array([0.0, math.sin(LATITUDE), math.cos(LATITUDE)])
        self.pole = pole

    def _rotate(self, v: np.ndarray, ang: float) -> np.ndarray:
        k = self.pole
        c, s = math.cos(ang), math.sin(ang)
        return v * c + np.cross(k, v) * s + np.outer(v @ k, k) * (1 - c)

    def in_view(self, t: float, az: float, el: float, radius_deg: float) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Stars within radius of (az, el) at time t: (directions Nx3, magnitudes, twinkle seeds)."""
        ang = -OMEGA_EARTH * t
        c = np.array([math.cos(el) * math.sin(az), math.sin(el), math.cos(el) * math.cos(az)])
        c0 = self._rotate(c[None, :], -ang)[0]                   # look direction in catalogue frame
        az0 = math.degrees(math.atan2(c0[0], c0[2])) % 360.0
        el0 = math.degrees(math.asin(max(-1.0, min(1.0, c0[1]))))
        r = radius_deg + self.BIN
        span_az = int(math.ceil(r / max(0.1, math.cos(math.radians(min(abs(el0), 85.0)))) / self.BIN)) + 1
        bx0, by0 = int(az0 // self.BIN), int((el0 + 90) // self.BIN)
        idx = []
        for dy in range(-int(math.ceil(r / self.BIN)), int(math.ceil(r / self.BIN)) + 1):
            for dx in range(-span_az, span_az + 1):
                a = self._bins.get(((bx0 + dx) % int(360 / self.BIN), by0 + dy))
                if a is not None:
                    idx.append(a)
        if not idx:
            return np.zeros((0, 3)), np.zeros(0), np.zeros(0)
        idx = np.concatenate(idx)
        d = self.dirs[idx]
        keep = d @ c0 > math.cos(math.radians(radius_deg))
        idx = idx[keep]
        return self._rotate(self.dirs[idx], ang), self.mags[idx], self.twinkle[idx]


class SpaceClutter:
    """Resident space objects crossing near the target track, plus a bright planet."""

    def __init__(self, seed: int) -> None:
        self.seed = seed

    def objects(self, t: float, target_az: float, target_el: float, level: float) -> List[Tuple[float, float, float]]:
        """[(az, el, relative intensity)] — intensities relative to the beacon's nominal level."""
        out = []
        n_active = 3 + int(4 * level)
        slot = 9.0
        k0 = int(t // slot)
        for k in range(k0 - 2, k0 + 1):
            for j in range(n_active):
                rng = random.Random(self.seed * 7907 + k * 131 + j * 17)
                start = k * slot + rng.uniform(0, slot)
                life = rng.uniform(8.0, 16.0)
                if not (start <= t <= start + life):
                    continue
                # a straight track through a point near the target position at spawn
                off = rng.uniform(0.3, 3.0) * DEG
                ang = rng.uniform(0, 2 * math.pi)
                rate = rng.uniform(0.2, 1.1) * DEG
                heading = rng.uniform(0, 2 * math.pi)
                frac = (t - start) / life - 0.5
                de = off * math.sin(ang) + rate * life * frac * math.sin(heading)
                da = off * math.cos(ang) + rate * life * frac * math.cos(heading)
                az = target_az + da / max(0.2, math.cos(target_el))
                el = target_el + de
                base = rng.uniform(0.25, 1.6)
                kind = rng.random()
                if kind < 0.35:                      # tumbling body: sharp periodic glints
                    period = rng.uniform(0.8, 4.0)
                    ph = ((t + rng.uniform(0, period)) % period) / period
                    inten = base * (0.15 + 2.5 * math.exp(-((ph - 0.5) / 0.06) ** 2))
                elif kind < 0.5:                     # slow flasher (e.g. rotating panel)
                    inten = base * (0.6 + 0.4 * math.sin(2 * math.pi * rng.uniform(1.2, 2.2) * t))
                else:
                    inten = base
                out.append((az, el, inten))
        return out

    @staticmethod
    def planet(t: float) -> Tuple[float, float, float]:
        return 205.0 * DEG, 38.0 * DEG, 6.0
