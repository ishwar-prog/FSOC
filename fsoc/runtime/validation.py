"""Validation suite: every terminal type and pattern, every hazard, beacon identification
under clutter — scored against the SIH targets.

Each case is a deterministic cold-start run. A 2.4 s forced beacon blockage is injected
mid-run so that re-acquisition is exercised in every case.
"""

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from ..sim.hazards import HAZARD_INFOS
from .engine import Engine
from .evaluator import KPI_ORDER


@dataclass
class Case:
    name: str
    pattern: str
    hazards: Dict[str, float] = field(default_factory=dict)
    time_of_day: Optional[str] = None
    group: str = "Pattern"
    brightness: Optional[float] = None
    mount: str = "fixed"
    speed: float = 1.0


PATTERN_CASES = [
    ("Drone · Hover Hold", "hover"), ("Aircraft · Linear Flyby", "flyby"), ("Aircraft · Circular Orbit", "orbit"),
    ("Aircraft · Figure-Eight", "figure8"), ("Drone · Zig-Zag Evasive", "zigzag"),
    ("Drone · Spiral Approach", "spiral"), ("Ship · Maritime Sway", "maritime"), ("Ship · Transit", "transit"),
    ("Drone · Random Manoeuvre", "random"), ("Satellite · LEO Pass", "leo_pass"),
    ("Satellite · GEO Relay", "geo_relay"), ("Space station · ISS Pass", "iss_pass"),
]

HAZARD_PATTERN = {
    "fog": "orbit", "rain": "flyby", "turbulence": "figure8", "noise": "zigzag",
    "vibration": "spiral", "glare": "flyby", "occlusion": "zigzag", "decoys": "orbit",
}


def default_cases() -> List[Case]:
    cases = [Case(name, key) for name, key in PATTERN_CASES]
    for h in HAZARD_INFOS:
        cases.append(Case(h.name, HAZARD_PATTERN[h.key], {h.key: 0.8}, group="Hazard"))
    cases += [
        Case("Dim beacon · bright blinking decoys", "hover", {"decoys": 1.0}, group="Identity", brightness=0.12),
        Case("Night · Decoys + Noise", "random", {"decoys": 0.7, "noise": 0.5}, time_of_day="night",
             group="Identity"),
        Case("LEO pass · dense satellites + shimmer", "leo_pass", {"decoys": 1.0, "turbulence": 0.5},
             group="Identity"),
        Case("ISS pass at dusk · sun-lit body", "iss_pass", {"occlusion": 0.4}, time_of_day="dusk", group="Identity"),
        Case("Vehicle-mounted terminal A", "figure8", {"vibration": 0.3}, group="Terminal", mount="vehicle"),
        Case("Ship-to-ship · deck mount", "transit", {"turbulence": 0.4}, group="Terminal", mount="ship"),
        Case("Fast aircraft · 2× speed", "flyby", {}, group="Terminal", speed=2.0),
        Case("Storm (fog+rain+shimmer+vibration)", "figure8",
             {"fog": 0.5, "rain": 0.5, "turbulence": 0.5, "vibration": 0.5, "occlusion": 0.4}, group="Compound"),
    ]
    return cases


def run_case(case: Case, duration_s: float = 40.0, seed: int = 42,
             block_at: float = 20.0, block_s: float = 2.4) -> dict:
    eng = Engine(seed=seed, pattern=case.pattern)
    if case.time_of_day:
        eng.world.time_of_day = case.time_of_day
    for key, lvl in case.hazards.items():
        eng.world.hazards.set_immediate(key, True, lvl)
    if case.brightness is not None:
        eng.world.beacon.brightness = case.brightness
    if case.mount != "fixed":
        eng.world.ground.set_mount(-10.0, case.mount)
    if case.speed != 1.0:
        eng.world.remote.warp._seg = [(0.0, 0.0, case.speed, case.speed)]
    events = {block_at: lambda e: e.world.hazards.force_block(block_at, block_s)}
    res = eng.run_headless(duration_s, events)
    passed = all(res["metrics"][k]["status"] in ("pass", "standby") for k in KPI_ORDER)
    res.update(case=case, passed=passed)
    return res


def run_suite(cases: Optional[List[Case]] = None, duration_s: float = 25.0, seed: int = 42,
              progress: Optional[Callable[[int, int, dict], None]] = None,
              should_stop: Optional[Callable[[], bool]] = None) -> List[dict]:
    cases = cases or default_cases()
    results = []
    for i, c in enumerate(cases):
        if should_stop and should_stop():
            break
        r = run_case(c, duration_s, seed)
        results.append(r)
        if progress:
            progress(i + 1, len(cases), r)
    return results
