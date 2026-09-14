"""Engine — runs the closed loop with decoupled threads.

  Vision thread  (30 Hz)  capture/render frame -> detect -> track -> evaluate -> publish
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
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

from ..core.controller import GimbalController
from ..core.geometry import CameraIntrinsics
from ..core.pipeline import PipelineOutput, TrackingPipeline, TrackState
from ..io.gimbal import SimulatedGimbal
from ..sim.hazards import HAZARD_KEYS
from ..sim.renderer import SensorRenderer, Truth
from ..sim.world import SimWorld
from .evaluator import Evaluator
from .recorder import Recorder


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
    search: Tuple[float, float, float, float, float]   # center az, el, pitch, rmax, s
    centroid_err: Optional[float]
    pointing_err: Optional[float]
    track_sep_px: Optional[float]
    paused: bool
    run_id: int


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
        self.frame_listeners: List[Callable[[Snapshot], None]] = []

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

    def cold_restart(self) -> None:
        def do():
            t = self.clock.now()
            self.gimbal.reset(0.0, 0.0)
            self.controller.reset()
            self.pipeline.reset()
            self.evaluator.reset(t)
            self.recorder.clear()
            self._last_control_t = None
            self.run_id += 1
        self._post(do)

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
            self.gimbal.reset(0.0, 0.0)
            self.controller.reset()
            self.pipeline.reset()
            self.evaluator.reset(0.0)
            self.recorder.clear()
            self._last_control_t = None
            self.run_id += 1
        self._post(do)

    def set_paused(self, paused: bool) -> None:
        if paused:
            self.clock.pause()
        else:
            self.clock.resume()

    @property
    def paused(self) -> bool:
        return self.clock.paused

    def set_pattern(self, key: str) -> None:
        self._post(lambda: self.world.patterns.set_pattern(key, self.clock.now()))

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
        snap = Snapshot(
            t=t, image=image, out=out, truth=truth, gimbal=g,
            cue=(cue.az, cue.el) if cue else (0.0, 0.0),
            target_pos=self.world.target_pos(t), range_m=truth.range_m,
            metrics=metrics, rates=rates, stage_ms=stage,
            hazard_levels=self.world.hazards.levels(), pattern=self.world.patterns.key,
            time_of_day=self.world.time_of_day, search=(caz, cel, b, rmax, s),
            centroid_err=ev.last_centroid_err, pointing_err=ev.last_pointing_err,
            track_sep_px=ev.last_track_sep_px, paused=self.clock.paused, run_id=self.run_id,
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
        """Smooth 60 Hz pose for the world view: (t, target_pos, gimbal az, el)."""
        t = self.clock.now()
        g = self.gimbal.true_pose(t)
        return t, self.world.target_pos(t), g[0], g[1]

    # ================================================================ headless
    def run_headless(self, duration_s: float, events: Dict[float, Callable[["Engine"], None]] = None,
                     on_frame: Optional[Callable[[Snapshot], None]] = None) -> dict:
        """Deterministic stepped run at simulated real-time rates (used by validation)."""
        self.headless = True
        self._run_commands()
        events = dict(events or {})
        steps = int(duration_s * self.CONTROL_HZ)
        ratio = int(round(self.CONTROL_HZ / self.VISION_HZ))
        wall0 = time.perf_counter()
        for k in range(steps + 1):
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
        return {"metrics": m, "summary": summary}
