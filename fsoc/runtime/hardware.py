"""Hardware session: a USB webcam on a two-servo pan/tilt head.

Stages before the tracker takes over (its own loop is SEARCH -> ACQUIRING -> LOCKED ->
COASTING (path prediction) -> REACQUIRE -> SEARCH):

  CONNECTING   open the camera and the serial link (off the tracking thread — an Uno/Nano
               reboots when its port is opened and needs ~2 s)
  HOMING       drive to straight-ahead / level and let the camera's auto-exposure settle
  CALIBRATING  nudge pan, then tilt, and watch the whole image move (phase correlation).
               This *measures* what would otherwise be guessed and would break the loop if
               wrong: which way each servo turns the camera, how many pixels one servo
               degree moves the image (optics x servo gain), and the camera's delay.
  TRACKING     the tracker owns the head
  ERROR        connection failed

A good calibration is saved to hardware.json and reused when a later start-up faces a scene
too bare to measure (a dark room with only the beacon in it).
"""

import json
import math
import os
import sys
import threading
from dataclasses import asdict, dataclass
from typing import List, Optional, Tuple

import cv2
import numpy as np

from ..core.geometry import CameraIntrinsics
from ..io.frame import Frame
from ..io.servo import ScaledGimbal, SerialLink, ServoGeometry, ServoPanTiltGimbal
from ..io.sources import LiveCameraSource

DEG = math.pi / 180.0


class RigStage:
    CONNECTING = "CONNECTING"
    HOMING = "HOMING"
    CALIBRATING = "CALIBRATING"
    TRACKING = "TRACKING"
    ERROR = "ERROR"


@dataclass
class Calibration:
    pan_dir: int = 1
    tilt_dir: int = -1
    ppd_x: float = 0.0          # processed-image pixels per servo degree (0 = unknown)
    ppd_y: float = 0.0
    latency_s: float = 0.10     # exposure -> frame available
    measured: bool = False


def default_config_path() -> str:
    base = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.getcwd()
    return os.path.join(base, "hardware.json")


class HardwareRig:
    WORK_PX_PER_DEG = 160.0     # the tracker's working angular scale (as in video mode)
    CAL_STEP_DEG = 8.0
    HOME_SETTLE_S = 1.5
    MOVE_SETTLE_S = 0.9
    MIN_RESPONSE = 0.06
    SERVO_HALF_MOVE_S = 0.035   # time for the modelled servo to cover half a calibration step

    def __init__(self, camera_index: int = 0, port: Optional[str] = None, hfov_deg: float = 60.0,
                 config_path: Optional[str] = None, camera=None, link=None,
                 geometry: Optional[ServoGeometry] = None) -> None:
        self.camera_index, self.port, self.hfov_deg = camera_index, port, hfov_deg
        self.config_path = config_path or default_config_path()
        self.camera = camera
        self.link = link
        self.geometry = geometry or ServoGeometry()
        self.cal = Calibration(self.geometry.pan_dir, self.geometry.tilt_dir)
        self._saved = self._load()
        self.servo: Optional[ServoPanTiltGimbal] = None
        self.gimbal: Optional[ScaledGimbal] = None
        self.K: Optional[CameraIntrinsics] = None
        self.stage = RigStage.CONNECTING
        self.detail = "Opening camera and pan/tilt head…"
        self._phase = None
        self._t0 = 0.0
        self._ref = None
        self._samples: List[Tuple[float, float, float, float]] = []
        self._results = {}
        self._win = None
        self._thread: Optional[threading.Thread] = None
        self._dir_ev = {"pan": [0.0, 0.0], "tilt": [0.0, 0.0]}
        self._prev_obs = None
        self.holding = False
        self._hold_seen = -1e9
        self._scan = None
        self._scan_i = 0
        self._scan_t = None

    # ------------------------------------------------------------ connect
    def start(self) -> None:
        if self.camera is not None:
            self._connected()
            return
        self._thread = threading.Thread(target=self._connect, name="hw-connect", daemon=True)
        self._thread.start()

    def _connect(self) -> None:
        try:
            self.camera = LiveCameraSource(self.camera_index, hfov_deg=self.hfov_deg)
            if self.port:
                self.link = SerialLink(self.port)
            self._connected()
        except Exception as ex:
            self.close()
            self.stage, self.detail = RigStage.ERROR, str(ex)

    def _connected(self) -> None:
        if self._saved is not None and self._saved.measured:
            self.geometry.pan_dir, self.geometry.tilt_dir = self._saved.pan_dir, self._saved.tilt_dir
        self.servo = ServoPanTiltGimbal(self.link, self.geometry)
        self.stage = RigStage.HOMING
        self.detail = "Homing: straight ahead, level" + ("" if self.link else " (no head connected — camera only)")
        self._phase = None

    @property
    def ready(self) -> bool:
        return self.stage == RigStage.TRACKING

    @property
    def frame_size(self) -> Tuple[int, int]:
        return self.camera.size

    # ------------------------------------------------------------ frames
    def frame(self, now: float) -> Optional[Tuple[Frame, float]]:
        """Newest camera frame as a tracker Frame (engine time base), plus its age at arrival."""
        got = self.camera.latest(now)
        if got is None:
            return None
        img, age, n = got
        t = now - age - self.cal.latency_s               # when it was exposed
        g = self.gimbal.read_state(t) if self.gimbal is not None else self.servo.read_state(t)
        return Frame(img, t, n, g.az, g.el), age

    # ------------------------------------------------------------ homing + calibration
    def step(self, now: float, img: np.ndarray, age: float) -> None:
        """Advance homing / calibration by one camera frame."""
        if self.stage not in (RigStage.HOMING, RigStage.CALIBRATING):
            return
        s = self.CAL_STEP_DEG
        arrival = now - age
        if self._phase is None:
            self.servo.goto(0.0, 0.0)
            self._phase, self._t0 = "home", now
            return
        if self._phase in ("home", "pan_back", "tilt_back"):
            if now - self._t0 < (self.HOME_SETTLE_S if self._phase == "home" else self.MOVE_SETTLE_S) \
                    or not self.servo.settled():
                return
            self._ref = self._prep(img)
            if self._phase == "tilt_back":
                self._finish()
                return
            axis = "pan" if self._phase == "home" else "tilt"
            self.stage = RigStage.CALIBRATING
            self.detail = f"Calibrating {axis}: measuring direction, scale and camera delay"
            self.servo.goto(s, 0.0) if axis == "pan" else self.servo.goto(0.0, s)
            self._phase, self._t0, self._samples = axis, now, []
            return
        # measuring a step
        dx, dy, resp = self._correlate(self._ref, self._prep(img))
        self._samples.append((arrival - self._t0, dx, dy, resp))
        if now - self._t0 < self.MOVE_SETTLE_S:
            return
        self._results[self._phase] = self._evaluate(self._phase, self._samples)
        self.servo.goto(0.0, 0.0)
        self._phase, self._t0 = self._phase + "_back", now

    @staticmethod
    def _prep(img: np.ndarray) -> np.ndarray:
        """Scene texture only. Lights are removed first: a point source that is on in one frame
        and off in the next (the beacon itself, blinking) has a flat spectrum and would dominate
        the phase correlation."""
        h, w = img.shape[:2]
        small = cv2.resize(img, (w // 2, h // 2), interpolation=cv2.INTER_AREA)
        small = cv2.medianBlur(small, 5)
        small = np.minimum(small, np.percentile(small, 97)).astype(np.float32)
        return cv2.GaussianBlur(small, (0, 0), 1.0)

    def _correlate(self, a: np.ndarray, b: np.ndarray):
        if self._win is None or self._win.shape != a.shape:
            self._win = cv2.createHanningWindow(a.shape[::-1], cv2.CV_32F)
        (dx, dy), resp = cv2.phaseCorrelate(a, b, self._win)
        return 2.0 * dx, 2.0 * dy, resp

    def _evaluate(self, axis: str, samples) -> Optional[dict]:
        settled = [x for x in samples if x[0] > 0.5 * self.MOVE_SETTLE_S and x[3] >= self.MIN_RESPONSE]
        if len(settled) < 3:
            return None
        dx = float(np.median([x[1] for x in settled]))
        dy = float(np.median([x[2] for x in settled]))
        main, cross = (dx, dy) if axis == "pan" else (dy, dx)
        ppd = abs(main) / self.CAL_STEP_DEG
        agree = [x for x in settled if abs((x[1] if axis == "pan" else x[2]) - main) < 0.1 * abs(main) + 1.0]
        if not (3.0 <= ppd <= 80.0) or abs(cross) > 0.5 * abs(main) or len(agree) < 0.6 * len(settled):
            return None
        # delay: first frame (by arrival) that shows at least half the final shift
        lat = None
        for dt_arr, x, y, r in samples:
            m = x if axis == "pan" else y
            if r >= self.MIN_RESPONSE and abs(m) >= 0.5 * abs(main) and m * main > 0:
                lat = dt_arr - self.SERVO_HALF_MOVE_S
                break
        return dict(main=main, ppd=ppd, latency=lat)

    def _finish(self) -> None:
        pan, tilt = self._results.get("pan"), self._results.get("tilt")
        cal = self.cal
        if pan and tilt:
            # a commanded turn right makes the scene slide left (dx < 0); a turn up slides it down
            cal.pan_dir = self.geometry.pan_dir * (1 if pan["main"] < 0 else -1)
            cal.tilt_dir = self.geometry.tilt_dir * (1 if tilt["main"] > 0 else -1)
            cal.ppd_x, cal.ppd_y = pan["ppd"], tilt["ppd"]
            lats = [r["latency"] for r in (pan, tilt) if r["latency"] is not None]
            cal.latency_s = min(0.30, max(0.03, float(np.mean(lats)))) if lats else 0.10
            cal.measured = True
            self._save()
            note = (f"Calibrated: {cal.ppd_x:.1f} / {cal.ppd_y:.1f} px per degree, "
                    f"camera delay {cal.latency_s * 1000:.0f} ms")
        elif self._saved is not None and self._saved.measured:
            self.cal = cal = Calibration(**asdict(self._saved))
            note = "Scene too bare to calibrate — using the last saved calibration"
        else:
            w = self.camera.size[0]
            fx = (w / 2.0) / math.tan(math.radians(self.hfov_deg) / 2.0)
            cal.ppd_x = cal.ppd_y = fx * DEG
            cal.pan_dir, cal.tilt_dir = self.geometry.pan_dir, self.geometry.tilt_dir
            note = (f"Scene too bare to calibrate — assuming a {self.hfov_deg:.0f}° lens and the "
                    "default servo directions")
        self.geometry.pan_dir, self.geometry.tilt_dir = cal.pan_dir, cal.tilt_dir
        self._enter_tracking()
        self.detail = note

    def _enter_tracking(self) -> None:
        if hasattr(self.camera, "lock_exposure"):
            self.camera.lock_exposure()
        w, h = self.camera.size
        f = self.WORK_PX_PER_DEG / DEG
        self.K = CameraIntrinsics(w, h, f, f, w / 2.0, h / 2.0)
        self.gimbal = ScaledGimbal(self.servo, self.cal.ppd_x / self.WORK_PX_PER_DEG,
                                   self.cal.ppd_y / self.WORK_PX_PER_DEG)
        self.stage = RigStage.TRACKING

    # ------------------------------------------------------------ step-stare search
    STARE_S = 1.4               # still time per pose: several blinks of a >= 2 Hz beacon
    SCAN_OVERLAP = 0.85         # pose spacing as a fraction of the field of view

    def scan_target(self, t: float, acquiring: bool) -> Tuple[float, float]:
        """Where to point (az, el in degrees) during a fresh search.

        A moving camera makes static room features flicker in and out of detection, which looks
        exactly like blinking to the identifier. So the head moves from pose to pose and stares:
        blink evidence is only gathered while still. While a candidate is being confirmed
        (`acquiring`) it keeps staring — the wide lens already has it in view."""
        az, el = self.servo.pose_at_deg(t)
        if self._scan is None:
            self._scan = self._scan_poses(az, el)
            self._scan_i, self._scan_t = 0, None
        target = self._scan[self._scan_i]
        if acquiring:
            self._scan_t = None if self._scan_t is None else t    # restart the stare clock
            return target
        if math.hypot(target[0] - az, target[1] - el) < 0.5 and self.servo.settled():
            if self._scan_t is None:
                self._scan_t = t
            elif t - self._scan_t >= self.STARE_S:
                self._scan_i = (self._scan_i + 1) % len(self._scan)
                self._scan_t = None
        return self._scan[self._scan_i]

    def restart_scan(self) -> None:
        """Next search starts where the head is now (the last place the beacon was seen)."""
        self._scan = None

    def _scan_poses(self, az0: float, el0: float):
        (a0, a1), (e0, e1) = self.geometry.limits()
        w, h = self.camera.size
        fov_x = w / max(self.cal.ppd_x, 1e-6)
        fov_y = h / max(self.cal.ppd_y, 1e-6)
        sx, sy = self.SCAN_OVERLAP * fov_x, self.SCAN_OVERLAP * fov_y

        def axis(lo, hi, c, step):
            vals = [c]
            k = 1
            while c - k * step > lo - 0.5 * step or c + k * step < hi + 0.5 * step:
                for v in (c + k * step, c - k * step):
                    if lo - 0.5 * step < v < hi + 0.5 * step:
                        vals.append(max(lo, min(hi, v)))
                k += 1
            return vals
        poses = [(a, e) for e in axis(e0, e1, max(e0, min(e1, el0)), sy)
                 for a in axis(a0, a1, max(a0, min(a1, az0)), sx)]
        poses.sort(key=lambda p: math.hypot(p[0] - az0, 1.3 * (p[1] - el0)))
        return poses

    # ------------------------------------------------------------ centre hold
    HOLD_ENTER_DEG = 0.3        # beacon this close to the image centre: stop correcting...
    HOLD_EXIT_DEG = 0.7         # ...until it is this far off again
    HOLD_STILL_DEG_S = 3.0      # target slower than this counts as still
    HOLD_STALE_S = 0.5          # no sighting for this long: let prediction drive again

    def update_hold(self, t: float, state: str, meas_px, target_rate_deg: float) -> None:
        """Hold the head still while the beacon sits at the image centre.

        A hobby servo ignores changes smaller than its deadband (~0.3-1 deg on an SG90) and then
        jumps. A controller that keeps correcting smaller errors limit-cycles against it — the
        head hunts back and forth. So the head stops once the beacon is centred in the *actual
        image* (not in the modelled angles, which a deadband makes slightly wrong) and moves again
        only when the beacon drifts clearly off-centre or starts moving. Hysteresis keeps it from
        chattering at the boundary."""
        if state != "LOCKED":
            self.holding = False
            return
        if meas_px is None:
            if t - self._hold_seen > self.HOLD_STALE_S:
                self.holding = False
            return
        self._hold_seen = t
        w, h = self.camera.size
        ex = (meas_px[0] - w / 2.0) / max(self.cal.ppd_x, 1e-6)
        ey = (meas_px[1] - h / 2.0) / max(self.cal.ppd_y, 1e-6)
        err = math.hypot(ex, ey)
        still = target_rate_deg < self.HOLD_STILL_DEG_S
        if self.holding:
            self.holding = still and err < self.HOLD_EXIT_DEG
        else:
            self.holding = still and err < self.HOLD_ENTER_DEG

    # ------------------------------------------------------------ direction watchdog
    WATCH_EVIDENCE_DEG2 = 2.0    # sum of squared head steps needed before judging an axis

    def observe(self, t: float, meas_px: Optional[Tuple[float, float]]) -> Optional[str]:
        """Safety net for a servo turning the wrong way (calibration impossible and the default
        guessed wrong). When the head turns, a still light must slide the *other* way across the
        image, at ~ppd pixels per degree. If, over several degrees of travel, it slides the same
        way, the axis is reversed: it is flipped in place and its name returned, so the caller can
        restart the track. Returns None otherwise."""
        if meas_px is None or self.servo is None:
            self._prev_obs = None
            return None
        az, el = self.servo.pose_at_deg(t)
        prev, self._prev_obs = self._prev_obs, (t, az, el, meas_px)
        if prev is None or t - prev[0] > 0.2:
            return None
        daz, del_ = az - prev[1], el - prev[2]
        du, dv = meas_px[0] - prev[3][0], meas_px[1] - prev[3][1]
        flipped = None
        # image u shrinks when turning right (+az); v grows when turning up (+el)
        for axis, dq, dp, sign, ppd in (("pan", daz, du, -1.0, self.cal.ppd_x), ("tilt", del_, dv, 1.0, self.cal.ppd_y)):
            if abs(dq) < 0.05 or abs(dp) > 4.0 * ppd * abs(dq) + 20.0:
                continue                                  # no motion, or a different light
            ev = self._dir_ev[axis]
            ev[0] += sign * dp * dq / max(ppd, 1e-6)       # ~ +dq^2 if right, -dq^2 if reversed
            ev[1] += dq * dq
            if ev[1] >= self.WATCH_EVIDENCE_DEG2 and ev[0] < -0.4 * ev[1]:
                self._flip(axis)
                flipped = axis
            elif ev[1] > 60.0:                            # plenty of good evidence: stop worrying
                ev[0] *= 0.5
                ev[1] *= 0.5
        if flipped:
            self._prev_obs = None
        return flipped

    def _flip(self, axis: str) -> None:
        self.servo.flip(axis)
        if axis == "pan":
            self.geometry.pan_dir = self.cal.pan_dir = -self.cal.pan_dir
        else:
            self.geometry.tilt_dir = self.cal.tilt_dir = -self.cal.tilt_dir
        self._dir_ev[axis] = [0.0, 0.0]
        self.detail = f"{axis.capitalize()} servo turns the other way — corrected on the fly"
        if self.cal.measured:
            self._save()

    # ------------------------------------------------------------ tracker settings
    def work_limits(self) -> Tuple[Tuple[float, float], Tuple[float, float]]:
        """Mechanical travel in the tracker's working angles (rad)."""
        (a0, a1), (e0, e1) = self.geometry.limits()
        kx, ky = self.gimbal.kx, self.gimbal.ky
        return (a0 * kx * DEG, a1 * kx * DEG), (e0 * ky * DEG, e1 * ky * DEG)

    def scale(self) -> float:
        return self.gimbal.kx

    # ------------------------------------------------------------ persistence
    def _load(self) -> Optional[Calibration]:
        try:
            with open(self.config_path, encoding="utf-8") as f:
                return Calibration(**json.load(f)["calibration"])
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def _save(self) -> None:
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump({"calibration": asdict(self.cal), "geometry": self.geometry.to_dict(),
                           "camera_index": self.camera_index, "port": self.port}, f, indent=2)
        except OSError:
            pass

    def status(self) -> dict:
        pan, tilt = self.servo.servo_angles() if self.servo is not None else (None, None)
        return dict(stage=self.stage, detail=self.detail, pan=pan, tilt=tilt,
                    head=self.link is not None, calibrated=self.cal.measured)

    def close(self) -> None:
        if self.camera is not None:
            try:
                self.camera.close()
            except Exception:
                pass
        if self.servo is not None:
            self.servo.close()
        elif self.link is not None:
            self.link.close()
