"""Physically-motivated FSOC scene simulator (implements the same Frame interface as real sources)."""

from .patterns import PATTERN_INFOS, PatternMixer
from .hazards import HAZARD_INFOS, HazardField
from .world import SimWorld, CAMERA_POS
from .renderer import SensorRenderer, Truth

__all__ = ["PATTERN_INFOS", "PatternMixer", "HAZARD_INFOS", "HazardField",
           "SimWorld", "CAMERA_POS", "SensorRenderer", "Truth"]
