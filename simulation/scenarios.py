"""
simulation/scenarios.py — Standardized Scenario Library (Stage 3 Alpha).

Based on the SIH FSOC scenario library specification:
  S01 BASELINE          — Straight motion, slow target, clear atmosphere, zero noise
  S02 CIRCULAR          — Circular motion, medium speed, light sensor noise
  S03 FIG8_FAST         — Figure-eight, high target speed, constrained camera rate (stress test)
  S04 GAUSSIAN_NOISE    — Circular motion with elevated Gaussian sensor noise
  S05 SALT_PEPPER       — Circular motion with impulse salt-and-pepper noise
  S06 FOG               — Degraded contrast and heavy scattering blur
  S07 PLATFORM_MOTION   — Platform attitude perturbations (mount wobble)
  S08 CAMERA_JITTER     — High-frequency camera vibration (~16 px/frame)
  S09 OCCLUSION         — Periodic 0.5-second beacon dropout (coasting / reacquisition test)
  S10 DENSE_STARFIELD   — Dense celestial background generating false detection candidates
  S11 MULTI_TARGET      — 3 optical beacons (1 primary designated target + 2 distractors)
  S12 KITCHEN_SINK      — Compound multi-disturbance environment
"""

from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional


@dataclass
class ScenarioPreset:
    """Deterministic configuration preset for an evaluation scenario."""
    id: str
    name: str
    description: str
    motion_mode: str          # "straight", "circle", "figure_eight", "random"
    target_speed: float       # speed multiplier (e.g. 0.8, 1.0, 2.2)
    camera_max_rate: float    # maximum gimbal slew rate in deg/s (e.g. 5.0, 3.5)
    atmosphere: str           # "clear", "haze", "fog", "rain", "low_light"
    fog_density: float        # 0.0 - 1.0
    rain_intensity: float     # 0.0 - 1.0
    noise_level: str          # "off", "low", "medium", "high", "custom"
    noise_custom_sigma: float # Gaussian sigma if custom
    noise_custom_sp: float    # Salt & Pepper probability if custom
    turbulence: str           # "off", "low", "medium", "high"
    jitter_level: str         # "off", "low", "medium", "high", "custom"
    jitter_custom_px: float   # Custom jitter px
    platform_motion: str      # "none", "linear", "circular", "random", "figure_eight"
    platform_strength: float  # 0.0 - 1.0
    dropout: str              # "off", "0.5s", "random"
    starfield_density: str    # "sparse", "normal", "dense"
    beacon_count: int         # 1 or 3
    beacon_intensity: float   # 0.5 - 2.5


SCENARIOS: Dict[str, ScenarioPreset] = {
    "S01": ScenarioPreset(
        id="S01",
        name="S01 Baseline",
        description="Ideal baseline: straight motion, slow target, clear atmosphere, zero disturbances.",
        motion_mode="straight",
        target_speed=0.8,
        camera_max_rate=5.0,
        atmosphere="clear",
        fog_density=0.0,
        rain_intensity=0.0,
        noise_level="off",
        noise_custom_sigma=0.0,
        noise_custom_sp=0.0,
        turbulence="off",
        jitter_level="off",
        jitter_custom_px=0.0,
        platform_motion="none",
        platform_strength=0.0,
        dropout="off",
        starfield_density="sparse",
        beacon_count=1,
        beacon_intensity=1.2,
    ),
    "S02": ScenarioPreset(
        id="S02",
        name="S02 Circular",
        description="Standard nominal tracking: circular orbit, medium speed, low readout noise.",
        motion_mode="circle",
        target_speed=1.0,
        camera_max_rate=5.0,
        atmosphere="clear",
        fog_density=0.0,
        rain_intensity=0.0,
        noise_level="low",
        noise_custom_sigma=3.0,
        noise_custom_sp=0.001,
        turbulence="off",
        jitter_level="off",
        jitter_custom_px=0.0,
        platform_motion="none",
        platform_strength=0.0,
        dropout="off",
        starfield_density="normal",
        beacon_count=1,
        beacon_intensity=1.0,
    ),
    "S03": ScenarioPreset(
        id="S03",
        name="S03 Fig8 Fast",
        description="High dynamic stress: fast figure-eight trajectory with constrained camera rate (3.5 deg/s).",
        motion_mode="figure_eight",
        target_speed=2.2,
        camera_max_rate=3.5,
        atmosphere="clear",
        fog_density=0.0,
        rain_intensity=0.0,
        noise_level="low",
        noise_custom_sigma=3.0,
        noise_custom_sp=0.001,
        turbulence="off",
        jitter_level="off",
        jitter_custom_px=0.0,
        platform_motion="none",
        platform_strength=0.0,
        dropout="off",
        starfield_density="normal",
        beacon_count=1,
        beacon_intensity=1.0,
    ),
    "S04": ScenarioPreset(
        id="S04",
        name="S04 Gaussian Noise",
        description="Sensor degradation: high Gaussian sensor readout and thermal noise sweep.",
        motion_mode="circle",
        target_speed=1.0,
        camera_max_rate=5.0,
        atmosphere="clear",
        fog_density=0.0,
        rain_intensity=0.0,
        noise_level="high",
        noise_custom_sigma=20.0,
        noise_custom_sp=0.002,
        turbulence="off",
        jitter_level="off",
        jitter_custom_px=0.0,
        platform_motion="none",
        platform_strength=0.0,
        dropout="off",
        starfield_density="normal",
        beacon_count=1,
        beacon_intensity=0.9,
    ),
    "S05": ScenarioPreset(
        id="S05",
        name="S05 Salt & Pepper",
        description="Impulse noise stress: prominent salt-and-pepper dead/hot pixel artifacts.",
        motion_mode="circle",
        target_speed=1.0,
        camera_max_rate=5.0,
        atmosphere="clear",
        fog_density=0.0,
        rain_intensity=0.0,
        noise_level="custom",
        noise_custom_sigma=4.0,
        noise_custom_sp=0.015,
        turbulence="off",
        jitter_level="off",
        jitter_custom_px=0.0,
        platform_motion="none",
        platform_strength=0.0,
        dropout="off",
        starfield_density="normal",
        beacon_count=1,
        beacon_intensity=1.0,
    ),
    "S06": ScenarioPreset(
        id="S06",
        name="S06 Fog",
        description="Atmospheric degradation: heavy fog scattering, reduced contrast, and halo blur.",
        motion_mode="circle",
        target_speed=0.9,
        camera_max_rate=5.0,
        atmosphere="fog",
        fog_density=0.75,
        rain_intensity=0.0,
        noise_level="low",
        noise_custom_sigma=3.0,
        noise_custom_sp=0.0,
        turbulence="low",
        jitter_level="off",
        jitter_custom_px=0.0,
        platform_motion="none",
        platform_strength=0.0,
        dropout="off",
        starfield_density="normal",
        beacon_count=1,
        beacon_intensity=1.0,
    ),
    "S07": ScenarioPreset(
        id="S07",
        name="S07 Platform Motion",
        description="Gimbal disturbance: mobile terminal platform roll/pitch/yaw oscillations.",
        motion_mode="circle",
        target_speed=1.0,
        camera_max_rate=5.0,
        atmosphere="clear",
        fog_density=0.0,
        rain_intensity=0.0,
        noise_level="low",
        noise_custom_sigma=3.0,
        noise_custom_sp=0.0,
        turbulence="off",
        jitter_level="off",
        jitter_custom_px=0.0,
        platform_motion="random",
        platform_strength=0.65,
        dropout="off",
        starfield_density="normal",
        beacon_count=1,
        beacon_intensity=1.0,
    ),
    "S08": ScenarioPreset(
        id="S08",
        name="S08 Camera Jitter",
        description="High-frequency mechanical jitter: high amplitude (±16 px/frame) vibration disturbance.",
        motion_mode="circle",
        target_speed=1.0,
        camera_max_rate=5.0,
        atmosphere="clear",
        fog_density=0.0,
        rain_intensity=0.0,
        noise_level="low",
        noise_custom_sigma=3.0,
        noise_custom_sp=0.0,
        turbulence="off",
        jitter_level="custom",
        jitter_custom_px=16.0,
        platform_motion="none",
        platform_strength=0.0,
        dropout="off",
        starfield_density="normal",
        beacon_count=1,
        beacon_intensity=1.0,
    ),
    "S09": ScenarioPreset(
        id="S09",
        name="S09 Occlusion",
        description="Signal dropout test: repeated 0.5-second beacon dropout (tests Kalman coasting & FSM reacquisition).",
        motion_mode="circle",
        target_speed=1.0,
        camera_max_rate=5.0,
        atmosphere="clear",
        fog_density=0.0,
        rain_intensity=0.0,
        noise_level="low",
        noise_custom_sigma=3.0,
        noise_custom_sp=0.0,
        turbulence="off",
        jitter_level="off",
        jitter_custom_px=0.0,
        platform_motion="none",
        platform_strength=0.0,
        dropout="0.5s",
        starfield_density="normal",
        beacon_count=1,
        beacon_intensity=1.0,
    ),
    "S10": ScenarioPreset(
        id="S10",
        name="S10 Dense Starfield",
        description="False candidate clutter: 500 bright celestial stars generating high-density clutter blobs.",
        motion_mode="circle",
        target_speed=1.0,
        camera_max_rate=5.0,
        atmosphere="clear",
        fog_density=0.0,
        rain_intensity=0.0,
        noise_level="low",
        noise_custom_sigma=3.0,
        noise_custom_sp=0.0,
        turbulence="off",
        jitter_level="off",
        jitter_custom_px=0.0,
        platform_motion="none",
        platform_strength=0.0,
        dropout="off",
        starfield_density="dense",
        beacon_count=1,
        beacon_intensity=0.9,
    ),
    "S11": ScenarioPreset(
        id="S11",
        name="S11 Multi-Target",
        description="Multi-beacon environment: 3 active beacons (1 primary designated target + 2 distractors).",
        motion_mode="circle",
        target_speed=1.0,
        camera_max_rate=5.0,
        atmosphere="clear",
        fog_density=0.0,
        rain_intensity=0.0,
        noise_level="low",
        noise_custom_sigma=3.0,
        noise_custom_sp=0.0,
        turbulence="off",
        jitter_level="off",
        jitter_custom_px=0.0,
        platform_motion="none",
        platform_strength=0.0,
        dropout="off",
        starfield_density="normal",
        beacon_count=3,
        beacon_intensity=1.0,
    ),
    "S12": ScenarioPreset(
        id="S12",
        name="S12 Kitchen Sink",
        description="Extreme compound challenge: figure-8, haze, medium noise, jitter, platform drift, dropout, 3 beacons.",
        motion_mode="figure_eight",
        target_speed=1.4,
        camera_max_rate=5.0,
        atmosphere="haze",
        fog_density=0.4,
        rain_intensity=0.0,
        noise_level="medium",
        noise_custom_sigma=8.0,
        noise_custom_sp=0.005,
        turbulence="medium",
        jitter_level="medium",
        jitter_custom_px=8.0,
        platform_motion="random",
        platform_strength=0.4,
        dropout="0.5s",
        starfield_density="normal",
        beacon_count=3,
        beacon_intensity=1.0,
    ),
}


def get_scenario(scenario_id_or_name: str) -> Optional[ScenarioPreset]:
    """Look up a scenario preset by ID (e.g. 'S01') or full name ('S01 Baseline')."""
    clean_key = scenario_id_or_name.strip().split()[0].upper()
    return SCENARIOS.get(clean_key)


def list_scenarios() -> List[ScenarioPreset]:
    """Return all 12 scenario presets in ordered list."""
    return [SCENARIOS[f"S{i:02d}"] for i in range(1, 13)]
