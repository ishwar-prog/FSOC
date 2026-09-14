"""
simulation/disturbances.py — Configurable Disturbance Model (Stage 2).

Applies frame-level and camera-level disturbances to the simulated sensor pipeline.

Frame-level effects (applied to numpy sensor frame):
  - Sensor noise: Gaussian, Poisson, Salt-and-Pepper
  - Atmospheric: CLEAR / HAZE / FOG / RAIN / LOW_LIGHT
  - Turbulence: beam wander (pixel shift) + scintillation (intensity) + blur
  - Camera jitter: global per-frame pixel offset

Camera-level effects (applied to camera orientation):
  - Platform motion: sinusoidal / random / circular / figure-eight disturbance
"""

import math
import random
import numpy as np
import cv2
from dataclasses import dataclass, field
from typing import Tuple


# ── Enum-style string constants ────────────────────────────────────────────
class Atmosphere:
    CLEAR     = "clear"
    HAZE      = "haze"
    FOG       = "fog"
    RAIN      = "rain"
    LOW_LIGHT = "low_light"


class NoiseLevel:
    OFF    = "off"
    LOW    = "low"
    MEDIUM = "medium"
    HIGH   = "high"
    CUSTOM = "custom"


class TurbulenceLevel:
    OFF    = "off"
    LOW    = "low"
    MEDIUM = "medium"
    HIGH   = "high"


class JitterLevel:
    OFF    = "off"
    LOW    = "low"
    MEDIUM = "medium"
    HIGH   = "high"
    CUSTOM = "custom"


class PlatformMotion:
    NONE        = "none"
    LINEAR      = "linear"
    CIRCULAR    = "circular"
    RANDOM      = "random"
    FIGURE_EIGHT = "figure_eight"


class Dropout:
    OFF         = "off"
    HALF_SECOND = "0.5s"
    RANDOM      = "random"


# ── Preset parameter tables ───────────────────────────────────────────────

_NOISE_PRESETS = {
    NoiseLevel.OFF:    {"gauss_sigma": 0.0,  "sp_prob": 0.0,   "poisson": False},
    NoiseLevel.LOW:    {"gauss_sigma": 3.0,  "sp_prob": 0.001, "poisson": False},
    NoiseLevel.MEDIUM: {"gauss_sigma": 8.0,  "sp_prob": 0.005, "poisson": True},
    NoiseLevel.HIGH:   {"gauss_sigma": 20.0, "sp_prob": 0.02,  "poisson": True},
}

_TURB_PRESETS = {
    TurbulenceLevel.OFF:    {"wander": 0.0, "scint": 0.0,  "blur": 0.0},
    TurbulenceLevel.LOW:    {"wander": 1.0, "scint": 0.05, "blur": 0.5},
    TurbulenceLevel.MEDIUM: {"wander": 3.0, "scint": 0.15, "blur": 1.2},
    TurbulenceLevel.HIGH:   {"wander": 8.0, "scint": 0.35, "blur": 2.5},
}

_JITTER_PRESETS = {
    JitterLevel.OFF:    0.0,
    JitterLevel.LOW:    2.0,
    JitterLevel.MEDIUM: 8.0,
    JitterLevel.HIGH:   20.0,   # per SIH spec upper reference
}

_PLATFORM_RATE = {   # max disturbance rate in degrees/s
    PlatformMotion.NONE:         0.0,
    PlatformMotion.LINEAR:       0.3,
    PlatformMotion.CIRCULAR:     1.0,
    PlatformMotion.RANDOM:       1.5,
    PlatformMotion.FIGURE_EIGHT: 1.2,
}


class DisturbanceModel:
    """All configurable disturbance effects for Stage 2.

    Usage:
        dm = DisturbanceModel()
        distorted_frame = dm.apply_frame_effects(raw_frame)
        dm.apply_camera_perturbations(camera, dt)

    Camera perturbations modify camera.pan and camera.tilt directly.
    Frame effects are applied to the numpy sensor frame in-place (returning a new array).
    """

    def __init__(self) -> None:
        # Atmospheric
        self.atmosphere: str = Atmosphere.CLEAR
        self.fog_density: float = 0.5   # 0–1
        self.rain_intensity: float = 0.5

        # Noise
        self.noise_level: str = NoiseLevel.LOW
        self.noise_custom_sigma: float = 5.0
        self.noise_custom_sp: float = 0.003

        # Turbulence
        self.turbulence: str = TurbulenceLevel.OFF

        # Jitter
        self.jitter_level: str = JitterLevel.OFF
        self.jitter_custom_px: float = 5.0

        # Platform motion
        self.platform_motion: str = PlatformMotion.NONE
        self.platform_strength: float = 0.5   # 0–1 multiplier on preset rate

        # Dropout
        self.dropout: str = Dropout.OFF
        self._dropout_active: bool = False
        self._dropout_timer: float = 0.0
        self._dropout_interval: float = 5.0   # random interval avg

        # State for time-varying effects
        self._sim_time: float = 0.0
        self._turb_rng = np.random.default_rng(1337)
        self._platform_rng = np.random.default_rng(42)
        self._platform_x: float = 0.0   # random walk state (deg)
        self._platform_y: float = 0.0

        # Procedural Rain particles cache
        self._init_rain_particles(42)

    def _init_rain_particles(self, seed: int) -> None:
        rng = np.random.default_rng(int(seed) + 300)
        self._rain_bg_x = rng.uniform(0, 640, size=100)
        self._rain_bg_y = rng.uniform(0, 480, size=100)
        self._rain_bg_len = rng.uniform(7, 14, size=100)
        self._rain_bg_alpha = rng.uniform(70, 120, size=100)

        self._rain_fg_x = rng.uniform(0, 640, size=70)
        self._rain_fg_y = rng.uniform(0, 480, size=70)
        self._rain_fg_len = rng.uniform(16, 32, size=70)
        self._rain_fg_alpha = rng.uniform(110, 180, size=70)

        self._lens_drop_x = rng.uniform(40, 600, size=12)
        self._lens_drop_y = rng.uniform(30, 450, size=12)
        self._lens_drop_r = rng.integers(5, 16, size=12)

    def set_seed(self, seed: int) -> None:
        """Seed all internal random number generators for exact reproducibility."""
        self._turb_rng = np.random.default_rng(int(seed) + 100)
        self._platform_rng = np.random.default_rng(int(seed) + 200)
        self._init_rain_particles(seed)
        self._sim_time = 0.0
        self._dropout_active = False
        self._dropout_timer = 0.0
        self._platform_x = 0.0
        self._platform_y = 0.0

    # ── Public API ─────────────────────────────────────────────────────────

    def tick(self, dt: float) -> None:
        """Advance internal timers (call once per simulation step)."""
        self._sim_time += dt

        # Manage dropout timer
        if self.dropout == Dropout.HALF_SECOND:
            self._dropout_timer += dt
            if self._dropout_active and self._dropout_timer >= 0.5:
                self._dropout_active = False
                self._dropout_timer = 0.0
            elif not self._dropout_active and self._dropout_timer >= 3.0:
                self._dropout_active = True
                self._dropout_timer = 0.0
        elif self.dropout == Dropout.RANDOM:
            self._dropout_timer += dt
            if self._dropout_active:
                if self._dropout_timer >= random.uniform(0.2, 1.5):
                    self._dropout_active = False
                    self._dropout_timer = 0.0
            else:
                if self._dropout_timer >= random.uniform(2.0, self._dropout_interval):
                    self._dropout_active = True
                    self._dropout_timer = 0.0
        else:
            self._dropout_active = False

    @property
    def beacon_occluded(self) -> bool:
        """True when target dropout is active (beacon should not be rendered)."""
        return self._dropout_active

    def apply_frame_effects(self, frame: np.ndarray) -> np.ndarray:
        """Apply all frame-level disturbances. Returns distorted uint8 BGR frame."""
        out = frame.astype(np.float32)

        # 1. Atmospheric effects
        out = self._apply_atmosphere(out)

        # 2. Turbulence (before noise so wander is clean)
        out = self._apply_turbulence(out)

        # 3. Sensor noise
        out = self._apply_noise(out)

        # 4. Jitter (global pixel shift)
        out = self._apply_jitter(out)

        return np.clip(out, 0, 255).astype(np.uint8)

    def apply_camera_perturbations(self, camera, dt: float) -> None:
        """Apply camera-level disturbances (platform motion) to pan/tilt angles."""
        if self.platform_motion == PlatformMotion.NONE:
            return

        t = self._sim_time
        s = self.platform_strength
        rate = _PLATFORM_RATE.get(self.platform_motion, 0.0) * s

        if self.platform_motion == PlatformMotion.LINEAR:
            dpan  = math.radians(rate * dt * 0.8)
            dtilt = math.radians(rate * dt * 0.3)

        elif self.platform_motion == PlatformMotion.CIRCULAR:
            dpan  = math.radians(rate * math.cos(2.0 * t) * dt)
            dtilt = math.radians(rate * math.sin(2.0 * t) * dt)

        elif self.platform_motion == PlatformMotion.FIGURE_EIGHT:
            dpan  = math.radians(rate * math.sin(t) * dt)
            dtilt = math.radians(rate * math.sin(2.0 * t) * dt * 0.5)

        elif self.platform_motion == PlatformMotion.RANDOM:
            # Low-frequency random walk
            ddx = self._platform_rng.normal(0, rate * dt * 0.5)
            ddy = self._platform_rng.normal(0, rate * dt * 0.3)
            self._platform_x = self._platform_x * 0.95 + ddx
            self._platform_y = self._platform_y * 0.95 + ddy
            dpan  = math.radians(self._platform_x * dt)
            dtilt = math.radians(self._platform_y * dt)
        else:
            return

        camera.set_pan(camera.pan + dpan)
        camera.set_tilt(camera.tilt + dtilt)

    # ── Internal effects ───────────────────────────────────────────────────

    def _apply_atmosphere(self, out: np.ndarray) -> np.ndarray:
        atm = self.atmosphere
        if atm == Atmosphere.CLEAR:
            return out

        H, W = out.shape[:2]
        t = self._sim_time

        if atm == Atmosphere.HAZE:
            d = float(self.fog_density) * 0.55
            # 1. Subtle optical blur
            out = cv2.GaussianBlur(out, (0, 0), 1.2 + d * 1.5)
            # 2. Contrast extinction
            out = out * (1.0 - d * 0.35)
            # 3. Forward-scattering optical bloom around bright spots
            bright = np.maximum(0.0, out - 40.0)
            bloom = cv2.GaussianBlur(bright, (0, 0), 12.0)
            out = out + bloom * (0.35 * d)
            # 4. Haze color veil (cool slate tint)
            veil = np.empty_like(out)
            veil[:, :, 0] = 22.0 * d  # B
            veil[:, :, 1] = 18.0 * d  # G
            veil[:, :, 2] = 14.0 * d  # R
            out = out + veil
            return np.clip(out, 0, 255)

        elif atm == Atmosphere.FOG:
            d = float(self.fog_density)
            # 1. Optical forward-scattering halo (Mie bloom)
            bright = np.maximum(0.0, out - 25.0)
            halo_inner = cv2.GaussianBlur(bright, (0, 0), 8.0 + d * 10.0)
            halo_outer = cv2.GaussianBlur(bright, (0, 0), 20.0 + d * 25.0)

            # 2. Atmospheric extinction blur
            sigma = 1.5 + d * 3.5
            out = cv2.GaussianBlur(out, (0, 0), sigma)
            out = out * (1.0 - d * 0.52)

            # Add forward-scatter optical bloom back
            out = out + halo_inner * (0.45 * d) + halo_outer * (0.35 * d)

            # 3. Volumetric rolling cloud wisps (drifting with time t)
            grid_h, grid_w = 48, 64
            gy, gx = np.mgrid[0:grid_h, 0:grid_w].astype(np.float32)
            wisp_small = (
                0.55
                + 0.28 * np.sin(gx * 0.12 + t * 0.7)
                + 0.22 * np.cos(gy * 0.16 - t * 0.5)
                + 0.15 * np.sin((gx + gy) * 0.08 + t * 0.3)
            )
            wisp = cv2.resize(wisp_small, (W, H), interpolation=cv2.INTER_LINEAR)
            wisp = np.clip(wisp, 0.2, 1.3)

            # Realistic blue-slate fog color
            fog_b = 40.0 * d * wisp
            fog_g = 34.0 * d * wisp
            fog_r = 28.0 * d * wisp

            out[:, :, 0] += fog_b
            out[:, :, 1] += fog_g
            out[:, :, 2] += fog_r

            return np.clip(out, 0, 255)

        elif atm == Atmosphere.RAIN:
            intensity = float(self.rain_intensity)
            # 1. Ambient drizzle moisture blur
            out = cv2.GaussianBlur(out, (0, 0), 0.8 + intensity * 0.8)

            # 2. Moisture contrast reduction
            out = out * (1.0 - intensity * 0.20)

            # 3. Slanted rain streaks (motion-blurred rain)
            speed_fg = 900.0  # px/s
            speed_bg = 600.0
            wind_dx = 0.25   # wind slant ~76 degrees

            # Draw background rain layer (denser, shorter, fainter)
            n_bg = int(70 * intensity)
            for i in range(n_bg):
                sx = (self._rain_bg_x[i] + t * speed_bg * wind_dx) % W
                sy = (self._rain_bg_y[i] + t * speed_bg) % H
                l = self._rain_bg_len[i]
                ex = int(sx + l * wind_dx)
                ey = int(sy + l)
                val = self._rain_bg_alpha[i]
                cv2.line(out, (int(sx), int(sy)), (ex, ey), (val, val * 1.05, val * 1.1), 1)

            # Draw foreground rain layer (longer, brighter streaks)
            n_fg = int(45 * intensity)
            for i in range(n_fg):
                sx = (self._rain_fg_x[i] + t * speed_fg * wind_dx) % W
                sy = (self._rain_fg_y[i] + t * speed_fg) % H
                l = self._rain_fg_len[i]
                ex = int(sx + l * wind_dx)
                ey = int(sy + l)
                val = self._rain_fg_alpha[i]
                cv2.line(out, (int(sx), int(sy)), (ex, ey), (val, val * 1.08, val * 1.15), 1)

            # 4. Defocused water droplets on front lens glass (bokeh spots)
            n_droplets = int(6 * intensity)
            for i in range(n_droplets):
                dx = int(self._lens_drop_x[i])
                dy = int(self._lens_drop_y[i] + t * 4.0) % H
                dr = self._lens_drop_r[i]
                # Soft transparent droplet ring
                cv2.circle(out, (dx, dy), dr, (120, 130, 140), 1)
                cv2.circle(out, (dx - 1, dy - 1), max(1, dr - 2), (60, 70, 80), -1)

            return np.clip(out, 0, 255)

        elif atm == Atmosphere.LOW_LIGHT:
            out = out * 0.32
            return out

        return out

    def _apply_turbulence(self, out: np.ndarray) -> np.ndarray:
        preset = _TURB_PRESETS.get(self.turbulence, _TURB_PRESETS[TurbulenceLevel.OFF])
        wander = preset["wander"]
        scint  = preset["scint"]
        blur   = preset["blur"]

        if wander <= 0 and scint <= 0 and blur <= 0:
            return out

        # 1. Beam wander: shift whole frame by random pixels
        if wander > 0:
            dx = int(self._turb_rng.uniform(-wander, wander))
            dy = int(self._turb_rng.uniform(-wander, wander))
            if dx != 0 or dy != 0:
                M = np.float32([[1, 0, dx], [0, 1, dy]])
                out = cv2.warpAffine(out, M, (out.shape[1], out.shape[0]))

        # 2. Scintillation: random intensity modulation
        if scint > 0:
            factor = 1.0 + self._turb_rng.uniform(-scint, scint)
            out = out * factor

        # 3. Atmospheric blur
        if blur > 0:
            out = cv2.GaussianBlur(out, (0, 0), blur)

        return out

    def _apply_noise(self, out: np.ndarray) -> np.ndarray:
        lvl = self.noise_level

        if lvl == NoiseLevel.OFF:
            return out

        if lvl == NoiseLevel.CUSTOM:
            sigma = self.noise_custom_sigma
            sp    = self.noise_custom_sp
            poisson = False
        else:
            preset = _NOISE_PRESETS.get(lvl, _NOISE_PRESETS[NoiseLevel.OFF])
            sigma   = preset["gauss_sigma"]
            sp      = preset["sp_prob"]
            poisson = preset["poisson"]

        # Gaussian noise
        if sigma > 0:
            noise = self._turb_rng.normal(0, sigma, out.shape).astype(np.float32)
            out = out + noise

        # Poisson noise (shot noise)
        if poisson and out.max() > 0:
            # Scale to photon count range and apply Poisson
            scale = 100.0
            photons = self._turb_rng.poisson(np.maximum(0, out / scale * 20).astype(int)).astype(np.float32)
            out = out * 0.85 + photons * (scale / 20) * 0.15

        # Salt and pepper
        if sp > 0:
            h, w = out.shape[:2]
            n_salt = int(sp * h * w)
            n_pepper = int(sp * h * w)
            # Salt
            ys = self._turb_rng.integers(0, h, n_salt)
            xs = self._turb_rng.integers(0, w, n_salt)
            out[ys, xs] = 255
            # Pepper
            yp = self._turb_rng.integers(0, h, n_pepper)
            xp = self._turb_rng.integers(0, w, n_pepper)
            out[yp, xp] = 0

        return out

    def _apply_jitter(self, out: np.ndarray) -> np.ndarray:
        lvl = self.jitter_level

        if lvl == JitterLevel.OFF:
            return out

        amp = (
            self.jitter_custom_px if lvl == JitterLevel.CUSTOM
            else _JITTER_PRESETS.get(lvl, 0.0)
        )
        if amp <= 0:
            return out

        dx = int(self._turb_rng.uniform(-amp, amp))
        dy = int(self._turb_rng.uniform(-amp, amp))
        if dx == 0 and dy == 0:
            return out

        M = np.float32([[1, 0, dx], [0, 1, dy]])
        return cv2.warpAffine(out, M, (out.shape[1], out.shape[0]))
