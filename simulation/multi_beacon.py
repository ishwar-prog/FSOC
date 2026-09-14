"""
simulation/multi_beacon.py — Multiple Beacon Manager (Stage 2).

Manages 1 or 3 optical beacons:
  Beacon 0: primary target  — follows TargetMotion (same as Stage 1)
  Beacon 1: distractor      — circular motion, reduced intensity
  Beacon 2: distractor      — figure-eight motion, reduced intensity

The detector sees all beacons as bright blobs.
The tracker is associated with the designated primary beacon.
Simple nearest-centroid association tracks the primary.
"""

import math
import numpy as np
from typing import List, Tuple, Optional
from .motion import TargetMotion
from .beacon import OpticalBeacon


class MultiBeaconManager:
    """Manages 1 or 3 beacons in the 3D world.

    Primary beacon (index 0) is the tracking target.
    Distractors (indices 1-2) use independent motions.
    """

    DISTRACTOR_INTENSITIES = [0.65, 0.50]  # relative to primary

    def __init__(self, beacon_count: int = 1) -> None:
        self._count: int = max(1, min(3, beacon_count))
        self._primary_beacon = OpticalBeacon(intensity=1.0)
        self._primary_motion: Optional[TargetMotion] = None   # set by engine

        # Distractor motions (independent of primary)
        self._dist_motions: List[TargetMotion] = [
            TargetMotion(mode="circle",       speed=0.4, seed=11),
            TargetMotion(mode="figure_eight", speed=0.35, seed=77),
        ]
        # Distractor start positions offset from primary
        self._dist_motions[0]._theta = 1.2
        self._dist_motions[1]._theta = 2.7

        # Designated target index (0 = primary)
        self.target_idx: int = 0

    # ── Properties ─────────────────────────────────────────────────────────

    @property
    def count(self) -> int:
        return self._count

    def set_count(self, n: int) -> None:
        self._count = max(1, min(3, n))

    def set_primary_motion(self, motion: TargetMotion) -> None:
        """Link the engine's primary TargetMotion object."""
        self._primary_motion = motion

    def set_primary_intensity(self, intensity: float) -> None:
        self._primary_beacon.set_intensity(intensity)

    @property
    def primary_intensity(self) -> float:
        return self._primary_beacon.intensity

    # ── Per-frame update ───────────────────────────────────────────────────

    def step(self, dt: float) -> None:
        """Advance distractor motions (primary motion is stepped by engine)."""
        for dm in self._dist_motions:
            dm.step(dt)

    def reset(self) -> None:
        for dm in self._dist_motions:
            dm.reset()

    # ── Position queries ───────────────────────────────────────────────────

    def get_beacon_positions(self) -> List[np.ndarray]:
        """Return 3D world positions of all active beacons."""
        positions = []
        if self._primary_motion is not None:
            positions.append(self._primary_motion.position)

        if self._count >= 2:
            positions.append(self._dist_motions[0].position)
        if self._count >= 3:
            positions.append(self._dist_motions[1].position)

        return positions

    def get_primary_position(self) -> np.ndarray:
        """Return 3D position of the primary (target) beacon."""
        if self._primary_motion is not None:
            return self._primary_motion.position
        return np.array([0.0, 100.0, 1000.0])

    def get_beacon_intensity(self, idx: int) -> float:
        """Return effective intensity for beacon at index."""
        if idx == 0:
            return self._primary_beacon.intensity
        dim_idx = idx - 1
        if dim_idx < len(self.DISTRACTOR_INTENSITIES):
            return self._primary_beacon.intensity * self.DISTRACTOR_INTENSITIES[dim_idx]
        return 0.5

    def get_beacon_info(self) -> List[dict]:
        """Return list of dicts for all beacons (for state/GUI)."""
        positions = self.get_beacon_positions()
        return [
            {
                "index": i,
                "position": positions[i].tolist(),
                "intensity": self.get_beacon_intensity(i),
                "is_target": (i == self.target_idx),
            }
            for i in range(len(positions))
        ]

    def associate_detection(
        self,
        detections: List[Tuple[float, float]],
        tracker_pred_x: float,
        tracker_pred_y: float,
    ) -> Optional[Tuple[float, float]]:
        """Associate detection candidates to the tracker prediction.

        Selects the nearest detection to the tracker's predicted position.
        Returns None if no detection is close enough.

        Args:
            detections:    List of (x, y) candidate centroids.
            tracker_pred_x/y: Current tracker prediction.

        Returns:
            Best matching (x, y) or None.
        """
        if not detections:
            return None

        max_dist = 80.0   # pixels — maximum gating distance

        best = None
        best_dist = max_dist

        for dx, dy in detections:
            dist = math.hypot(dx - tracker_pred_x, dy - tracker_pred_y)
            if dist < best_dist:
                best_dist = dist
                best = (dx, dy)

        return best
