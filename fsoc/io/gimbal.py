"""Gimbal abstraction.

The control loop only needs two calls:
    state = gimbal.read_state(t)          # encoder angles + rates
    gimbal.command_rate(t, az_rate, el_rate)
Implement those for any pan/tilt unit and the whole tracker works on it.
"""

import math
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class GimbalState:
    t: float
    az: float
    el: float
    az_rate: float
    el_rate: float


class GimbalInterface(ABC):
    max_rate_deg: float = 40.0
    max_accel_deg: float = 220.0

    @abstractmethod
    def read_state(self, t: float) -> GimbalState: ...

    @abstractmethod
    def command_rate(self, t: float, az_rate: float, el_rate: float) -> None: ...

    def reset(self, az: float = 0.0, el: float = 0.0) -> None:
        pass


class SimulatedGimbal(GimbalInterface):
    """Two-axis servo: first-order rate loop, rate/accel limits, elevation stops,
    encoder quantisation. Integrated on the control thread, read by the vision thread."""

    def __init__(self, tau_s: float = 0.025, max_rate_deg: float = 45.0,
                 max_accel_deg: float = 260.0, encoder_bits: int = 19) -> None:
        self.tau = tau_s
        self.max_rate_deg = max_rate_deg
        self.max_accel_deg = max_accel_deg
        self._max_rate = math.radians(max_rate_deg)
        self._max_accel = math.radians(max_accel_deg)
        self._quant = 2 * math.pi / (1 << encoder_bits)
        self._el_min, self._el_max = math.radians(-10.0), math.radians(80.0)
        self._lock = threading.Lock()
        self.reset()

    def reset(self, az: float = 0.0, el: float = 0.0) -> None:
        with self._lock:
            self._t = None
            self._az, self._el = az, el
            self._raz, self._rel = 0.0, 0.0
            self._caz, self._cel = 0.0, 0.0

    def advance(self, t: float) -> None:
        with self._lock:
            if self._t is None:
                self._t = t
                return
            dt = t - self._t
            if dt <= 0:
                return
            self._t = t
            n = max(1, int(math.ceil(dt / 0.004)))
            h = dt / n
            a = min(1.0, h / self.tau)
            for _ in range(n):
                for axis in ("az", "el"):
                    r = getattr(self, "_r" + axis)
                    c = getattr(self, "_c" + axis)
                    dr = (c - r) * a
                    lim = self._max_accel * h
                    dr = max(-lim, min(lim, dr))
                    r = max(-self._max_rate, min(self._max_rate, r + dr))
                    setattr(self, "_r" + axis, r)
                self._az += self._raz * h
                el = self._el + self._rel * h
                if el < self._el_min or el > self._el_max:
                    el = max(self._el_min, min(self._el_max, el))
                    self._rel = 0.0
                self._el = el

    def command_rate(self, t: float, az_rate: float, el_rate: float) -> None:
        with self._lock:
            self._caz, self._cel = az_rate, el_rate

    def read_state(self, t: float) -> GimbalState:
        """Encoder reading (quantised), extrapolated to t."""
        with self._lock:
            base = self._t if self._t is not None else t
            dt = max(-0.05, min(0.05, t - base))
            q = self._quant
            az = round((self._az + self._raz * dt) / q) * q
            el = round((self._el + self._rel * dt) / q) * q
            return GimbalState(t, az, el, self._raz, self._rel)

    def true_pose(self, t: float):
        """Exact (unquantised) pose — used by the simulator's renderer only."""
        with self._lock:
            base = self._t if self._t is not None else t
            dt = max(-0.05, min(0.05, t - base))
            return self._az + self._raz * dt, self._el + self._rel * dt, self._raz, self._rel


class StaticMount(GimbalInterface):
    """Fixed camera (e.g. a recorded video). Tracking still runs in LOS space."""

    def __init__(self, az: float = 0.0, el: float = 0.0) -> None:
        self.az, self.el = az, el

    def read_state(self, t: float) -> GimbalState:
        return GimbalState(t, self.az, self.el, 0.0, 0.0)

    def command_rate(self, t: float, az_rate: float, el_rate: float) -> None:
        pass


class SerialPanTiltGimbal(GimbalInterface):
    """Hardware stage (next milestone): servo drive over serial / CAN.

    Expected wiring of the two methods:
      read_state  -> poll encoders (or use the drive's streamed telemetry), convert counts
                     to radians, timestamp with time.perf_counter() at reception minus the
                     measured transport delay.
      command_rate-> send velocity setpoints in the drive's units at >= 50 Hz.
    """

    def __init__(self, port: str = "COM3", baud: int = 115200) -> None:
        self.port, self.baud = port, baud

    def read_state(self, t: float) -> GimbalState:
        raise NotImplementedError("Hardware gimbal driver is scheduled for the hardware stage")

    def command_rate(self, t: float, az_rate: float, el_rate: float) -> None:
        raise NotImplementedError("Hardware gimbal driver is scheduled for the hardware stage")
