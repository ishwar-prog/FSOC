"""Gimbal rate controller: velocity feed-forward + PI feedback, rate and acceleration limited.

  rate_cmd = ff * target_rate + Kp * e + Ki * integral(e)

Feed-forward from the Kalman LOS rate removes the steady-state lag that a pure
proportional loop has against a moving target (the dominant error source in the old
build). The command is slew-limited so the mechanism never sees steps — this is also
what makes the motion look smooth on screen. Output is a rate command, the native
interface of almost every pan/tilt servo drive.
"""

import math
from dataclasses import dataclass
from typing import Tuple

from .geometry import wrap_pi


@dataclass
class ControllerGains:
    kp_track: float = 9.0       # 1/s
    ki_track: float = 14.0      # 1/s^2
    kp_search: float = 11.0
    ff_gain: float = 1.0
    latency_s: float = 0.02     # actuator/transport latency compensated by prediction


class GimbalController:
    def __init__(self, max_rate_deg: float = 40.0, max_accel_deg: float = 220.0,
                 gains: ControllerGains = None) -> None:
        self.gains = gains or ControllerGains()
        self.max_rate = math.radians(max_rate_deg)
        self.max_accel = math.radians(max_accel_deg)
        self.reset()

    def reset(self) -> None:
        self._i_az = 0.0
        self._i_el = 0.0
        self._cmd_az = 0.0
        self._cmd_el = 0.0
        self.last_error = (0.0, 0.0)

    def set_max_rate(self, deg_s: float) -> None:
        self.max_rate = math.radians(max(2.0, min(120.0, deg_s)))

    def compute(self, dt: float, enc_az: float, enc_el: float,
                ref_az: float, ref_el: float, ref_vaz: float, ref_vel: float,
                tracking: bool) -> Tuple[float, float]:
        g = self.gains
        e_az = wrap_pi(ref_az - enc_az)
        e_el = ref_el - enc_el
        self.last_error = (e_az, e_el)

        if tracking:
            kp = g.kp_track
            lim = math.radians(0.6)
            self._i_az = max(-lim, min(lim, self._i_az + e_az * dt))
            self._i_el = max(-lim, min(lim, self._i_el + e_el * dt))
            ki = g.ki_track
        else:
            kp = g.kp_search
            ki = 0.0
            self._i_az *= 0.8
            self._i_el *= 0.8

        want_az = g.ff_gain * ref_vaz + kp * e_az + ki * self._i_az
        want_el = g.ff_gain * ref_vel + kp * e_el + ki * self._i_el
        want_az = max(-self.max_rate, min(self.max_rate, want_az))
        want_el = max(-self.max_rate, min(self.max_rate, want_el))

        step = self.max_accel * dt
        self._cmd_az += max(-step, min(step, want_az - self._cmd_az))
        self._cmd_el += max(-step, min(step, want_el - self._cmd_el))
        return self._cmd_az, self._cmd_el
