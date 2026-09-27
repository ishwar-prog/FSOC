"""Hobby-servo pan/tilt head (two SG90s behind an Arduino) as a GimbalInterface.

Hobby servos have no encoder output, so the head's pose is *modelled*: every command sent is
followed through a first-order, speed-limited servo response, and that trajectory is kept in a
short history. A camera frame is then paired with the pose the head actually had when that
frame was exposed (`read_state(t)` for a past t), which is what keeps the line-of-sight
measurement right while the head is moving — the difference between smooth tracking and a
head that overshoots and hunts.

Two further details matter on SG90-class servos:
  * resolution — angles go out in hundredths of a degree and the firmware drives
    `writeMicroseconds`, so a command is not rounded to whole degrees (~1 px at 720p);
  * buzz — a servo fed a setpoint that dithers by a few hundredths of a degree chatters
    against its own deadband. Small changes are therefore held back until they add up
    (`HOLD_DEG`), unless the head is deliberately moving.
"""

import math
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass
from typing import Optional, Tuple

from .gimbal import GimbalInterface, GimbalState

DEG = math.pi / 180.0


@dataclass
class ServoGeometry:
    """How servo angles map to pointing. Defaults: the SIH rig (SG90s on D9 pan / D10 tilt).

    az/el are in degrees, az positive to the right, el positive up, (0, 0) = straight ahead,
    level. `pan_dir` / `tilt_dir` say which way a growing servo angle turns the camera; the
    rig measures both at start-up, the defaults only matter if the scene is too bare to see.
    """
    pan_center: float = 90.0      # servo angle looking straight ahead
    pan_dir: int = 1              # +1: larger pan angle turns the camera right
    pan_min: float = 5.0
    pan_max: float = 175.0
    tilt_level: float = 130.0     # servo angle with the camera level (face perpendicular to the ground)
    tilt_dir: int = -1            # -1: larger tilt angle turns the camera down
    tilt_min: float = 55.0        # keep clear of the zenith, where pan loses all authority
    tilt_max: float = 175.0

    def pose(self, pan: float, tilt: float) -> Tuple[float, float]:
        return self.pan_dir * (pan - self.pan_center), self.tilt_dir * (tilt - self.tilt_level)

    def servo(self, az: float, el: float) -> Tuple[float, float]:
        pan = self.pan_center + self.pan_dir * az
        tilt = self.tilt_level + self.tilt_dir * el
        return (max(self.pan_min, min(self.pan_max, pan)), max(self.tilt_min, min(self.tilt_max, tilt)))

    def limits(self) -> Tuple[Tuple[float, float], Tuple[float, float]]:
        """((az_min, az_max), (el_min, el_max)) in degrees."""
        a = sorted(self.pose(p, self.tilt_level)[0] for p in (self.pan_min, self.pan_max))
        e = sorted(self.pose(self.pan_center, q)[1] for q in (self.tilt_min, self.tilt_max))
        return (a[0], a[1]), (e[0], e[1])

    def to_dict(self) -> dict:
        return asdict(self)


class SerialLink:
    """Line protocol to `firmware/fsoc_pantilt`. Opening the port resets an Uno/Nano, so the
    link waits for the firmware's banner before it is considered up."""

    BANNER = "FSOC-PT"

    def __init__(self, port: str, baud: int = 115200, boot_timeout_s: float = 4.0) -> None:
        try:
            import serial                                  # pyserial
        except ImportError as ex:                          # pragma: no cover - install issue
            raise IOError("pyserial is not installed (pip install pyserial)") from ex
        self.port = port
        self._ser = serial.Serial(port, baud, timeout=0.05, write_timeout=0.1)
        self._lock = threading.Lock()
        deadline = time.perf_counter() + boot_timeout_s
        buf = b""
        while time.perf_counter() < deadline:
            buf += self._ser.read(64)
            if self.BANNER.encode() in buf:
                return
        self._ser.close()
        raise IOError(f"No pan/tilt firmware answered on {port} — is fsoc_pantilt.ino uploaded?")

    def send(self, pan: float, tilt: float) -> None:
        msg = f"A {int(round(pan * 100))} {int(round(tilt * 100))}\n".encode()
        with self._lock:
            try:
                self._ser.write(msg)
            except Exception:                              # a dropped USB link must not kill the loop
                pass

    def close(self) -> None:
        with self._lock:
            try:
                self._ser.close()
            except Exception:
                pass


class ServoPanTiltGimbal(GimbalInterface):
    """Rate-commanded interface over a position-servo head, with a modelled pose.

    Angles in the GimbalInterface are radians (az right, el up). `link=None` runs the model
    without hardware (dry run).
    """

    SERVO_TAU_S = 0.05          # SG90 under a webcam: first-order time constant...
    SERVO_SPEED_DEG = 300.0     # ...and top speed
    SEND_PERIOD_S = 0.02        # servos refresh at 50 Hz; sending faster buys nothing
    HOLD_DEG = 0.35             # a still head is not nudged by less than this (~ the servo deadband)
    MOVING_DEG_S = 1.0          # above this commanded rate the head is "moving": no hold-back
    HISTORY_S = 1.5

    def __init__(self, link: Optional[SerialLink], geometry: ServoGeometry = None,
                 max_rate_deg: float = 60.0, max_accel_deg: float = 300.0) -> None:
        self.link = link
        self.geo = geometry or ServoGeometry()
        self.max_rate_deg = max_rate_deg
        self.max_accel_deg = max_accel_deg
        self._lock = threading.Lock()
        self._t: Optional[float] = None
        self._rate = (0.0, 0.0)                          # commanded, deg/s (az, el)
        self._sp = (0.0, 0.0)                            # setpoint, deg (az, el)
        self._sent = (0.0, 0.0)                          # what the servos were last told
        self._pose = (0.0, 0.0)                          # modelled physical pose
        self._vel = (0.0, 0.0)
        self._last_send_t = -1e9
        self._glide = None
        self._hist: deque = deque()
        self._send(self._sp)

    # ------------------------------------------------------------ commands
    GLIDE_SPEED_DEG = 40.0      # manual / homing moves: top speed...
    GLIDE_ACCEL_DEG = 120.0     # ...and acceleration (a trapezoidal profile — no jerks)

    def command_rate(self, t: float, az_rate: float, el_rate: float) -> None:
        with self._lock:
            self._glide = None
            self._rate = (az_rate / DEG, el_rate / DEG)

    def glide_to(self, az_deg: float, el_deg: float, speed_deg: Optional[float] = None) -> None:
        """Move smoothly to a pose: accelerate, cruise, brake to a stop on it."""
        with self._lock:
            self._glide = (self._clamp(az_deg, el_deg), speed_deg or self.GLIDE_SPEED_DEG)

    def glide_target(self) -> Optional[Tuple[float, float]]:
        with self._lock:
            return self._glide[0] if self._glide else None

    def _glide_step(self, dt: float) -> None:
        (ta, te), vmax = self._glide
        out = []
        for i, tgt in enumerate((ta, te)):
            e = tgt - self._sp[i]
            want = math.copysign(min(vmax, math.sqrt(2.0 * self.GLIDE_ACCEL_DEG * abs(e))), e)
            step = self.GLIDE_ACCEL_DEG * dt
            out.append(self._rate[i] + max(-step, min(step, want - self._rate[i])))
        self._rate = (out[0], out[1])
        if math.hypot(ta - self._sp[0], te - self._sp[1]) < 0.02 and math.hypot(*self._rate) < 1.0:
            self._sp, self._rate = (ta, te), (0.0, 0.0)

    def goto(self, az_deg: float, el_deg: float) -> None:
        """Step to a pose at once (calibration steps). For smooth moves use glide_to."""
        with self._lock:
            self._glide = None
            self._rate = (0.0, 0.0)
            self._sp = self._clamp(az_deg, el_deg)
            self._send(self._sp)

    def reset(self, az: float = 0.0, el: float = 0.0) -> None:
        self.goto(az / DEG, el / DEG)

    # ------------------------------------------------------------ model
    def advance(self, t: float) -> None:
        with self._lock:
            if self._t is None:
                self._t = t
                self._hist.append((t, self._pose[0], self._pose[1]))
                return
            dt = t - self._t
            if dt <= 0:
                return
            self._t = t
            dt = min(dt, 0.1)
            if self._glide is not None:
                self._glide_step(dt)
            sp = self._clamp(self._sp[0] + self._rate[0] * dt, self._sp[1] + self._rate[1] * dt)
            self._sp = sp
            moving = math.hypot(*self._rate) > self.MOVING_DEG_S
            if t - self._last_send_t >= self.SEND_PERIOD_S:
                d = math.hypot(sp[0] - self._sent[0], sp[1] - self._sent[1])
                if d >= (0.01 if moving else self.HOLD_DEG):
                    self._send(sp)
                    self._last_send_t = t

            # physical response to what was actually sent
            a = 1.0 - math.exp(-dt / self.SERVO_TAU_S)
            cap = self.SERVO_SPEED_DEG * dt
            nx = []
            for p, s in zip(self._pose, self._sent):
                step = max(-cap, min(cap, (s - p) * a))
                nx.append(p + step)
            self._vel = ((nx[0] - self._pose[0]) / dt, (nx[1] - self._pose[1]) / dt)
            self._pose = (nx[0], nx[1])
            self._hist.append((t, nx[0], nx[1]))
            while self._hist and t - self._hist[0][0] > self.HISTORY_S:
                self._hist.popleft()

    def _clamp(self, az: float, el: float) -> Tuple[float, float]:
        (a0, a1), (e0, e1) = self.geo.limits()
        return max(a0, min(a1, az)), max(e0, min(e1, el))

    def _send(self, sp) -> None:
        self._sent = sp
        if self.link is not None:
            self.link.send(*self.geo.servo(*sp))

    def _pose_at(self, t: float) -> Tuple[float, float]:
        h = self._hist
        if not h or t >= h[-1][0]:
            return self._pose
        if t <= h[0][0]:
            return h[0][1], h[0][2]
        lo, hi = 0, len(h) - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if h[mid][0] <= t:
                lo = mid
            else:
                hi = mid
        t0, a0, e0 = h[lo]
        t1, a1, e1 = h[hi]
        w = (t - t0) / max(1e-9, t1 - t0)
        return a0 + (a1 - a0) * w, e0 + (e1 - e0) * w

    # ------------------------------------------------------------ readout
    def read_state(self, t: float) -> GimbalState:
        """Modelled pose at time t — also a past t, to match a camera frame's exposure."""
        with self._lock:
            az, el = self._pose_at(t)
            return GimbalState(t, az * DEG, el * DEG, self._vel[0] * DEG, self._vel[1] * DEG)

    def true_pose(self, t: float):
        with self._lock:
            return self._pose[0] * DEG, self._pose[1] * DEG, self._vel[0] * DEG, self._vel[1] * DEG

    def servo_angles(self) -> Tuple[float, float]:
        """(pan, tilt) servo degrees currently being commanded."""
        with self._lock:
            return self.geo.servo(*self._sent)

    def pose_at_deg(self, t: float) -> Tuple[float, float]:
        """Modelled (az, el) in degrees at time t."""
        with self._lock:
            return self._pose_at(t)

    def flip(self, axis: str) -> None:
        """The servo on `axis` turns the camera the opposite way to what was assumed. Mirror the
        model in place: the head stays physically where it is, only the bookkeeping changes."""
        i = 0 if axis == "pan" else 1
        with self._lock:
            if i == 0:
                self.geo.pan_dir = -self.geo.pan_dir
            else:
                self.geo.tilt_dir = -self.geo.tilt_dir

            def m(p):
                q = list(p)
                q[i] = -q[i]
                return tuple(q)
            self._sp, self._sent, self._pose, self._vel = m(self._sp), m(self._sent), m(self._pose), m(self._vel)
            self._rate = (0.0, 0.0)
            self._hist = deque((h[0], -h[1], h[2]) if i == 0 else (h[0], h[1], -h[2]) for h in self._hist)

    def settled(self, tol_deg: float = 0.15) -> bool:
        with self._lock:
            return math.hypot(self._pose[0] - self._sent[0], self._pose[1] - self._sent[1]) < tol_deg

    def close(self) -> None:
        if self.link is not None:
            self.link.close()
            self.link = None


class ScaledGimbal(GimbalInterface):
    """Presents a real head in the tracker's working angle scale.

    The tracking core's gates and noise models were tuned at a fixed angular scale
    (px per degree). A wide webcam has ~15x fewer px per degree, so instead of re-tuning every
    gate, the real head is shown to the tracker with its angles multiplied by
    k = real px/deg ÷ working px/deg: one pixel means the same thing everywhere.
    """

    def __init__(self, inner: ServoPanTiltGimbal, kx: float, ky: float) -> None:
        self.inner, self.kx, self.ky = inner, kx, ky
        self.max_rate_deg = inner.max_rate_deg * kx
        self.max_accel_deg = inner.max_accel_deg * kx

    def advance(self, t: float) -> None:
        self.inner.advance(t)

    def read_state(self, t: float) -> GimbalState:
        s = self.inner.read_state(t)
        return GimbalState(s.t, s.az * self.kx, s.el * self.ky, s.az_rate * self.kx, s.el_rate * self.ky)

    def command_rate(self, t: float, az_rate: float, el_rate: float) -> None:
        self.inner.command_rate(t, az_rate / self.kx, el_rate / self.ky)

    def reset(self, az: float = 0.0, el: float = 0.0) -> None:
        self.inner.reset(az / self.kx, el / self.ky)

    def true_pose(self, t: float):
        az, el, vaz, vel = self.inner.true_pose(t)
        return az * self.kx, el * self.ky, vaz * self.kx, vel * self.ky
