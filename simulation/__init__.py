"""Simulation modules for FSOC Beacon Tracking — Stage 3 Alpha (SIH 2026 PS SIH26169)."""

from .world import World
from .terminal import TerminalA, TerminalB
from .beacon import OpticalBeacon
from .motion import TargetMotion
from .camera import VirtualCamera3D
from .controller import CoarseAlignmentController
from .disturbances import (
    DisturbanceModel, Atmosphere, NoiseLevel, TurbulenceLevel,
    JitterLevel, PlatformMotion, Dropout
)
from .detector import BeaconDetector, DetectionResult
from .tracker import BeaconTracker, TrackerState
from .state_machine import AcquisitionFSM, TrackingState
from .search import SearchPattern
from .multi_beacon import MultiBeaconManager
from .scenarios import SCENARIOS, ScenarioPreset, get_scenario, list_scenarios
from .logger import SimulationLogger
from .engine import Stage3Engine, Stage2Engine, Stage1Engine, SimulationEngine

__all__ = [
    "World", "TerminalA", "TerminalB", "OpticalBeacon", "TargetMotion",
    "VirtualCamera3D", "CoarseAlignmentController",
    "DisturbanceModel", "Atmosphere", "NoiseLevel", "TurbulenceLevel",
    "JitterLevel", "PlatformMotion", "Dropout",
    "BeaconDetector", "DetectionResult",
    "BeaconTracker", "TrackerState",
    "AcquisitionFSM", "TrackingState",
    "SearchPattern", "MultiBeaconManager",
    "SCENARIOS", "ScenarioPreset", "get_scenario", "list_scenarios",
    "SimulationLogger",
    "Stage3Engine", "Stage2Engine", "Stage1Engine", "SimulationEngine",
]
