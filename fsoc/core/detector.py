"""Classical beacon detector — designed for real sensor data, not just the simulator.

Stages (all O(N) OpenCV primitives, ~1–3 ms full frame, <0.5 ms in ROI mode):
  1. Optional region of interest around the tracker prediction.
  2. 3x3 median          -> removes hot/dead pixels and salt & pepper impulses.
  3. White top-hat       -> removes sky gradients, sun glare, fog veil, terrain.
  4. Gaussian matched filter (sigma ~ PSF) -> maximises point-source SNR.
  5. CFAR threshold      -> median + k * 1.4826 * MAD of the filtered image, so the
                            threshold follows the real noise floor of any camera.
  6. Connected components with shape gating -> rejects rain streaks and large glare.
  7. Intensity-weighted sub-pixel centroid on the matched-filter response.

The detector returns *all* plausible candidates with features (SNR, flux, area,
elongation). Choosing which one is the beacon is the tracker's job (gating +
multi-hypothesis acquisition), which keeps the detector generic.
"""

import math
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import cv2
import numpy as np


@dataclass
class Candidate:
    x: float
    y: float
    snr: float
    flux: float
    peak: float
    area: int
    elongation: float


@dataclass
class DetectionResult:
    candidates: List[Candidate] = field(default_factory=list)
    noise_sigma: float = 0.0
    threshold: float = 0.0
    roi: Tuple[int, int, int, int] = (0, 0, 0, 0)
    proc_ms: float = 0.0


class BeaconDetector:
    def __init__(self, k_sigma: float = 7.0, psf_sigma: float = 1.4,
                 bg_kernel: int = 15, min_area: int = 3, max_area: int = 1200,
                 max_elongation: float = 3.2, max_candidates: int = 16) -> None:
        self.k_sigma = k_sigma
        self.psf_sigma = psf_sigma
        self.min_area = min_area
        self.max_area = max_area
        self.max_elongation = max_elongation
        self.max_candidates = max_candidates
        self.max_moment_elongation = 2.2
        self._kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (bg_kernel, bg_kernel))
        self.min_threshold_dn = 5.0

    def detect(self, image: np.ndarray,
               roi: Optional[Tuple[int, int, int, int]] = None) -> DetectionResult:
        t0 = time.perf_counter()
        gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        if gray.dtype != np.uint8:
            gray = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
        H, W = gray.shape

        if roi is None:
            x0, y0, x1, y1 = 0, 0, W, H
        else:
            x0, y0 = max(0, int(roi[0])), max(0, int(roi[1]))
            x1, y1 = min(W, int(roi[2])), min(H, int(roi[3]))
            if x1 - x0 < 24 or y1 - y0 < 24:
                x0, y0, x1, y1 = 0, 0, W, H
        sub = gray[y0:y1, x0:x1]

        med = cv2.medianBlur(sub, 3)
        tophat = cv2.morphologyEx(med, cv2.MORPH_TOPHAT, self._kernel)
        mf = cv2.GaussianBlur(tophat.astype(np.float32), (0, 0), self.psf_sigma)

        sample = mf[::3, ::3]
        med_v = float(np.median(sample))
        mad = float(np.median(np.abs(sample - med_v)))
        sigma = max(0.35, 1.4826 * mad)
        thr = max(med_v + self.k_sigma * sigma, self.min_threshold_dn)

        mask = (mf > thr).astype(np.uint8)
        n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)

        cands: List[Candidate] = []
        if n > 1:
            order = np.argsort(-stats[1:, cv2.CC_STAT_AREA])[:64] + 1
            low = med_v + 1.5 * sigma
            for i in order:
                area = int(stats[i, cv2.CC_STAT_AREA])
                if area < self.min_area or area > self.max_area:
                    continue
                bx, by = int(stats[i, cv2.CC_STAT_LEFT]), int(stats[i, cv2.CC_STAT_TOP])
                bw, bh = int(stats[i, cv2.CC_STAT_WIDTH]), int(stats[i, cv2.CC_STAT_HEIGHT])
                elong = max(bw, bh) / max(1.0, min(bw, bh))
                fill = area / float(bw * bh)
                if elong > self.max_elongation or (elong > 2.0 and fill < 0.35):
                    continue
                pad = 3
                px0, py0 = max(0, bx - pad), max(0, by - pad)
                px1, py1 = min(mf.shape[1], bx + bw + pad), min(mf.shape[0], by + bh + pad)
                patch = mf[py0:py1, px0:px1]
                w = patch - low
                np.maximum(w, 0.0, out=w)
                tot = float(w.sum())
                if tot <= 1e-6:
                    continue
                ys, xs = np.mgrid[py0:py1, px0:px1]
                mx = float((w * xs).sum() / tot)
                my = float((w * ys).sum() / tot)
                # Intensity-moment elongation (rejects rain streaks / edges, keeps round PSFs).
                dx, dy = xs - mx, ys - my
                sxx = float((w * dx * dx).sum() / tot)
                syy = float((w * dy * dy).sum() / tot)
                sxy = float((w * dx * dy).sum() / tot)
                half_tr = 0.5 * (sxx + syy)
                disc = math.sqrt(max(half_tr * half_tr - (sxx * syy - sxy * sxy), 0.0))
                l2 = max(half_tr - disc, 1e-3)
                elong_m = math.sqrt((half_tr + disc) / l2)
                if elong_m > self.max_moment_elongation:
                    continue
                # Local contrast against the surrounding ring: a point source must be brighter
                # than its neighbourhood, not merely a gap between dark structures.
                peak_raw = float(med[by:by + bh, bx:bx + bw].max())
                rx0, ry0 = max(0, bx - 8), max(0, by - 8)
                rx1, ry1 = min(med.shape[1], bx + bw + 8), min(med.shape[0], by + bh + 8)
                ring = med[ry0:ry1, rx0:rx1].astype(np.float32)
                inner = np.zeros(ring.shape, bool)
                inner[max(0, by - 2 - ry0):by + bh + 2 - ry0, max(0, bx - 2 - rx0):bx + bw + 2 - rx0] = True
                ring_vals = ring[~inner]
                if ring_vals.size >= 8:
                    if peak_raw - float(np.percentile(ring_vals, 70)) < 4.0 * sigma + 5.0:
                        continue
                peak_mf = float(patch.max())
                snr = (peak_mf - med_v) / sigma
                cands.append(Candidate(mx + x0, my + y0, snr, tot, peak_raw, area, elong_m))

        cands.sort(key=lambda c: c.snr, reverse=True)
        del cands[self.max_candidates:]
        return DetectionResult(cands, sigma, thr, (x0, y0, x1, y1),
                               (time.perf_counter() - t0) * 1000.0)
