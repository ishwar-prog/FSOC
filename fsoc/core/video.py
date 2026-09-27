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


class EgoMotion:
    """Estimate the camera's own rotation from the image, for footage with no gimbal encoders.

    On a real gimbal the tracker knows where the camera points and works in line-of-sight
    angles, so a pan does not move the target in its world. A handheld or vehicle recording has
    no encoders: when the camera pans, *every* light slides across the frame and a static-camera
    tracker loses its target instantly. Phase correlation of successive frames (band-passed so
    it keys on the star field / scene texture, not on smooth glow or smoke) measures that global
    shift; accumulated and converted to angles it stands in for the missing encoder, so the
    identical tracker keeps working through pans and shake.
    """

    MIN_RESPONSE = 0.06                 # below this the correlation peak is not trustworthy
    SCALE = 0.5

    def __init__(self, fx: float, fy: float) -> None:
        self.fx, self.fy = fx, fy
        self.reset()

    MAX_ACCEL = 8.0                     # per-frame change of shift a real pan can make (1/2-res px)
    MAX_GAP = 6                         # frames to wait for clean video before re-anchoring

    def reset(self) -> None:
        self._prev = None
        self._win = None
        self._v = (0.0, 0.0)           # last accepted per-frame shift (1/2-res px)
        self._gap = 1                  # frames since the reference frame was taken
        self.dx = self.dy = 0.0        # accumulated image shift, full-resolution pixels

    def update(self, gray: np.ndarray):
        """Return the accumulated (az, el) of the camera in radians.

        Real footage has glitch frames — compression tearing, a dropped field, a flash — on which
        phase correlation returns a large, bogus shift. A camera has inertia: a genuine pan builds
        up and dies away over several frames, it does not jump. A shift whose change from the
        previous one is physically implausible is rejected, and the *last good* frame is kept as
        the reference, so the next clean frame is measured against it and nothing is lost.
        """
        s = self.SCALE
        small = cv2.resize(gray, None, fx=s, fy=s, interpolation=cv2.INTER_AREA).astype(np.float32)
        band = small - cv2.GaussianBlur(small, (0, 0), 6.0)
        if self._win is None or self._win.shape != band.shape:
            self._win = cv2.createHanningWindow((band.shape[1], band.shape[0]), cv2.CV_32F)
        if self._prev is None:
            self._prev = band
        else:
            (sx, sy), resp = cv2.phaseCorrelate(self._prev, band, self._win)
            lim = 0.2 * band.shape[1]
            g = self._gap
            ok = resp >= self.MIN_RESPONSE and abs(sx) < lim and abs(sy) < lim
            if ok:
                ex, ey = self._v[0] * g, self._v[1] * g          # what inertia predicts
                ok = math.hypot(sx - ex, sy - ey) <= self.MAX_ACCEL * g
            if ok:
                self.dx += sx / s
                self.dy += sy / s
                self._v = (sx / g, sy / g)
                self._prev, self._gap = band, 1
            elif g >= self.MAX_GAP:
                # clean video never came back in time: accept the new view as the reference
                # (a genuine cut); the tracker's own gating handles whatever jump that implies
                self._prev, self._gap, self._v = band, 1, (0.0, 0.0)
            else:
                self._gap += 1
        # scene moves left (dx < 0) when the camera turns right (azimuth up); image y is down
        return -self.dx / self.fx, self.dy / self.fy


class VideoBeaconDetector(BeaconDetector):
    MERGE_PX = 6.0                     # candidates closer than this are the same light
    # Keep a compact, much brighter point that sits off-centre inside a larger detection: a
    # distinct light (an LED in front of a lit wall), not the same object at a coarser scale.
    # Off by default: the recorded-video results were validated without it.
    KEEP_EMBEDDED = False
    # One light, one detection. A close, saturated beacon is found as several fragments (edge
    # pieces at full resolution, the whole blob at 1/4 scale) whose centres differ by pixels and
    # which trade places frame to frame — the track hops between them and its blink history is
    # lost with every hop. When set, each light's bright region is traced on the full image, the
    # fragments inside it are folded into one, and its centre is the region's own centroid.
    # Off by default: the recorded-video results were validated without it.
    CONSOLIDATE = False
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
        kw.setdefault("max_area", 2500)          # per pyramid level; 1/4 scale covers ~40,000 px
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
    PYRAMID = (2, 4)                   # extra scales: a beacon 40 px across is a point at 1/4

    def _multiscale(self, gray: np.ndarray, res: DetectionResult) -> None:
        """Scale-space detection.

        The point-source stages (top-hat, matched filter, shape tests) are tuned for a spot a
        few pixels across. A real beacon filmed up close, or blooming on a phone sensor, can be
        tens of pixels wide: the top-hat hollows it into a ring and the shape tests reject what
        is left, so the most obvious light in the frame is never even offered to the tracker.
        Running the same detector on a 1/2 and 1/4 image pyramid finds every source at the
        scale where it *is* a point; results are mapped back and de-duplicated, keeping the
        strongest response for each physical light.
        """
        allc = [(c, 1) for c in res.candidates]
        for s in self.PYRAMID:
            small = cv2.resize(gray, (gray.shape[1] // s, gray.shape[0] // s), interpolation=cv2.INTER_AREA)
            if min(small.shape) < 48:
                continue
            sub = BeaconDetector.detect(self, small, None)
            for c in sub.candidates:
                allc.append((Candidate(c.x * s + (s - 1) / 2.0, c.y * s + (s - 1) / 2.0, c.snr,
                                       c.flux * s * s, c.peak, c.area * s * s, c.elongation), s))
        allc.sort(key=lambda cs: cs[0].snr, reverse=True)
        kept: List[Candidate] = []
        for c, s in allc:
            r_new = 0.6 * math.sqrt(max(c.area, 1))
            if all(self._distinct(c, k, r_new) for k in kept):
                kept.append(c)
        del kept[self.max_candidates:]
        if self.CONSOLIDATE:
            kept = self._consolidate(gray, kept)
        res.candidates = kept

    def _consolidate(self, gray: np.ndarray, cands: List[Candidate]) -> List[Candidate]:
        out: List[Candidate] = []
        regions = []                                  # (x0, y0, mask) of each light already kept
        for c in cands:                               # strongest first
            if any(self._inside(c, reg) for reg in regions):
                continue                              # a fragment of a light already kept
            if c.area < 20:
                out.append(c)
                continue
            got = self._region(gray, c)
            if got is None:
                out.append(c)
                continue
            out.append(got[0])
            regions.append(got[1])
        return out

    @staticmethod
    def _inside(c: Candidate, reg) -> bool:
        x0, y0, mask = reg
        ix, iy = int(round(c.x)) - x0, int(round(c.y)) - y0
        h, w = mask.shape
        return bool(mask[max(0, iy - 3):min(h, iy + 4), max(0, ix - 3):min(w, ix + 4)].any())

    @staticmethod
    def _region(gray: np.ndarray, c: Candidate):
        """The light's bright region: connected pixels above half-maximum, holding the peak.
        The window grows until the region no longer touches its border."""
        h, w = gray.shape[:2]
        r = int(max(8, 1.3 * math.sqrt(c.area)))
        while True:
            x0, y0 = max(0, int(c.x) - r), max(0, int(c.y) - r)
            x1, y1 = min(w, int(c.x) + r + 1), min(h, int(c.y) + r + 1)
            patch = gray[y0:y1, x0:x1].astype(np.float32)
            bg, pk = float(np.percentile(patch, 20)), float(patch.max())
            if pk - bg < 8.0:
                return None
            thr = bg + 0.5 * (pk - bg)
            _n, lab = cv2.connectedComponents((patch >= thr).astype(np.uint8), connectivity=8)
            py, px = np.unravel_index(int(np.argmax(patch)), patch.shape)
            mask = lab == lab[py, px]
            touches = (mask[0].any() and y0 > 0) or (mask[-1].any() and y1 < h)                 or (mask[:, 0].any() and x0 > 0) or (mask[:, -1].any() and x1 < w)
            if not touches or r >= 200:
                break
            r *= 2
        wgt = mask * (patch - thr)
        tot = float(wgt.sum())
        if tot <= 0:
            return None
        ys, xs = np.mgrid[0:patch.shape[0], 0:patch.shape[1]]
        cx = x0 + float((wgt * xs).sum()) / tot
        cy = y0 + float((wgt * ys).sum()) / tot
        area = float(mask.sum())
        flux = float((mask * (patch - bg)).sum())
        return Candidate(cx, cy, c.snr, flux, pk, area, c.elongation), (x0, y0, mask)

    def _distinct(self, c: Candidate, k: Candidate, r_new: float) -> bool:
        d = math.hypot(c.x - k.x, c.y - k.y)
        rk = math.sqrt(max(k.area, 1))
        if d > max(self.MERGE_PX, r_new + 0.6 * rk):
            return True
        # k must not be saturated itself: then c is a hot spot in the same light's own glow
        return (self.KEEP_EMBEDDED and c.area <= 0.1 * k.area and c.peak > 1.5 * k.peak
                and k.peak < 150.0 and d > max(self.MERGE_PX, 0.3 * rk))

    def detect(self, image: np.ndarray, roi: Optional[Tuple[int, int, int, int]] = None) -> DetectionResult:
        gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        res = super().detect(gray, None)      # full frame: a pyramid needs the whole view anyway
        t0 = cv2.getTickCount()
        self._multiscale(gray, res)
        res.proc_ms += (cv2.getTickCount() - t0) / cv2.getTickFrequency() * 1000.0
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
