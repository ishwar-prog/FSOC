"""Beacon identification by learned optical signature.

Brightness is not identity: a beacon can be dimmer than a street light, a star or a
sun-lit satellite. Operational FSOC terminals therefore recognise their partner's
beacon by its *signature* — above all its intensity modulation — and confirm it with
geometry (ephemeris / GPS cue, motion consistency).

This module does that without being told what the beacon looks like:

  1. Every light source in the camera gets a short *tracklet* in line-of-sight space
     (gimbal motion is compensated, so stars, drones and satellites all track cleanly).
  2. Each frame a forced-photometry sample is taken at the tracklet position, including
     frames where the detector did not fire — so an OFF phase is recorded as "dark",
     not as "missing".
  3. Every other frame, each tracklet's brightness history is resampled to a uniform
     grid and Fourier-analysed: dominant frequency, periodicity (share of AC power in
     the peak), modulation depth and duty cycle.
  4. A naive-Bayes likelihood ratio compares a *beacon model* with a *clutter model*:
       • Before anything is known, the beacon prior only says "a beacon is modulated".
       • While locked, the beacon model LEARNS the real frequency, depth and duty cycle,
         and the clutter model learns what everything else looks like (scintillating
         stars, 1 Hz tower lights, strobes, tumbling-satellite glints).
     After learning, a 5.2 Hz beacon and a 0.8 Hz strobe no longer look alike at all.
  5. The learned signature can be saved and re-loaded, so a recorded video or a new
     hardware session starts already knowing its beacon.

The pipeline fuses this posterior with the geometric evidence it already has.
"""

import json
import math
from collections import deque
from dataclasses import asdict, dataclass
from typing import Dict, List, Optional

import numpy as np

from .geometry import CameraIntrinsics, los_to_pixel, wrap_pi

DEG = math.pi / 180.0
F_MAX = 14.5
_LOG_SQRT_2PI = 0.5 * math.log(2 * math.pi)


def _gauss_ll(x: float, mu: float, sd: float) -> float:
    z = (x - mu) / sd
    return -0.5 * z * z - math.log(sd) - _LOG_SQRT_2PI


@dataclass
class Signature:
    freq_hz: float = 0.0
    freq_sd: float = 1.0
    periodicity: float = 0.7
    periodicity_sd: float = 0.22
    depth: float = 0.8
    depth_sd: float = 0.3
    duty: float = 0.5
    duty_sd: float = 0.18
    observed_s: float = 0.0
    learned: bool = False

    def reset(self) -> None:
        self.__init__()


@dataclass
class Features:
    span_s: float
    freq_hz: float
    periodicity: float
    depth: float
    duty: float
    log_flux: float


class Tracklet:
    __slots__ = ("id", "az", "el", "vaz", "vel", "t", "born", "last_det", "hits", "samples",
                 "det_az", "det_el", "det_t", "feat", "llr", "p", "outside", "px", "distinct",
                 "lflux", "size", "lo", "hi", "sal", "terms", "integ")

    def __init__(self, tid: int, t: float, az: float, el: float) -> None:
        self.id = tid
        self.az, self.el = az, el
        self.vaz = self.vel = 0.0
        self.t = self.born = self.last_det = self.det_t = t
        self.det_az, self.det_el = az, el
        self.hits = 1
        self.samples = deque(maxlen=64)
        self.feat: Optional[Features] = None
        self.llr = 0.0
        self.p = 0.0
        self.outside = 0
        self.px = None
        self.distinct = 0.0          # how differently this light moves from the rest of the field
        self.lflux = None            # log detection flux (EMA) — how prominent it is
        self.size = 2.0              # apparent radius, px — photometry aperture follows it
        self.lo = self.hi = None     # pixel extent it has covered (static-overlay test)
        self.sal = -9.0              # integrated "is this the target?" score (no-cue mode)
        self.terms = None            # last evidence terms (prominence, keyed, persist, overlay, distinct)
        self.integ = None            # time-integrated evidence behind `sal`

    def observe(self, c) -> None:
        # Prominence on integrated flux: peak SNR saturates for every bright point on a phone
        # sensor, so it cannot tell a beacon from its neighbours; total light still can.
        lf = math.log(max(c.flux, 1.0))
        self.lflux = lf if self.lflux is None else self.lflux + 0.15 * (lf - self.lflux)
        self.size += 0.2 * (0.5 * math.sqrt(max(c.area, 1.0)) - self.size)
        if self.lo is None:
            self.lo, self.hi = [c.x, c.y], [c.x, c.y]
        else:
            self.lo = [min(self.lo[0], c.x), min(self.lo[1], c.y)]
            self.hi = [max(self.hi[0], c.x), max(self.hi[1], c.y)]

    @property
    def age(self) -> float:
        return self.t - self.born


class _ClutterModel:
    NB = 29                              # 0.5 Hz bins from 0 to 14.5 Hz

    def __init__(self) -> None:
        self.p_mu, self.p_sd = 0.12, 0.16
        self.d_mu, self.d_sd = 0.3, 0.3
        self.u_mu, self.u_sd = 0.45, 0.32
        self.hist = np.ones(self.NB)
        self.n = 0

    def freq_density(self, f: float) -> float:
        b = min(self.NB - 1, max(0, int(f / 0.5)))
        dens = self.hist[b] / (self.hist.sum() * 0.5)
        return 0.6 * dens + 0.4 / F_MAX

    def ll(self, f: Features) -> float:
        return (_gauss_ll(f.periodicity, self.p_mu, self.p_sd) + _gauss_ll(f.depth, self.d_mu, self.d_sd)
                + _gauss_ll(f.duty, self.u_mu, self.u_sd) + math.log(self.freq_density(f.freq_hz)))

    def learn(self, f: Features) -> None:
        a = 0.02
        self.p_mu += a * (f.periodicity - self.p_mu)
        self.p_sd = max(0.08, math.sqrt((1 - a) * self.p_sd ** 2 + a * (f.periodicity - self.p_mu) ** 2))
        self.d_mu += a * (f.depth - self.d_mu)
        self.d_sd = max(0.1, math.sqrt((1 - a) * self.d_sd ** 2 + a * (f.depth - self.d_mu) ** 2))
        self.u_mu += a * (f.duty - self.u_mu)
        self.u_sd = max(0.12, math.sqrt((1 - a) * self.u_sd ** 2 + a * (f.duty - self.u_mu) ** 2))
        self.hist *= 0.998
        self.hist[min(self.NB - 1, int(f.freq_hz / 0.5))] += 0.05 + f.periodicity
        self.n += 1


class BeaconIdentifier:
    MAX_TRACKLETS = 28
    GATE_DEG = 0.06

    def __init__(self, K: CameraIntrinsics) -> None:
        self.K = K
        self.sig = Signature()
        self.clutter = _ClutterModel()
        self.enabled = True
        self.tracklets: List[Tracklet] = []
        self.by_id: Dict[int, Tracklet] = {}
        self._next = 1
        self._frame = 0
        self._fs = 30.0
        self._mismatch_s = 0.0
        self.locked_id: Optional[int] = None
        self._occ: Optional[np.ndarray] = None      # image-position occupancy (overlay test)

    # --------------------------------------------------------------- lifecycle
    def reset(self, keep_signature: bool = True) -> None:
        self.tracklets, self.by_id = [], {}
        self.merged: Dict[int, int] = {}
        self.locked_id = None
        self._mismatch_s = 0.0
        if not keep_signature:
            self.sig.reset()
            self.clutter = _ClutterModel()

    def signature_dict(self) -> dict:
        return asdict(self.sig)

    def save_signature(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.signature_dict(), f, indent=2)

    def _merge_duplicates(self, assigned) -> None:
        K = self.K
        trs = sorted(self.tracklets, key=lambda x: (-x.hits, x.id))       # oldest / best-seen first
        gone = set()
        for i, a in enumerate(trs):
            if a.id in gone:
                continue
            for b in trs[i + 1:]:
                if b.id in gone:
                    continue
                gate = max(self.GATE_DEG * DEG, 0.6 * max(a.size or 1.0, b.size or 1.0) / K.fx)
                if math.hypot(wrap_pi(a.az - b.az) * math.cos(a.el), a.el - b.el) > gate:
                    continue
                if b.px is not None and (a.px is None or b.last_det > a.last_det):
                    a.az, a.el, a.t, a.px = b.az, b.el, b.t, b.px          # b holds this frame's sighting
                    a.det_az, a.det_el, a.det_t, a.last_det = b.det_az, b.det_el, b.det_t, b.last_det
                gone.add(b.id)
                self.merged[b.id] = a.id
                for k, x in enumerate(assigned):
                    if x is b:
                        assigned[k] = a
        if gone:
            if self.locked_id in self.merged:
                self.locked_id = self.merged[self.locked_id]
            self.tracklets = [x for x in self.tracklets if x.id not in gone]
            self.by_id = {x.id: x for x in self.tracklets}

    def load_signature(self, path: str) -> None:
        with open(path, encoding="utf-8") as f:
            self.sig = Signature(**json.load(f))

    # ------------------------------------------------------------------ update
    def update(self, t: float, image: np.ndarray, gaz: float, gel: float, los) -> List[Optional[Tracklet]]:
        """Associate this frame's candidates to tracklets, sample brightness, refresh identity.
        Returns, for every candidate in `los`, the tracklet it belongs to."""
        self._frame += 1
        K = self.K
        assigned: List[Optional[Tracklet]] = [None] * len(los)
        pairs = []
        preds = []
        for ti, tr in enumerate(self.tracklets):
            dt = t - tr.t
            paz, pel = tr.az + tr.vaz * dt, tr.el + tr.vel * dt
            preds.append((paz, pel))
            speed = math.hypot(tr.vaz * math.cos(pel), tr.vel)
            gate = self.GATE_DEG * DEG + 0.5 * speed * max(dt, 0.033) + 0.3 * speed * min(t - tr.last_det, 0.5)
            for ci, (c, az, el, _) in enumerate(los):
                d = math.hypot(wrap_pi(az - paz) * math.cos(el), el - pel)
                if d < gate:
                    pairs.append((d, ti, ci))
        pairs.sort()
        used_t, used_c = set(), set()
        for d, ti, ci in pairs:
            if ti in used_t or ci in used_c:
                continue
            used_t.add(ti)
            used_c.add(ci)
            tr = self.tracklets[ti]
            c, az, el, _ = los[ci]
            ddt = t - tr.det_t
            if 0.02 < ddt < 0.6:
                iv_az, iv_el = wrap_pi(az - tr.det_az) / ddt, (el - tr.det_el) / ddt
                k = 1.0 if tr.hits == 1 else 0.4
                tr.vaz += k * (iv_az - tr.vaz)
                tr.vel += k * (iv_el - tr.vel)
            tr.az, tr.el, tr.t = az, el, t
            tr.det_az, tr.det_el, tr.det_t, tr.last_det = az, el, t, t
            tr.hits += 1
            tr.px = (c.x, c.y)
            tr.observe(c)
            assigned[ci] = tr
        for ti, tr in enumerate(self.tracklets):
            if ti not in used_t:
                tr.az, tr.el = preds[ti]
                tr.t = t
                tr.px = None
        for ci, (c, az, el, _) in enumerate(los):
            if ci in used_c or len(self.tracklets) >= self.MAX_TRACKLETS:
                continue
            tr = Tracklet(self._next, t, az, el)
            tr.px = (c.x, c.y)
            tr.observe(c)
            self._next += 1
            self.tracklets.append(tr)
            assigned[ci] = tr

        self.merged = {}
        if self.MERGE_DUPLICATES:
            self._merge_duplicates(assigned)

        # forced photometry — dark (OFF-phase) frames are real samples, not gaps
        H, W = image.shape[:2]
        keep = []
        for tr in self.tracklets:
            px = tr.px or los_to_pixel(tr.az, tr.el, gaz, gel, K)
            # point sources keep the original 13x13 aperture; only a genuinely large light gets a
            # larger one, so the photometry measures it rather than the inside of its own glow
            rad = 6 if tr.size <= 4.0 else int(min(self.APERTURE_MAX, round(2.2 * tr.size)))
            if px is None or not (rad <= px[0] < W - rad - 1 and rad <= px[1] < H - rad - 1):
                tr.outside += 1
            else:
                tr.outside = 0
                tr.samples.append((t, _aperture_flux(image, px[0], px[1], rad)))
            if t - tr.last_det < 1.2 and tr.outside < 10:
                keep.append(tr)
        self.tracklets = keep
        self.by_id = {tr.id: tr for tr in keep}
        if self.locked_id is not None and self.locked_id not in self.by_id:
            self.locked_id = None

        if self._frame % 2 == 0:
            self._compute_features()
        self._score()
        self._score_motion()
        self._score_saliency(W, H)
        return assigned

    # ---------------------------------------------------------------- features
    def _compute_features(self) -> None:
        dts = [tr.samples[-1][0] - tr.samples[-2][0] for tr in self.tracklets if len(tr.samples) > 2]
        if dts:
            self._fs = max(5.0, min(120.0, 1.0 / max(1e-3, float(np.median(dts)))))
        fs = self._fs
        groups: Dict[int, list] = {}
        for tr in self.tracklets:
            n = len(tr.samples)
            span = tr.samples[-1][0] - tr.samples[0][0] if n > 1 else 0.0
            N = 48 if span >= 48 / fs * 0.95 else (24 if span >= 24 / fs * 0.95 else 0)
            if N == 0:
                tr.feat = None
                continue
            groups.setdefault(N, []).append(tr)
        for N, trs in groups.items():
            win = np.hanning(N)
            rows = np.empty((len(trs), N))
            raws = []
            for i, tr in enumerate(trs):
                ts = np.fromiter((s[0] for s in tr.samples), float, len(tr.samples))
                xs = np.fromiter((s[1] for s in tr.samples), float, len(tr.samples))
                tg = ts[-1] - np.arange(N - 1, -1, -1) / fs
                rows[i] = np.interp(tg, ts, xs)
                raws.append(xs[ts >= tg[0] - 1e-6])
            # remove mean and linear trend: a source drifting into vignetting or a slow fade
            # must not leak into the lowest bins and pose as a periodic signal
            x = np.arange(N) - (N - 1) / 2.0
            ac = rows - rows.mean(axis=1, keepdims=True)
            ac -= np.outer(ac @ x / float(x @ x), x)
            spec = np.abs(np.fft.rfft(ac * win, axis=1)) ** 2
            spec[:, 0] = 0.0
            spec[:, 1] *= 0.25
            total = spec.sum(axis=1) + 1e-12
            nb = spec.shape[1]
            base = 3.0 / max(1, nb - 1)
            for i, tr in enumerate(trs):
                s = spec[i]
                k = int(np.argmax(s[1:]) + 1)
                lo, hi = max(1, k - 1), min(nb, k + 2)
                per = float(s[lo:hi].sum() / total[i])
                per = max(0.0, (per - base) / (1 - base))
                mag = np.sqrt(s)
                delta = 0.0
                if 1 <= k - 1 and k + 1 < nb:
                    den = mag[k - 1] - 2 * mag[k] + mag[k + 1]
                    if abs(den) > 1e-12:
                        delta = max(-0.5, min(0.5, 0.5 * (mag[k - 1] - mag[k + 1]) / den))
                freq = min(F_MAX, (k + delta) * fs / N)
                raw = raws[i]
                p10, p90 = np.percentile(raw, (10, 90))
                depth = float(max(0.0, min(1.0, (p90 - p10) / max(p90 + p10, 1e-6))))
                duty = float(np.mean(raw > 0.5 * (p10 + p90))) if p90 > p10 else 1.0
                tr.feat = Features(N / fs, float(freq), per, depth, duty, math.log(max(p90, 1.0)))

    def _beacon_ll(self, f: Features) -> float:
        """Before learning, only generic engineering knowledge is used: a beacon is keyed with a
        roughly symmetric on/off pattern well above natural flicker (tumbling glints, obstruction
        lights and strobes are slow, short flashes). After learning, its real values are used."""
        s = self.sig
        if s.learned:
            ll = _gauss_ll(f.periodicity, s.periodicity, max(0.12, s.periodicity_sd)) \
                + _gauss_ll(f.depth, s.depth, max(0.15, s.depth_sd)) \
                + _gauss_ll(f.duty, s.duty, max(0.1, s.duty_sd))
            if s.periodicity > 0.35:
                ll += _gauss_ll(f.freq_hz, s.freq_hz, max(0.3, s.freq_sd))
            else:
                ll += math.log(1.0 / F_MAX)
            return ll
        return self._prior_ll(f)

    @staticmethod
    def _prior_ll(f: Features) -> float:
        rolloff = 1.0 / (1.0 + math.exp(-(f.freq_hz - 1.8) / 0.25))
        return (_gauss_ll(f.periodicity, 0.7, 0.22) + _gauss_ll(f.depth, 0.6, 0.4)
                + _gauss_ll(f.duty, 0.5, 0.2) + math.log(max(1e-4, rolloff) / (F_MAX - 1.8)))

    def _posterior(self, beacon_ll: float, f: Features):
        llr = (beacon_ll - self.clutter.ll(f)) * min(1.0, f.span_s / 1.2)
        llr = max(-12.0, min(12.0, llr))
        return llr, 1.0 / (1.0 + math.exp(-(llr - 1.0)))

    def prior_p(self, f: Features) -> float:
        """Probability under generic 'a beacon is keyed' knowledge only (ignores what was learned)."""
        return self._posterior(self._prior_ll(f), f)[1]

    def _score(self) -> None:
        for tr in self.tracklets:
            f = tr.feat
            if f is None or not self.enabled:
                tr.llr, tr.p = 0.0, 0.0
                continue
            tr.llr, tr.p = self._posterior(self._beacon_ll(f), f)

    def _score_motion(self) -> None:
        """How differently does each light move from everything else in view?

        Not every beacon blinks. When the modulation test has nothing to say, the remaining
        honest discriminator is behaviour: a terminal on a moving platform drifts across a field
        of lights that are fixed to the world (street lights, windows), while a geostationary
        one sits still against stars that all drift together. Either way the target is the
        source whose motion disagrees with the consensus, so this measures exactly that — in
        pixels per second, against the median of the field, which is also the camera's own shake.
        """
        trs = [tr for tr in self.tracklets if tr.hits >= 4]
        if len(trs) < 3:
            for tr in self.tracklets:
                tr.distinct = 0.0
            return
        vx = np.fromiter((tr.vaz * math.cos(tr.el) for tr in trs), float, len(trs))
        vy = np.fromiter((tr.vel for tr in trs), float, len(trs))
        mx, my = float(np.median(vx)), float(np.median(vy))
        spread = float(np.median(np.hypot(vx - mx, vy - my))) + 1e-9
        for tr in self.tracklets:
            if tr.hits < 4:
                tr.distinct = 0.0
                continue
            d = math.hypot(tr.vaz * math.cos(tr.el) - mx, tr.vel - my)
            # Relative to the field's own scatter, but with an absolute floor so that a frame
            # full of perfectly static lights cannot make trivial jitter look significant.
            tr.distinct = min(1.0, d / max(3.0 * spread, 1.5e-4))

    SAL_MIN_HITS = 8
    KEYED_WEIGHT = 2.0       # how much blink evidence counts against raw brightness in the ranking
    APERTURE_MAX = 40        # largest photometry half-width, px (the rig raises it for close beacons)
    # Fold tracklets that sit on the same light into the oldest one. A light otherwise collects
    # duplicate tracklets (a noisy velocity pushes a prediction out of the gate, a new one is
    # born) and its detection then alternates between them. Off by default (validated videos).
    MERGE_DUPLICATES = False
    SAL_PRIOR = -1.0                    # where a newly ranked light starts
    SAL_RATE = 0.06                     # per frame: ~0.6 s to earn (or lose) a rank at 24-30 FPS
    OCC_DECAY = 0.95                    # image-position occupancy memory, ~1 s
    OCC_OVERLAY = 0.7                   # a border cell this persistently occupied is burned in

    def _score_saliency(self, W: int, H: int) -> None:
        """Which light is the target? — used when no external cue exists (recorded video).

        Real footage does not promise a blinking beacon, a dark sky or a clean frame, so no
        single cue can be trusted and none is hard-coded. Every light is rated on independent,
        scene-relative evidence and the ratings are combined:

          prominence   brightness relative to *this* field (robust z-score of log flux) — a
                       beacon is built to stand out from its surroundings, whatever they are;
          keyed        the learned blink-signature probability (identity), when there is one;
          behaviour    motion that disagrees with the rest of the field (motion distinctness);
          persistence  detected on most frames of its life, unlike noise or sparkle;
          overlay      a light parked in the border band that never moves is almost always
                       burned in after capture — timestamps, OSD text, logos, watermarks — and
                       a tracker's whole job is to bring its target *to the centre*.

        Nothing here is tuned to a particular clip; every term is relative to the scene.
        """
        live = [tr for tr in self.tracklets if tr.hits >= self.SAL_MIN_HITS and tr.lflux is not None]
        for tr in self.tracklets:
            tr.sal = -9.0
        if not live:
            return
        lf = np.array([tr.lflux for tr in live])
        med = float(np.median(lf))
        mad = float(np.median(np.abs(lf - med))) * 1.4826 + 0.25
        bx, by = 0.12 * W, 0.12 * H
        for tr, f in zip(live, lf):
            prom = max(-3.0, min(4.0, (f - med) / mad))
            keyed = tr.p if tr.feat is not None else 0.0
            persist = min(1.0, tr.hits / max(1.0, (tr.t - tr.born) * self._fs + 1.0))
            overlay = 0.0
            if tr.lo is not None and tr.age > 1.0:
                ext = math.hypot(tr.hi[0] - tr.lo[0], tr.hi[1] - tr.lo[1])
                cx, cy = 0.5 * (tr.lo[0] + tr.hi[0]), 0.5 * (tr.lo[1] + tr.hi[1])
                border = cx < bx or cx > W - bx or cy < by or cy > H - by
                # 5 % of the frame: a multi-lobed logo's centroid wanders tens of pixels as its
                # lobes pass in and out of detection, yet it never actually goes anywhere
                if border and ext < 0.05 * max(W, H):
                    overlay = 1.0
            tr.terms = (prom, keyed, persist, overlay, tr.distinct)
            tr.sal = (1.0 * prom + self.KEYED_WEIGHT * keyed + 1.0 * tr.distinct
                      + 1.5 * (persist - 0.7) - 4.0 * overlay)

    # ---------------------------------------------------------------- learning
    def learn(self, locked: Optional[Tracklet], dt: float) -> None:
        """Called every frame while the pipeline holds a confirmed lock."""
        if locked is None:
            return
        self.locked_id = locked.id
        f = locked.feat
        if f is not None and f.span_s >= 1.5:
            s = self.sig
            # Only learn from a lock that actually looks like a keyed beacon. Locking a steady
            # star or a glint must never teach the model that "beacons are steady".
            if s.learned:
                off_freq = s.periodicity > 0.35 and abs(f.freq_hz - s.freq_hz) > max(1.0, 4 * s.freq_sd)
                if off_freq or locked.p < 0.3:
                    if self.prior_p(f) >= 0.6:
                        self._mismatch_s += dt
                        if self._mismatch_s > 2.5:  # the beacon itself changed: relearn
                            s.reset()
                            self._mismatch_s = 0.0
                    return
                self._mismatch_s = max(0.0, self._mismatch_s - dt)
            elif locked.p < 0.6:
                return
            a = 0.12 if s.observed_s < 3.0 else 0.03
            for name, val in (("periodicity", f.periodicity), ("depth", f.depth), ("duty", f.duty),
                              ("freq_hz", f.freq_hz)):
                mu = getattr(s, name)
                mu = val if s.observed_s == 0 else mu + a * (val - mu)
                sd_name = name.replace("_hz", "") + "_sd"
                sd = getattr(s, sd_name)
                sd = math.sqrt((1 - a) * sd * sd + a * (val - mu) ** 2)
                setattr(s, name, mu)
                setattr(s, sd_name, sd)
            s.observed_s += dt
            if s.observed_s >= 2.0:
                s.learned = True
            for tr in self.tracklets:
                if tr is not locked and tr.feat is not None and tr.feat.span_s >= 1.5 \
                        and math.hypot(wrap_pi(tr.az - locked.az) * math.cos(tr.el), tr.el - locked.el) > 0.05 * DEG:
                    self.clutter.learn(tr.feat)

    def merge(self, old_id: int, new: Tracklet) -> None:
        """A fragment of the same light (tracklet split by jitter): keep its brightness history."""
        old = self.by_id.get(old_id)
        if old is None or old is new:
            return
        merged = sorted(list(old.samples) + list(new.samples), key=lambda s: s[0])
        new.samples = deque(merged, maxlen=64)
        new.born = min(new.born, old.born)
        new.hits += old.hits
        new.feat, new.llr, new.p = old.feat, old.llr, old.p
        self.tracklets = [tr for tr in self.tracklets if tr is not old]
        self.by_id.pop(old_id, None)
        if self.locked_id == old_id:
            self.locked_id = new.id

    def best_other(self, exclude_id: Optional[int]) -> float:
        return max((tr.p for tr in self.tracklets if tr.id != exclude_id), default=0.0)


def _aperture_flux(img: np.ndarray, u: float, v: float, rad: int = 6) -> float:
    """Background-subtracted flux in a square aperture; the outer ring estimates the sky.
    rad=6 is the original 13x13 point-source aperture (core = inner half)."""
    iu, iv = int(round(u)), int(round(v))
    patch = img[iv - rad:iv + rad + 1, iu - rad:iu + rad + 1].astype(np.float32)
    ring = np.concatenate((patch[0], patch[-1], patch[1:-1, 0], patch[1:-1, -1]))
    bg = float(np.median(ring))
    q = rad // 2
    core = patch[q:2 * rad + 1 - q, q:2 * rad + 1 - q] - bg
    return float(np.maximum(core, 0.0).sum())
