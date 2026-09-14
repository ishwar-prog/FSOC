"""
simulation/search.py — Camera Search Pattern Generator (Stage 2).

Used by the engine when FSM is in SEARCH or REACQUIRE state.

Provides:
  - Spiral search (expanding concentric square raster)
  - Raster search (left-right, step down)

Both patterns generate a sequence of (pan_deg, tilt_deg) waypoints.
The camera is commanded toward each waypoint respecting its rate limits.
"""

import math
from typing import List, Tuple, Optional
from .camera import VirtualCamera3D


class SearchPattern:
    """Camera search pattern generator.

    Generates pan/tilt waypoints and commands the camera toward each one.
    Respects the camera's pan/tilt limits and rate limits.

    Usage:
        sp = SearchPattern(mode="spiral")
        sp.reset(camera)
        # Per-frame:
        sp.step(camera, dt, max_rate_deg=5.0)
        if sp.completed:
            sp.reset(camera)  # restart
    """

    # Step size for scan grid (degrees)
    STEP_DEG = 1.5
    # Tolerance to consider a waypoint "reached"
    REACH_TOL_DEG = 0.3

    def __init__(self, mode: str = "spiral") -> None:
        self.mode: str = mode   # "spiral" or "raster"
        self._waypoints: List[Tuple[float, float]] = []
        self._wp_idx: int = 0
        self._origin_pan: float = 0.0
        self._origin_tilt: float = 0.0
        self.completed: bool = False

    def reset(self, camera: VirtualCamera3D) -> None:
        """Restart search from camera's current pointing direction."""
        self._origin_pan  = math.degrees(camera.pan)
        self._origin_tilt = math.degrees(camera.tilt)
        self.completed = False
        self._wp_idx = 0
        self._waypoints = self._generate_waypoints()

    def step(self, camera: VirtualCamera3D, dt: float, max_rate_deg: float = 5.0) -> None:
        """Advance the search pattern by one time step.

        Commands the camera toward the current waypoint.
        Advances to next waypoint when current is reached.
        """
        if not self._waypoints or self._wp_idx >= len(self._waypoints):
            self.completed = True
            return

        target_pan_deg, target_tilt_deg = self._waypoints[self._wp_idx]

        # Current angles in degrees
        curr_pan  = math.degrees(camera.pan)
        curr_tilt = math.degrees(camera.tilt)

        # Angular error to current waypoint
        dpan  = target_pan_deg  - curr_pan
        dtilt = target_tilt_deg - curr_tilt

        # Check if waypoint reached
        if abs(dpan) < self.REACH_TOL_DEG and abs(dtilt) < self.REACH_TOL_DEG:
            self._wp_idx += 1
            if self._wp_idx >= len(self._waypoints):
                self.completed = True
            return

        # Rate-limit slew
        max_delta = max_rate_deg * dt
        cmd_pan  = math.copysign(min(abs(dpan),  max_delta), dpan)
        cmd_tilt = math.copysign(min(abs(dtilt), max_delta), dtilt)

        camera.set_pan(camera.pan   + math.radians(cmd_pan))
        camera.set_tilt(camera.tilt + math.radians(cmd_tilt))

    @property
    def current_waypoint(self) -> Optional[Tuple[float, float]]:
        if self._waypoints and self._wp_idx < len(self._waypoints):
            return self._waypoints[self._wp_idx]
        return None

    @property
    def progress_pct(self) -> float:
        if not self._waypoints:
            return 0.0
        return 100.0 * self._wp_idx / len(self._waypoints)

    # ── Waypoint generation ────────────────────────────────────────────────

    def _generate_waypoints(self) -> List[Tuple[float, float]]:
        if self.mode == "raster":
            return self._raster_waypoints()
        return self._spiral_waypoints()

    def _raster_waypoints(self) -> List[Tuple[float, float]]:
        """Left-right raster scan covering ±25° pan, ±18° tilt from origin."""
        wps = []
        op, ot = self._origin_pan, self._origin_tilt
        step = self.STEP_DEG * 2.5
        tilt_vals = list(range(-18, 19, int(step)))
        for i, dt in enumerate(tilt_vals):
            pan_vals = list(range(-25, 26, int(step)))
            if i % 2 == 1:
                pan_vals = pan_vals[::-1]  # boustrophedon (snake pattern)
            for dp in pan_vals:
                wps.append((op + dp, ot + dt))
        return wps

    def _spiral_waypoints(self) -> List[Tuple[float, float]]:
        """Expanding square spiral search centered on origin pointing."""
        wps = [(self._origin_pan, self._origin_tilt)]
        step = self.STEP_DEG
        op, ot = self._origin_pan, self._origin_tilt
        x, y = 0.0, 0.0   # relative pan, tilt offsets (degrees)
        direction = 0   # 0=right, 1=up, 2=left, 3=down
        segment_len = 1
        steps_in_seg = 0
        segments_done = 0
        max_offset_deg = 30.0

        while True:
            dx_map = [1, 0, -1, 0]
            dy_map = [0, 1, 0, -1]
            dx = dx_map[direction] * step
            dy = dy_map[direction] * step

            x += dx
            y += dy

            if abs(x) > max_offset_deg or abs(y) > max_offset_deg:
                break

            pan_deg  = op + x
            tilt_deg = ot + y

            # Clamp to camera limits
            if abs(pan_deg) > 175 or abs(tilt_deg) > 55:
                steps_in_seg += 1
                if steps_in_seg >= segment_len:
                    steps_in_seg = 0
                    segments_done += 1
                    direction = (direction + 1) % 4
                    if segments_done % 2 == 0:
                        segment_len += 1
                continue

            wps.append((pan_deg, tilt_deg))
            steps_in_seg += 1

            if steps_in_seg >= segment_len:
                steps_in_seg = 0
                segments_done += 1
                direction = (direction + 1) % 4
                if segments_done % 2 == 0:
                    segment_len += 1

        return wps
