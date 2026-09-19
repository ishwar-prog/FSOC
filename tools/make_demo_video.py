"""Generate realistic real-world test footage for the video-input mode.

These are NOT the narrow-field NIR frames the simulator renders. They are what a phone or
security camera actually produces: a wide field of view, a textured daylight or night scene,
handheld shake, rolling auto-exposure, H.264 compression, and a beacon that is only a few
pixels across — plus the distractors that break naive "find the brightest pixel" detectors
(sun glint off windows, street lights, car headlights, birds, lens flare).

    python tools/make_demo_video.py                 # writes every clip to demo_videos/
    python tools/make_demo_video.py --only day_drone

Each clip is written with a sidecar <name>_truth.csv (frame, x, y, visible) so the tracker can
be scored honestly against a known answer.
"""

import argparse
import csv
import math
import os

import cv2
import numpy as np

W, H, FPS = 1280, 720, 30
# OpenCV's bundled mp4v encoder is not frugal; a 12 s clip is already plenty to acquire, hold
# and demonstrate a re-acquisition, and keeps each file to a sane size.
DEFAULT_SECONDS = 12.0
OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "demo_videos")


def _fbm(h, w, rng, octaves=5, base=4):
    """Fractal noise for cloud / terrain texture."""
    out = np.zeros((h, w), np.float32)
    amp, tot = 1.0, 0.0
    for o in range(octaves):
        gh, gw = max(2, base << o), max(2, (base << o) * w // h)
        g = rng.random((gh, gw)).astype(np.float32)
        out += amp * cv2.resize(g, (w, h), interpolation=cv2.INTER_CUBIC)
        tot += amp
        amp *= 0.5
    return out / max(tot, 1e-6)


def _skyline(w, rng):
    """A city skyline / treeline silhouette height profile."""
    prof = np.zeros(w, np.float32)
    x = 0
    while x < w:
        bw = rng.integers(40, 150)
        bh = rng.integers(40, 230)
        prof[x:x + bw] = bh
        x += bw + int(rng.integers(0, 40))
    prof = cv2.GaussianBlur(prof.reshape(1, -1), (0, 0), 1.5).ravel()
    return prof


class Scene:
    """One synthetic but photo-realistic scene with a moving beacon and real distractors."""

    def __init__(self, name: str, night: bool, seed: int = 7, blink_hz: float = 5.0,
                 beacon_px: float = 2.2, duration_s: float = 20.0, glare: bool = False,
                 decoys: bool = True, shake: float = 1.0) -> None:
        self.name, self.night, self.blink_hz = name, night, blink_hz
        self.beacon_px, self.duration_s, self.glare, self.decoys = beacon_px, duration_s, glare, decoys
        self.shake = shake
        self.rng = np.random.default_rng(seed)
        r = self.rng
        self.clouds = _fbm(H, W * 2, r, octaves=6, base=3)
        self.ground_tex = _fbm(H, W * 2, r, octaves=6, base=8)
        self.prof = _skyline(W * 2, r)
        self.horizon = int(H * 0.62)
        # static scene lights (windows, street lamps) — steady, not beacons
        n = 26 if night else 10
        self.lights = [(float(r.integers(0, W)), float(self.horizon + r.integers(5, H - self.horizon - 5)),
                        float(r.uniform(0.35, 1.0))) for _ in range(n)]
        # a second blinking light at a *different* rate — the classic false positive
        self.rival = (W * 0.22, self.horizon - 40.0, 1.6 if blink_hz < 7 else 9.0)
        self.birds = [(float(r.uniform(0, W)), float(r.uniform(60, self.horizon - 40)),
                       float(r.uniform(18, 40)), float(r.uniform(0, 6.28))) for _ in range(3)]

    # ---------------------------------------------------------------- geometry
    def beacon_xy(self, t: float):
        """Drone crossing the sky: smooth arc, a little wander, always well above the skyline."""
        u = t / self.duration_s
        x = W * (0.12 + 0.76 * u) + 26 * math.sin(2 * math.pi * 0.23 * t)
        y = H * 0.30 - 90 * math.sin(math.pi * u) + 14 * math.sin(2 * math.pi * 0.31 * t + 1.0)
        return x, y

    def shake_xy(self, t: float):
        s = self.shake
        return (s * (7.0 * math.sin(2 * math.pi * 0.17 * t) + 1.6 * math.sin(2 * math.pi * 3.1 * t)),
                s * (5.0 * math.sin(2 * math.pi * 0.23 * t + 1.0) + 1.2 * math.sin(2 * math.pi * 4.7 * t)))

    # ------------------------------------------------------------------ render
    def background(self, ox: float, oy: float, t: float) -> np.ndarray:
        """Sky gradient + drifting clouds + skyline silhouette + ground texture, panned by shake."""
        x0 = int(W * 0.5 + ox + 8 * t) % W
        sky_top, sky_bot = (14, 34) if self.night else (96, 188)
        img = np.linspace(sky_top, sky_bot, H, dtype=np.float32)[:, None].repeat(W, 1)
        cl = self.clouds[:, x0:x0 + W]
        img += (16.0 if self.night else 52.0) * np.clip(cl - 0.45, 0, 1) * 2.0
        prof = self.prof[x0:x0 + W]
        gt = self.ground_tex[:, x0:x0 + W]
        yy = np.arange(H, dtype=np.float32)[:, None]
        hor = self.horizon + oy * 0.5
        top = hor - prof[None, :]
        solid = (yy >= top).astype(np.float32)
        solid = cv2.GaussianBlur(solid, (0, 0), 0.8)
        ground = (18.0 if self.night else 62.0) + (10.0 if self.night else 34.0) * gt
        img = img * (1 - solid) + ground * solid
        return img

    def frame(self, t: float):
        ox, oy = self.shake_xy(t)
        img = self.background(ox, oy, t)
        r = self.rng

        def splat(x, y, energy, sigma):
            """Add a point source with a realistic PSF + bloom."""
            if not (-30 < x < W + 30 and -30 < y < H + 30):
                return
            rad = int(max(3, sigma * 4))
            x0, x1 = max(0, int(x) - rad), min(W, int(x) + rad + 1)
            y0, y1 = max(0, int(y) - rad), min(H, int(y) + rad + 1)
            if x1 <= x0 or y1 <= y0:
                return
            gx = np.arange(x0, x1, dtype=np.float32) - x
            gy = np.arange(y0, y1, dtype=np.float32)[:, None] - y
            img[y0:y1, x0:x1] += energy * np.exp(-(gx * gx + gy * gy) / (2 * sigma * sigma))

        # scene lights (steady), rival blinker, birds
        for (lx, ly, li) in self.lights:
            sway = 0.0 if self.night else 0.0
            splat(lx + ox * 0.9 + sway, ly + oy * 0.9, (150 if self.night else 60) * li, 1.6)
        rx, ry, rhz = self.rival
        if (t * rhz) % 1.0 < 0.5:
            splat(rx + ox * 0.9, ry + oy * 0.9, 190 if self.night else 110, 1.9)
        for (bx, by, bs, bp) in self.birds:
            px = (bx + bs * t) % (W + 80) - 40
            py = by + 12 * math.sin(2 * math.pi * 0.7 * t + bp)
            splat(px + ox, py + oy, -60 if not self.night else -20, 2.2)     # dark bird against sky

        if self.glare:
            sx, sy = W * 0.80 + ox, H * 0.16 + oy
            splat(sx, sy, 900, 26)
            splat(sx, sy, 420, 9)
            for k in (0.35, 0.6, 0.85):                                      # lens flare ghosts
                splat(W * 0.5 + (sx - W * 0.5) * -k, H * 0.5 + (sy - H * 0.5) * -k, 70, 12)

        # the beacon itself
        bx, by = self.beacon_xy(t)
        on = True if self.blink_hz <= 0 else ((t * self.blink_hz) % 1.0 < 0.5)
        peak = (230.0 if self.night else 300.0)
        if on:
            splat(bx + ox, by + oy, peak, self.beacon_px)
            splat(bx + ox, by + oy, peak * 0.12, self.beacon_px * 3.5)       # faint halo
        vis = 1 if on else 0

        # sensor: vignetting, auto-exposure drift, shot+read noise, 8-bit clipping
        vig = 1.0 - 0.22 * (((np.arange(W) - W / 2) / (W / 2)) ** 2)[None, :] \
                  - 0.18 * (((np.arange(H) - H / 2) / (H / 2)) ** 2)[:, None]
        img *= vig
        img *= 1.0 + 0.04 * math.sin(2 * math.pi * 0.11 * t)                 # AE breathing
        img = np.clip(img, 0, None)
        img += r.normal(0, 2.0 + (3.0 if self.night else 0.0), img.shape).astype(np.float32)
        img += np.sqrt(np.clip(img, 0, None)) * r.normal(0, 0.35, img.shape).astype(np.float32)
        out = np.clip(img, 0, 255).astype(np.uint8)
        return out, (bx + ox, by + oy, vis)


def render(scene: Scene, out_dir: str) -> str:
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, scene.name + ".mp4")
    vw = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W, H), isColor=True)
    rows = []
    n = int(scene.duration_s * FPS)
    for i in range(n):
        t = i / FPS
        gray, (bx, by, vis) = scene.frame(t)
        bgr = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
        # mild chroma so it looks like a real colour camera, then H.264-ish compression damage
        bgr[:, :, 0] = np.clip(bgr[:, :, 0] * 1.06, 0, 255)
        bgr[:, :, 2] = np.clip(bgr[:, :, 2] * 0.97, 0, 255)
        vw.write(bgr)
        rows.append((i, round(bx, 2), round(by, 2), vis))
    vw.release()
    with open(path.replace(".mp4", "_truth.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["frame", "x", "y", "visible"])
        w.writerows(rows)
    return path


SCENES = {
    "day_drone":     dict(night=False, blink_hz=5.0, glare=False, beacon_px=2.2),
    "day_glare":     dict(night=False, blink_hz=6.5, glare=True, beacon_px=2.0, seed=11),
    "night_city":    dict(night=True, blink_hz=4.0, glare=False, beacon_px=2.4, seed=23),
    "steady_beacon": dict(night=False, blink_hz=0.0, glare=False, beacon_px=2.2, seed=31),
    "tiny_far":      dict(night=False, blink_hz=8.0, glare=False, beacon_px=1.3, seed=41),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--out", default=OUT_DIR)
    ap.add_argument("--duration", type=float, default=DEFAULT_SECONDS)
    args = ap.parse_args()
    names = [n.strip() for n in args.only.split(",") if n.strip()] or list(SCENES)
    for name in names:
        cfg = dict(SCENES[name])
        cfg.setdefault("seed", 7)
        p = render(Scene(name, duration_s=args.duration, **cfg), args.out)
        print("wrote", p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
