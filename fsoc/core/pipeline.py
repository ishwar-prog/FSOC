"""TrackingPipeline — acquisition state machine, beacon identification, data association and
pointing reference.

States
  SEARCH     No track. Archimedean spiral scan around the external cue (GPS telemetry for
             aircraft/ships, ephemeris for spacecraft) — the standard FSOC acquisition
             procedure (open-loop pointing, then closed-loop on the beacon).
  ACQUIRING  One or more tentative tracks (multi-hypothesis). Each is scored on cue
             proximity, rate consistency and — decisively — its *learned beacon identity*
             (modulation signature, see identity.py). Brightness alone never wins.
  LOCKED     Confirmed track. Gated association (Mahalanobis + brightness + identity).
             Frames where an on-off-keyed beacon is simply OFF are held, not treated as loss.
  COASTING   Detection missing (occlusion, fade). Kalman prediction keeps the gimbal on
             target for up to `coast_window_s`.
  REACQUIRE  Coast expired. Local spiral around the prediction, then the cue cone.

Thread model: process_frame() runs on the vision thread, pointing_reference() on the
control thread. Shared state is guarded by one lock; the control side only reads
non-mutating Kalman predictions.
"""

import math
import threading
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .detector import BeaconDetector, Candidate
from .geometry import CameraIntrinsics, angular_separation, los_to_pixel, pixel_to_los, wrap_pi
from .identity import BeaconIdentifier
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
    """External pointing cue (GPS/INS/AIS/telemetry or ephemeris). Angles in radians."""
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
    flux_tolerance: float = 1.2
    flux_tolerance_coast: float = 0.9
    coast_gate_sigma_deg: float = 0.15
    require_cue: bool = True
    gate_locked: float = 16.0
    gate_coast: float = 25.0
    search_speed_deg: float = 12.0
    search_pitch_fov: float = 0.8
    search_radius_deg: float = 5.0
    reacq_timeout_s: float = 4.0
    max_hypotheses: int = 6
    hypothesis_timeout_s: float = 0.45
    # Mechanical travel of a real mount, (min, max) in rad. The search pattern is held inside
    # it, so a scan never waits for a pose the servos cannot reach. None: unlimited (simulator).
    az_limits: Optional[Tuple[float, float]] = None
    el_limits: Optional[Tuple[float, float]] = None
    # Overrides for the Kalman manoeuvre model (see LosKalmanTracker) — a hand-held beacon a few
    # metres away turns far harder, in angle, than an aircraft kilometres out.
    tracker_kwargs: dict = field(default_factory=dict)
    # No-cue lock rule: rank the target only against lights that have a live hypothesis, so a
    # bright light that can never be locked (a window, a lamp half out of view) cannot block it.
    rank_among_candidates: bool = False
    # Watch a light this long before ranking it for a no-cue lock...
    min_rank_age_s: float = 0.35
    # ...and, when set, never lock a steady light while a beacon-like blinking one is in view; a
    # steady light (a beacon that does not blink) qualifies only after `steady_accept_s`.
    prefer_keyed: bool = False
    steady_accept_s: float = 3.0
    min_blink_depth: float = 0.6       # an on/off beacon (photometry is background-subtracted)
    min_blink_hits: int = 8
    # Detect in a window around the prediction while locked (False: whole frame every frame —
    # affordable at webcam resolution, and a close beacon can be larger than any window).
    use_roi: bool = True
    # Extra centroid noise per pixel of blob size: a large, saturated light's centre is less
    # certain than a point's. 0 keeps the point-source model.
    size_noise: float = 0.0
    # Measure the spot the operator clicked even when no detection passed the gates there.
    seed_probe: bool = False


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
    sources: List[Tuple[float, float, float, float, bool]] = field(default_factory=list)  # x, y, P, Hz, locked
    lock_p: float = 0.0
    signature: dict = field(default_factory=dict)


@dataclass
class _Steer:
    az: float
    el: float
    vaz: float
    vel: float


class _Hypothesis:
    __slots__ = ("kf", "hits", "misses", "prior", "snr_sum", "flux", "born", "last_px",
                 "lf_mean", "lf_var", "cue", "tid", "last_t", "pgood_t", "seeded")

    def __init__(self, kf: LosKalmanTracker, prior: float, snr: float, flux: float, t: float) -> None:
        self.kf = kf
        self.hits = 1
        self.misses = 0
        self.prior = prior
        self.snr_sum = min(snr, 40.0)
        self.flux = flux
        self.born = t
        self.last_t = t
        self.last_px = None
        self.lf_mean = math.log(max(flux, 1e-3))
        self.lf_var = 0.0
        self.cue = False
        self.tid = None
        self.pgood_t = None                  # since when its light has looked beacon-like
        self.seeded = False                  # operator pointed at this one

    def add_flux(self, flux: float) -> None:
        lf = math.log(max(flux, 1e-3))
        d = lf - self.lf_mean
        self.lf_mean += 0.3 * d
        self.lf_var = 0.7 * self.lf_var + 0.3 * d * d
        self.flux = 0.7 * self.flux + 0.3 * flux


class TrackingPipeline:
    SEED_TTL_S = 6.0                   # how long an operator's "track that one" stays in force
    SEED_RADIUS_PX = 70.0              # how close a detection must be to the point they clicked
    SEED_DRIFT_PX_S = 45.0             # ...widened per second, since the target keeps moving
    SEED_MIN_SNR = 15.0                # and it must be a real detection, not noise at that spot

    def __init__(self, K: CameraIntrinsics, config: PipelineConfig = None,
                 detector: BeaconDetector = None, latency_s: float = 0.02) -> None:
        self.K = K
        self.cfg = config or PipelineConfig()
        self.detector = detector or BeaconDetector()
        self.identifier = BeaconIdentifier(K)
        self.latency_s = latency_s
        self._lock = threading.RLock()
        self._cue: Optional[Cue] = None
        self.reset()

    # ------------------------------------------------------------------ API
    def reset(self) -> None:
        with self._lock:
            self.state = TrackState.SEARCH
            self._state_t = None
            self._mode = TrackState.SEARCH
            self.tracker = LosKalmanTracker(**self.cfg.tracker_kwargs)
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
            self._lock_tid = None
            self._gap_max = 0.07
            self._last_frame_t = None
            self._assign = []
            self._bad_lock_s = 0.0
            self._seed = None
            self._seed_t = None
            self._lock_seeded = False
            self._img = None
            self._frame_pose = (0.0, 0.0)
            self.identifier.reset(keep_signature=True)

    def reset_identity(self) -> None:
        with self._lock:
            self.identifier.reset(keep_signature=False)

    def set_cue(self, cue: Cue) -> None:
        with self._lock:
            self._cue = cue

    def clear_cue(self) -> None:
        """No external pointing cue exists — e.g. a recorded video has no live GPS/ephemeris
        feed. Search starts from bore-sight instead of a cue cone."""
        with self._lock:
            self._cue = None

    def seed_target(self, px: float, py: float) -> None:
        """Operator pointed at the target in the camera image: "track that one".

        This is the manual equivalent of a cue — it does not bypass the detector or the
        identifier, it just says where to look. The nearest detection to the seed is preferred
        while acquiring, and once the lock is established the learned signature takes over, so a
        seed on a real recording ends up exactly where an automatic lock would have.
        """
        with self._lock:
            self._seed = (px, py)
            self._seed_t = None                  # stamped on the next frame we see
            self._lock_seeded = False
            self._hyps = []
            self._lock_tid = None
            self._clutter = []
            self.tracker.reset()
            self._mode = TrackState.SEARCH
            self._set_state(TrackState.SEARCH, self._last_frame_t or 0.0)

    def _probe_seed(self, t: float, los) -> Optional[tuple]:
        """Measure the light under the operator's click directly. Pointing at something is an
        instruction, not a suggestion: it is tracked even if the automatic gates (SNR floor,
        point-source shape) would have discarded it."""
        probe = getattr(self.detector, "probe", None)
        if probe is None or self._img is None or self._seed is None:
            return None
        c = probe(self._img, self._seed[0], self._seed[1], self.SEED_RADIUS_PX)
        if c is None:
            return None
        gaz, gel = self._frame_pose
        az, el = pixel_to_los(c.x, c.y, gaz, gel, self.K)
        sig_px = 0.25 + 2.0 / math.sqrt(max(c.snr, 1.0)) + self.cfg.size_noise * math.sqrt(max(c.area, 1.0))
        return (c, az, el, (sig_px / self.K.fx) ** 2)

    def _seed_px_dist(self, c: Candidate) -> Optional[float]:
        if self._seed is None:
            return None
        return math.hypot(c.x - self._seed[0], c.y - self._seed[1])

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
                sig_px = 0.25 + 2.0 / math.sqrt(max(c.snr, 1.0)) + self.cfg.size_noise * math.sqrt(max(c.area, 1.0))
                los.append((c, az, el, (sig_px / K.fx) ** 2))
            gimg = frame.image if frame.image.ndim == 2 else frame.image[..., 1]
            self._img = gimg
            self._frame_pose = (frame.gimbal_az, frame.gimbal_el)
            self._assign = self.identifier.update(t, gimg, frame.gimbal_az, frame.gimbal_el, los)
            mg = self.identifier.merged
            if mg:                                   # duplicates of one light were folded together
                if self._lock_tid in mg:
                    self._lock_tid = mg[self._lock_tid]
                for h in self._hyps:
                    h.tid = mg.get(h.tid, h.tid)
            dt = (t - self._last_frame_t) if self._last_frame_t is not None else 1.0 / 30
            self._last_frame_t = t

            if self.state in (TrackState.LOCKED, TrackState.COASTING):
                meas = self._track_step(t, los, dt)
            else:
                meas = self._acquire_step(t, los)

            idf = self.identifier
            locked_tr = idf.by_id.get(self._lock_tid) if self._lock_tid is not None else None
            if self.state == TrackState.LOCKED and locked_tr is not None:
                idf.learn(locked_tr, dt)

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
            for tr in idf.tracklets:
                if tr.feat is None:
                    continue
                px = tr.px or los_to_pixel(tr.az, tr.el, frame.gimbal_az, frame.gimbal_el, K)
                if px and 0 <= px[0] < K.width and 0 <= px[1] < K.height:
                    out.sources.append((px[0], px[1], tr.p, tr.feat.freq_hz, tr.id == self._lock_tid))
            out.sources.sort(key=lambda s: s[2], reverse=True)
            out.lock_p = locked_tr.p if (locked_tr is not None and locked_tr.feat is not None) else 0.0
            s = idf.sig
            out.signature = dict(learned=s.learned, freq_hz=s.freq_hz, freq_sd=s.freq_sd, depth=s.depth,
                                 duty=s.duty, periodicity=s.periodicity, observed_s=s.observed_s,
                                 sources=len(idf.tracklets))
            out.confidence = self._confidence(meas)
            out.track_ms = (time.perf_counter() - t1) * 1000.0
            return out

    def _roi_for(self, frame) -> Optional[Tuple[int, int, int, int]]:
        if self.state not in (TrackState.LOCKED, TrackState.COASTING) or not self.tracker.initialized:
            return None
        if not self.cfg.use_roi:
            return None
        if frame.frame_id % 10 == 0:
            return None                      # periodic full frame keeps the clutter model learning
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

    def _is_known_clutter(self, i: int) -> bool:
        idf = self.identifier
        tr = self._assign[i] if i < len(self._assign) else None
        return (idf.enabled and idf.sig.learned and tr is not None and tr.id != self._lock_tid
                and tr.feat is not None and tr.feat.span_s >= 1.2 and tr.p < 0.08)

    def _handover(self, t: float, los, dt: float) -> Optional[Candidate]:
        """Identity correction: the locked light has shown, for a sustained time, that it is not
        modulated like a beacon while a clearly beacon-like light sits inside the cue cone
        (typical: a star a few arc-minutes from a GEO relay won the geometric race at lock)."""
        idf = self.identifier
        ltr = idf.by_id.get(self._lock_tid) if self._lock_tid is not None else None
        if self._lock_seeded:
            # The operator pointed at this one. A steady target scores low on "looks keyed", so
            # identity evidence alone must not be allowed to hand the lock to a blinking decoy.
            self._bad_lock_s = 0.0
            return None
        if self._cue is None and idf.enabled:
            best = self._salient_challenger(ltr, los)
            if best is None:
                self._bad_lock_s = 0.0
                return None
            self._bad_lock_s += dt
            if self._bad_lock_s < self.SAL_HANDOVER_S:
                return None
            return self._switch_to(t, *best[1:])
        if not idf.enabled or ltr is None or ltr.feat is None or ltr.feat.span_s < 1.2 or ltr.p >= 0.2:
            self._bad_lock_s = 0.0
            return None
        self._bad_lock_s += dt
        if self._bad_lock_s < 0.6:
            return None
        best, best_key = None, None
        for i, (c, az, el, r) in enumerate(los):
            tr = self._assign[i] if i < len(self._assign) else None
            if (tr is None or tr is ltr or tr.feat is None or tr.feat.span_s < 1.2 or tr.p < 0.9
                    or c.snr < self.cfg.min_snr_track):
                continue
            if self._cue is not None and self._cue_prior(t, az, el)[0] < -0.5 * 2.5 ** 2:
                continue
            key = (tr.p, c.snr)
            if best_key is None or key > best_key:
                best, best_key = (i, c, az, el, tr), key
        if best is None:
            return None
        return self._switch_to(t, *best[1:])

    SAL_HANDOVER_S = 0.5               # a better-ranked light must stay better this long
    SAL_MARGIN = 1.5                   # ...by at least this much saliency

    def _make_room_for_blinker(self, i: int, t: float, reacq: bool) -> None:
        """Hypothesis slots are few, and steady scene features never time out of them. A light
        proven to blink cleanly must not be locked out: it takes the weakest non-blinker's slot."""
        tr = self._assign[i] if i < len(self._assign) else None
        if tr is None or not self._blinkers([tr]) or any(h.tid == tr.id for h in self._hyps):
            return
        idf = self.identifier
        steady = [h for h in self._hyps if not self._blinkers([x for x in [idf.by_id.get(h.tid)] if x])]
        if steady:
            self._hyps.remove(min(steady, key=lambda h: self._score(h, t, reacq)))

    def _blinkers(self, tracklets):
        """Lights that switch cleanly on and off, watched long enough to judge."""
        cfg = self.cfg
        return [o for o in tracklets if o.feat is not None and o.p >= 0.6 and o.sal > -9.0
                and o.feat.depth >= cfg.min_blink_depth and o.hits >= cfg.min_blink_hits]

    @staticmethod
    def _blink_q(o) -> float:
        """Blink quality: a clean periodic on/off. Brightness plays no part — a window or a lamp
        is brighter than an LED, and a patch of scene that merely contains the beacon (or that
        flickers as the camera moves) has a shallow or irregular modulation."""
        return o.feat.periodicity * o.feat.depth

    def _salient_challenger(self, ltr, los):
        """No-cue self-correction: is some other visible light now clearly more target-like than
        the one we hold? The ranking keeps learning as the clip plays, so an early lock onto an
        overlay or a star is undone as soon as the evidence says so."""
        if self.cfg.prefer_keyed:
            return self._blink_challenger(ltr, los)
        cur = ltr.sal if (ltr is not None and ltr.sal > -9.0) else -3.0
        best, best_sal = None, cur + self.SAL_MARGIN
        for i, (c, az, el, r) in enumerate(los):
            tr = self._assign[i] if i < len(self._assign) else None
            if tr is None or tr is ltr or tr.sal <= -9.0 or c.snr < self.cfg.min_snr_track:
                continue
            if tr.sal > best_sal:
                best, best_sal = (i, c, az, el, tr), tr.sal
        return best

    def _blink_challenger(self, ltr, los):
        """prefer_keyed variant: hand over only to a clearly better blinker."""
        cur = self._blink_q(ltr) if (ltr is not None and ltr in self._blinkers([ltr])) else 0.0
        best, best_q = None, max(0.15, 1.3 * cur)
        for i, (c, az, el, r) in enumerate(los):
            tr = self._assign[i] if i < len(self._assign) else None
            if tr is None or tr is ltr or c.snr < self.cfg.min_snr_track or not self._blinkers([tr]):
                continue
            q = self._blink_q(tr)
            if q > best_q:
                best, best_q = (i, c, az, el, tr), q
        return best

    def _switch_to(self, t: float, c, az: float, el: float, tr) -> Candidate:
        kf = LosKalmanTracker(**self.cfg.tracker_kwargs)
        kf.initialize(t, az, el, tr.vaz, tr.vel, pos_sigma=(0.4 / self.K.fx) * 4, vel_sigma=0.5 * DEG)
        self.tracker = kf
        self._flux_avg, self._lf_var = c.flux, 0.0
        self._vs = (tr.vaz, tr.vel)
        self._last_hit_t, self._last_snr = t, c.snr
        self._lock_tid, self._gap_max, self._bad_lock_s, self._pending = tr.id, 0.07, 0.0, None
        self._set_state(TrackState.LOCKED, t)
        return c

    def _track_step(self, t: float, los, dt: float = 1.0 / 30) -> Optional[Candidate]:
        cfg = self.cfg
        h = self._handover(t, los, dt)
        if h is not None:
            return h
        gate = cfg.gate_locked if self.state == TrackState.LOCKED else cfg.gate_coast
        locked = self.state == TrackState.LOCKED
        space = self._space_cue()
        # Locked still gets a generous cap (not the tight coasting one): real manoeuvres and
        # fast passes need room, but the gate must not grow without bound — a run of missed
        # detections under vibration must not let the filter confirm a match many degrees from
        # where it last looked and treat the jump as evidence of a genuine manoeuvre.
        cap = (1.5 * DEG) if locked else (0.06 if space else cfg.coast_gate_sigma_deg) * DEG
        tol = self._flux_tol(locked)
        idf = self.identifier
        ltr = idf.by_id.get(self._lock_tid) if self._lock_tid is not None else None
        ltr_alive = ltr is not None and t - ltr.last_det < 0.6
        best, best_cost = None, 1e18
        fallback, n_consistent = None, 0
        for i, (c, az, el, r) in enumerate(los):
            if c.snr < cfg.min_snr_track or self._is_known_clutter(i):
                continue
            tr = self._assign[i] if i < len(self._assign) else None
            same = tr is not None and tr.id == self._lock_tid
            if tr is not None and not same and self._lock_tid is not None and tr.feat is not None and tr.p < 0.5:
                continue                     # a different light with a non-beacon signature
            fragment = False
            if tr is not None and not same and ltr_alive:
                # While our beacon's tracklet is alive (e.g. in its OFF phase) another light may
                # not take over the lock just by passing close. Exceptions: a fresh fragment of
                # the same light (split by jitter), or a far more beacon-like source.
                # (under vibration the old tracklet may have grabbed a noise blip this frame, so its
                # own detection state is not required — the 3σ gate below still applies)
                young = (tr.age < 0.35 and tr.hits <= 10) or tr.feat is None
                strong = (not self._lock_seeded and tr.feat is not None and tr.p >= 0.7
                          and (ltr.feat is None or ltr.p < 0.3))
                if not (young or strong):
                    continue
                fragment = young and not strong
            lr = math.log(max(c.flux, 1e-3) / self._flux_avg) if self._flux_avg > 0 else 0.0
            if abs(lr) > tol:
                continue
            n_consistent += 1
            d2 = self.tracker.gate_distance(t, az, el, r, cap)
            if fragment and d2 > 9.0:
                continue
            if space and not locked and tr is not None and not same and tr.feat is None and d2 > 9.0:
                continue                     # star field while coasting: an unknown new light must sit on the prediction
            if d2 <= gate:
                cost = d2 + 1.5 * lr * lr - (2.0 if same else 0.0)
                if cost < best_cost:
                    best, best_cost = (i, c, az, el, r), cost
            elif abs(lr) < (0.75 * tol if locked else 0.4) and c.snr >= 2 * cfg.min_snr_track \
                    and (locked or d2 < 100.0) \
                    and (same or tr is None or (tr.feat is not None and tr.p >= 0.7)):
                fallback = (i, c, az, el, r)   # re-centre only on the identified beacon

        recentred = False
        if best is None and fallback is not None and n_consistent == 1:
            best = fallback
            recentred = True

        if best is not None and not locked:
            i, c, az, el, r = best
            p = self._pending
            if p is None or t - p[0] > 0.12 or angular_separation(az, el, p[1], p[2]) > 0.25 * DEG:
                self._pending = (t, az, el)
                best = None
            else:
                self._pending = None

        if best is not None:
            i, c, az, el, r = best
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
            gap = t - self._last_hit_t
            if gap < 0.6:
                self._gap_max = max(gap, self._gap_max * 0.985)
            self._last_hit_t = t
            self._last_snr = c.snr
            tr = self._assign[i] if i < len(self._assign) else None
            if tr is not None and tr.id != self._lock_tid:
                if ltr is not None and ltr_alive and tr.feat is None:
                    idf.merge(ltr.id, tr)    # same light, new fragment: keep its history
                self._lock_tid = tr.id
            self._set_state(TrackState.LOCKED, t)
            return c

        self.tracker.predict_to(t)
        if self.state == TrackState.LOCKED:
            if t - self._last_hit_t <= self._hold_s():
                return None                  # modulated beacon in its OFF phase: hold the lock
            if self._jittery():
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

    def _hold_s(self) -> float:
        return min(0.5, max(0.12, 1.6 * self._gap_max))

    def _acquire_step(self, t: float, los) -> Optional[Candidate]:
        cfg = self.cfg
        idf = self.identifier
        used = set()
        best_meas = None

        r_floor = (2.5 / self.K.fx) ** 2
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
                h.last_t = t
                h.snr_sum += min(c.snr, 40.0)
                h.add_flux(c.flux)
                h.last_px = c
                tr = self._assign[best] if best < len(self._assign) else None
                if tr is not None:
                    h.tid = tr.id
            else:
                h.kf.predict_to(t)
                h.misses += 1
        self._hyps = [h for h in self._hyps if t - h.last_t <= cfg.hypothesis_timeout_s]
        for h in self._hyps:
            tr = idf.by_id.get(h.tid)
            if tr is not None and tr.feat is not None and tr.p >= 0.6:
                h.pgood_t = t if h.pgood_t is None else h.pgood_t
            else:
                h.pgood_t = None

        reacq = self._mode == TrackState.REACQUIRE and self.tracker.initialized
        reacq_cap = None
        if reacq:
            age = t - self._last_hit_t
            if self._space_cue():
                reacq_cap = min(0.12, 0.04 + 0.02 * age) * DEG   # orbit prediction stays within arc-minutes
            else:
                reacq_cap = min(0.35, 0.12 + 0.05 * age) * DEG
            self.tracker.inflate(reacq_cap)
            self._reacq_rmax = max(0.6 * DEG, min(1.5 * DEG, 3.0 * reacq_cap))
            if not self._reacq_cue_phase and self._cue is not None and t - self._reacq_t > 0.6:
                self._reacq_cue_phase = True
                self._search_s = 0.0
                self._search_dwell = 0.0
        self._clutter = [cl for cl in self._clutter if t - cl[0] < 6.0]
        # An operator seed ("track that one") is a pointing hint with a lifetime: it steers
        # acquisition to the light that was pointed at, then hands over to the normal identity
        # and association logic once a lock exists.
        seeded_now, seed_pick = False, None
        if self._seed is not None:
            if self._seed_t is None:
                self._seed_t = t
            if t - self._seed_t > self.SEED_TTL_S:
                self._seed = self._seed_t = None
            else:
                seeded_now = True
                # Once a seeded hypothesis exists it is already being tracked frame to frame, so
                # let it mature and confirm normally. Only while there is none does the seed hunt
                # for its target: an operator can easily click while a keyed beacon is in its
                # dark half, so it waits for a solid detection rather than grabbing whatever
                # noise sits at that point, widening its reach as the target moves meanwhile.
                if not any(h.seeded for h in self._hyps):
                    radius = self.SEED_RADIUS_PX + self.SEED_DRIFT_PX_S * (t - self._seed_t)
                    best_snr, best_i = None, None
                    for i, (c, az, el, r) in enumerate(los):
                        if i in used or c.snr < max(cfg.min_snr_new, self.SEED_MIN_SNR):
                            continue
                        d = self._seed_px_dist(c)
                        if d is None or d > radius:
                            continue
                        if best_snr is None or c.snr > best_snr:
                            best_snr, best_i = c.snr, i
                    seed_pick = best_i
                    if seed_pick is None and self.cfg.seed_probe:
                        probed = self._probe_seed(t, los)
                        if probed is not None:
                            los.append(probed)
                            self._assign.append(None)
                            seed_pick = len(los) - 1
                    if seed_pick is None:
                        self._set_state(TrackState.SEARCH, t)
                        return None              # nothing convincing there yet — keep waiting
        allow_spawn = reacq or self._search_started or seeded_now \
            or (self._cue is None and not cfg.require_cue)
        order = range(len(los))
        max_h = cfg.max_hypotheses
        for i in order:
            c, az, el, r = los[i]
            if len(self._hyps) >= max_h and cfg.prefer_keyed and allow_spawn and i not in used:
                self._make_room_for_blinker(i, t, reacq)
            picked = seeded_now and i == seed_pick        # the operator pointed at this one
            if (not allow_spawn or i in used or (c.snr < cfg.min_snr_new and not picked)
                    or len(self._hyps) >= max_h):
                continue
            if self._is_known_clutter(i) and not seeded_now:
                continue
            if seeded_now and (seed_pick is None or i != seed_pick):
                continue                         # only the light the operator pointed at
            cue_based = False
            if reacq:
                if self._flux_avg > 0 and \
                        abs(math.log(max(c.flux, 1e-3) / self._flux_avg)) > self._flux_tol(False) + 1.5:
                    continue
                d2 = self.tracker.gate_distance(t, az, el, r, reacq_cap)
                if d2 <= (9.0 if self._space_cue() else 16.0):
                    prior = -0.5 * d2
                    e = self.tracker.estimate_at(t)
                    vaz, vel = e.vaz, e.vel
                elif self._reacq_cue_phase:
                    prior, vaz, vel = self._cue_prior(t, az, el)
                    if prior < -0.5 * 2.5 ** 2:
                        continue
                    cue_based = True
                else:
                    continue
            elif seeded_now:
                prior, vaz, vel = 0.0, 0.0, 0.0
            else:
                prior, vaz, vel = self._cue_prior(t, az, el)
                if prior < -0.5 * 2.5 ** 2:
                    continue
                if any(angular_separation(az, el, cl[1], cl[2]) < 0.2 * DEG for cl in self._clutter):
                    continue
            kf = LosKalmanTracker(**self.cfg.tracker_kwargs)
            kf.initialize(t, az, el, vaz, vel, pos_sigma=(0.4 / self.K.fx) * 4,
                          vel_sigma=(0.25 if (reacq and not cue_based) else 2.5) * DEG)
            h = _Hypothesis(kf, prior, c.snr, c.flux, t)
            h.cue = cue_based
            h.seeded = seeded_now and not reacq
            h.last_px = c
            tr = self._assign[i] if i < len(self._assign) else None
            h.tid = tr.id if tr is not None else None
            self._hyps.append(h)

        if self._hyps:
            scored = sorted(((self._score(h, t, reacq and not h.cue), h) for h in self._hyps),
                            key=lambda p: p[0], reverse=True)
            top_score, top = scored[0]
            hreacq = reacq and not top.cue
            need = cfg.confirm_hits_reacq if hreacq else cfg.confirm_hits_search
            if hreacq and self._space_cue():
                need = 6                      # dense star field near the prediction: a little more proof
            elif top.seeded:
                need = 2                      # pointed at by hand: confirm as soon as it is consistent
            margin_ok = len(scored) == 1 or top_score - scored[1][0] > 1.0 or top.hits >= need + 4
            plausible = self._plausible(top, t, hreacq)
            if not plausible and top.hits >= need + 6:
                if not hreacq:
                    e = top.kf.estimate_at(t)
                    self._clutter.append((t, e.az, e.el))
                self._hyps.remove(top)
            elif (top.hits >= need and top.misses == 0 and margin_ok and plausible
                  and self._id_ok(top, t, hreacq)):
                self.tracker = top.kf
                self._flux_avg = top.flux
                self._lf_var = top.lf_var
                ec = top.kf.estimate_at(t)
                self._vs = (ec.vaz, ec.vel)
                self._last_hit_t = t
                self._last_snr = top.last_px.snr if top.last_px else 0.0
                self._lock_tid = top.tid
                self._gap_max = 0.07
                self._hyps = []
                self._mode = TrackState.SEARCH
                if top.seeded:
                    self._lock_seeded = True          # operator's pick owns this lock
                self._seed = self._seed_t = None      # seed consumed; association takes over now
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

    # ------------------------------------------------------------- evidence
    def _cue_prior(self, t: float, az: float, el: float):
        cue = self._cue
        if cue is None:
            return 0.0, 0.0, 0.0
        dt = t - cue.t
        caz, cel = cue.az + cue.vaz * dt, cue.el + cue.vel * dt
        sep = angular_separation(az, el, caz, cel)
        return -0.5 * (sep / cue.sigma) ** 2, cue.vaz, cue.vel

    def _competitor(self, h: _Hypothesis, t: float) -> float:
        best = 0.0
        for tr in self.identifier.tracklets:
            if tr.id == h.tid or tr.feat is None:
                continue
            if tr.feat.span_s < 1.2 or tr.hits < 15:
                continue                      # sparse blips (rain, noise) are not a rival light
            if self._cue is not None and self._cue_prior(t, tr.az, tr.el)[0] < -0.5 * 2.5 ** 2:
                continue
            best = max(best, tr.p)
        return best

    def _id_ok(self, h: _Hypothesis, t: float, reacq: bool) -> bool:
        """Identity gate before a lock is declared."""
        idf = self.identifier
        if not idf.enabled or h.seeded:
            return True                       # the operator already said which light this is
        if self._cue is None and not reacq:
            # No cue: lock only the light the scene evidence ranks as the target, once it has been
            # watched long enough to rank at all. (The keyed-only rules below would let any
            # flickering overlay veto the real target forever when there is no cue cone.)
            tr = idf.by_id.get(h.tid)
            if tr is None or tr.sal <= -9.0 or t - h.born < self.cfg.min_rank_age_s:
                return False
            pool = idf.tracklets
            if self.cfg.prefer_keyed:
                blinking = self._blinkers(pool)
                if blinking:                       # a beacon-like light is in view: only the best one
                    return tr in blinking and self._blink_q(tr) >= 0.9 * max(self._blink_q(o) for o in blinking)
                if t - h.born < self.cfg.steady_accept_s:
                    return False                   # nothing blinks: a steady light, after a long look
            if self.cfg.rank_among_candidates:
                live = {x.tid for x in self._hyps}
                pool = [o for o in pool if o.id in live]
            best = max((o.sal for o in pool), default=-9.0)
            return tr.sal >= best - 0.5
        tr = idf.by_id.get(h.tid)
        p = tr.p if (tr is not None and tr.feat is not None) else None
        if reacq:
            if self.cfg.prefer_keyed:
                # a lost blinking beacon comes back blinking: never re-lock a light near the
                # predicted path on position alone (a lamp or a window would stick)
                return tr is not None and bool(self._blinkers([tr]))
            return p is None or p >= 0.25 or not idf.sig.learned
        age = t - h.born
        if self._space_cue() and not idf.sig.learned:
            # Star field: stars outnumber the beacon and scintillation can spike one score, so
            # a lock needs a blink that stays beacon-like, or long geometric consistency.
            if h.pgood_t is not None and t - h.pgood_t >= 0.3:
                return True
            if age < 1.6 or self._competitor(h, t) >= 0.6:
                return False
            return p is None or p >= 0.3
        if p is not None and p >= 0.7:
            return True
        if self._competitor(h, t) >= 0.6:
            return False                      # a more beacon-like source is in the cue cone
        if idf.sig.learned and p is not None and p < 0.05 and age < 3.0:
            return False                      # looks exactly like learned clutter
        if not idf.sig.learned and p is not None and p < 0.3 and age < 1.5:
            return False                      # already measured as steady / non-keyed: wait for more
        return age >= (1.2 if idf.sig.learned else 0.9)   # no modulated source seen: geometry decides

    def _flux_tol(self, locked: bool) -> float:
        sig = math.sqrt(self._lf_var)
        if locked:
            return max(self.cfg.flux_tolerance, min(2.0, 3.0 * sig))
        return max(self.cfg.flux_tolerance_coast, min(1.5, 2.5 * sig))

    def _jittery(self) -> bool:
        return self.tracker.initialized and self.tracker.measurement_noise_adapt * self.K.fx > 3.0

    def _plausible(self, h: _Hypothesis, t: float, reacq: bool) -> bool:
        e = h.kf.estimate_at(t)
        if reacq:
            ref = self.tracker.estimate_at(t)
            dv = math.hypot(wrap_pi(e.vaz - ref.vaz) * math.cos(e.el), e.vel - ref.vel)
            if self._space_cue():
                sv = math.hypot(e.sigma_vaz * math.cos(e.el), e.sigma_vel)
                return dv <= 0.4 * DEG + 3.0 * sv      # smooth orbital motion: stars don't match
            return dv <= 3.0 * DEG
        if self._cue is None:
            return True
        pr, cvaz, cvel = self._cue_prior(t, e.az, e.el)
        dv = math.hypot(wrap_pi(e.vaz - cvaz) * math.cos(e.el), e.vel - cvel)
        sv = math.hypot(e.sigma_vaz * math.cos(e.el), e.sigma_vel)
        dv_lim = (0.3 if self._cue.sigma < 1.0 * DEG else 1.0) * DEG   # ephemeris rates are precise
        return pr >= -0.5 * 2.0 ** 2 and dv <= dv_lim + 3.0 * sv

    def _score(self, h: _Hypothesis, t: float, reacq: bool) -> float:
        s = 0.01 * min(h.snr_sum, 8 * 40.0)
        if h.seeded:
            s += 8.0                          # an explicit operator pick outranks everything else
        e = h.kf.estimate_at(t)
        if reacq or self._cue is None:
            s += h.prior
        else:
            s += 2.0 * self._cue_prior(t, e.az, e.el)[0]
        tr = self.identifier.by_id.get(h.tid)
        if tr is not None and tr.feat is not None and self.identifier.enabled:
            s += 0.8 * tr.llr
        if tr is not None and self._cue is None and self.identifier.enabled and tr.sal > -9.0:
            if self.cfg.prefer_keyed:
                # Our own blinking beacon: a clean periodic on/off decides, not brightness.
                s += 12.0 * self._blink_q(tr) if self._blinkers([tr]) else -2.0
            else:
                # No external cue to point the way (a recorded video): the identifier's scene-relative
                # saliency — prominence, keying, behaviour, persistence, not-an-overlay — decides.
                # With a cue present this stays off entirely, so the simulator is unaffected.
                s += 1.5 * tr.sal
        if h.hits >= 3:
            s -= 3.0 * h.lf_var if tr is None or tr.feat is None else 0.0
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
        if st == TrackState.LOCKED:
            if meas is None:
                return 0.6
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
                space = self._space_cue()
                for h in self._hyps:
                    if h.hits < (1 if (reacq and not h.cue) else 2) or t - h.last_t > 0.3:
                        continue
                    if space and (h.hits < 6 or not self._plausible(h, t, reacq and not h.cue)):
                        continue                 # ephemeris already keeps the target in view: don't
                                                 # let a young star hypothesis drag the gimbal away
                    if not reacq or h.cue:
                        eh = h.kf.estimate_at(t)
                        if self._cue_prior(t, eh.az, eh.el)[0] < -0.5 * 2.0 ** 2:
                            continue
                    ready.append(h)
                if len(ready) > 1:
                    # blend only hypotheses that are nearly as good as the best one, so a drifting
                    # noise track cannot pull the camera away from a well-supported candidate
                    sc = [self._score(h, t, reacq and not h.cue) for h in ready]
                    top = max(sc)
                    ready = [h for h, v in zip(ready, sc) if v >= top - 2.0]
                if ready:
                    ests = [self._steer_est(h, tl, reacq) for h in ready]
                    if len(ests) > 1:
                        span_az = (max(e.az for e in ests) - min(e.az for e in ests)) * math.cos(ests[0].el)
                        span_el = max(e.el for e in ests) - min(e.el for e in ests)
                        if span_az < 0.7 * self.K.hfov_deg * DEG and span_el < 0.7 * self.K.vfov_deg * DEG:
                            n = len(ests)
                            return (sum(e.az for e in ests) / n, sum(e.el for e in ests) / n,
                                    sum(e.vaz for e in ests) / n, sum(e.vel for e in ests) / n, True)
                    if reacq:
                        k = max(range(len(ready)), key=lambda i: self._score(ready[i], t, not ready[i].cue))
                    else:
                        k = max(range(len(ready)),
                                key=lambda i: self._cue_prior(t, ests[i].az, ests[i].el)[0]
                                + 0.5 * self._id_llr(ready[i]))
                    e = ests[k]
                    return e.az, e.el, e.vaz, e.vel, True
            return self._spiral_reference(tl, dt, enc_az, enc_el)

    def _steer_est(self, h: _Hypothesis, tl: float, reacq: bool):
        """Where to point for a hypothesis. A young one (few, jittery, gappy hits) has an unreliable
        rate, and extrapolating it drags the camera off a target that is already in view; so it
        uses its last measured position moved at the externally known rate (cue, or the lost
        track's rate) until it has enough hits of its own."""
        if h.hits >= 5:
            return h.kf.estimate_at(tl)
        e = h.kf.estimate_at(h.last_t)
        if reacq and not h.cue and self.tracker.initialized:
            ref = self.tracker.estimate_at(h.last_t)
            vaz, vel = ref.vaz, ref.vel
        elif self._cue is not None:
            vaz, vel = self._cue.vaz, self._cue.vel
        else:
            vaz = vel = 0.0
        dt = max(0.0, tl - h.last_t)
        return _Steer(e.az + vaz * dt, e.el + vel * dt, vaz, vel)

    def _space_cue(self) -> bool:
        return self._cue is not None and self._cue.sigma < 1.0 * DEG

    def _id_llr(self, h: _Hypothesis) -> float:
        tr = self.identifier.by_id.get(h.tid)
        return tr.llr if (tr is not None and tr.feat is not None) else 0.0

    def _search_center_at(self, t: float):
        if self._mode == TrackState.REACQUIRE and self.tracker.initialized:
            horizon = self._last_hit_t + 3.0
            e = self.tracker.estimate_at(min(t, horizon))
            vaz, vel = self._vs if self._jittery() else (e.vaz, e.vel)
            use_pred = True
            if self._reacq_cue_phase and self._cue is not None:
                c = self._cue
                dc = t - c.t
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
        b = self.cfg.search_pitch_fov * min(self.K.hfov_deg, self.K.vfov_deg) * DEG / (2 * math.pi)
        rmax = self.cfg.search_radius_deg * DEG
        if self._cue is not None and self._cue.sigma < 1.0 * DEG:
            rmax = max(2.0 * DEG, 4.0 * self._cue.sigma)
        if self._mode == TrackState.REACQUIRE and not self._reacq_center_cue:
            rmax = self._reacq_rmax
        return b, rmax, self._search_s

    @property
    def reacquiring(self) -> bool:
        """True while hunting for a target just lost (path prediction), False on a fresh search."""
        return self._mode == TrackState.REACQUIRE

    def search_center(self, t: float):
        with self._lock:
            return self._search_center_at(t)

    def _within_travel(self, az: float, el: float) -> Tuple[float, float]:
        cfg = self.cfg
        if cfg.az_limits is not None:
            az = max(cfg.az_limits[0], min(cfg.az_limits[1], az))
        if cfg.el_limits is not None:
            el = max(cfg.el_limits[0], min(cfg.el_limits[1], el))
        return az, el

    def _spiral_reference(self, t: float, dt: float, enc_az: float, enc_el: float):
        if self._mode == TrackState.SEARCH and self._cue is None:
            if self.cfg.require_cue:
                return enc_az, enc_el, 0.0, 0.0, False
            if self._search_center is None:
                self._search_center = (enc_az, enc_el)
        caz, cel, cvaz, cvel = self._search_center_at(t)
        b, rmax, _ = self.search_geometry()
        speed = self.cfg.search_speed_deg * DEG
        if math.hypot(wrap_pi(caz - enc_az) * math.cos(cel), cel - enc_el) < 2.0 * DEG:
            self._search_started = True

        ox, oy = self._spiral_offsets(self._search_s, b)
        ref_az, ref_el = self._within_travel(caz + ox / max(0.2, math.cos(cel)), cel + oy)
        err = math.hypot(wrap_pi(ref_az - enc_az) * math.cos(cel), ref_el - enc_el)
        # Space: ephemeris + orbit prediction are accurate, so stare instead of scanning while
        # candidates in view mature, and after a loss while the prediction is still fresh.
        hold = self._space_cue() and (
            self.state == TrackState.ACQUIRING
            or (self._mode == TrackState.REACQUIRE and self.tracker.initialized
                and not self._reacq_center_cue and t - self._last_hit_t < 3.0))
        if err < 0.6 * DEG and not hold:
            if self._search_dwell < 0.15:
                self._search_dwell += dt
            else:
                self._search_s += speed * dt
        if b * math.sqrt(2.0 * self._search_s / b) > rmax:
            self._search_s = 0.0
            self._search_dwell = 0.0

        ox2, oy2 = self._spiral_offsets(self._search_s + speed * 0.01, b)
        moving = err < 0.6 * DEG and not hold        # a held spiral must not feed forward its scan rate
        vx = (ox2 - ox) / 0.01 if moving else 0.0
        vy = (oy2 - oy) / 0.01 if moving else 0.0
        vaz = cvaz + vx / max(0.2, math.cos(cel))
        vel = cvel + vy
        return ref_az, ref_el, vaz, vel, False
