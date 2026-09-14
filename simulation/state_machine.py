"""
simulation/state_machine.py — Acquisition State Machine (Stage 2).

States:
  SEARCH     — camera scanning, beacon not yet detected
  ACQUIRING  — beacon detected, accumulating consecutive frames to confirm lock
  LOCKED     — beacon consistently detected and tracked
  COASTING   — beacon temporarily lost, tracker predicting from inertia
  REACQUIRE  — track definitively lost, restart search

Transitions:
  SEARCH     → ACQUIRING   (first detection)
  ACQUIRING  → LOCKED      (N consecutive detections, default 5)
  ACQUIRING  → SEARCH      (detection lost before lock confirmed)
  LOCKED     → COASTING    (detection lost)
  COASTING   → LOCKED      (detection recovered within coast window)
  COASTING   → REACQUIRE   (coast_frames > MAX_COAST_FRAMES)
  REACQUIRE  → SEARCH      (immediate, after one search init)
"""

import time
from dataclasses import dataclass


class TrackingState:
    SEARCH     = "SEARCH"
    ACQUIRING  = "ACQUIRING"
    LOCKED     = "LOCKED"
    COASTING   = "COASTING"
    REACQUIRE  = "REACQUIRE"


@dataclass
class FSMMetrics:
    """Accumulated statistics from the state machine."""
    acquisition_time: float   = 0.0   # seconds from SEARCH to first LOCK
    lock_retention: float     = 1.0   # fraction of time in LOCKED state
    reacquisition_time: float = 0.0   # seconds from REACQUIRE to next LOCK
    target_loss_events: int   = 0     # total number of lock-loss events
    total_time: float         = 0.0   # total sim time elapsed


class AcquisitionFSM:
    """Finite state machine managing beacon acquisition and tracking states.

    Drives transitions based on detector output and tracker coast count.
    Also accumulates metrics (acquisition time, lock retention, etc.).
    """

    ACQUIRE_CONSEC  = 5    # consecutive detections needed to confirm LOCKED
    MAX_COAST       = 30   # frames in COASTING before declaring REACQUIRE

    def __init__(self) -> None:
        self.state: str = TrackingState.SEARCH
        self._consec_detections: int = 0
        self._search_start_time: float = 0.0
        self._lock_start_time: float = 0.0
        self._reacquire_start_time: float = 0.0
        self._sim_time: float = 0.0

        # Metric accumulators
        self._time_locked: float = 0.0
        self._metrics = FSMMetrics()

    # ── Public API ─────────────────────────────────────────────────────────

    def update(self, detected: bool, coast_frames: int, track_lost: bool, dt: float) -> str:
        """Advance FSM by one frame.

        Args:
            detected:     True if the detector found a valid centroid this frame.
            coast_frames: Number of frames the tracker has been coasting.
            track_lost:   True if tracker has exceeded MAX_COAST_FRAMES.
            dt:           Frame time step (seconds).

        Returns:
            Current state string.
        """
        self._sim_time += dt
        self._metrics.total_time = self._sim_time

        prev_state = self.state

        # ── State transitions ──────────────────────────────────────────────
        if self.state == TrackingState.SEARCH:
            if detected:
                self._consec_detections = 1
                self.state = TrackingState.ACQUIRING

        elif self.state == TrackingState.ACQUIRING:
            if detected:
                self._consec_detections += 1
                if self._consec_detections >= self.ACQUIRE_CONSEC:
                    self.state = TrackingState.LOCKED
                    self._on_locked()
            else:
                self._consec_detections = 0
                self.state = TrackingState.SEARCH

        elif self.state == TrackingState.LOCKED:
            if not detected:
                self.state = TrackingState.COASTING
                self._on_lock_lost()

        elif self.state == TrackingState.COASTING:
            if detected:
                self.state = TrackingState.LOCKED
                self._on_locked()
            elif track_lost:
                self.state = TrackingState.REACQUIRE

        elif self.state == TrackingState.REACQUIRE:
            # Immediately go back to SEARCH to restart scan
            self.state = TrackingState.SEARCH
            self._search_start_time = self._sim_time

        # ── Metric tracking ────────────────────────────────────────────────
        if self.state == TrackingState.LOCKED:
            self._time_locked += dt
        if self._metrics.total_time > 0:
            self._metrics.lock_retention = self._time_locked / self._metrics.total_time

        return self.state

    @property
    def metrics(self) -> FSMMetrics:
        return self._metrics

    def reset(self) -> None:
        """Reset FSM to initial SEARCH state."""
        self.state = TrackingState.SEARCH
        self._consec_detections = 0
        self._search_start_time = 0.0
        self._lock_start_time = 0.0
        self._sim_time = 0.0
        self._time_locked = 0.0
        self._metrics = FSMMetrics()

    # ── Private callbacks ─────────────────────────────────────────────────

    def _on_locked(self) -> None:
        """Called when transitioning into LOCKED state."""
        if self._metrics.acquisition_time == 0.0:
            self._metrics.acquisition_time = self._sim_time - self._search_start_time
        if self._reacquire_start_time > 0:
            self._metrics.reacquisition_time = self._sim_time - self._reacquire_start_time
            self._reacquire_start_time = 0.0
        self._lock_start_time = self._sim_time

    def _on_lock_lost(self) -> None:
        """Called when transitioning out of LOCKED state."""
        self._metrics.target_loss_events += 1
        self._reacquire_start_time = self._sim_time
