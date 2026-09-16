"""Engine — runs the closed loop with decoupled threads.

  Vision thread  (30 Hz)  capture/render frame -> detect -> identify -> track -> evaluate -> publish
  Control thread (60 Hz)  read encoders -> Kalman prediction to 'now + latency' ->
                          PI + feed-forward -> gimbal rate command
  GUI thread     (60 Hz)  reads immutable snapshots; never blocks the loops

Exactly the same tick functions are used by the headless stepped mode (validation suite),
so what is benchmarked is what runs in the app.
"""

import math
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

from ..core.controller import GimbalController
from ..core.geometry import CameraIntrinsics
from ..core.pipeline import PipelineOutput, TrackingPipeline
from ..io.gimbal import SimulatedGimbal
from ..io.sources import VideoFileSource
from ..sim.patterns import INFO_BY_KEY
from ..sim.renderer import SensorRenderer, Truth
from ..sim.terminals import PLATFORM_BY_KEY
from ..sim.world import SimWorld
from .evaluator import Evaluator
from .recorder import Recorder

DEFAULT_PATTERN = {"quad": "hover", "fixedwing": "orbit", "ship": "maritime",
                   "satellite": "leo_pass", "station": "iss_pass"}


class RateMeter:
    def __init__(self, window_s: float = 1.0) -> None:
        self.window = window_s
        self._ts = deque(maxlen=400)

    def tick(self, now: Optional[float] = None) -> None:
        self._ts.append(time.perf_counter() if now is None else now)

    def rate(self) -> float:
        ts = self._ts
        if len(ts) < 2:
            return 0.0
        now = time.perf_counter()
        while len(ts) > 2 and now - ts[0] > self.window:
            ts.popleft()
        span = ts[-1] - ts[0]
        if span <= 0 or now - ts[-1] > 0.5:
            return 0.0
        return (len(ts) - 1) / span


class SimClock:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._origin = time.perf_counter()
        self._paused_at: Optional[float] = None

    def now(self) -> float:
        ref = self._paused_at if self._paused_at is not None else time.perf_counter()
        return ref - self._origin

    @property
    def paused(self) -> bool:
        return self._paused_at is not None

    def pause(self) -> None:
        if self._paused_at is None:
            self._paused_at = time.perf_counter()

    def resume(self) -> None:
        if self._paused_at is not None:
            self._origin += time.perf_counter() - self._paused_at
            self._paused_at = None


@dataclass
class Snapshot:
    t: float
    image: np.ndarray
    out: PipelineOutput
    truth: Truth
    gimbal: Tuple[float, float, float, float]
    cue: Tuple[float, float]
    target_pos: Tuple[float, float, float]
    range_m: float
    metrics: Dict[str, dict]
    rates: Dict[str, float]
    stage_ms: Tuple[float, float, float]
    hazard_levels: Dict[str, float]
    pattern: str
    time_of_day: str
    search: Tuple[float, float, float, float, float]
    centroid_err: Optional[float]
    pointing_err: Optional[float]
    track_sep_px: Optional[float]
    paused: bool
    run_id: int
    cam_pos: Tuple[float, float, float]
    platform: str
    domain: str


class Engine:
    VISION_HZ = 30.0
    CONTROL_HZ = 60.0

    def __init__(self, seed: int = 42, pattern: str = "orbit") -> None:
        self.K = CameraIntrinsics.from_fov(640, 480, 4.0, 3.0)
        self.seed = seed
        self.world = SimWorld(seed, pattern)
        self.gimbal = SimulatedGimbal()
        self.renderer = SensorRenderer(self.K, self.world, self.gimbal, seed)
        self.pipeline = TrackingPipeline(self.K)
        self.controller = GimbalController()
        self.evaluator = Evaluator(self.K)
        self.recorder = Recorder()
        self.clock = SimClock()

        self.vision_rate = RateMeter()
        self.control_rate = RateMeter()
        self.render_rate = RateMeter()
        self.headless = False
        self._sim_rates = (self.VISION_HZ, self.CONTROL_HZ)

        self._commands: List[Callable[[], None]] = []
        self._cmd_lock = threading.Lock()
        self._snapshot: Optional[Snapshot] = None
        self._stop = threading.Event()
        self._threads: List[threading.Thread] = []
        self._last_control_t: Optional[float] = None
        self.run_id = 0
        self.ui_revision = 0          # bumped when the engine changes settings the UI shows
        self.frame_listeners: List[Callable[[Snapshot], None]] = []
        self.video_source: Optional[VideoFileSource] = None
        self._video_path: Optional[str] = None
        self.video_error: Optional[str] = None
        self.gimbal.reset(*self._park_pose(0.0))

    # ================================================================ lifecycle
    def start(self) -> None:
        self._stop.clear()
        self.clock.reset()
        self._threads = [
            threading.Thread(target=self._vision_loop, name="vision", daemon=True),
            threading.Thread(target=self._control_loop, name="control", daemon=True),
        ]
        for th in self._threads:
            th.start()

    def shutdown(self) -> None:
        self._stop.set()
        for th in self._threads:
            th.join(timeout=1.0)

    # ================================================================ commands
    def _post(self, fn: Callable[[], None]) -> None:
        with self._cmd_lock:
            self._commands.append(fn)

    def _run_commands(self) -> None:
        with self._cmd_lock:
            cmds, self._commands = self._commands, []
        for fn in cmds:
            fn()

    def _park_pose(self, t: float) -> Tuple[float, float]:
        """Cold-start pointing. Spacecraft (either end): open-loop pre-point to the
        ephemeris-predicted position (as operational ground stations — or satellites tracking
        a crosslink partner — do before a pass). Otherwise: stow at 0/0."""
        if self.world.space_scene:
            c = self.world.cue(t)
            return c.az, c.el
        return 0.0, 0.0

    def _restart_tracking(self, t: float, park: bool = False) -> None:
        if park:
            self.gimbal.reset(*self._park_pose(t))
        self.controller.reset()
        self.pipeline.reset()
        self.evaluator.reset(t)
        self.recorder.clear()
        self._last_control_t = None
        self.run_id += 1

    def cold_restart(self) -> None:
        self._post(lambda: self._restart_tracking(self.clock.now(), park=True))

    def new_run(self, seed: Optional[int] = None) -> None:
        def do():
            if seed is not None:
                self.seed = int(seed)
            self.world.reset(self.seed)
            self.renderer.reseed(self.seed)
            was_paused = self.clock.paused
            self.clock.reset()
            if was_paused:
                self.clock.pause()
            self._restart_tracking(0.0, park=True)
        self._post(do)

    def set_paused(self, paused: bool) -> None:
        if paused:
            self.clock.pause()
        else:
            self.clock.resume()

    @property
    def paused(self) -> bool:
        return self.clock.paused

    # ------------------------------------------------------------ remote terminal
    def set_pattern(self, key: str) -> None:
        def do():
            t = self.clock.now()
            w = self.world
            was_space = w.remote.space
            w.remote.set_pattern(key, t)
            now_space = w.remote.space
            if was_space != now_space:
                w.time_of_day = "night" if now_space else "day"
                self.ui_revision += 1
            if was_space or now_space:
                # a different sky: acquisition starts afresh from the new ephemeris
                self._restart_tracking(t, park=True)
        self._post(do)

    def set_platform(self, platform: str) -> None:
        self.set_pattern(DEFAULT_PATTERN[platform])

    def set_remote(self, speed: Optional[float] = None, range_km: Optional[float] = None,
                   bearing: Optional[float] = None, altitude: Optional[float] = None,
                   variation: Optional[float] = None) -> None:
        def do():
            t, r = self.clock.now(), self.world.remote
            if speed is not None:
                r.set_speed(t, speed)
            if range_km is not None:
                r.range_km.set(t, range_km)
            if bearing is not None:
                r.bearing.set(t, bearing)
            if altitude is not None:
                r.alt_off.set(t, altitude)
            if variation is not None:
                r.variation.set(t, variation)
        self._post(do)

    def set_orbit(self, alt_km: Optional[float] = None, max_el: Optional[float] = None,
                  heading: Optional[float] = None) -> None:
        def do():
            t = self.clock.now()
            self.world.remote.set_orbit(t, alt_km, max_el, heading)
            if self.world.remote.key in ("leo_pass", "iss_pass"):
                self._restart_tracking(t, park=True)
        self._post(do)

    def remote_goto(self, x: float, z: float, y: Optional[float] = None) -> None:
        def do():
            r = self.world.remote
            before = r.key
            r.goto(self.clock.now(), x, z, y)
            if r.key != before:
                self.ui_revision += 1
        self._post(do)

    # ------------------------------------------------------------ ground terminal
    def set_ground(self, mount: Optional[str] = None, x: Optional[float] = None, z: Optional[float] = None,
                   height: Optional[float] = None) -> None:
        def do():
            t, w, g = self.clock.now(), self.world, self.world.ground
            was_space = w.space_scene
            if mount is not None:
                g.set_mount(t, mount)
            g.set_position(t, x, z, height)
            now_space = w.space_scene
            if was_space != now_space:
                # Terminal A itself moved between ground and orbit: a different sky (and, for a
                # satellite, a different pre-pointing strategy), so acquisition starts afresh.
                w.time_of_day = "night" if now_space else "day"
                self.ui_revision += 1
                self._restart_tracking(t, park=True)
        self._post(do)

    def set_ground_orbit(self, alt_km: Optional[float] = None, incl: Optional[float] = None,
                         heading: Optional[float] = None) -> None:
        def do():
            self.world.ground.set_orbit(alt_km, incl, heading)
            if self.world.ground.space:
                self._restart_tracking(self.clock.now(), park=True)
        self._post(do)

    # ------------------------------------------------------------------ beacon
    def set_beacon(self, freq_hz: Optional[float] = None, brightness: Optional[float] = None,
                   depth: Optional[float] = None) -> None:
        b = self.world.beacon
        if freq_hz is not None:
            b.freq_hz = float(freq_hz)
        if brightness is not None:
            b.brightness = float(brightness)
        if depth is not None:
            b.depth = float(depth)

    def reset_identity(self) -> None:
        self._post(self.pipeline.reset_identity)

    # -------------------------------------------------------------------- video
    def load_video(self, path: str, hfov_deg: float = 4.0) -> None:
        """Switch to a recorded video: the exact same TrackingPipeline and GimbalController run
        on real frames instead of the simulator. No ground truth exists for a real recording, so
        the SIH scoring that depends on it (tracking error, target loss, re-acquisition) reports
        "—"; acquisition, processing speed and camera update rate are still measured live."""
        def do():
            try:
                src = VideoFileSource(path, hfov_deg=hfov_deg)
            except Exception as ex:
                self.video_error = str(ex)
                return
            if self.video_source is not None:
                self.video_source.close()
            self.video_source = src
            self._video_path = path
            self.video_error = None
            self.pipeline.cfg.require_cue = False   # no telemetry cue for a recorded video
            self.pipeline.clear_cue()
            self._restart_tracking(self.clock.now())
            self.ui_revision += 1
        self._post(do)

    def use_simulation(self) -> None:
        def do():
            if self.video_source is not None:
                self.video_source.close()
            self.video_source = None
            self._video_path = None
            self.video_error = None
            self.pipeline.cfg.require_cue = True
            self._restart_tracking(self.clock.now(), park=True)
            self.ui_revision += 1
        self._post(do)

    @property
    def is_video(self) -> bool:
        return self.video_source is not None

    # ------------------------------------------------------------------ misc
    def set_hazard(self, key: str, enabled: Optional[bool] = None, intensity: Optional[float] = None) -> None:
        self.world.hazards.set(key, enabled, intensity)

    def set_time_of_day(self, tod: str) -> None:
        self.world.time_of_day = tod

    def block_beacon(self, seconds: float = 2.0) -> None:
        self._post(lambda: self.world.hazards.force_block(self.clock.now(), seconds))

    def set_max_slew(self, deg_s: float) -> None:
        self.controller.set_max_rate(deg_s)

    def report_render_frame(self) -> None:
        self.render_rate.tick()

    def remote_state(self) -> dict:
        r, g, b = self.world.remote, self.world.ground, self.world.beacon
        return dict(platform=r.info.platform, pattern=r.key, speed=r.warp._seg[-1][3], range_km=r.range_km.target(),
                    bearing=r.bearing.target(), altitude=r.alt_off.target(), variation=r.variation.target(),
                    orbit_alt=r.orbit_alt, max_el=r.max_el, heading=r.heading, mount=g.mount,
                    ground_x=g.x.target(), ground_z=g.z.target(), ground_h=g.height.target(),
                    ground_orbit_alt=g.sat_alt_km, ground_incl=g.sat_incl, ground_heading=g.sat_heading,
                    beacon_freq=b.freq_hz, beacon_brightness=b.brightness, beacon_depth=b.depth,
                    max_slew=math.degrees(self.controller.max_rate), time_of_day=self.world.time_of_day)

    # ================================================================ loops
    def _control_loop(self) -> None:
        period = 1.0 / self.CONTROL_HZ
        nxt = time.perf_counter()
        while not self._stop.is_set():
            if not self.clock.paused:
                self._control_tick(self.clock.now())
                self.control_rate.tick()
            nxt += period
            delay = nxt - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
            else:
                nxt = time.perf_counter()

    def _vision_loop(self) -> None:
        period = 1.0 / self.VISION_HZ
        nxt = time.perf_counter()
        while not self._stop.is_set():
            self._run_commands()
            if not self.clock.paused:
                self._vision_tick(self.clock.now())
                self.vision_rate.tick()
            else:
                self._republish_paused()
            nxt += period
            delay = nxt - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
            else:
                nxt = time.perf_counter()

    def _control_tick(self, t: float) -> None:
        last = self._last_control_t
        dt = (t - last) if last is not None else 1.0 / self.CONTROL_HZ
        if dt <= 0 or dt > 0.2:
            dt = 1.0 / self.CONTROL_HZ
        self._last_control_t = t
        self.gimbal.advance(t)
        st = self.gimbal.read_state(t)
        az, el, vaz, vel, tracking = self.pipeline.pointing_reference(t, dt, st.az, st.el)
        caz, cel = self.controller.compute(dt, st.az, st.el, az, el, vaz, vel, tracking)
        self.gimbal.command_rate(t, caz, cel)

    def _vision_tick(self, t: float) -> None:
        if self.video_source is not None:
            self._vision_tick_video(t)
            return
        w = self.world
        c0 = time.perf_counter()
        self.pipeline.set_cue(w.cue(t))
        frame, truth = self.renderer.render(t)
        c1 = time.perf_counter()
        out = self.pipeline.process_frame(frame)
        render_ms = (c1 - c0) * 1000.0
        ev = self.evaluator
        ev.on_frame(out, truth, render_ms, out.detect_ms, out.track_ms)
        stage = (render_ms, out.detect_ms, out.track_ms)
        self.recorder.add(out, truth, ev, stage)
        self._publish(t, frame.image, out, truth, stage)

    def _vision_tick_video(self, t: float) -> None:
        c0 = time.perf_counter()
        src = self.video_source
        frame = src.read() if src is not None else None
        if frame is None and self._video_path is not None:
            src.close()
            self.video_source = VideoFileSource(self._video_path, hfov_deg=self.K.hfov_deg)
            frame = self.video_source.read()
        if frame is None:
            return
        out = self.pipeline.process_frame(frame)
        render_ms = (time.perf_counter() - c0) * 1000.0
        # No ground truth exists for a real recording; the pipeline and GUI already treat a
        # None target_px / cam_az,el-only Truth as "unknown", which is exactly what this is.
        truth = Truth(t=frame.t, target_px=None, in_fov=False, occluded=False, occlusion_kind="",
                      target_los=(0.0, 0.0), range_m=0.0, cam_az=frame.gimbal_az, cam_el=frame.gimbal_el,
                      beacon_peak_dn=0.0, beacon_on=True)
        stage = (render_ms, out.detect_ms, out.track_ms)
        self.evaluator.on_frame(out, truth, render_ms, out.detect_ms, out.track_ms, has_truth=False)
        self.recorder.add(out, truth, self.evaluator, stage)
        self._publish(frame.t, frame.image, out, truth, stage)

    def rates(self) -> Dict[str, float]:
        if self.headless:
            return {"vision": self._sim_rates[0], "control": self._sim_rates[1], "render": None}
        return {"vision": self.vision_rate.rate(), "control": self.control_rate.rate(),
                "render": self.render_rate.rate()}

    def _publish(self, t, image, out, truth, stage) -> None:
        g = self.gimbal.true_pose(t)
        cue = self.pipeline._cue
        rates = self.rates()
        metrics = self.evaluator.metrics(rates["vision"], rates["control"], rates["render"])
        b, rmax, s = self.pipeline.search_geometry()
        caz, cel, _, _ = self.pipeline.search_center(t)
        ev = self.evaluator
        w = self.world
        snap = Snapshot(
            t=t, image=image, out=out, truth=truth, gimbal=g,
            cue=(cue.az, cue.el) if cue else (0.0, 0.0),
            target_pos=w.target_pos(t), range_m=truth.range_m,
            metrics=metrics, rates=rates, stage_ms=stage,
            hazard_levels=w.hazards.levels(), pattern=w.remote.key,
            time_of_day=w.time_of_day, search=(caz, cel, b, rmax, s),
            centroid_err=ev.last_centroid_err, pointing_err=ev.last_pointing_err,
            track_sep_px=ev.last_track_sep_px, paused=self.clock.paused, run_id=self.run_id,
            cam_pos=w.camera_pos(t), platform=w.remote.info.platform, domain=w.domain,
        )
        self._snapshot = snap
        for fn in self.frame_listeners:
            fn(snap)

    def _republish_paused(self) -> None:
        s = self._snapshot
        if s is not None and not s.paused:
            s.paused = True

    def snapshot(self) -> Optional[Snapshot]:
        return self._snapshot

    def live_pose(self):
        """Smooth 60 Hz pose for the world view: (t, target_pos, gimbal az, el, camera_pos)."""
        t = self.clock.now()
        g = self.gimbal.true_pose(t)
        return t, self.world.target_pos(t), g[0], g[1], self.world.camera_pos(t)

    # ================================================================ headless
    def run_headless(self, duration_s: float, events: Dict[float, Callable[["Engine"], None]] = None,
                     on_frame: Optional[Callable[[Snapshot], None]] = None,
                     should_stop: Optional[Callable[[], bool]] = None) -> dict:
        self.headless = True
        self._run_commands()
        events = dict(events or {})
        steps = int(duration_s * self.CONTROL_HZ)
        ratio = int(round(self.CONTROL_HZ / self.VISION_HZ))
        wall0 = time.perf_counter()
        stopped = False
        for k in range(steps + 1):
            if should_stop is not None and should_stop():
                stopped = True
                break
            t = k / self.CONTROL_HZ
            for et in [e for e in events if e <= t]:
                events.pop(et)(self)
            self._run_commands()
            self._control_tick(t)
            if k % ratio == 0:
                self._vision_tick(t)
                if on_frame is not None and self._snapshot is not None:
                    on_frame(self._snapshot)
        wall = time.perf_counter() - wall0
        rates = self.rates()
        m = self.evaluator.metrics(rates["vision"], rates["control"], None)
        summary = self.evaluator.summary()
        summary["wall_time_s"] = round(wall, 2)
        summary["stopped"] = stopped
        sig = self.pipeline.identifier.sig
        summary["identity_learned"] = sig.learned
        summary["identity_freq_hz"] = round(sig.freq_hz, 2)
        return {"metrics": m, "summary": summary}
