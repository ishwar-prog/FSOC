"""Hardware abstraction layer. Swap simulation for video or hardware without touching fsoc.core."""

from .frame import Frame
from .gimbal import GimbalInterface, GimbalState, SimulatedGimbal, StaticMount
from .servo import ScaledGimbal, SerialLink, ServoGeometry, ServoPanTiltGimbal
from .sources import FrameSource, VideoFileSource, LiveCameraSource

__all__ = [
    "Frame", "GimbalInterface", "GimbalState", "SimulatedGimbal", "StaticMount",
    "ServoPanTiltGimbal", "ServoGeometry", "SerialLink", "ScaledGimbal",
    "FrameSource", "VideoFileSource", "LiveCameraSource",
]
