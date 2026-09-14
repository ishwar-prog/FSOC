"""Headless validation of all beacon patterns and hazards against SIH26169 targets.

    python benchmark.py                 # full suite, 25 s per case
    python benchmark.py --duration 15 --seed 7 --only fog,orbit
"""

import argparse
import sys
import time

from fsoc.runtime.evaluator import KPI_ORDER
from fsoc.runtime.validation import default_cases, run_case

ICON = {"pass": "PASS", "fail": "FAIL", "pending": "....", "standby": " -- "}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--duration", type=float, default=40.0)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--only", type=str, default="")
    args = ap.parse_args()

    cases = default_cases()
    if args.only:
        keys = [k.strip().lower() for k in args.only.split(",")]
        cases = [c for c in cases if c.pattern in keys or any(k in c.name.lower() for k in keys)
                 or any(k in c.hazards for k in keys)]

    hdr = f"{'Case':38s} {'Acq s':>7s} {'Err px':>7s} {'Loss %':>7s} {'Reacq s':>8s} {'Cap FPS':>8s}  Result"
    print(hdr)
    print("-" * len(hdr))
    all_ok = True
    t0 = time.perf_counter()
    for c in cases:
        r = run_case(c, args.duration, args.seed)
        s, m = r["summary"], r["metrics"]

        def f(v, fmt):
            return fmt.format(v) if v is not None else "  —"
        flags = " ".join(f"{k[:4]}:{ICON[m[k]['status']]}" for k in KPI_ORDER[:4] if m[k]["status"] == "fail")
        print(f"{c.name[:38]:38s} {f(s['acquisition_time_s'], '{:7.2f}')} "
              f"{f(s['tracking_error_mean_px'], '{:7.2f}')} {f(s['target_loss_pct'], '{:7.2f}')} "
              f"{f(s['reacquisition_worst_s'], '{:8.2f}')} {f(s['processing_capacity_fps'], '{:8.0f}')}  "
              f"{'PASS' if r['passed'] else 'FAIL ' + flags}   ({s['wall_time_s']:.1f}s)")
        all_ok &= r["passed"]
        sys.stdout.flush()
    print(f"\n{'ALL CASES PASS' if all_ok else 'SOME CASES FAIL'}  in {time.perf_counter() - t0:.0f} s")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
