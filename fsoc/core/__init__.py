"""Source-agnostic tracking core. Works identically on simulated, recorded or live frames."""

from .geometry import CameraIntrinsics, pixel_to_los, los_to_pixel, wrap_pi
from .detector import BeaconDetector, Candidate, DetectionResult
from .tracker import LosKalmanTracker
from .controller import GimbalController
from .pipeline import TrackingPipeline, TrackState, PipelineOutput, Cue

__all__ = [
    "CameraIntrinsics", "pixel_to_los", "los_to_pixel", "wrap_pi",
    "BeaconDetector", "Candidate", "DetectionResult",
    "LosKalmanTracker", "GimbalController",
    "TrackingPipeline", "TrackState", "PipelineOutput", "Cue",
]
