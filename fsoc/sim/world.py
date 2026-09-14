"""Simulated world: terminals, beacon pattern, hazards, environment lights and the GPS cue."""

import math
import random
from typing import List, Tuple

from ..core.geometry import direction_to_los
from ..core.pipeline import Cue
from .hazards import HazardField
from .patterns import PatternMixer

DEG = math.pi / 180.0
CAMERA_POS = (0.0, 6.0, 0.0)          # Terminal A optical head, 6 m mast

PLATFORM_POWER = {"quad": 1.0, "fixedwing": 1.25, "ship": 1.7}
TIME_OF_DAY = ("day", "dusk", "night")


class SimWorld:
    CUE_RATE_HZ = 5.0

    def __init__(self, seed: int = 42, pattern: str = "orbit") -> None:
        self.patterns = PatternMixer(pattern, seed)
        self.hazards = HazardField(seed)
        self.time_of_day = "day"
        self.reset(seed)

    def reset(self, seed: int) -> None:
        self.seed = seed
        self.patterns.reseed(seed)
        self.hazards.reset(seed)
        rng = random.Random(seed * 31 + 5)
        mag = rng.uniform(0.3, 1.3) * DEG
        ang = rng.uniform(0, 2 * math.pi)
        self.cue_bias = (mag * math.cos(ang), mag * math.sin(ang))
        self._cue_seed = seed
        self._decoy_seed = seed
        self._cue_cache = (None, None)

    # ----------------------------------------------------------------- target
    def target_pos(self, t: float):
        return self.patterns.position(t)

    def target_vel(self, t: float):
        return self.patterns.velocity(t)

    def target_los(self, t: float) -> Tuple[float, float]:
        p = self.target_pos(t)
        return direction_to_los(p[0] - CAMERA_POS[0], p[1] - CAMERA_POS[1], p[2] - CAMERA_POS[2])

    def target_range(self, t: float) -> float:
        p = self.target_pos(t)
        return math.dist(p, CAMERA_POS)

    def beacon_power(self) -> float:
        return PLATFORM_POWER.get(self.patterns.info.platform, 1.0)

    # -------------------------------------------------------------------- cue
    def cue(self, t: float) -> Cue:
        """GPS/telemetry cue: 5 Hz sample-and-hold, 150 ms latency, bias + noise."""
        k = math.floor(t * self.CUE_RATE_HZ)
        if self._cue_cache[0] == k:
            return self._cue_cache[1]
        ts = k / self.CUE_RATE_HZ
        tm = ts - 0.15
        az, el = self.target_los(tm)
        az2, el2 = self.target_los(tm + 0.1)
        rng = random.Random(self._cue_seed * 100003 + k)
        n = 0.04 * DEG
        c = Cue(ts, az + self.cue_bias[0] + rng.gauss(0, n), el + self.cue_bias[1] + rng.gauss(0, n),
                (az2 - az) / 0.1, (el2 - el) / 0.1, 1.5 * DEG)
        c.az += c.vaz * 0.15
        c.el += c.vel * 0.15
        self._cue_cache = (k, c)
        return c

    # ------------------------------------------------------- environment lights
    def _anchor_bearing(self) -> float:
        p = self.patterns.position(0.0)
        return math.atan2(p[0], p[2])

    def sun_direction(self, t: float) -> Tuple[float, float, float]:
        b = self._anchor_bearing() + 6.5 * DEG + 0.8 * DEG * math.sin(t / 40.0)
        el = (9.0 if self.time_of_day != "night" else 2.0) * DEG
        ce = math.cos(el)
        return ce * math.sin(b), math.sin(el), ce * math.cos(b)

    def decoys(self, t: float) -> List[Tuple[Tuple[float, float, float], float]]:
        """World positions and relative intensities of distractor lights."""
        lvl = self.hazards.level("decoys")
        if lvl <= 0.01:
            return []
        rng = random.Random(self._decoy_seed * 977 + 3)
        tp = self.target_pos(t)
        rng_t = math.dist(tp, CAMERA_POS)
        bearing = math.atan2(tp[0], tp[2])
        lights = []
        # Static lights: towers / street lights / glints anchored on the ground.
        base_b = self._anchor_bearing()
        for i in range(6):
            off = rng.uniform(1.0, 5.0) * (1 if rng.random() < 0.5 else -1)
            rr = rng.uniform(1200, 3200)
            b = base_b + off * DEG
            h = rng.uniform(4, 45)
            inten = rng.uniform(0.25, 0.8)
            blink = rng.random() < 0.3
            if blink and (t * 1.0 + i * 0.37) % 1.0 > 0.12:
                inten *= 0.15
            lights.append(((rr * math.sin(b), h, rr * math.cos(b)), inten * lvl))
        # A crossing aircraft (nav light + anti-collision strobe) passing close to the target
        # bearing every 20 s — uncued, and moving differently from the remote terminal.
        ph = (t + 6.0) % 20.0
        if ph < 15.0:
            p0 = self.patterns.position(0.0)
            b0 = base_b
            rr = 2400.0
            lateral = -600.0 + 80.0 * ph
            dp = (rr * math.sin(b0) + lateral * math.cos(b0), p0[1] + 90.0,
                  rr * math.cos(b0) - lateral * math.sin(b0))
            strobe = 1.3 if (t % 1.2) < 0.08 else 0.55
            lights.append((dp, strobe * lvl))
        return lights
