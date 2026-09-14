"""Validation suite: every beacon pattern and every hazard, scored against SIH targets.

Each case is a deterministic cold-start run. A 1.4 s forced beacon blockage is injected
mid-run so that re-acquisition is exercised in every case, not only in the occlusion one.
"""

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from ..sim.hazards import HAZARD_INFOS
from ..sim.patterns import PATTERN_INFOS
from .engine import Engine
from .evaluator import KPI_ORDER


@dataclass
class Case:
    name: str
    pattern: str
    hazards: Dict[str, float] = field(default_factory=dict)
    time_of_day: str = "day"
    group: str = "Pattern"


HAZARD_PATTERN = {
    "fog": "orbit", "rain": "flyby", "turbulence": "figure8", "noise": "zigzag",
    "vibration": "spiral", "glare": "flyby", "occlusion": "zigzag", "decoys": "orbit",
}


def default_cases() -> List[Case]:
    cases = [Case(p.name, p.key) for p in PATTERN_INFOS]
    for h in HAZARD_INFOS:
        cases.append(Case(h.name, HAZARD_PATTERN[h.key], {h.key: 0.8}, group="Hazard"))
    cases.append(Case("Night · Decoys + Noise", "random", {"decoys": 0.7, "noise": 0.5},
                      time_of_day="night", group="Compound"))
    cases.append(Case("Storm (fog+rain+shimmer+vibration)", "figure8",
                      {"fog": 0.5, "rain": 0.5, "turbulence": 0.5, "vibration": 0.5, "occlusion": 0.4},
                      group="Compound"))
    return cases


def run_case(case: Case, duration_s: float = 40.0, seed: int = 42,
             block_at: float = 20.0, block_s: float = 2.4) -> dict:
    eng = Engine(seed=seed, pattern=case.pattern)
    eng.world.time_of_day = case.time_of_day
    for key, lvl in case.hazards.items():
        eng.world.hazards.set_immediate(key, True, lvl)
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
