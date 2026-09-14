"""Line-of-sight Kalman tracker — Singer manoeuvring-target model.

State per axis: [angle, rate, acceleration] (rad, rad/s, rad/s^2). Acceleration is a
first-order Markov process with time constant tau (Singer, 1970): targets can turn,
weave and brake, and during an occlusion the predicted acceleration decays smoothly
instead of being extrapolated forever. This is the textbook model for manoeuvring
targets and keeps coasting error small through evasive turns.

Azimuth and elevation are filtered independently (nearly decoupled for small fields of
view), keeping the filter in plain Python floats.

Hardware-relevant features:
  * Timestamp-driven predict/update (frame drops, jittery USB cameras, variable FPS video).
  * Per-detection measurement noise from SNR plus innovation-based adaptive noise that
    learns unmodelled jitter (mount vibration, turbulence).
  * Manoeuvre adaptation of the process noise from the normalised innovation.
  * Physical clamps on rate and acceleration (a tracker must never "run away").
  * Mahalanobis gating for data association.
"""

import math
from dataclasses import dataclass
from typing import List, Tuple

from .geometry import wrap_pi

DEG = math.pi / 180.0


@dataclass
class TrackEstimate:
    t: float
    az: float
    el: float
    vaz: float
    vel: float
    sigma_az: float
    sigma_el: float
    sigma_vaz: float = 0.0
    sigma_vel: float = 0.0


class _Axis:
    __slots__ = ("x", "P")

    def __init__(self, p: float, v: float, sp: float, sv: float, sa: float) -> None:
        self.x: List[float] = [p, v, 0.0]
        self.P: List[List[float]] = [[sp * sp, 0.0, 0.0], [0.0, sv * sv, 0.0], [0.0, 0.0, sa * sa]]

    @staticmethod
    def _coeffs(dt: float, alpha: float):
        e = math.exp(-alpha * dt)
        return e, (alpha * dt - 1.0 + e) / (alpha * alpha), (1.0 - e) / alpha

    def position_only(self, dt: float, q: float, alpha: float) -> Tuple[float, float, float, float]:
        """Predicted (angle, rate, var(angle), var(rate)) without mutating — cheap path for gating."""
        e, f02, f12 = self._coeffs(dt, alpha)
        x, P = self.x, self.P
        p = x[0] + dt * x[1] + f02 * x[2]
        v = x[1] + f12 * x[2]
        p00 = (P[0][0] + dt * dt * P[1][1] + f02 * f02 * P[2][2]
               + 2 * dt * P[0][1] + 2 * f02 * P[0][2] + 2 * dt * f02 * P[1][2]
               + q * dt ** 5 / 20.0)
        p11 = P[1][1] + 2 * f12 * P[1][2] + f12 * f12 * P[2][2] + q * dt ** 3 / 3.0
        return p, v, p00, p11

    def predict(self, dt: float, q: float, alpha: float) -> None:
        e, f02, f12 = self._coeffs(dt, alpha)
        F = ((1.0, dt, f02), (0.0, 1.0, f12), (0.0, 0.0, e))
        x, P = self.x, self.P
        self.x = [x[0] + dt * x[1] + f02 * x[2], x[1] + f12 * x[2], e * x[2]]
        FP = [[F[i][0] * P[0][j] + F[i][1] * P[1][j] + F[i][2] * P[2][j] for j in range(3)] for i in range(3)]
        d2 = dt * dt
        d3 = d2 * dt
        Q = ((q * d3 * d2 / 20.0, q * d2 * d2 / 8.0, q * d3 / 6.0),
             (q * d2 * d2 / 8.0, q * d3 / 3.0, q * d2 / 2.0),
             (q * d3 / 6.0, q * d2 / 2.0, q * dt))
        self.P = [[FP[i][0] * F[j][0] + FP[i][1] * F[j][1] + FP[i][2] * F[j][2] + Q[i][j]
                   for j in range(3)] for i in range(3)]

    def update(self, z: float, r: float) -> Tuple[float, float]:
        P = self.P
        s = P[0][0] + r
        k = (P[0][0] / s, P[1][0] / s, P[2][0] / s)
        y = z - self.x[0]
        self.x = [self.x[0] + k[0] * y, self.x[1] + k[1] * y, self.x[2] + k[2] * y]
        row0 = (P[0][0], P[0][1], P[0][2])
        nP = [[P[i][j] - k[i] * row0[j] for j in range(3)] for i in range(3)]
        for i in range(3):
            for j in range(i + 1, 3):
                m = 0.5 * (nP[i][j] + nP[j][i])
                nP[i][j] = nP[j][i] = m
        self.P = nP
        return y, s


class LosKalmanTracker:
    def __init__(self, q_jerk: float = 1.0e-5, tau_s: float = 2.0,
                 vel_limit: float = 10.0 * DEG, acc_limit: float = 3.0 * DEG) -> None:
        self.q_base = q_jerk
        self.alpha = 1.0 / tau_s
        self.vel_limit = vel_limit
        self.acc_limit = acc_limit
        self.initialized = False
        self.t = 0.0
        self._az = _Axis(0, 0, 1, 1, 1)
        self._el = _Axis(0, 0, 1, 1, 1)
        self._q_boost = 1.0
        self._r_adapt = 0.0
        self._inn = ((0.0, 0.0), (1e-12, 1e-12))
        self.last_update_t = 0.0
        self.updates = 0

    # ---------------------------------------------------------------- lifecycle
    def initialize(self, t: float, az: float, el: float, vaz: float = 0.0, vel: float = 0.0,
                   pos_sigma: float = 2e-4, vel_sigma: float = 1.5 * DEG, acc_sigma: float = 0.3 * DEG) -> None:
        self._az = _Axis(az, vaz, pos_sigma, vel_sigma, acc_sigma)
        self._el = _Axis(el, vel, pos_sigma, vel_sigma, acc_sigma)
        self.t = t
        self.last_update_t = t
        self.initialized = True
        self._q_boost = 1.0
        self._r_adapt = 0.0
        self._inn = ((0.0, 0.0), (1e-12, 1e-12))
        self.updates = 1

    def reset(self) -> None:
        self.initialized = False
        self.updates = 0

    # ---------------------------------------------------------------- core
    @property
    def q(self) -> float:
        return self.q_base * self._q_boost

    def predict_to(self, t: float) -> None:
        dt = t - self.t
        if dt <= 0 or not self.initialized:
            return
        q = self.q
        self._az.predict(dt, q, self.alpha)
        self._el.predict(dt, q, self.alpha)
        self.t = t
        self._clamp()

    def estimate_at(self, t: float) -> TrackEstimate:
        """Non-mutating prediction (safe to call from the control loop)."""
        dt = max(0.0, t - self.t)
        q = self.q
        pa = self._az.position_only(dt, q, self.alpha)
        pe = self._el.position_only(dt, q, self.alpha)
        return TrackEstimate(t, pa[0], pe[0], pa[1], pe[1],
                             math.sqrt(max(pa[2], 0.0)), math.sqrt(max(pe[2], 0.0)),
                             math.sqrt(max(pa[3], 0.0)), math.sqrt(max(pe[3], 0.0)))

    def gate_distance(self, t: float, az_m: float, el_m: float, r_meas: float,
                      pos_sigma_cap: float = None) -> float:
        """Squared Mahalanobis distance of a LOS measurement (2 dof). Optionally caps the
        predicted position uncertainty so long coasts do not open an unbounded gate."""
        dt = max(0.0, t - self.t)
        q = self.q
        pa = self._az.position_only(dt, q, self.alpha)
        pe = self._el.position_only(dt, q, self.alpha)
        va, ve = pa[2], pe[2]
        if pos_sigma_cap is not None:
            c2 = pos_sigma_cap * pos_sigma_cap
            va, ve = min(va, c2), min(ve, c2)
        r = r_meas + self._r_adapt
        daz = wrap_pi(az_m - pa[0])
        delv = el_m - pe[0]
        return daz * daz / (va + r) + delv * delv / (ve + r)

    def update(self, t: float, az_m: float, el_m: float, r_meas: float) -> float:
        """Predict to t and fuse a LOS measurement. Returns normalised innovation squared."""
        self.predict_to(t)
        az_m = self._az.x[0] + wrap_pi(az_m - self._az.x[0])
        r = r_meas + self._r_adapt
        pa00, pe00 = self._az.P[0][0], self._el.P[0][0]
        ya, sa = self._az.update(az_m, r)
        ye, se = self._el.update(el_m, r)
        nis = ya * ya / sa + ye * ye / se

        # Innovation whiteness test: a manoeuvre produces a persistent (biased) innovation,
        # sensor or mount jitter a zero-mean one. Boost process noise only for the former and
        # learn measurement noise from the latter.
        m, s2 = self._inn
        m = (0.8 * m[0] + 0.2 * ya, 0.8 * m[1] + 0.2 * ye)
        s2 = (0.8 * s2[0] + 0.2 * ya * ya, 0.8 * s2[1] + 0.2 * ye * ye)
        self._inn = (m, s2)
        bias = max(abs(m[0]) / math.sqrt(s2[0] + 1e-18), abs(m[1]) / math.sqrt(s2[1] + 1e-18))
        var = 0.5 * ((s2[0] - m[0] * m[0]) + (s2[1] - m[1] * m[1]))
        excess = var - 0.5 * (pa00 + pe00) - r_meas
        self._r_adapt = min((2.5e-3) ** 2, max(0.0, 0.9 * self._r_adapt + 0.1 * excess))

        if nis > 13.8 and bias > 0.6:
            self._q_boost = min(40.0, self._q_boost * 2.5)
        else:
            self._q_boost = max(1.0, self._q_boost * 0.9)
        self._clamp()
        self.last_update_t = t
        self.updates += 1
        return nis

    def recentre(self, t: float, az_m: float, el_m: float, r_meas: float) -> None:
        """Robust re-centre when a trusted detection lies outside the gate: open the covariance
        to the observed innovation so the filter follows the measurement, then fuse it."""
        self.predict_to(t)
        for ax, z in ((self._az, self._az.x[0] + wrap_pi(az_m - self._az.x[0])), (self._el, el_m)):
            inn = z - ax.x[0]
            ax.P[0][0] = max(ax.P[0][0], inn * inn * 4.0)
            ax.P[1][1] = max(ax.P[1][1], (inn / 0.4) ** 2)
            ax.P[0][1] = ax.P[1][0] = 0.0
            ax.P[0][2] = ax.P[2][0] = 0.0
            ax.P[1][2] = ax.P[2][1] = 0.0
        self._q_boost = 20.0
        self.update(t, az_m, el_m, r_meas)

    def set_rate(self, vaz: float, vel: float) -> None:
        """Replace the rate estimate (e.g. with a smoothed one before a coast)."""
        self._az.x[1], self._el.x[1] = vaz, vel
        self._az.x[2] *= 0.3
        self._el.x[2] *= 0.3

    def inflate(self, pos_sigma: float) -> None:
        s2 = pos_sigma * pos_sigma
        self._az.P[0][0] = max(self._az.P[0][0], s2)
        self._el.P[0][0] = max(self._el.P[0][0], s2)

    def _clamp(self) -> None:
        for ax in (self._az, self._el):
            ax.x[1] = max(-self.vel_limit, min(self.vel_limit, ax.x[1]))
            ax.x[2] = max(-self.acc_limit, min(self.acc_limit, ax.x[2]))

    @property
    def measurement_noise_adapt(self) -> float:
        return math.sqrt(self._r_adapt)
