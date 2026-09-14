"""TrackingPipeline — acquisition state machine, data association and pointing reference.

States
  SEARCH     No track. Archimedean spiral scan around the external cue (GPS/telemetry
             bearing of the remote terminal) — the standard FSOC acquisition procedure.
  ACQUIRING  One or more tentative tracks (multi-hypothesis). Each is scored on cue
             proximity, rate consistency with the cue and SNR; the winner is confirmed
             after N consistent detections. This is what rejects decoy lights.
  LOCKED     Confirmed track, detection associated this frame (Mahalanobis gate +
             brightness consistency). Detector runs in a small ROI around prediction.
  COASTING   Detection missing (occlusion, fade). Kalman prediction keeps the gimbal on
             target for up to `coast_window_s`.
  REACQUIRE  Coast expired. Local spiral around the predicted LOS (not the cold-start
             cue), with gate growing over time; falls back to SEARCH after a timeout.

Thread model: process_frame() runs on the vision thread, pointing_reference() on the
control thread. All shared state is guarded by one lock and the control side only reads
non-mutating Kalman predictions.
"""

import math
import threading
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .detector import BeaconDetector, Candidate
from .geometry import CameraIntrinsics, angular_separation, los_to_pixel, pixel_to_los, wrap_pi
from .tracker import LosKalmanTracker

DEG = math.pi / 180.0


class TrackState:
    SEARCH = "SEARCH"
    ACQUIRING = "ACQUIRING"
    LOCKED = "LOCKED"
    COASTING = "COASTING"
    REACQUIRE = "REACQUIRE"

    ALL = (SEARCH, ACQUIRING, LOCKED, COASTING, REACQUIRE)


@dataclass
class Cue:
    """External pointing cue (GPS/INS/AIS/telemetry bearing). Angles in radians."""
    t: float
    az: float
    el: float
    vaz: float = 0.0
    vel: float = 0.0
    sigma: float = 1.5 * DEG


@dataclass
class PipelineConfig:
    coast_window_s: float = 1.5
    confirm_hits_search: int = 4
    confirm_hits_reacq: int = 3
    min_snr_new: float = 12.0
    min_snr_track: float = 10.0
    flux_tolerance: float = 1.2        # base |ln(flux / track flux)| while locked (widens with scintillation)
    flux_tolerance_coast: float = 0.9  # tighter while coasting / re-acquiring
    coast_gate_sigma_deg: float = 0.15
    require_cue: bool = True           # video without telemetry: set False (search from boresight)
    gate_locked: float = 16.0
    gate_coast: float = 25.0
    search_speed_deg: float = 12.0
    search_pitch_fov: float = 0.8
    search_radius_deg: float = 5.0
    reacq_timeout_s: float = 4.0
    max_hypotheses: int = 5


@dataclass
class PipelineOutput:
    t: float
    frame_id: int
    state: str
    state_age: float
    candidates: List[Tuple[float, float, float]] = field(default_factory=list)
    roi: Tuple[int, int, int, int] = (0, 0, 0, 0)
    measurement: Optional[Tuple[float, float]] = None
    track_px: Optional[Tuple[float, float]] = None
    track_los: Optional[Tuple[float, float, float, float]] = None
    hypotheses_px: List[Tuple[float, float]] = field(default_factory=list)
    snr: float = 0.0
    confidence: float = 0.0
    noise_sigma: float = 0.0
    detect_ms: float = 0.0
    track_ms: float = 0.0
    loss_events: int = 0


class _Hypothesis:
    __slots__ = ("kf", "hits", "misses", "prior", "snr_sum", "flux", "born", "last_px",
                 "lf_mean", "lf_var", "cue")

    def __init__(self, kf: LosKalmanTracker, prior: float, snr: float, flux: float, t: float) -> None:
        self.kf = kf
        self.hits = 1
        self.misses = 0
        self.prior = prior
        self.snr_sum = min(snr, 40.0)
        self.flux = flux
        self.born = t
        self.last_px = None
        self.lf_mean = math.log(max(flux, 1e-3))
        self.lf_var = 0.0
        self.cue = False         # spawned from the GPS cue cone rather than the track prediction

    def add_flux(self, flux: float) -> None:
        """Track log-flux statistics: a steady beacon vs a blinking/strobing decoy."""
        lf = math.log(max(flux, 1e-3))
        d = lf - self.lf_mean
        self.lf_mean += 0.3 * d
        self.lf_var = 0.7 * self.lf_var + 0.3 * d * d
        self.flux = 0.7 * self.flux + 0.3 * flux


class TrackingPipeline:
    def __init__(self, K: CameraIntrinsics, config: PipelineConfig = None,
                 detector: BeaconDetector = None, latency_s: float = 0.02) -> None:
        self.K = K
        self.cfg = config or PipelineConfig()
        self.detector = detector or BeaconDetector()
        self.latency_s = latency_s
        self._lock = threading.RLock()
        self._cue: Optional[Cue] = None
        self.reset()

    # ------------------------------------------------------------------ API
    def reset(self) -> None:
        with self._lock:
            self.state = TrackState.SEARCH
            self._state_t = None
            self._mode = TrackState.SEARCH          # SEARCH or REACQUIRE while acquiring
            self.tracker = LosKalmanTracker()
            self._hyps: List[_Hypothesis] = []
            self._last_hit_t = 0.0
            self._flux_avg = 0.0
            self._reacq_t = 0.0
            self.loss_events = 0
            self._search_s = 0.0
            self._search_dwell = 0.0
            self._search_center = None
            self._search_started = False
            self._clutter: List[Tuple[float, float, float]] = []
            self._pending = None
            self._reacq_rmax = 1.2 * DEG
            self._lf_var = 0.0
            self._vs = (0.0, 0.0)
            self._reacq_cue_phase = False
            self._reacq_center_cue = False
            self._last_snr = 0.0
            self._last_nis = 0.0

    def set_cue(self, cue: Cue) -> None:
        with self._lock:
            self._cue = cue

    def _set_state(self, s: str, t: float) -> None:
        if s != self.state:
            self.state = s
            self._state_t = t

    # ------------------------------------------------------------ vision side
    def process_frame(self, frame) -> PipelineOutput:
        K = self.K
        t = frame.t
        with self._lock:
            if self._state_t is None:
                self._state_t = t
            roi = self._roi_for(frame)

        det = self.detector.detect(frame.image, roi)
        t1 = time.perf_counter()

        with self._lock:
            los = []
            for c in det.candidates:
                az, el = pixel_to_los(c.x, c.y, frame.gimbal_az, frame.gimbal_el, K)
                sig_px = 0.25 + 2.0 / math.sqrt(max(c.snr, 1.0))
                los.append((c, az, el, (sig_px / K.fx) ** 2))

            meas = None
            if self.state in (TrackState.LOCKED, TrackState.COASTING):
                meas = self._track_step(t, los)
            else:
                meas = self._acquire_step(t, los)

            out = PipelineOutput(
                t=t, frame_id=frame.frame_id, state=self.state,
                state_age=t - (self._state_t or t),
                candidates=[(c.x, c.y, c.snr) for c in det.candidates],
                roi=det.roi, noise_sigma=det.noise_sigma, detect_ms=det.proc_ms,
                loss_events=self.loss_events,
            )
            if meas is not None:
                out.measurement = (meas.x, meas.y)
                out.snr = meas.snr
            est = self._active_estimate(t)
            if est is not None:
                out.track_los = (est.az, est.el, est.vaz, est.vel)
                out.track_px = los_to_pixel(est.az, est.el, frame.gimbal_az, frame.gimbal_el, K)
            for h in self._hyps:
                e = h.kf.estimate_at(t)
                p = los_to_pixel(e.az, e.el, frame.gimbal_az, frame.gimbal_el, K)
                if p:
                    out.hypotheses_px.append(p)
            out.confidence = self._confidence(meas)
            out.track_ms = (time.perf_counter() - t1) * 1000.0
            return out

    def _roi_for(self, frame) -> Optional[Tuple[int, int, int, int]]:
        if self.state not in (TrackState.LOCKED, TrackState.COASTING) or not self.tracker.initialized:
            return None
        e = self.tracker.estimate_at(frame.t)
        p = los_to_pixel(e.az, e.el, frame.gimbal_az, frame.gimbal_el, self.K)
        if p is None:
            return None
        u, v = p
        if not (0 <= u < self.K.width and 0 <= v < self.K.height):
            return None
        sig_px = max(e.sigma_az, e.sigma_el) * self.K.fx
        half = int(max(56, min(220, 5.0 * sig_px + 40)))
        return (int(u) - half, int(v) - half, int(u) + half, int(v) + half)

    def _track_step(self, t: float, los) -> Optional[Candidate]:
        cfg = self.cfg
        gate = cfg.gate_locked if self.state == TrackState.LOCKED else cfg.gate_coast
        locked = self.state == TrackState.LOCKED
        # While coasting the prediction uncertainty grows; cap it for gating so a wide gate
        # cannot swallow nearby decoys, and demand a tighter brightness match.
        cap = None if locked else cfg.coast_gate_sigma_deg * DEG
        tol = self._flux_tol(locked)
        best, best_cost = None, 1e18
        fallback, n_consistent = None, 0
        for c, az, el, r in los:
            if c.snr < cfg.min_snr_track:
                continue
            lr = math.log(max(c.flux, 1e-3) / self._flux_avg) if self._flux_avg > 0 else 0.0
            if abs(lr) > tol:
                continue                     # far too faint/bright to be our beacon (rain, glints)
            n_consistent += 1
            d2 = self.tracker.gate_distance(t, az, el, r, cap)
            if d2 <= gate:
                cost = d2 + 1.5 * lr * lr
                if cost < best_cost:
                    best, best_cost = (c, az, el, r), cost
            elif abs(lr) < (0.75 * tol if locked else 0.4) and c.snr >= 2 * cfg.min_snr_track \
                    and (locked or d2 < 100.0):
                fallback = (c, az, el, r)

        recentred = False
        if best is None and fallback is not None and n_consistent == 1:
            # Detected last frame, and exactly one beacon-like blob in the ROI but outside the
            # gate (vibration kick, sudden manoeuvre): trust it and re-centre the filter.
            best = fallback
            recentred = True

        if best is not None and not locked:
            # Re-association after a gap needs two consistent frames, so a single decoy flash
            # or glint can never capture the track.
            c, az, el, r = best
            p = self._pending
            if p is None or t - p[0] > 0.12 or angular_separation(az, el, p[1], p[2]) > 0.25 * DEG:
                self._pending = (t, az, el)
                best = None
            else:
                self._pending = None

        if best is not None:
            c, az, el, r = best
            if recentred:
                self.tracker.recentre(t, az, el, r)
                self._last_nis = gate
            else:
                self._last_nis = self.tracker.update(t, az, el, r)
            if self._flux_avg > 0:
                lr = math.log(max(c.flux, 1e-3) / self._flux_avg)
                self._lf_var = 0.9 * self._lf_var + 0.1 * lr * lr
            self._flux_avg = c.flux if self._flux_avg <= 0 else 0.85 * self._flux_avg + 0.15 * c.flux
            e = self.tracker.estimate_at(t)
            k = min(1.0, max(1e-3, t - self._last_hit_t) / 0.25)
            self._vs = (self._vs[0] + (e.vaz - self._vs[0]) * k, self._vs[1] + (e.vel - self._vs[1]) * k)
            self._last_hit_t = t
            self._last_snr = c.snr
            self._set_state(TrackState.LOCKED, t)
            return c

        self.tracker.predict_to(t)
        if self.state == TrackState.LOCKED:
            if self._jittery():
                # Noisy measurements (vibration / turbulence): coast on the smoothed rate.
                self.tracker.set_rate(self._vs[0], self._vs[1])
            self._set_state(TrackState.COASTING, t)
        elif t - self._last_hit_t > cfg.coast_window_s:
            self.loss_events += 1
            self._reacq_t = t
            self._reacq_cue_phase = False
            self._mode = TrackState.REACQUIRE
            self._search_s = 0.0
            self._search_dwell = 0.0
            self._set_state(TrackState.REACQUIRE, t)
        return None

    def _acquire_step(self, t: float, los) -> Optional[Candidate]:
        cfg = self.cfg
        used = set()
        best_meas = None

        # 1. Update existing hypotheses with their nearest gated candidate.
        r_floor = (2.5 / self.K.fx) ** 2      # unknown jitter floor for young tracks
        for h in self._hyps:
            best, bd2 = None, 16.0
            for i, (c, az, el, r) in enumerate(los):
                if i in used:
                    continue
                d2 = h.kf.gate_distance(t, az, el, r + r_floor)
                if d2 < bd2:
                    best, bd2 = i, d2
            if best is not None:
                c, az, el, r = los[best]
                used.add(best)
                h.kf.update(t, az, el, r + r_floor)
                h.hits += 1
                h.misses = 0
                h.snr_sum += min(c.snr, 40.0)
                h.add_flux(c.flux)
                h.last_px = c
            else:
                h.kf.predict_to(t)
                h.misses += 1
        self._hyps = [h for h in self._hyps if h.misses <= 2]

        # 2. Spawn new hypotheses from unused, sufficiently bright candidates.
        reacq = self._mode == TrackState.REACQUIRE and self.tracker.initialized
        reacq_cap = None
        if reacq:
            # Gate grows with the time since the last detection, but stays tied to how good the
            # prediction really is — so a second drone 1–2° away is never mistaken for the target.
            age = t - self._last_hit_t
            reacq_cap = min(0.35, 0.12 + 0.05 * age) * DEG
            self.tracker.inflate(reacq_cap)
            self._reacq_rmax = max(0.6 * DEG, min(1.5 * DEG, 3.0 * reacq_cap))
            if not self._reacq_cue_phase and self._cue is not None and t - self._reacq_t > 0.6:
                # Prediction alone has not found it: also scan the GPS cue cone.
                self._reacq_cue_phase = True
                self._search_s = 0.0
                self._search_dwell = 0.0
        self._clutter = [cl for cl in self._clutter if t - cl[0] < 6.0]
        # Cold-start detections are only accepted once the boresight has reached the cue
        # cone — anything seen while slewing from park is outside the cue uncertainty.
        allow_spawn = reacq or self._search_started
        for i, (c, az, el, r) in enumerate(los):
            if (not allow_spawn or i in used or c.snr < cfg.min_snr_new
                    or len(self._hyps) >= cfg.max_hypotheses):
                continue
            cue_based = False
            if reacq:
                if self._flux_avg > 0 and \
                        abs(math.log(max(c.flux, 1e-3) / self._flux_avg)) > self._flux_tol(False):
                    continue
                d2 = self.tracker.gate_distance(t, az, el, r, reacq_cap)
                if d2 <= 16.0:
                    prior = -0.5 * d2
                    e = self.tracker.estimate_at(t)
                    vaz, vel = e.vaz, e.vel
                elif self._reacq_cue_phase:
                    # The prediction may be stale: accept a brightness-consistent blob inside the
                    # cue cone, confirmed with the full cold-start checks.
                    prior, vaz, vel = self._cue_prior(t, az, el)
                    if prior < -0.5 * 2.5 ** 2:
                        continue
                    cue_based = True
                else:
                    continue
            else:
                prior, vaz, vel = self._cue_prior(t, az, el)
                if prior < -0.5 * 2.5 ** 2:      # outside the 2.5-sigma cue cone
                    continue
                if any(angular_separation(az, el, cl[1], cl[2]) < 0.2 * DEG for cl in self._clutter):
                    continue                     # recently rejected as clutter / decoy
            kf = LosKalmanTracker()
            # Re-acquisition starts from the pre-loss velocity with tight uncertainty, so a few
            # jittery hits cannot corrupt it.
            kf.initialize(t, az, el, vaz, vel, pos_sigma=(0.4 / self.K.fx) * 4,
                          vel_sigma=(0.25 if (reacq and not cue_based) else 2.5) * DEG)
            h = _Hypothesis(kf, prior, c.snr, c.flux, t)
            h.cue = cue_based
            h.last_px = c
            self._hyps.append(h)

        # 3. Score and confirm.
        if self._hyps:
            scored = sorted(((self._score(h, t, reacq and not h.cue), h) for h in self._hyps),
                            key=lambda p: p[0], reverse=True)
            top_score, top = scored[0]
            hreacq = reacq and not top.cue
            need = cfg.confirm_hits_reacq if hreacq else cfg.confirm_hits_search
            margin_ok = len(scored) == 1 or top_score - scored[1][0] > 1.0 or top.hits >= need + 4
            plausible = self._plausible(top, t, hreacq)
            if not plausible and top.hits >= need + 6:
                if not hreacq:
                    e = top.kf.estimate_at(t)
                    self._clutter.append((t, e.az, e.el))
                self._hyps.remove(top)
            elif top.hits >= need and top.misses == 0 and margin_ok and plausible:
                self.tracker = top.kf
                self._flux_avg = top.flux
                self._lf_var = top.lf_var
                ec = top.kf.estimate_at(t)
                self._vs = (ec.vaz, ec.vel)
                self._last_hit_t = t
                self._last_snr = top.last_px.snr if top.last_px else 0.0
                self._hyps = []
                self._mode = TrackState.SEARCH
                self._set_state(TrackState.LOCKED, t)
                return top.last_px
            if top.misses == 0:
                best_meas = top.last_px
            self._set_state(TrackState.ACQUIRING, t)
        else:
            if self._mode == TrackState.REACQUIRE and t - self._reacq_t > cfg.reacq_timeout_s:
                self._mode = TrackState.SEARCH
                self.tracker.reset()
                self._search_s = 0.0
                self._search_started = False
            self._set_state(self._mode, t)
        return best_meas

    def _cue_prior(self, t: float, az: float, el: float):
        cue = self._cue
        if cue is None:
            return 0.0, 0.0, 0.0
        dt = t - cue.t
        caz, cel = cue.az + cue.vaz * dt, cue.el + cue.vel * dt
        sep = angular_separation(az, el, caz, cel)
        return -0.5 * (sep / cue.sigma) ** 2, cue.vaz, cue.vel

    def _flux_tol(self, locked: bool) -> float:
        """Brightness tolerance that widens with the track's own observed scintillation."""
        sig = math.sqrt(self._lf_var)
        if locked:
            return min(2.0, max(self.cfg.flux_tolerance, 3.0 * sig))
        return min(1.5, max(self.cfg.flux_tolerance_coast, 2.5 * sig))

    def _jittery(self) -> bool:
        return self.tracker.initialized and self.tracker.measurement_noise_adapt * self.K.fx > 3.0

    def _plausible(self, h: _Hypothesis, t: float, reacq: bool) -> bool:
        """Hard sanity checks before a tentative track may become the lock."""
        e = h.kf.estimate_at(t)
        if reacq:
            ref = self.tracker.estimate_at(t)
            dv = math.hypot(wrap_pi(e.vaz - ref.vaz) * math.cos(e.el), e.vel - ref.vel)
            return dv <= 3.0 * DEG
        if self._cue is None:
            return True
        pr, cvaz, cvel = self._cue_prior(t, e.az, e.el)
        dv = math.hypot(wrap_pi(e.vaz - cvaz) * math.cos(e.el), e.vel - cvel)
        sv = math.hypot(e.sigma_vaz * math.cos(e.el), e.sigma_vel)
        return pr >= -0.5 * 2.0 ** 2 and dv <= 1.0 * DEG + 3.0 * sv

    def _score(self, h: _Hypothesis, t: float, reacq: bool) -> float:
        """Log-likelihood-style score: geometry (cue or prediction) dominates, SNR only breaks ties."""
        s = 0.01 * min(h.snr_sum, 8 * 40.0)
        e = h.kf.estimate_at(t)
        if reacq or self._cue is None:
            s += h.prior
        else:
            s += 2.0 * self._cue_prior(t, e.az, e.el)[0]
        if h.hits >= 3:
            s -= 6.0 * h.lf_var
            if reacq:
                ref = self.tracker.estimate_at(t)
                rvaz, rvel = ref.vaz, ref.vel
            elif self._cue is not None:
                rvaz, rvel = self._cue.vaz, self._cue.vel
            else:
                rvaz = rvel = None
            if rvaz is not None:
                dv = math.hypot(wrap_pi(e.vaz - rvaz) * math.cos(e.el), e.vel - rvel)
                sv = math.hypot(0.3 * DEG, math.hypot(e.sigma_vaz * math.cos(e.el), e.sigma_vel))
                s -= 0.5 * (dv / sv) ** 2
        return s

    def _confidence(self, meas: Optional[Candidate]) -> float:
        st = self.state
        if st == TrackState.LOCKED and meas is not None:
            return max(0.05, min(1.0, meas.snr / 30.0) * math.exp(-self._last_nis / 30.0))
        if st == TrackState.COASTING:
            return 0.35
        if st == TrackState.ACQUIRING:
            return 0.25
        return 0.0

    def _active_estimate(self, t: float):
        if self.state in (TrackState.LOCKED, TrackState.COASTING, TrackState.REACQUIRE) \
                and self.tracker.initialized:
            return self.tracker.estimate_at(t)
        if self.state == TrackState.ACQUIRING and self._hyps:
            best = max(self._hyps, key=lambda h: self._score(h, t, self._mode == TrackState.REACQUIRE))
            return best.kf.estimate_at(t)
        return None

    # ----------------------------------------------------------- control side
    def pointing_reference(self, t: float, dt: float, enc_az: float, enc_el: float):
        """Return (az, el, vaz, vel, tracking) for the gimbal controller."""
        with self._lock:
            st = self.state
            tl = t + self.latency_s
            if st in (TrackState.LOCKED, TrackState.COASTING) and self.tracker.initialized:
                e = self.tracker.estimate_at(tl)
                return e.az, e.el, e.vaz, e.vel, True
            if st == TrackState.ACQUIRING and self._hyps:
                reacq = self._mode == TrackState.REACQUIRE and self.tracker.initialized
                ready = []
                for h in self._hyps:
                    if h.hits < (1 if (reacq and not h.cue) else 2) or h.misses:
                        continue
                    if not reacq or h.cue:
                        eh = h.kf.estimate_at(t)
                        if self._cue_prior(t, eh.az, eh.el)[0] < -0.5 * 2.0 ** 2:
                            continue
                    ready.append(h)
                if ready:
                    ests = [h.kf.estimate_at(tl) for h in ready]
                    if len(ests) > 1:
                        span_az = (max(e.az for e in ests) - min(e.az for e in ests)) * math.cos(ests[0].el)
                        span_el = max(e.el for e in ests) - min(e.el for e in ests)
                        if span_az < 0.7 * self.K.hfov_deg * DEG and span_el < 0.7 * self.K.vfov_deg * DEG:
                            # Keep every live hypothesis in view so none is starved of detections.
                            n = len(ests)
                            return (sum(e.az for e in ests) / n, sum(e.el for e in ests) / n,
                                    sum(e.vaz for e in ests) / n, sum(e.vel for e in ests) / n, True)
                    if reacq:
                        k = max(range(len(ready)), key=lambda i: self._score(ready[i], t, not ready[i].cue))
                    else:
                        k = max(range(len(ready)),
                                key=lambda i: self._cue_prior(t, ests[i].az, ests[i].el)[0])
                    e = ests[k]
                    return e.az, e.el, e.vaz, e.vel, True
            return self._spiral_reference(tl, dt, enc_az, enc_el)

    def _search_center_at(self, t: float):
        if self._mode == TrackState.REACQUIRE and self.tracker.initialized:
            horizon = self._last_hit_t + 3.0
            e = self.tracker.estimate_at(min(t, horizon))
            vaz, vel = self._vs if self._jittery() else (e.vaz, e.vel)
            use_pred = True
            if self._reacq_cue_phase and self._cue is not None:
                c = self._cue
                dc = t - c.t
                # Trust the prediction while it agrees with the independent GPS cue; if the two
                # disagree the prediction has gone stale, so scan the cue cone instead.
                use_pred = angular_separation(e.az, e.el, c.az + c.vaz * dc, c.el + c.vel * dc) < 1.5 * c.sigma
            self._reacq_center_cue = not use_pred
            if use_pred:
                if t < horizon:
                    return e.az, e.el, vaz, vel
                return e.az, e.el, 0.0, 0.0
        if self._cue is not None:
            c = self._cue
            dt = t - c.t
            return c.az + c.vaz * dt, c.el + c.vel * dt, c.vaz, c.vel
        if self._search_center is None:
            self._search_center = (0.0, 0.0)
        return self._search_center[0], self._search_center[1], 0.0, 0.0

    def _spiral_offsets(self, s: float, b: float):
        if s <= 0:
            return 0.0, 0.0
        theta = math.sqrt(2.0 * s / b)
        r = b * theta
        return r * math.cos(theta), r * math.sin(theta)

    def search_geometry(self):
        """(pitch_rad, radius_rad, s_rad) — used by the GUI to draw the scan path."""
        b = self.cfg.search_pitch_fov * min(self.K.hfov_deg, self.K.vfov_deg) * DEG / (2 * math.pi)
        rmax = self.cfg.search_radius_deg * DEG
        if self._mode == TrackState.REACQUIRE and not self._reacq_center_cue:
            rmax = self._reacq_rmax
        return b, rmax, self._search_s

    def search_center(self, t: float):
        with self._lock:
            return self._search_center_at(t)

    def _spiral_reference(self, t: float, dt: float, enc_az: float, enc_el: float):
        if self._mode == TrackState.SEARCH and self._cue is None:
            if self.cfg.require_cue:
                return enc_az, enc_el, 0.0, 0.0, False     # hold until the first cue arrives
            if self._search_center is None:
                self._search_center = (enc_az, enc_el)
        caz, cel, cvaz, cvel = self._search_center_at(t)
        b, rmax, _ = self.search_geometry()
        speed = self.cfg.search_speed_deg * DEG
        if math.hypot(wrap_pi(caz - enc_az) * math.cos(cel), cel - enc_el) < 2.0 * DEG:
            self._search_started = True

        ox, oy = self._spiral_offsets(self._search_s, b)
        ref_az = caz + ox / max(0.2, math.cos(cel))
        ref_el = cel + oy
        err = math.hypot(wrap_pi(ref_az - enc_az) * math.cos(cel), ref_el - enc_el)
        if err < 0.6 * DEG:
            if self._search_dwell < 0.15:
                self._search_dwell += dt
            else:
                self._search_s += speed * dt
        if b * math.sqrt(2.0 * self._search_s / b) > rmax:
            self._search_s = 0.0
            self._search_dwell = 0.0

        ox2, oy2 = self._spiral_offsets(self._search_s + speed * 0.01, b)
        vx = (ox2 - ox) / 0.01 if err < 0.6 * DEG else 0.0
        vy = (oy2 - oy) / 0.01 if err < 0.6 * DEG else 0.0
        vaz = cvaz + vx / max(0.2, math.cos(cel))
        vel = cvel + vy
        return ref_az, ref_el, vaz, vel, False
