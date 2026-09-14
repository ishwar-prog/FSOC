from dataclasses import dataclass, field
from typing import Any, Dict

import numpy as np


@dataclass
class Frame:
    """One timestamped sensor frame plus the gimbal pose at exposure time.

    Anything that can fill this structure (simulator, MP4 file, USB/GigE camera)
    can drive the tracking pipeline.
    """
    image: np.ndarray            # uint8, HxW mono (BGR accepted, converted by the detector)
    t: float                     # capture timestamp, seconds (monotonic)
    frame_id: int
    gimbal_az: float = 0.0       # encoder azimuth at mid-exposure, rad
    gimbal_el: float = 0.0       # encoder elevation at mid-exposure, rad
    exposure_s: float = 0.004
    meta: Dict[str, Any] = field(default_factory=dict)
