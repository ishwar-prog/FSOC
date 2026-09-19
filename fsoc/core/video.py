"""Front-end for real recorded video.

The simulator hands the tracker a narrow-field NIR frame where the beacon is essentially the
only thing in the sky. A real recording is not like that: a wide field of view, a textured
daylight or night scene, rolling auto-exposure, compression blocking, camera shake — and a
target that may be a bright blinking spot, a steady lamp, or a dark drone silhouette against
cloud. Brightness alone is not enough to find it.

`VideoBeaconDetector` keeps the classical point-source detector (which is still the right tool
for a beacon: a matched filter at the PSF scale with a CFAR threshold) and adds two things real
footage needs:

  * **Motion saliency.** An MOG2 background model learns the static scene — sky gradient,
    buildings, street lights, window reflections — so anything that *moves against it* is
    offered as a candidate even when it is dimmer than the clutter. This is what finds a drone
    against bright cloud, or a target that is not the brightest pixel in the frame.
  * **Scale awareness.** The point-source path is tuned for spots a few pixels across. A second,
    coarser pass catches targets that are tens of pixels across (a close drone, a lit window on
    a moving vehicle) which a small-kernel top-hat would flatten away.

Candidates from both paths are merged (nearest-neighbour de-duplication) and handed to exactly
the same identification, association and tracking code the simulator uses — the beacon is still
chosen by its learned blink signature and its motion consistency, never by being brightest.
"""

import math
from typing import List, Optional, Tuple

import cv2
import numpy as np

from .detector import BeaconDetector, Candidate, DetectionResult
from .geometry import CameraIntrinsics


class VideoBeaconDetector(BeaconDetector):
    MERGE_PX = 6.0                     # candidates closer than this are the same light
    MAX_MOTION_BLOBS = 10

    STRONG_SNR = 12.0                  # a bright detection this good needs no help from motion
    ENOUGH_STRONG = 2                  # ...and this many of them means the scene is well covered

    def __init__(self, K: Optional[CameraIntrinsics] = None, motion: bool = False, **kw) -> None:
        # Real footage is wider and noisier than the simulated sensor: allow larger blobs (a
        # close target is not a point source) and a more forgiving shape, because bloom, JPEG
        # blocking and saturation all distort a real spot.
        # Measured on real footage: loosening the shape gates much beyond the simulator's is a
        # net loss — cloud edges and building corners start qualifying and flood the association
        # gate. Allow a genuinely closer (larger) target, keep the point-source shape tests.
        kw.setdefault("max_area", 4000)
        kw.setdefault("max_elongation", 3.2)
        kw.setdefault("max_candidates", 32)
        super().__init__(**kw)
        self.max_moment_elongation = 2.2
        self.K = K
        self.motion_enabled = motion
        self._bg = cv2.createBackgroundSubtractorMOG2(history=240, varThreshold=26,
                                                      detectShadows=False) if motion else None
        self._warm = 0
        self._prev_small: Optional[np.ndarray] = None
        self._pan = np.zeros(2, np.float32)

    # ------------------------------------------------------------------ helpers
    def _stabilise(self, small: np.ndarray) -> np.ndarray:
        """Undo camera shake before background subtraction.

        Handheld and mast-mounted cameras never hold still, and to a background model a shaking
        scene is a moving scene — every edge in the frame lights up and the real target is lost
        in the noise. A phase-correlation estimate of the frame-to-frame shift, accumulated and
        warped out, keeps the static world static so only genuinely moving things stand out.
        """
        f = small.astype(np.float32)
        if self._prev_small is not None:
            try:
                (dx, dy), _ = cv2.phaseCorrelate(self._prev_small, f)
                if abs(dx) < small.shape[1] * 0.25 and abs(dy) < small.shape[0] * 0.25:
                    self._pan += (dx, dy)
            except cv2.error:
                pass
        self._prev_small = f
        self._pan *= 0.995                      # slow bleed so drift cannot accumulate forever
        M = np.float32([[1, 0, -self._pan[0]], [0, 1, -self._pan[1]]])
        return cv2.warpAffine(small, M, (small.shape[1], small.shape[0]),
                              flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)

    def _motion_candidates(self, gray: np.ndarray, sigma: float, med_v: float) -> List[Candidate]:
        """Blobs that move against the learned static background."""
        if self._bg is None:
            return []
        small = cv2.resize(gray, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
        small = self._stabilise(small)
        mask = self._bg.apply(small, learningRate=0.02)
        self._warm += 1
        if self._warm < 12:                       # let the background model settle first
            return []
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        mask = cv2.dilate(mask, np.ones((3, 3), np.uint8), iterations=1)
        n, labels, stats, cent = cv2.connectedComponentsWithStats(mask, connectivity=8)
        if n <= 1:
            return []
        out: List[Candidate] = []
        order = np.argsort(-stats[1:, cv2.CC_STAT_AREA])[:self.MAX_MOTION_BLOBS] + 1
        for i in order:
            area = int(stats[i, cv2.CC_STAT_AREA])
            if area < 2 or area > small.size * 0.08:       # ignore specks and whole-frame shifts
                continue
            cx, cy = float(cent[i][0]) * 2.0, float(cent[i][1]) * 2.0
            bw = int(stats[i, cv2.CC_STAT_WIDTH]) * 2
            bh = int(stats[i, cv2.CC_STAT_HEIGHT]) * 2
            x0, y0 = int(max(0, cx - bw)), int(max(0, cy - bh))
            x1, y1 = int(min(gray.shape[1], cx + bw + 1)), int(min(gray.shape[0], cy + bh + 1))
            if x1 <= x0 or y1 <= y0:
                continue
            patch = gray[y0:y1, x0:x1].astype(np.float32)
            peak = float(patch.max())
            # Refine the centroid on whichever is stronger locally: a bright core, or (for a dark
            # target against sky) the darkest core — a drone silhouette is still a real target.
            bright = peak - med_v
            dark = med_v - float(patch.min())
            w = (patch - med_v) if bright >= dark else (med_v - patch)
            np.maximum(w, 0.0, out=w)
            tot = float(w.sum())
            if tot <= 1e-6:
                continue
            mom = cv2.moments(w)
            if mom["m00"] <= 1e-6:
                continue
            mx, my = x0 + mom["m10"] / mom["m00"], y0 + mom["m01"] / mom["m00"]
            snr = max(bright, dark) / max(sigma, 1e-3)
            if snr < 3.0:
                continue
            out.append(Candidate(mx, my, snr, tot, peak, area * 4, 1.0))
        return out

    # ------------------------------------------------------------------ detect
    def detect(self, image: np.ndarray, roi: Optional[Tuple[int, int, int, int]] = None) -> DetectionResult:
        gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        res = super().detect(gray, roi)
        if not self.motion_enabled:
            return res
        # Motion runs full-frame (the background model needs a consistent view) but only ever
        # *supplements*: when the frame already offers well-formed bright sources, those are what
        # a beacon looks like and adding movers would only feed the association gate more ways to
        # go wrong. Motion earns its place when brightness alone finds nothing — a dark drone
        # against cloud, a target dimmer than the street lights around it.
        t0 = cv2.getTickCount()
        strong = sum(1 for c in res.candidates if c.snr >= self.STRONG_SNR)
        if strong < self.ENOUGH_STRONG:
            med_v = float(np.median(gray[::4, ::4]))
            extra = self._motion_candidates(gray, max(res.noise_sigma, 0.5), med_v)
            if extra:
                merged = list(res.candidates)
                for c in extra:
                    if all(math.hypot(c.x - d.x, c.y - d.y) > self.MERGE_PX for d in merged):
                        merged.append(c)
                merged.sort(key=lambda c: c.snr, reverse=True)
                del merged[self.max_candidates:]
                res.candidates = merged
        else:
            self._motion_candidates(gray, max(res.noise_sigma, 0.5), 0.0)   # keep the model warm
        res.proc_ms += (cv2.getTickCount() - t0) / cv2.getTickFrequency() * 1000.0
        return res
