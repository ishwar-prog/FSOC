"""
simulation/tracker.py — Kalman Filter Beacon Tracker (Stage 2).

Implements a constant-velocity 2D pixel-space Kalman filter tracker.

State vector: [x, y, vx, vy]
Measurement:  [x, y]

Behavior:
  predict()   — advance state each frame (even without detection)
  update()    — correct with detected centroid
  coast()     — predict only; used when detection is lost temporarily

The tracker operates entirely in pixel space (0–639, 0–479).
"""

import math
import numpy as np
import cv2
from dataclasses import dataclass
from typing import Optional


@dataclass
class TrackerState:
    """Current tracker state snapshot."""
    x: float           # Estimated centroid X (pixels)
    y: float           # Estimated centroid Y (pixels)
    vx: float          # Estimated velocity X (pixels/s)
    vy: float          # Estimated velocity Y (pixels/s)
    valid: bool        # True if tracker has been initialized
    coast_frames: int  # How many frames since last detection


class BeaconTracker:
    """2D Kalman filter tracker for beacon centroid in pixel space.

    Uses cv2.KalmanFilter with a constant-velocity state model.
    Can coast (predict-only) for a configurable number of frames
    before declaring track lost.
    """

    MAX_COAST_FRAMES = 30   # frames to coast before declaring track lost

    # Process noise — how much the beacon can accelerate
    Q_POS = 2.0      # position process noise (pixels²)
    Q_VEL = 25.0     # velocity process noise (pixels²/s²)

    # Measurement noise — detector precision
    R_NOISE = 4.0    # measurement noise covariance (pixels²)

    def __init__(self) -> None:
        self._kf: Optional[cv2.KalmanFilter] = None
        self._initialized: bool = False
        self._coast_frames: int = 0
        self._last_x: float = 320.0
        self._last_y: float = 240.0
        self._last_vx: float = 0.0
        self._last_vy: float = 0.0

    # ── Public API ─────────────────────────────────────────────────────────

    def initialize(self, x: float, y: float) -> None:
        """Initialize (or re-initialize) tracker at a given pixel position."""
        self._kf = cv2.KalmanFilter(4, 2)  # 4 state, 2 measurement

        # Transition matrix (will be updated each frame with dt)
        self._kf.transitionMatrix = np.eye(4, dtype=np.float32)

        # Measurement matrix: observe [x, y] from state [x, y, vx, vy]
        self._kf.measurementMatrix = np.array(
            [[1, 0, 0, 0],
             [0, 1, 0, 0]], dtype=np.float32
        )

        # Process noise covariance
        self._kf.processNoiseCov = np.diag(
            [self.Q_POS, self.Q_POS, self.Q_VEL, self.Q_VEL]
        ).astype(np.float32)

        # Measurement noise covariance
        self._kf.measurementNoiseCov = np.array(
            [[self.R_NOISE, 0],
             [0, self.R_NOISE]], dtype=np.float32
        )

        # Initial state
        self._kf.statePre = np.array(
            [[x], [y], [0.0], [0.0]], dtype=np.float32
        )
        self._kf.statePost = self._kf.statePre.copy()

        # Initial error covariance (large = uncertain)
        self._kf.errorCovPost = np.eye(4, dtype=np.float32) * 100.0

        self._initialized = True
        self._coast_frames = 0
        self._last_x = x
        self._last_y = y
        self._last_vx = 0.0
        self._last_vy = 0.0

    def predict(self, dt: float) -> TrackerState:
        """Advance tracker state by dt seconds (predict step only).

        Returns current state estimate.
        """
        if not self._initialized:
            return self._empty_state()

        self._update_transition(dt)
        prediction = self._kf.predict()
        self._extract_state(prediction)
        return self._current_state()

    def update(self, x: float, y: float, dt: float) -> TrackerState:
        """Predict + correct with a new measurement.

        Call this when detection is available.
        """
        if not self._initialized:
            self.initialize(x, y)
            return self._current_state()

        self._update_transition(dt)
        self._kf.predict()

        measurement = np.array([[x], [y]], dtype=np.float32)
        state = self._kf.correct(measurement)
        self._extract_state(state)
        self._coast_frames = 0
        return self._current_state()

    def coast(self, dt: float) -> TrackerState:
        """Predict-only step when no detection available.

        Increments coast counter; caller should check .track_lost.
        """
        if not self._initialized:
            return self._empty_state()

        self._coast_frames += 1
        return self.predict(dt)

    @property
    def track_lost(self) -> bool:
        """True when coasting has exceeded MAX_COAST_FRAMES."""
        return self._coast_frames >= self.MAX_COAST_FRAMES

    @property
    def initialized(self) -> bool:
        return self._initialized

    def reset(self) -> None:
        """Reset tracker to uninitialized state."""
        self._kf = None
        self._initialized = False
        self._coast_frames = 0

    # ── Internal ───────────────────────────────────────────────────────────

    def _update_transition(self, dt: float) -> None:
        """Update transition matrix with current dt."""
        dt = float(min(dt, 0.1))
        F = self._kf.transitionMatrix
        F[0, 2] = dt
        F[1, 3] = dt
        self._kf.transitionMatrix = F

    def _extract_state(self, state: np.ndarray) -> None:
        flat = state.flatten()
        self._last_x  = float(flat[0])
        self._last_y  = float(flat[1])
        self._last_vx = float(flat[2])
        self._last_vy = float(flat[3])

    def _current_state(self) -> TrackerState:
        return TrackerState(
            x=self._last_x,
            y=self._last_y,
            vx=self._last_vx,
            vy=self._last_vy,
            valid=self._initialized,
            coast_frames=self._coast_frames,
        )

    def _empty_state(self) -> TrackerState:
        return TrackerState(
            x=320.0, y=240.0, vx=0.0, vy=0.0,
            valid=False, coast_frames=0,
        )
