"""Hardware abstraction layer. Swap simulation for video or hardware without touching fsoc.core."""

from .frame import Frame
from .gimbal import GimbalInterface, GimbalState, SimulatedGimbal, StaticMount, SerialPanTiltGimbal
from .sources import FrameSource, VideoFileSource, LiveCameraSource

__all__ = [
    "Frame", "GimbalInterface", "GimbalState", "SimulatedGimbal", "StaticMount",
    "SerialPanTiltGimbal", "FrameSource", "VideoFileSource", "LiveCameraSource",
]
