"""
simulation/detector.py — Classical OpenCV Beacon Detector (Stage 2 & 3).

Pipeline:
  BGR frame → grayscale → morphological top-hat background isolation →
  adaptive thresholding → morphological closing → connected components →
  blob filtering → intensity-weighted sub-pixel centroid → DetectionResult

Designed specifically for optical beacon tracking in free-space optical communications:
- Uses Morphological Top-Hat rather than temporal frame subtraction so stationary
  tracked beacons at bore-sight are NEVER subtracted out or lost.
- Resilient to diffuse atmospheric fog, haze, rain streaks, and sensor readout noise.
- Ground truth is NEVER used here.
"""

import time
import math
import numpy as np
import cv2
from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass
class DetectionResult:
    """Output of one detector run on a single frame."""
    detected: bool          # True if a valid centroid was found
    x: float                # Centroid X in sensor pixels (0–639)
    y: float                # Centroid Y in sensor pixels (0–479)
    confidence: float       # 0.0–1.0 (higher = more certain)
    candidates: int         # Number of candidate blobs found (before selection)
    candidate_list: list    # [(x, y, area, peak)] for all candidates (debug)


class BeaconDetector:
    """Robust OpenCV optical beacon detector.

    Uses:
      - Morphological Top-Hat filter for background gradient / fog isolation
      - Gaussian pre-filter to suppress high-frequency thermal noise
      - Adaptive statistical thresholding based on frame noise floor
      - Connected-component blob extraction
      - Intensity-weighted sub-pixel centroiding on best candidate
    """

    MIN_AREA_PX = 2
    MAX_AREA_PX = 1500
    MIN_PEAK_INTENSITY = 25.0

    def __init__(self) -> None:
        self._frame_count: int = 0
        self._proc_time_ms: float = 0.0

        # Morphology kernels
        self._kernel_tophat = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (19, 19))
        self._kernel_close  = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        self._kernel_open   = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))

    def detect(self, frame: np.ndarray) -> DetectionResult:
        """Run detector on a single BGR uint8 frame."""
        t0 = time.perf_counter()
        result = self._run_detection(frame)
        self._proc_time_ms = (time.perf_counter() - t0) * 1000.0
        return result

    @property
    def processing_time_ms(self) -> float:
        return self._proc_time_ms

    def reset(self) -> None:
        """Reset internal frame counters."""
        self._frame_count = 0

    # ── Internal pipeline ──────────────────────────────────────────────────

    def _run_detection(self, frame: np.ndarray) -> DetectionResult:
        self._frame_count += 1
        H, W = frame.shape[:2]

        # 1. Grayscale conversion
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # 2. Morphological White Top-Hat: isolates bright optical spots (beacon/stars)
        # from low-frequency diffuse background (fog veil, haze, vignetting)
        tophat = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, self._kernel_tophat)

        # 3. Gaussian pre-blur on top-hat to reduce single-pixel shot noise
        blurred = cv2.GaussianBlur(tophat, (3, 3), 0.8)

        # 4. Adaptive statistical thresholding
        mean_val = float(np.mean(blurred))
        std_val = float(np.std(blurred))
        thresh_val = max(18.0, min(160.0, mean_val + 2.8 * std_val))

        _, binary = cv2.threshold(blurred, int(thresh_val), 255, cv2.THRESH_BINARY)

        # 5. Morphological cleanup
        binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, self._kernel_close)

        # 6. Connected components analysis
        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(
            binary, connectivity=8
        )

        # 7. Candidate filtering
        candidates = []
        for i in range(1, num_labels):
            area = stats[i, cv2.CC_STAT_AREA]
            if area < self.MIN_AREA_PX or area > self.MAX_AREA_PX:
                continue

            cx, cy = centroids[i]
            mask = (labels == i)
            roi = gray[mask]
            if len(roi) == 0:
                continue

            peak_val = float(roi.max())
            mean_val_roi = float(roi.mean())

            if peak_val < self.MIN_PEAK_INTENSITY:
                continue

            candidates.append({
                "x": float(cx),
                "y": float(cy),
                "area": int(area),
                "peak": peak_val,
                "mean": mean_val_roi,
                "label": i,
            })

        if not candidates:
            # Fallback: simple global peak detection if beacon is faint
            max_val = float(np.max(gray))
            if max_val >= 30.0:
                max_loc = np.unravel_index(np.argmax(gray), gray.shape)
                py, px = float(max_loc[0]), float(max_loc[1])
                return DetectionResult(
                    detected=True,
                    x=px,
                    y=py,
                    confidence=min(0.5, max_val / 255.0),
                    candidates=1,
                    candidate_list=[(px, py, 4, max_val)],
                )

            return DetectionResult(
                detected=False, x=320.0, y=240.0, confidence=0.0,
                candidates=0, candidate_list=[]
            )

        # 8. Select best candidate:
        # Optical beacon has both high peak brightness and wider PSF spread than guide stars
        best = max(candidates, key=lambda c: c["peak"] * (1.0 + math.sqrt(c["area"])))

        # 9. Intensity-weighted sub-pixel centroid refinement on best candidate
        mask = (labels == best["label"]).astype(np.uint8)
        wx, wy = self._weighted_centroid(gray, mask, best["x"], best["y"], radius=14)

        # 10. Confidence score
        area_score = min(1.0, math.sqrt(best["area"]) / 5.0)
        peak_score = min(1.0, best["peak"] / 200.0)
        confidence = float(min(1.0, max(0.15, area_score * 0.4 + peak_score * 0.6)))

        candidate_list = [(c["x"], c["y"], c["area"], c["peak"]) for c in candidates]

        return DetectionResult(
            detected=True,
            x=float(wx),
            y=float(wy),
            confidence=confidence,
            candidates=len(candidates),
            candidate_list=candidate_list,
        )

    def _weighted_centroid(
        self,
        gray: np.ndarray,
        mask: np.ndarray,
        cx: float,
        cy: float,
        radius: int = 14,
    ) -> Tuple[float, float]:
        """Compute sub-pixel intensity-weighted centroid around candidate peak."""
        H, W = gray.shape
        x0 = max(0, int(cx) - radius)
        x1 = min(W, int(cx) + radius + 1)
        y0 = max(0, int(cy) - radius)
        y1 = min(H, int(cy) + radius + 1)

        patch = gray[y0:y1, x0:x1].astype(np.float32)
        pmask = mask[y0:y1, x0:x1]

        # Background floor subtraction
        floor = np.percentile(patch, 15)
        weights = np.maximum(0.0, patch - floor)

        # Bias weights by component mask
        weights = weights * (pmask.astype(np.float32) * 0.8 + 0.2)

        total_weight = float(weights.sum())
        if total_weight < 1e-4:
            return float(cx), float(cy)

        yy, xx = np.mgrid[y0:y1, x0:x1]
        wx = float((xx * weights).sum() / total_weight)
        wy = float((yy * weights).sum() / total_weight)

        return wx, wy
