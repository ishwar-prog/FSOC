"""
simulation/world.py — 3D Space Environment (Stage 1 Alpha).

Provides a 3D starfield distributed on a celestial sphere, so stars
shift naturally as the camera pans and tilts (true perspective).

Stars are stored as 3D unit direction vectors (on a unit sphere centered
at Terminal A), so camera_view.py can project them via the same pinhole
math used for the beacon and Terminal B.

Also provides faint background celestial objects (distant planet limb).
"""

import math
import random
from typing import List, Tuple, Dict, Any


class World:
    """3D space environment with stellar catalog and celestial objects.

    Stars are placed on a celestial sphere (unit direction vectors).
    They appear to rotate naturally when the camera pans/tilts —
    no special handling needed beyond the standard project_world_point() call.
    """

    # "Radius" of the celestial sphere — far enough to look like infinity
    STAR_SPHERE_RADIUS: float = 50000.0

    # Legacy 2D world bounds (kept for any residual 2D widget compatibility)
    WIDTH: float = 2000.0
    HEIGHT: float = 2000.0

    DENSITY_COUNTS = {"sparse": 60, "normal": 250, "dense": 500}
    DENSITY_BRIGHTNESS = {"sparse": 0.7, "normal": 1.0, "dense": 1.4}

    def __init__(self, num_stars: int = 250, seed: int = 42) -> None:
        self._stars_3d: List[Dict[str, Any]] = []
        self._celestial_objects_3d: List[Dict[str, Any]] = []
        self._density: str = "normal"
        self._seed: int = seed
        self._generate_stars_3d(num_stars)
        self._generate_celestial_objects_3d()

    def reset(self, seed: Optional[int] = None) -> None:
        """Regenerate world stars with optional new seed."""
        if seed is not None:
            self._seed = int(seed)
        n = self.DENSITY_COUNTS.get(self._density, 250)
        self._generate_stars_3d(n, brightness_scale=self.DENSITY_BRIGHTNESS.get(self._density, 1.0))
        self._generate_celestial_objects_3d()

    def set_starfield_density(self, density: str) -> None:
        """Change starfield density: 'sparse', 'normal', or 'dense'."""
        if density in self.DENSITY_COUNTS and density != self._density:
            self._density = density
            n = self.DENSITY_COUNTS[density]
            self._generate_stars_3d(n, brightness_scale=self.DENSITY_BRIGHTNESS[density])

    @property
    def starfield_density(self) -> str:
        return self._density

    # ------------------------------------------------------------------ #
    # Generation
    # ------------------------------------------------------------------ #

    def _generate_stars_3d(self, count: int, brightness_scale: float = 1.0) -> None:
        """Generate 3D starfield on a celestial sphere."""
        rng = random.Random(self._seed)  # Deterministic seed for reproducibility
        self._stars_3d.clear()

        for _ in range(count):
            # Uniform distribution on sphere using spherical coordinates
            # Phi: full azimuth [0, 2π], Theta: elevation [-π/2, π/2]
            phi = rng.uniform(0.0, 2.0 * math.pi)
            # Uniform area sampling (use cos(theta) pdf)
            costheta = rng.uniform(-1.0, 1.0)
            sintheta = math.sqrt(max(0.0, 1.0 - costheta * costheta))
            sign = 1.0 if costheta >= 0 else -1.0
            sintheta *= sign  # recover actual signed sin

            # 3D direction on unit sphere
            dx = sintheta * math.cos(phi)
            dy = costheta
            dz = sintheta * math.sin(phi)  # note: this puts stars all around

            # World position = direction × radius (far away)
            r = self.STAR_SPHERE_RADIUS
            wx = dx * r
            wy = dy * r
            wz = dz * r

            # Magnitude distribution
            roll = rng.random()
            if roll < 0.72:
                size = rng.uniform(0.5, 1.1)
                alpha = rng.randint(35, 90)
            elif roll < 0.95:
                size = rng.uniform(1.2, 1.8)
                alpha = rng.randint(95, 155)
            else:
                size = rng.uniform(1.9, 2.6)
                alpha = rng.randint(160, 220)

            alpha = int(min(255, alpha * brightness_scale))

            self._stars_3d.append({
                "pos": (wx, wy, wz),
                "size": size,
                "alpha": alpha,
            })

    def _generate_celestial_objects_3d(self) -> None:
        """Generate distant background celestial bodies.

        Planets/moons are placed at fixed directions on the celestial sphere.
        """
        r = self.STAR_SPHERE_RADIUS * 0.8  # Slightly closer for parallax effect

        self._celestial_objects_3d = [
            {
                "type": "planet_limb",
                # Upper-right of the +Z direction
                "pos": (r * 0.25, r * 0.12, r * 0.96),
                "angular_radius_deg": 1.2,  # Angular radius as seen from camera
                "body_color": (12, 16, 26, 180),
                "crescent_color": (130, 170, 210, 80),
            }
        ]

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def get_stars_3d(self) -> List[Dict[str, Any]]:
        """Return list of star dicts with keys: pos (3-tuple), size (float), alpha (int)."""
        return self._stars_3d

    def get_celestial_objects_3d(self) -> List[Dict[str, Any]]:
        """Return list of background celestial object dicts."""
        return self._celestial_objects_3d

    # --- Legacy 2D API (kept for world_map.py compatibility) ---

    def get_stars(self) -> List[Tuple[float, float, float, int]]:
        """Legacy 2D API: Return stars as (x, y, size, alpha) using XZ plane projection."""
        result = []
        for s in self._stars_3d:
            wx, wy, wz = s["pos"]
            # Project onto XZ plane (top-down view) scaled to 2D world bounds
            x2d = (wx / self.STAR_SPHERE_RADIUS) * (self.WIDTH / 2.0) + self.WIDTH / 2.0
            y2d = (wz / self.STAR_SPHERE_RADIUS) * (self.HEIGHT / 2.0) + self.HEIGHT / 2.0
            result.append((x2d, y2d, s["size"], s["alpha"]))
        return result

    def get_celestial_objects(self) -> List[Dict[str, Any]]:
        """Legacy 2D celestial objects for backward compat."""
        return []
