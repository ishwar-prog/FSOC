"""
simulation/beacon.py — Optical beacon point source characteristics.

The beacon is the optical signal transmitted by Terminal B that Terminal A
must acquire and track via the virtual pan/tilt camera.
"""

from dataclasses import dataclass


@dataclass
class OpticalBeacon:
    """Optical beacon point-source characteristics.

    These parameters control how the beacon appears on the sensor.
    In Stage 2, a CV detector will estimate the beacon pixel position
    from the rendered sensor frame — this class will supply that frame's rendering params.
    """

    intensity: float = 1.0      # Normalized beacon source power (0.5–2.5)
    bloom_radius: float = 16.0  # Base optical bloom radius in screen pixels
    psf_sigma: float = 6.5      # Gaussian PSF sigma in screen pixels

    def set_intensity(self, intensity: float) -> None:
        """Set beacon source power (clamped to valid range)."""
        self.intensity = max(0.3, min(3.0, float(intensity)))

    def get_effective_power(self, exposure: float = 1.0) -> float:
        """Effective detected power = source intensity × exposure gain."""
        return self.intensity * max(0.1, float(exposure))

    def get_bloom_radius(self, exposure: float = 1.0) -> float:
        """Bloom radius grows with sqrt of effective power (optical bloom physics)."""
        import math
        return self.bloom_radius * min(1.8, math.sqrt(self.get_effective_power(exposure)))

    def get_psf_radius(self, exposure: float = 1.0) -> float:
        """PSF radius for Gaussian point spread function rendering."""
        import math
        return self.psf_sigma * min(1.5, math.sqrt(self.get_effective_power(exposure)))
