"""Eight operational hazards with physically-motivated parameterisation.

Each hazard has an operator-set intensity (0–1). The effective level ramps smoothly
(~0.7 s) when toggled so the scene never pops. Stochastic hazards are seeded and
evolved causally (Ornstein–Uhlenbeck processes, event schedules), so runs are
reproducible and the benchmark can replay them.
"""

import math
import random
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

DEG = math.pi / 180.0


@dataclass(frozen=True)
class HazardInfo:
    key: str
    name: str
    summary: str
    default: float


HAZARD_INFOS: List[HazardInfo] = [
    HazardInfo("fog", "Fog", "Mie scattering: visibility drops to 2 km, contrast veil, halo.", 0.6),
    HazardInfo("rain", "Rain", "Rain attenuation, streaks and droplets on the lens.", 0.6),
    HazardInfo("turbulence", "Heat Shimmer", "Turbulence: scintillation, beam wander, blur.", 0.6),
    HazardInfo("noise", "Sensor Noise", "Read/shot noise, hot pixels, row banding.", 0.6),
    HazardInfo("vibration", "Mount Vibration", "11–21 Hz platform vibration shaking the LOS.", 0.6),
    HazardInfo("glare", "Sun Glare", "Veiling glare gradient and lens ghosts near the sun.", 0.6),
    HazardInfo("occlusion", "Occlusion", "Birds, branches and cloud blocking the beacon.", 0.6),
    HazardInfo("decoys", "Decoy Lights", "Street lights, blinking glints and a crossing aircraft near the target.", 0.7),
]
HAZARD_KEYS = [h.key for h in HAZARD_INFOS]


class HazardField:
    RAMP_PER_S = 1.5

    def __init__(self, seed: int = 42) -> None:
        self.enabled: Dict[str, bool] = {k: False for k in HAZARD_KEYS}
        self.intensity: Dict[str, float] = {h.key: h.default for h in HAZARD_INFOS}
        self._level: Dict[str, float] = {k: 0.0 for k in HAZARD_KEYS}
        self.reset(seed)

    # ------------------------------------------------------------------ control
    def reset(self, seed: int) -> None:
        self.seed = seed
        self._t: Optional[float] = None
        self._rng = random.Random(seed * 7919 + 17)
        self._aoa = [0.0, 0.0]
        self._chi = 0.0
        self._occ_events: List[Tuple[float, float, str]] = []
        self._occ_next = None
        self._forced: List[Tuple[float, float]] = []
        for k in HAZARD_KEYS:
            self._level[k] = self.intensity[k] if self.enabled[k] else 0.0

    def set(self, key: str, enabled: Optional[bool] = None, intensity: Optional[float] = None) -> None:
        if enabled is not None:
            self.enabled[key] = bool(enabled)
        if intensity is not None:
            self.intensity[key] = max(0.0, min(1.0, float(intensity)))

    def set_immediate(self, key: str, enabled: bool, intensity: Optional[float] = None) -> None:
        self.set(key, enabled, intensity)
        self._level[key] = self.intensity[key] if enabled else 0.0

    def level(self, key: str) -> float:
        return self._level[key]

    def levels(self) -> Dict[str, float]:
        return dict(self._level)

    def force_block(self, t: float, duration: float) -> None:
        self._forced.append((t, t + duration))

    # ---------------------------------------------------------------- evolution
    def advance(self, t: float) -> None:
        """Advance ramps and stochastic processes to time t (vision thread, monotonic)."""
        if self._t is None:
            self._t = t
            return
        dt = t - self._t
        if dt <= 0:
            return
        self._t = t
        step = self.RAMP_PER_S * dt
        for k in HAZARD_KEYS:
            target = self.intensity[k] if self.enabled[k] else 0.0
            cur = self._level[k]
            self._level[k] = cur + max(-step, min(step, target - cur))

        L = self._level["turbulence"]
        tau = 0.12
        a = math.exp(-dt / tau)
        sig = 3.2 * L
        for i in range(2):
            self._aoa[i] = self._aoa[i] * a + sig * math.sqrt(1 - a * a) * self._rng.gauss(0, 1)
        a2 = math.exp(-dt / 0.045)
        self._chi = self._chi * a2 + 0.45 * L * math.sqrt(1 - a2 * a2) * self._rng.gauss(0, 1)

        self._schedule_occlusions(t)

    # ----------------------------------------------------------------- turbulence
    def turbulence(self) -> Tuple[float, float, float, float]:
        """(aoa_x_px, aoa_y_px, scintillation_gain, extra_blur_px)."""
        L = self._level["turbulence"]
        s = 0.45 * L
        gain = math.exp(2 * self._chi - 2 * s * s)
        return self._aoa[0], self._aoa[1], gain, 1.1 * L

    # ------------------------------------------------------------------ vibration
    _VIB_AZ = ((0.55, 11.3, 0.0), (0.30, 17.9, 1.1), (0.15, 3.1, 0.4))
    _VIB_EL = ((0.50, 13.7, 0.6), (0.35, 21.3, 2.1), (0.15, 2.3, 0.0))

    def vibration(self, t: float) -> Tuple[float, float, float, float]:
        """(d_az, d_el, rate_az, rate_el) of the camera LOS due to mount vibration (rad)."""
        A = 0.085 * DEG * self._level["vibration"]
        if A <= 0:
            return 0.0, 0.0, 0.0, 0.0
        out = []
        for terms in (self._VIB_AZ, self._VIB_EL):
            p = sum(w * math.sin(2 * math.pi * f * t + ph) for w, f, ph in terms)
            r = sum(w * 2 * math.pi * f * math.cos(2 * math.pi * f * t + ph) for w, f, ph in terms)
            out.append((A * p, A * r))
        return out[0][0], out[1][0], out[0][1], out[1][1]

    # ------------------------------------------------------------------ occlusion
    def _schedule_occlusions(self, t: float) -> None:
        L = self._level["occlusion"]
        if L <= 0.02:
            self._occ_next = None
            return
        if self._occ_next is None:
            self._occ_next = t + self._rng.uniform(1.5, 3.5)
        while self._occ_next <= t + 0.5:
            start = self._occ_next
            dur = self._rng.uniform(0.25, 0.45 + 1.05 * L)
            kind = "bird" if dur < 0.5 else ("branch" if self._rng.random() < 0.5 else "cloud")
            self._occ_events.append((start, start + dur, kind))
            self._occ_next = start + dur + self._rng.uniform(3.5, 7.5)
        self._occ_events = [e for e in self._occ_events if e[1] > t - 2.0]
        self._forced = [e for e in self._forced if e[1] > t - 2.0]

    def occlusion(self, t: float) -> Tuple[float, str, float]:
        """(block factor 0..1, kind, phase 0..1 through the event)."""
        best = (0.0, "", 0.0)
        edge = 0.06
        for s, e in self._forced:
            if s - edge <= t <= e + edge:
                f = min(1.0, (t - (s - edge)) / edge, ((e + edge) - t) / edge)
                if f > best[0]:
                    best = (f, "manual", (t - s) / max(e - s, 1e-3))
        if self._level["occlusion"] > 0.02:
            for s, e, kind in self._occ_events:
                if s - edge <= t <= e + edge:
                    f = min(1.0, (t - (s - edge)) / edge, ((e + edge) - t) / edge)
                    if f > best[0]:
                        best = (f, kind, (t - s) / max(e - s, 1e-3))
        return best

    # ------------------------------------------------------------- atmosphere
    def fog_beta_per_km(self) -> float:
        L = self._level["fog"]
        if L <= 0:
            return 0.0
        vis_km = math.exp(math.log(30.0) * (1 - L) + math.log(2.0) * L)
        return 3.912 / vis_km

    def rain_beta_per_km(self) -> float:
        return 0.45 * self._level["rain"]

    def noise_params(self) -> Tuple[float, float, float, float]:
        """(read_sigma_dn, hot_pixel_fraction, row_sigma_dn, flicker_fraction)."""
        L = self._level["noise"]
        return 1.2 + 14.0 * L, 0.004 * L, 3.0 * L, 0.0015 * L
