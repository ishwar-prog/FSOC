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

from ..core.controller import ControllerGains, GimbalController
from ..core.geometry import CameraIntrinsics
from ..core.pipeline import PipelineOutput, TrackingPipeline, TrackState
from ..core.video import EgoMotion, VideoBeaconDetector
from ..io.gimbal import SimulatedGimbal
from ..io.sources import VideoFileSource
from ..sim.patterns import INFO_BY_KEY
from ..sim.renderer import SensorRenderer, Truth
from ..sim.terminals import PLATFORM_BY_KEY
from ..sim.world import SimWorld
from .evaluator import Evaluator
from .hardware import HardwareRig, RigStage
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
    hardware: Optional[dict] = None


class Engine:
    VISION_HZ = 30.0
    CONTROL_HZ = 60.0

    def __init__(self, seed: int = 42, pattern: str = "orbit") -> None:
        self.K = CameraIntrinsics.from_fov(640, 480, 4.0, 3.0)
        self._sim_K = self.K
        self.seed = seed
        self.world = SimWorld(seed, pattern)
        self.gimbal = SimulatedGimbal()
        self._sim_gimbal = self.gimbal
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
        self._ego: Optional[EgoMotion] = None
        self.hw: Optional[HardwareRig] = None
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
        if self.hw is not None:
            self.hw.close()

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
    VIDEO_PX_PER_DEG = 160.0
    VIDEO_EGO_MOTION = False

    def load_video(self, path: str, hfov_deg: Optional[float] = None) -> None:
        """Switch to a recorded video: the exact same detector, identifier, Kalman tracker and
        controller run on real frames instead of the simulator.

        A real clip has its own resolution, so the whole pipeline is rebuilt around the video's
        intrinsics — keeping the simulator's 640x480 ones would leave every pixel<->angle
        conversion, ROI and overlay at the wrong scale. An uncalibrated recording gives no way to
        know its true field of view, so the default keeps the angular scale the gates were tuned
        at (`VIDEO_PX_PER_DEG`); pass `hfov_deg` when the real optics are known.
        """
        def do():
            fov = hfov_deg
            try:
                if fov is None:                      # probe the size first to pick a sane FOV
                    probe = VideoFileSource(path, hfov_deg=4.0)
                    fov = max(2.0, probe.intrinsics.width / self.VIDEO_PX_PER_DEG)
                    probe.close()
                src = VideoFileSource(path, hfov_deg=fov)
            except Exception as ex:
                self.video_error = str(ex)
                self.ui_revision += 1
                return
            self._drop_hardware()
            if self.video_source is not None:
                self.video_source.close()
            self.video_source = src
            self._video_path = path
            self.video_error = None
            self._rebuild_for(src.intrinsics, video=True)
            self.ui_revision += 1
        self._post(do)

    def use_simulation(self) -> None:
        def do():
            self._drop_hardware()
            if self.video_source is not None:
                self.video_source.close()
            self.video_source = None
            self._video_path = None
            self.video_error = None
            self._rebuild_for(self._sim_K, video=False)
            self.ui_revision += 1
        self._post(do)

    def _rebuild_for(self, K: CameraIntrinsics, video: bool) -> None:
        """Point the whole vision chain at a new camera geometry (simulator <-> video)."""
        self.K = K
        self.pipeline = TrackingPipeline(K, detector=VideoBeaconDetector(K) if video else None)
        self.pipeline.cfg.require_cue = not video    # a recording has no telemetry cue
        # Ego-motion (camera pan compensation) is implemented and measures pans correctly, but on
        # the test recordings it did more harm than good (glitch frames); opt-in for now.
        self._ego = EgoMotion(K.fx, K.fy) if (video and self.VIDEO_EGO_MOTION) else None
        if video:
            self.pipeline.clear_cue()
            # real scenes (smoke, cracks, star fields) offer far more lights than the simulator;
            # the identifier must be able to keep all of them in view to rank them fairly
            self.pipeline.identifier.MAX_TRACKLETS = 48
        self.evaluator = Evaluator(K, has_truth=not video)
        self.recorder.clear()
        self.controller.reset()
        self._last_control_t = None
        if not video:
            self.gimbal.reset(*self._park_pose(self.clock.now()))
        self.evaluator.reset(self.clock.now())
        self.run_id += 1

    def seed_target(self, x: float, y: float) -> None:
        """Operator points at the target in the camera view ("that one"). Works in video mode
        where no telemetry cue exists, and on stubborn real footage full of look-alikes."""
        self._post(lambda: self.pipeline.seed_target(x, y))

    @property
    def is_video(self) -> bool:
        return self.video_source is not None

    @property
    def is_hardware(self) -> bool:
        return self.hw is not None

    @property
    def is_real(self) -> bool:
        """Real footage (video or live camera): no ground truth, operator may point at the target."""
        return self.is_video or self.is_hardware

    # ------------------------------------------------------------------ hardware
    # Tracking settings for the pan/tilt head, in real degrees; converted to the tracker's working
    # scale once the rig has measured its pixels per degree.
    HW_SEARCH_SPEED_DEG = 18.0       # scan speed while searching
    HW_SEARCH_RADIUS_DEG = 100.0     # scan reach (held inside the servo travel)
    HW_MAX_RATE_DEG = 35.0           # head slew limit (adjustable live: set_head_speed)...
    HW_MAX_ACCEL_DEG = 120.0         # ...and acceleration limit: no jerks, no overshoot
    HW_TARGET_RATE_DEG = 120.0       # what the Kalman model allows a hand-held beacon to do
    HW_TARGET_ACCEL_DEG = 400.0
    HW_Q_JERK = 1.0e-3               # manoeuvre noise (working units); stand-in validated 5e-4..1e-3
    HW_TARGET_TAU_S = 1.0
    HW_ACTUATOR_LATENCY_S = 0.06     # command -> servo motion, compensated by prediction
    HW_KEYED_WEIGHT = 5.0            # blink evidence vs brightness when ranking lights
    HW_MIN_RANK_AGE_S = 1.0          # watch a light this long (blink evidence) before a lock
    HW_SIZE_NOISE = 0.12             # centroid uncertainty per px of blob size (close beacons)
    # Loop gains. A webcam's ~0.1 s delay and a hobby servo's lag put the phase margin of the
    # simulator's gains (kp 9/s + integral, tuned for a 20 ms gimbal) near zero: the head would
    # oscillate. No integral here: the servo is a position device, and a deadband winds it up.
    HW_KP = 2.5
    HW_KI = 0.0
    HW_KP_SEARCH = 4.0

    def connect_hardware(self, camera_index: int = 0, port: Optional[str] = None,
                         hfov_deg: float = 60.0) -> None:
        """Track with the real rig: USB webcam + two-servo pan/tilt head on `port`."""
        def do():
            self._drop_hardware()
            if self.video_source is not None:
                self.video_source.close()
                self.video_source, self._video_path = None, None
            rig = HardwareRig(camera_index, port, hfov_deg)
            self.hw = rig
            rig.start()
            self.ui_revision += 1
        self._post(do)

    def disconnect_hardware(self) -> None:
        def do():
            if self.hw is not None:
                self._drop_hardware()
                self._rebuild_for(self._sim_K, video=False)
                self.ui_revision += 1
        self._post(do)

    def _drop_hardware(self) -> None:
        self.hw_manual = False
        rig, self.hw = self.hw, None
        if rig is None:
            return
        self.gimbal = self._sim_gimbal
        self.controller = GimbalController()
        rig.close()

    def _enter_hardware_tracking(self, rig: HardwareRig) -> None:
        """Calibration done: the same pipeline and controller as the simulator take the head."""
        k = rig.scale()
        self.gimbal = rig.gimbal
        self._rebuild_for(rig.K, video=True)
        cfg = self.pipeline.cfg
        cfg.az_limits, cfg.el_limits = rig.work_limits()
        cfg.search_speed_deg = self.HW_SEARCH_SPEED_DEG * k
        cfg.search_radius_deg = self.HW_SEARCH_RADIUS_DEG * k
        cfg.tracker_kwargs = dict(q_jerk=self.HW_Q_JERK, tau_s=self.HW_TARGET_TAU_S,
                                  vel_limit=self.HW_TARGET_RATE_DEG * k * math.pi / 180.0,
                                  acc_limit=self.HW_TARGET_ACCEL_DEG * k * math.pi / 180.0)
        # Our own beacon blinks: on a live rig that evidence outranks raw brightness (windows,
        # lamps and reflections in a room are brighter and larger than a small LED).
        cfg.rank_among_candidates = True
        self.pipeline.detector.KEEP_EMBEDDED = True
        cfg.prefer_keyed = True
        cfg.min_rank_age_s = self.HW_MIN_RANK_AGE_S
        # A beacon brought close grows into a large saturated blob: its brightness climbs fast,
        # its centre is coarser, and it outgrows the photometry window.
        cfg.use_roi = False
        cfg.seed_probe = True            # a clicked light is tracked even below the auto gates
        cfg.size_noise = self.HW_SIZE_NOISE
        cfg.flux_tolerance, cfg.flux_tolerance_coast = 3.0, 2.5
        self.pipeline.detector.CONSOLIDATE = True
        self.pipeline.detector.BRIGHT_PATH = True    # an LED beacon is simply the brightest thing
        self.pipeline.identifier.APERTURE_MAX = 150
        self.pipeline.identifier.MERGE_DUPLICATES = True
        self.pipeline.identifier.KEYED_WEIGHT = self.HW_KEYED_WEIGHT
        self.pipeline.latency_s = self.HW_ACTUATOR_LATENCY_S
        self.pipeline.reset()
        self.controller = GimbalController(max_rate_deg=self.HW_MAX_RATE_DEG * k,
                                           max_accel_deg=self.HW_MAX_ACCEL_DEG * k,
                                           gains=ControllerGains(kp_track=self.HW_KP, ki_track=self.HW_KI,
                                                                 kp_search=self.HW_KP_SEARCH))
        self.ui_revision += 1

    def hardware_status(self) -> Optional[dict]:
        if self.hw is None:
            return None
        st = self.hw.status()
        st["manual"] = self.hw_manual
        st["speed"] = self.HW_MAX_RATE_DEG
        return st

    # ---- manual pan/tilt
    hw_manual = False

    def set_manual(self, on: bool) -> None:
        """Manual: the operator drives the head; detection keeps running and is shown, but the
        tracker does not move the servos. Back to auto resumes from whatever it sees."""
        def do():
            self.hw_manual = bool(on)
            self.controller.reset()
            rig = self.hw
            if rig is not None and rig.servo is not None:
                if on:
                    az, el = rig.servo.pose_at_deg(self.clock.now())
                    rig.servo.glide_to(az, el)                 # stop smoothly where it is
                else:
                    rig.servo.command_rate(self.clock.now(), 0.0, 0.0)
                    rig.holding = False
            self.ui_revision += 1
        self._post(do)

    def manual_servo(self, pan: Optional[float] = None, tilt: Optional[float] = None) -> None:
        """Glide to absolute servo angles (degrees, as on the Arduino: pan 90 ahead, tilt 130 level)."""
        def do():
            rig = self.hw
            if rig is None or rig.servo is None or not rig.ready:
                return
            cur = rig.servo.glide_target() or rig.servo.pose_at_deg(self.clock.now())
            p0, t0 = rig.geometry.servo(*cur)
            self.hw_manual = True
            rig.servo.glide_to(*rig.geometry.pose(p0 if pan is None else pan, t0 if tilt is None else tilt),
                               self.HW_MAX_RATE_DEG)
        self._post(do)

    def manual_step(self, right_deg: float = 0.0, up_deg: float = 0.0) -> None:
        """Turn the camera right / up by the given degrees (negative: left / down)."""
        def do():
            rig = self.hw
            if rig is None or rig.servo is None or not rig.ready:
                return
            az, el = rig.servo.glide_target() or rig.servo.pose_at_deg(self.clock.now())
            self.hw_manual = True
            rig.servo.glide_to(az + right_deg, el + up_deg, self.HW_MAX_RATE_DEG)
        self._post(do)

    def manual_home(self) -> None:
        g = self.hw.geometry if self.hw is not None else None
        if g is not None:
            self.manual_servo(g.pan_center, g.tilt_level)

    def set_head_speed(self, deg_s: float) -> None:
        """Top speed of the head, degrees/s — tracking, search and manual moves alike."""
        deg_s = max(5.0, min(90.0, deg_s))
        self.HW_MAX_RATE_DEG = deg_s
        rig = self.hw
        if rig is not None and rig.ready:
            self.controller.max_rate = math.radians(deg_s * rig.scale())

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
        rig = self.hw
        if rig is not None and (not rig.ready or self.hw_manual):
            if rig.servo is not None:               # homing / calibration / manual drive the head directly
                rig.servo.advance(t)
            return
        last = self._last_control_t
        dt = (t - last) if last is not None else 1.0 / self.CONTROL_HZ
        if dt <= 0 or dt > 0.2:
            dt = 1.0 / self.CONTROL_HZ
        self._last_control_t = t
        self.gimbal.advance(t)
        st = self.gimbal.read_state(t)
        az, el, vaz, vel, tracking = self.pipeline.pointing_reference(t, dt, st.az, st.el)
        if rig is not None:
            p = self.pipeline
            if p.state in (TrackState.SEARCH, TrackState.ACQUIRING) and not p.reacquiring:
                saz, sel = rig.scan_target(t, acquiring=p.state == TrackState.ACQUIRING)
                az, el = saz * rig.gimbal.kx * math.pi / 180.0, sel * rig.gimbal.ky * math.pi / 180.0
                vaz = vel = 0.0
                tracking = False
            else:
                rig.restart_scan()
        if rig is not None and rig.holding:
            self.controller.reset()                 # beacon centred: keep the head still (servo deadband)
            caz = cel = 0.0
        else:
            caz, cel = self.controller.compute(dt, st.az, st.el, az, el, vaz, vel, tracking)
        self.gimbal.command_rate(t, caz, cel)

    def _vision_tick(self, t: float) -> None:
        if self.hw is not None:
            self._vision_tick_hardware(t)
            return
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
        if frame.frame_id <= 1 and self._ego is not None:
            self._ego.reset()                 # new clip or loop: the camera pose starts afresh
        if self._ego is not None:
            # no encoders on a recording: the camera's own pan/shake, measured from the image,
            # stands in for them so the tracker keeps working in stable scene angles
            frame.gimbal_az, frame.gimbal_el = self._ego.update(frame.image)
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

    def _vision_tick_hardware(self, t: float) -> None:
        rig = self.hw
        if rig.stage in (RigStage.CONNECTING, RigStage.ERROR):
            return
        c0 = time.perf_counter()
        got = rig.frame(t)
        if got is None:
            return
        frame, age = got
        if not rig.ready:
            rig.step(t, frame.image, age)
            h, w = frame.image.shape[:2]
            if self.K.width != w or self.K.height != h:
                f = HardwareRig.WORK_PX_PER_DEG * 180.0 / math.pi
                self.K = CameraIntrinsics(w, h, f, f, w / 2.0, h / 2.0)
            if rig.ready:
                self._enter_hardware_tracking(rig)
            out = PipelineOutput(t=frame.t, frame_id=frame.frame_id, state=TrackState.SEARCH, state_age=0.0)
            stage = ((time.perf_counter() - c0) * 1000.0, 0.0, 0.0)
            self._publish(frame.t, frame.image, out, self._no_truth(frame), stage)
            return
        out = self.pipeline.process_frame(frame)
        if rig.observe(frame.t, out.measurement):       # a servo turned out reversed: restart the track
            self.pipeline.reset()
            self.controller.reset()
        rate = 0.0
        if out.track_los is not None:
            k = rig.scale()
            rate = math.degrees(math.hypot(out.track_los[2], out.track_los[3])) / k
        rig.update_hold(frame.t, out.state, out.measurement, rate)
        render_ms = (time.perf_counter() - c0) * 1000.0 - out.detect_ms - out.track_ms
        truth = self._no_truth(frame)
        stage = (max(0.0, render_ms), out.detect_ms, out.track_ms)
        self.evaluator.on_frame(out, truth, stage[0], out.detect_ms, out.track_ms, has_truth=False)
        self.recorder.add(out, truth, self.evaluator, stage)
        self._publish(frame.t, frame.image, out, truth, stage)

    @staticmethod
    def _no_truth(frame) -> Truth:
        return Truth(t=frame.t, target_px=None, in_fov=False, occluded=False, occlusion_kind="",
                     target_los=(0.0, 0.0), range_m=0.0, cam_az=frame.gimbal_az, cam_el=frame.gimbal_el,
                     beacon_peak_dn=0.0, beacon_on=True)

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
            hardware=self.hardware_status(),
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
