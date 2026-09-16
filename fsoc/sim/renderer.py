"""NIR (850 nm) sensor renderer — produces the same Frame a real camera would.

Image formation, in physical order:
  background radiance (sky gradient, drifting clouds, terrain / sea with aerial perspective)
  -> fog/rain transmission and path-radiance veil
  -> point sources: beacon (modulated, 1/R^2, transmission, scintillation, beam wander,
     motion blur, forward-scatter halo) and any sun-lit spacecraft body; decoy lights;
     for space targets a rotating star field, other satellites and a planet; sun disk
  -> occluders, rain streaks, lens droplets, blur (turbulence / scattering)
  -> veiling glare and ghosts -> vignetting
  -> sensor: shot noise, read noise, row banding, hot pixels, quantisation, saturation.
Ground truth for scoring is returned separately and never enters the pipeline.
"""

import math
from dataclasses import dataclass
from typing import Optional, Tuple

import cv2
import numpy as np

from ..core.geometry import CameraIntrinsics, direction_to_pixel, los_to_direction
from ..io.frame import Frame
from .world import SimWorld

DEG = math.pi / 180.0
RAD2DEG = 180.0 / math.pi
E_REF = 1400.0 * 2 * math.pi * 1.3 ** 2        # reference point source: 1400 DN peak

AMBIENT = {
    #          zenith, horizon, clouds, ground, ground_tex, exposure_s
    "day":   (38.0, 80.0, 30.0, 26.0, 9.0, 0.003),
    "dusk":  (13.0, 34.0, 9.0, 8.0, 3.0, 0.006),
    "night": (2.5, 6.0, 1.5, 1.5, 0.8, 0.010),
}


@dataclass
class Truth:
    t: float
    target_px: Optional[Tuple[float, float]]
    in_fov: bool
    occluded: bool
    occlusion_kind: str
    target_los: Tuple[float, float]
    range_m: float
    cam_az: float
    cam_el: float
    beacon_peak_dn: float
    beacon_on: bool = True


def _fractal_noise(h: int, w: int, rng: np.random.Generator, octaves=5, base=6) -> np.ndarray:
    out = np.zeros((h, w), np.float32)
    amp, total = 1.0, 0.0
    for o in range(octaves):
        gh, gw = max(2, base * 2 ** o * h // w + 2), max(2, base * 2 ** o + 2)
        g = rng.random((gh, gw)).astype(np.float32)
        out += amp * cv2.resize(g, (w, h), interpolation=cv2.INTER_CUBIC)
        total += amp
        amp *= 0.5
    out /= total
    out -= out.min()
    out /= max(1e-6, out.max())
    return out


def _unit(p, c):
    dx, dy, dz = p[0] - c[0], p[1] - c[1], p[2] - c[2]
    n = math.sqrt(dx * dx + dy * dy + dz * dz) or 1.0
    return dx / n, dy / n, dz / n


class SensorRenderer:
    CLOUD_PPD = 12.0
    CLOUD_EL_TOP = 40.0
    GROUND_PPD = 6.0
    GROUND_EL_TOP = 2.0

    def __init__(self, K: CameraIntrinsics, world: SimWorld, gimbal, seed: int = 42) -> None:
        # cv2.randn() (used below for shot/read noise) draws from OpenCV's own C++-level RNG,
        # which is process-global and keeps advancing across every SensorRenderer that has ever
        # existed in this process — not reset just because a new instance was constructed. Left
        # alone, two runs of the identical (seed, pattern, hazards) case render different noise
        # depending on how many earlier renders happened first in this process, which a nonlinear
        # gated tracker can amplify into a completely different outcome. Seeding it explicitly
        # here makes every render deterministic in `seed` alone, matching every other RNG in this
        # class.
        cv2.setRNGSeed(int(seed) * 2654435761 % (2 ** 31))
        self.K = K
        self.world = world
        self.gimbal = gimbal
        self.frame_id = 0
        H, W = K.height, K.width
        self._u_off = ((np.arange(W, dtype=np.float32) - K.cx) / K.fx)
        self._v_off = ((K.cy - np.arange(H, dtype=np.float32)) / K.fy)
        self._noise_buf = np.empty((H, W), np.float32)
        self._layer = np.zeros((H, W), np.float32)
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        r2 = ((xx - K.cx) / K.cx) ** 2 + ((yy - K.cy) / K.cy) ** 2
        self._vignette = (1.0 - 0.14 * r2).astype(np.float32)
        self._fov_radius_deg = 0.5 * math.hypot(K.hfov_deg, K.vfov_deg) + 0.3
        self.build_textures(seed)

    def build_textures(self, seed: int) -> None:
        rng = np.random.default_rng(seed + 424242)
        cw = int(360 * self.CLOUD_PPD)
        ch = int((self.CLOUD_EL_TOP + 10) * self.CLOUD_PPD)
        c = _fractal_noise(ch, cw, rng, octaves=6, base=45)
        self._clouds = (np.clip((c - 0.36) * 1.9, 0, 1) ** 1.3).astype(np.float32)
        gw = int(360 * self.GROUND_PPD)
        gh = int((self.GROUND_EL_TOP + 12) * self.GROUND_PPD)
        g = _fractal_noise(gh, gw, rng, octaves=6, base=40)
        self._ground = (g - 0.5).astype(np.float32)
        n = 18000
        hills = _fractal_noise(1, n, rng, octaves=7, base=60)[0]
        self._hz_step = 360.0 / n
        self._horizon = (0.15 + 1.05 * hills ** 1.6).astype(np.float32) * DEG
        self._hot_idx = rng.permutation(self.K.width * self.K.height)[:int(0.006 * self.K.width * self.K.height)]
        self._hot_val = rng.uniform(90, 255, self._hot_idx.size).astype(np.float32)
        self._rng = np.random.default_rng(seed + 77)
        rs = np.random.default_rng(seed + 313)
        self._rain = rs.random((260, 4)).astype(np.float32)
        self._drops = rs.random((8, 3)).astype(np.float32)

    def reseed(self, seed: int) -> None:
        cv2.setRNGSeed(int(seed) * 2654435761 % (2 ** 31))
        self._rng = np.random.default_rng(seed + 77)

    # ------------------------------------------------------------------ render
    def render(self, t: float) -> Tuple[Frame, Truth]:
        K, world, hz = self.K, self.world, self.world.hazards
        H, W = K.height, K.width
        hz.advance(t)
        tod = world.time_of_day
        amb = AMBIENT[tod]
        exposure = amb[5]
        cam = world.camera_pos(t)

        g_az, g_el, g_raz, g_rel = self.gimbal.true_pose(t)
        v_daz, v_del, v_raz, v_rel = hz.vibration(t)
        j_az, j_el = world.ground.residual_jitter(t)
        cam_az, cam_el = g_az + v_daz + j_az, g_el + v_del + j_el
        enc = self.gimbal.read_state(t)

        sea = world.remote.info.platform == "ship"
        img = self._background(cam_az, cam_el, t, amb, sea)

        beta = hz.fog_beta_per_km()
        beta_rain = hz.rain_beta_per_km()
        if beta > 0:
            tb = math.exp(-beta * 3.0)
            mean = float(img.mean())
            img = mean + (img - mean) * (0.15 + 0.85 * tb)
            img += (1 - tb) * amb[1] * 1.05
        if beta_rain > 0:
            img *= 1.0 - 0.18 * hz.level("rain")
            img += 6.0 * hz.level("rain") * (amb[1] / 80.0)

        aoa_x, aoa_y, scint, turb_blur = hz.turbulence()
        psf = math.hypot(1.3, turb_blur)
        space = world.space_scene
        # the atmosphere only extends ~10 km for extinction purposes
        atm_km_target = lambda r_km: min(r_km, 8.0) if space else r_km

        # ---- sky clutter for space targets (stars, satellites, planet)
        if space and tod != "day":
            self._stars(img, t, cam_az, cam_el, psf, exposure, beta + beta_rain, hz.level("turbulence"), tod)
            for oaz, oel, rel in world.space_objects(t, cam_az, cam_el):
                p = direction_to_pixel(los_to_direction(oaz, oel), cam_az, cam_el, K)
                if p is not None and -20 < p[0] < W + 20 and -20 < p[1] < H + 20:
                    self._splat(img, p[0], p[1], E_REF * 3.0 * 0.35 * rel * math.exp(-(beta + beta_rain) * 8.0),
                                psf, (0, 0), 0)

        # ---- beacon (+ sun-lit spacecraft body at the same place)
        rng_m = world.target_range(t)
        tpos = world.target_pos(t)
        tdir = _unit(tpos, cam)
        occ, occ_kind, occ_phase = hz.occlusion(t)
        truth_px = direction_to_pixel(tdir, cam_az, cam_el, K)
        r_km = rng_m / 1000.0
        trans = math.exp(-(beta + beta_rain) * atm_km_target(r_km))
        on = world.beacon.modulation(t) > 0.5
        energy = E_REF * world.beacon_scale(t, rng_m) * trans * scint * (1.0 - occ)
        body = E_REF * world.body_glint(t, rng_m) * trans * (1.0 - occ)
        peak_dn = 0.0
        if truth_px is not None:
            u, v = truth_px[0] + aoa_x, truth_px[1] + aoa_y
            vel_px = self._image_velocity(t, tpos, cam, cam_az, cam_el, g_raz + v_raz, g_rel + v_rel)
            peak_dn = self._splat(img, u, v, energy + body, psf, vel_px, exposure)
            if beta > 0:
                self._splat(img, u, v, (energy + body) / max(trans, 1e-3) * (1 - trans) * 0.10,
                            10 + 30 * hz.level("fog"), (0, 0), 0)
            self._splat(img, u, v, (energy + body) * 0.02, 6.0, (0, 0), 0)
            if occ > 0.01:
                self._draw_occluder(img, u, v, occ, occ_kind, occ_phase, amb)

        # ---- ground / sea decoys
        for pos, inten in world.decoys(t):
            d = _unit(pos, cam)
            p = direction_to_pixel(d, cam_az, cam_el, K)
            if p is None or not (-40 < p[0] < W + 40 and -40 < p[1] < H + 40):
                continue
            rk = math.dist(pos, cam) / 1000.0
            e = E_REF * 4.0 * inten / max(rk, 0.3) ** 2 * math.exp(-(beta + beta_rain) * rk)
            self._splat(img, p[0], p[1], e, psf, (0, 0), 0)

        # ---- sun disk
        sun = world.sun_direction(t)
        sp = direction_to_pixel(sun, cam_az, cam_el, K)
        sun_r = 0.265 * DEG * K.fx
        if tod != "night" and not space and sp is not None \
                and -sun_r * 3 < sp[0] < W + sun_r * 3 and -sun_r * 3 < sp[1] < H + sun_r * 3:
            dim = 1.0 - 0.9 * max(hz.level("fog"), hz.level("rain"))
            if tod == "dusk":
                dim *= 0.5
            cv2.circle(img, (int(sp[0]), int(sp[1])), int(sun_r), 300.0 + 2200.0 * dim, -1, cv2.LINE_AA)
            self._splat(img, sp[0], sp[1], 90.0 * dim * 2 * math.pi * (sun_r * 0.9) ** 2, sun_r * 0.9, (0, 0), 0)

        lr = hz.level("rain")
        if lr > 0.01:
            self._rain_layer(img, t, lr, amb)

        blur = 0.35 * hz.level("fog") + 0.5 * turb_blur + 0.5 * lr
        if blur > 0.15:
            img = cv2.GaussianBlur(img, (0, 0), blur)

        lg = hz.level("glare")
        if lg > 0.01 and not space:
            self._glare(img, sun, cam_az, cam_el, lg, amb)

        img *= self._vignette

        read, hot_frac, row_sig, flick = hz.noise_params()
        np.maximum(img, 0, out=img)
        img += 2.0
        sig = cv2.sqrt(img * 0.06 + read * read)
        cv2.randn(self._noise_buf, 0.0, 1.0)
        img += self._noise_buf * sig
        if row_sig > 0.05:
            img += (self._rng.standard_normal(H).astype(np.float32) * row_sig)[:, None]
        flat = img.reshape(-1)
        nhot = int(hot_frac * flat.size) + 24
        idx = self._hot_idx[:nhot]
        flat[idx] = np.maximum(flat[idx], self._hot_val[:nhot])
        if flick > 0:
            n = int(flick * flat.size)
            flat[self._rng.integers(0, flat.size, n)] = 255.0
            flat[self._rng.integers(0, flat.size, n)] = 0.0
        np.clip(img, 0, 255, out=img)
        image = img.astype(np.uint8)

        self.frame_id += 1
        frame = Frame(image, t, self.frame_id, enc.az, enc.el, exposure)
        in_fov = truth_px is not None and 0 <= truth_px[0] < W and 0 <= truth_px[1] < H
        truth = Truth(t, truth_px, in_fov, occ >= 0.5, occ_kind, world.target_los(t),
                      rng_m, cam_az, cam_el, min(255.0, peak_dn), on)
        return frame, truth

    # --------------------------------------------------------------- helpers
    def _stars(self, img, t, cam_az, cam_el, psf, exposure, beta, turb, tod) -> None:
        K = self.K
        H, W = img.shape
        dirs, mags, tw = self.world.stars().in_view(t, cam_az, cam_el, self._fov_radius_deg)
        if mags.size == 0:
            return
        keep = mags < (8.6 if tod == "night" else 6.0)
        dirs, mags = dirs[keep], mags[keep]
        sig = 0.06 + 0.35 * turb
        gains = np.exp(sig * self._rng.standard_normal(mags.size) - 0.5 * sig * sig)
        ext = math.exp(-beta * 8.0)
        base = E_REF * 3.0 * (exposure / 0.010) * ext
        for d, m, g in zip(dirs, mags, gains):
            p = direction_to_pixel((float(d[0]), float(d[1]), float(d[2])), cam_az, cam_el, K)
            if p is None or not (-8 < p[0] < W + 8 and -8 < p[1] < H + 8):
                continue
            self._splat(img, p[0], p[1], base * 10 ** (-0.4 * (float(m) - 1.5)) * float(g), psf, (0, 0), 0)

    def _image_velocity(self, t, tpos, cam, cam_az, cam_el, raz, rel):
        h = 0.002
        p2 = self.world.target_pos(t + h)
        c2 = self.world.camera_pos(t + h)
        a = direction_to_pixel(_unit(tpos, cam), cam_az, cam_el, self.K)
        b = direction_to_pixel(_unit(p2, c2), cam_az + raz * h, cam_el + rel * h, self.K)
        if a is None or b is None:
            return (0.0, 0.0)
        return ((b[0] - a[0]) / h, (b[1] - a[1]) / h)

    def _background(self, cam_az, cam_el, t, amb, sea: bool) -> np.ndarray:
        K = self.K
        H, W = K.height, K.width
        zen, hor, cloud_amp, g0, gtex = amb[:5]
        ce = max(0.2, math.cos(cam_el))
        az_deg = cam_az * RAD2DEG
        el_deg = cam_el * RAD2DEG

        el_rows = cam_el + self._v_off
        sky_rows = zen + (hor - zen) * np.exp(-np.maximum(el_rows, 0.0) / 0.16)

        ppd = self.CLOUD_PPD
        drift = t * 0.02
        a = ppd * RAD2DEG / (K.fx * ce)
        el_top = min(self.CLOUD_EL_TOP, 49.0)
        M = np.float32([[a, 0, (az_deg + 180.0 + drift) * ppd - a * K.cx],
                        [0, ppd * RAD2DEG / K.fy, (el_top - el_deg) * ppd - ppd * RAD2DEG / K.fy * K.cy]])
        clouds = cv2.warpAffine(self._clouds, M, (W, H), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                                borderMode=cv2.BORDER_REFLECT)
        sky = (sky_rows[:, None] + cloud_amp * clouds).astype(np.float32, copy=False)

        col_az = (az_deg + self._u_off * RAD2DEG / ce)
        if sea:
            h_cols = np.full(W, -0.07 * DEG, np.float32)
        else:
            idx = ((col_az + 180.0) / self._hz_step).astype(np.int64) % self._horizon.size
            h_cols = self._horizon[idx]
        below = np.nonzero(el_rows < float(h_cols.max()) + 1.0 / K.fy)[0]
        if below.size == 0:
            return sky
        r0 = int(below[0])
        er = el_rows[r0:]
        depth = h_cols[None, :] - er[:, None]
        wground = np.clip(depth * K.fy + 0.5, 0.0, 1.0)

        gp = self.GROUND_PPD
        a2 = gp * RAD2DEG / (K.fx * ce)
        c2 = gp * RAD2DEG / K.fy
        M2 = np.float32([[a2, 0, (az_deg + 180.0) * gp - a2 * K.cx],
                         [0, c2, (self.GROUND_EL_TOP - el_deg) * gp - c2 * K.cy + c2 * r0]])
        tex = cv2.warpAffine(self._ground, M2, (W, H - r0), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                             borderMode=cv2.BORDER_REFLECT)
        if sea:
            rows = np.arange(r0, H, dtype=np.float32)[:, None]
            waves = 0.5 + 0.5 * np.sin(rows * 0.9 + t * 3.0 + tex * 9.0)
            ground = g0 * 1.2 + gtex * (0.6 * tex + 0.4 * waves)
        else:
            ground = g0 + gtex * 2.0 * tex
        persp = np.exp(-np.maximum(depth, 0.0) / (0.5 * DEG))
        ground = ground + (hor * 0.85 - ground) * persp
        sky[r0:] += (ground - sky[r0:]) * wground
        return sky

    def _splat(self, img, u, v, energy, sigma, vel_px, exposure) -> float:
        if energy <= 0.5:
            return 0.0
        H, W = img.shape
        bx, by = vel_px[0] * exposure, vel_px[1] * exposure
        blur_len = math.hypot(bx, by)
        n = 1 if blur_len < 1.0 else min(28, 1 + int(math.ceil(blur_len)))
        r = int(3.5 * sigma + blur_len / 2 + 2)
        x0, x1 = max(0, int(u) - r), min(W, int(u) + r + 2)
        y0, y1 = max(0, int(v) - r), min(H, int(v) + r + 2)
        if x1 <= x0 or y1 <= y0:
            return 0.0
        xs = np.arange(x0, x1, dtype=np.float32)
        ys = np.arange(y0, y1, dtype=np.float32)
        peak = energy / (2 * math.pi * sigma * sigma) / n
        inv = 1.0 / (2 * sigma * sigma)
        patch = np.zeros((y1 - y0, x1 - x0), np.float32)
        for k in range(n):
            f = (k / (n - 1) - 0.5) if n > 1 else 0.0
            cx, cy = u + bx * f, v + by * f
            gx = np.exp(-((xs - cx) ** 2) * inv)
            gy = np.exp(-((ys - cy) ** 2) * inv)
            patch += np.outer(gy, gx) * peak
        img[y0:y1, x0:x1] += patch
        return float(patch.max())

    def _draw_occluder(self, img, u, v, occ, kind, phase, amb):
        H, W = img.shape
        R = 50
        x0, y0 = int(u) - R, int(v) - R
        cx0, cy0, cx1, cy1 = max(0, x0), max(0, y0), min(W, x0 + 2 * R), min(H, y0 + 2 * R)
        if cx1 <= cx0 or cy1 <= cy0:
            return
        m = np.zeros((2 * R, 2 * R), np.float32)
        cc = R
        if kind in ("bird", "manual"):
            ox = cc + (phase - 0.5) * 14
            oy = cc + 1.5 * math.sin(phase * 18)
            flap = 3.5 * math.sin(phase * 25)
            pts = np.array([[ox - 15, oy - 4 - flap], [ox - 7, oy - 1], [ox, oy + 2],
                            [ox + 7, oy - 1], [ox + 15, oy - 4 - flap]], np.int32)
            cv2.polylines(m, [pts], False, 1.0, 5, cv2.LINE_AA)
            cv2.circle(m, (int(ox), int(oy + 1)), 6, 1.0, -1, cv2.LINE_AA)
            level, target = 1.0, amb[3] * 0.4
        elif kind == "branch":
            ox = cc + (phase - 0.5) * 20
            cv2.line(m, (int(ox - 40), cc - 32), (int(ox + 30), cc + 34), 1.0, 10, cv2.LINE_AA)
            cv2.line(m, (int(ox - 2), cc + 2), (int(ox + 30), cc - 22), 1.0, 5, cv2.LINE_AA)
            cv2.circle(m, (int(ox + 2), cc + 3), 8, 1.0, -1, cv2.LINE_AA)
            level, target = 1.0, amb[3] * 0.4
        else:
            cv2.circle(m, (cc, cc), 42, 1.0, -1)
            level, target = 0.75, amb[1] * 0.85
        m = cv2.GaussianBlur(m, (0, 0), 1.2 if kind != "cloud" else 10.0)
        region = img[cy0:cy1, cx0:cx1]
        mm = m[cy0 - y0:cy1 - y0, cx0 - x0:cx1 - x0] * (occ * level)
        region += (target - region) * mm

    def _rain_layer(self, img, t, level, amb):
        H, W = img.shape
        n = int(230 * level)
        bright = 6.0 + 16.0 * (amb[1] / 80.0)
        wind = 0.22
        layer = self._layer
        layer.fill(0.0)
        for i in range(n):
            rx, ry, rl, rs = (float(x) for x in self._rain[i])
            speed = 700 + 900 * rs
            length = 10 + 26 * rl
            y = (ry * H + speed * t) % (H + length) - length
            x = (rx * W + speed * wind * t) % W
            cv2.line(layer, (int(x), int(y)), (int(x + length * wind), int(y + length)),
                     bright * (0.4 + rs), 1, cv2.LINE_AA)
        img += layer
        for i in range(int(6 * level)):
            dx, dy, dr = (float(x) for x in self._drops[i])
            cx, cy = int(dx * W), int((dy * H + t * 6.0) % H)
            r = int(12 + 20 * dr)
            x0, x1, y0, y1 = max(0, cx - r - 4), min(W, cx + r + 4), max(0, cy - r - 4), min(H, cy + r + 4)
            if x1 - x0 < 8 or y1 - y0 < 8:
                continue
            roi = img[y0:y1, x0:x1]
            yy, xx = np.ogrid[y0:y1, x0:x1]
            m = np.clip((r - np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)) / 3.0, 0, 1).astype(np.float32) * 0.85
            blurred = cv2.GaussianBlur(roi, (0, 0), 4.0) * 1.04 + 3.0
            roi += (blurred - roi) * m

    def _glare(self, img, sun, cam_az, cam_el, level, amb):
        K = self.K
        H, W = img.shape
        f, r, up = _basis(cam_az, cam_el)
        zc = sun[0] * f[0] + sun[1] * f[1] + sun[2] * f[2]
        if zc < 0.2:
            return
        sx = (sun[0] * r[0] + sun[1] * r[1] + sun[2] * r[2]) / zc
        sy = (sun[0] * up[0] + sun[1] * up[1] + sun[2] * up[2]) / zc
        gw, gh = 80, 60
        xs = ((np.arange(gw, dtype=np.float32) + 0.5) * (W / gw) - K.cx) / K.fx
        ys = (K.cy - (np.arange(gh, dtype=np.float32) + 0.5) * (H / gh)) / K.fy
        d2 = (xs[None, :] - sx) ** 2 + (ys[:, None] - sy) ** 2
        th0 = 2.5 * DEG
        strength = 260.0 * level * (1.0 if amb[1] > 20 else 0.4)
        field = strength * th0 * th0 / (d2 + th0 * th0)
        su, sv = K.cx + K.fx * sx, K.cy - K.fy * sy
        ghosts = np.zeros_like(field)
        for k, rad, val in ((-0.45, 3.0, 16.0), (-0.9, 5.0, 11.0), (-1.4, 2.0, 20.0)):
            gx = (K.cx + (su - K.cx) * k) / (W / gw)
            gy = (K.cy + (sv - K.cy) * k) / (H / gh)
            if -10 < gx < gw + 10 and -10 < gy < gh + 10:
                cv2.circle(ghosts, (int(gx), int(gy)), int(rad), val * level, -1, cv2.LINE_AA)
        field += cv2.GaussianBlur(ghosts, (0, 0), 0.9)
        img += cv2.resize(field, (W, H), interpolation=cv2.INTER_CUBIC)


def _basis(az, el):
    ca, sa, ce, se = math.cos(az), math.sin(az), math.cos(el), math.sin(el)
    return (ce * sa, se, ce * ca), (ca, 0.0, -sa), (-se * sa, ce, -se * ca)
