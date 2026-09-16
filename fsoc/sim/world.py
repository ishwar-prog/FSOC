"""Simulated world: ground terminal A, remote terminal B, the beacon, hazards, clutter lights, cue."""

import math
import random
from dataclasses import dataclass
from typing import List, Optional, Tuple

from ..core.geometry import direction_to_los
from ..core.pipeline import Cue
from .hazards import HazardField
from .sky import SpaceClutter, StarCatalog
from .terminals import GroundTerminal, RemoteTerminal

DEG = math.pi / 180.0
CAMERA_POS = (0.0, 6.0, 0.0)          # default Terminal A optical head (compatibility)
TIME_OF_DAY = ("day", "dusk", "night")


@dataclass
class BeaconSpec:
    """Beacon laser as transmitted by terminal B. The tracker is NOT told any of this."""
    freq_hz: float = 5.2          # on-off keying rate
    duty: float = 0.5
    depth: float = 1.0            # 1 = full on/off, 0 = unmodulated
    brightness: float = 0.35      # relative to the brightest decoys
    phase: float = 0.0

    def modulation(self, t: float) -> float:
        if self.depth <= 0.001 or self.freq_hz <= 0:
            return 1.0
        ph = (t * self.freq_hz + self.phase) % 1.0
        return 1.0 if ph < self.duty else 1.0 - self.depth


class SimWorld:
    CUE_RATE_HZ = 5.0

    def __init__(self, seed: int = 42, pattern: str = "orbit") -> None:
        self.remote = RemoteTerminal(pattern, seed)
        self.ground = GroundTerminal()
        self.hazards = HazardField(seed)
        self.beacon = BeaconSpec()
        self.time_of_day = "night" if self.space_scene else "day"
        self._stars: Optional[StarCatalog] = None
        self._stars_seed = None
        self.reset(seed)

    # compatibility with earlier code paths
    @property
    def patterns(self) -> RemoteTerminal:
        return self.remote

    @property
    def domain(self) -> str:
        return self.remote.platform.domain

    @property
    def space_scene(self) -> bool:
        """True when either end of the link is in space: the remote terminal, or Terminal A
        itself when it is mounted as a satellite (an inter-satellite crosslink)."""
        return self.remote.space or self.ground.space

    def reset(self, seed: int) -> None:
        self.seed = seed
        self.remote.reseed(seed)
        self.hazards.reset(seed)
        rng = random.Random(seed * 31 + 5)
        self._bias = (rng.uniform(0.3, 1.3), rng.uniform(0, 2 * math.pi))
        self.beacon.phase = rng.random()
        self.clutter = SpaceClutter(seed)
        self._cue_seed = seed
        self._decoy_seed = seed
        self._cue_cache = (None, None)

    def stars(self) -> StarCatalog:
        if self._stars is None or self._stars_seed != self.seed:
            self._stars = StarCatalog(self.seed)
            self._stars_seed = self.seed
        return self._stars

    # --------------------------------------------------------------- geometry
    def camera_pos(self, t: float):
        return self.ground.position(t)

    def target_pos(self, t: float):
        return self.remote.position(t)

    def target_vel(self, t: float):
        return self.remote.velocity(t)

    def target_los(self, t: float) -> Tuple[float, float]:
        p, c = self.target_pos(t), self.camera_pos(t)
        return direction_to_los(p[0] - c[0], p[1] - c[1], p[2] - c[2])

    def target_range(self, t: float) -> float:
        return math.dist(self.target_pos(t), self.camera_pos(t))

    # ---------------------------------------------------------------- radiometry
    def beacon_scale(self, t: float, range_m: float) -> float:
        """Received beacon energy relative to the renderer's reference point source."""
        r_km = max(range_m / 1000.0, 0.3)
        s = 3.0 * self.beacon.brightness * (self.ref_range_km() / r_km) ** 2 * self.beacon.modulation(t)
        if self.remote.space:
            v = self.remote.variation.value(t)
            s *= 1.0 + 0.3 * v * math.sin(2 * math.pi * 0.37 * t) * math.sin(2 * math.pi * 0.11 * t + 1.0)
        return s

    def ref_range_km(self) -> float:
        """Range at which the beacon has nominal brightness. GEO terminals use far higher power
        and narrower beams than LEO ones, so their reference range is correspondingly larger."""
        return 36000.0 if self.remote.key == "geo_relay" else self.remote.platform.ref_range_km

    def body_glint(self, t: float, range_m: float) -> float:
        """Sun-lit spacecraft body: a steady source at the same position as the beacon."""
        plat = self.remote.info.platform
        if plat not in ("station", "satellite"):
            return 0.0
        light = {"night": 0.0, "dusk": 1.0, "day": 0.35}[self.time_of_day]
        size = 0.9 if plat == "station" else 0.15
        r_km = max(range_m / 1000.0, 1.0)
        return 3.0 * size * light * (self.ref_range_km() / r_km) ** 2

    # -------------------------------------------------------------------- cue
    def cue(self, t: float) -> Cue:
        """Space: ephemeris (TLE / GPS state vector) prediction — small bias, σ 0.5°.
        Aerial / sea: GPS telemetry link — 5 Hz, 150 ms latency, larger bias, σ 1.5°."""
        k = math.floor(t * self.CUE_RATE_HZ)
        if self._cue_cache[0] == k:
            return self._cue_cache[1]
        space = self.space_scene
        ts = k / self.CUE_RATE_HZ
        tm = ts - 0.15
        az, el = self.target_los(tm)
        az2, el2 = self.target_los(tm + 0.1)
        mag = self._bias[0] * (0.25 if space else 1.0) * DEG
        bx, by = mag * math.cos(self._bias[1]), mag * math.sin(self._bias[1])
        rng = random.Random(self._cue_seed * 100003 + k)
        n = (0.02 if space else 0.04) * DEG
        c = Cue(ts, az + bx / max(0.2, math.cos(el)) + rng.gauss(0, n), el + by + rng.gauss(0, n),
                (az2 - az) / 0.1, (el2 - el) / 0.1, (0.5 if space else 1.5) * DEG)
        c.az += c.vaz * 0.15
        c.el += c.vel * 0.15
        self._cue_cache = (k, c)
        return c

    # ------------------------------------------------------- environment lights
    def _anchor_bearing(self) -> float:
        p = self.remote.position(0.0)
        return math.atan2(p[0], p[2])

    def sun_direction(self, t: float) -> Tuple[float, float, float]:
        b = self._anchor_bearing() + 6.5 * DEG + 0.8 * DEG * math.sin(t / 40.0)
        el = (9.0 if self.time_of_day != "night" else 2.0) * DEG
        ce = math.cos(el)
        return ce * math.sin(b), math.sin(el), ce * math.cos(b)

    def decoys(self, t: float) -> List[Tuple[Tuple[float, float, float], float]]:
        """Ground / sea scene distractor lights (world position, relative intensity).
        Many blink — obstruction lights, hazard lamps, strobes, another laser link —
        so only a *learned* signature separates them from the beacon."""
        lvl = self.hazards.level("decoys")
        if lvl <= 0.01 or self.space_scene:
            return []
        rng = random.Random(self._decoy_seed * 977 + 3)
        base_b = self._anchor_bearing()
        lights = []
        kinds = ("steady", "tower", "steady", "hazard", "glint", "steady", "laser")
        for i, kind in enumerate(kinds):
            off = rng.uniform(1.0, 5.0) * (1 if rng.random() < 0.5 else -1)
            rr = rng.uniform(1200, 3200)
            b = base_b + off * DEG
            h = rng.uniform(4, 45)
            inten = rng.uniform(0.5, 1.4)
            ph = rng.random()
            if kind == "tower":                          # aviation obstruction light ~0.5 Hz
                inten *= 1.0 if (t * 0.5 + ph) % 1.0 < 0.5 else 0.04
            elif kind == "hazard":                       # vehicle hazard lamp ~1.6 Hz
                inten *= 1.0 if (t * 1.6 + ph) % 1.0 < 0.5 else 0.04
            elif kind == "glint":                        # water / glass glint, irregular
                inten *= 0.55 + 0.45 * math.sin(2 * math.pi * 0.31 * t + ph) * math.sin(2 * math.pi * 0.83 * t)
            elif kind == "laser":                        # another optical link's beacon, different rate
                f = self.beacon.freq_hz + (2.4 if self.beacon.freq_hz < 7 else -2.4)
                inten *= 1.0 if (t * f + ph) % 1.0 < 0.5 else 0.03
                off = (3.0 + rng.uniform(0, 2.0)) * (1 if off > 0 else -1)
                b = base_b + off * DEG
            lights.append(((rr * math.sin(b), h, rr * math.cos(b)), inten * lvl))
        ph = (t + 6.0) % 20.0
        if ph < 15.0:                                    # crossing aircraft with strobe
            p0 = self.remote.position(0.0)
            lateral = -600.0 + 80.0 * ph
            dp = (2400.0 * math.sin(base_b) + lateral * math.cos(base_b), p0[1] + 90.0,
                  2400.0 * math.cos(base_b) - lateral * math.sin(base_b))
            strobe = 1.6 if (t % 1.2) < 0.08 else 0.55
            lights.append((dp, strobe * lvl))
        return lights

    def space_objects(self, t: float, az: float, el: float) -> List[Tuple[float, float, float]]:
        if not self.space_scene:
            return []
        lvl = 0.35 + 0.65 * self.hazards.level("decoys")
        objs = self.clutter.objects(t, az, el, lvl)
        objs.append(self.clutter.planet(t))
        return objs
