"""Export real tracker data for the Remotion videos (video/public/data/).

Runs validation cases headless and writes, per case, one JSON of per-frame state,
centroid error, track position and every light's beacon probability, plus a few
sensor frames as PNG. Nothing in the videos is invented; rerun this when numbers change.
"""
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fsoc.runtime.validation import default_cases, run_case  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "video" / "public" / "data"
CASES = {
    "hover": "Drone · Hover Hold",
    "decoys": "Dim beacon · bright blinking decoys",
    "leo": "Satellite · LEO Pass",
    "storm": "Storm (fog+rain+shimmer+vibration)",
}


def r(v, n=2):
    return None if v is None else round(float(v), n)


def export(key, case, duration):
    frames, stills = [], {}
    wanted = {15, 30, 60, 90, 150}

    def on_frame(s):
        o = s.out
        frames.append({
            "t": r(s.t, 3), "state": o.state, "err": r(s.centroid_err, 3),
            "track": [r(o.track_px[0], 1), r(o.track_px[1], 1)] if o.track_px else None,
            "p": r(o.lock_p, 3), "snr": r(o.snr, 1),
            "src": [[r(x, 1), r(y, 1), r(p, 3), r(hz, 2), bool(lk)] for x, y, p, hz, lk in o.sources],
        })
        i = len(frames)
        if i in wanted:
            img = s.image
            if img.dtype != np.uint8:
                img = np.clip(img * (255.0 if img.max() <= 1.0 else 1.0), 0, 255).astype(np.uint8)
            stills[i] = img

    res = run_case(case, duration_s=duration, seed=42, on_frame=on_frame)
    metrics = {k: {"value": r(v.get("value"), 3), "status": v.get("status")} for k, v in res["metrics"].items()}
    (OUT / f"{key}.json").write_text(json.dumps({"case": case.name, "metrics": metrics, "frames": frames}))
    for i, img in stills.items():
        cv2.imwrite(str(OUT / f"{key}_{i:03d}.png"), img)
    print(f"{key}: {len(frames)} frames, passed={res['passed']}")
    return {"case": case.name, "passed": res["passed"], "metrics": metrics}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    by_name = {c.name: c for c in default_cases()}
    only = sys.argv[1:] or list(CASES)
    summary = {k: export(k, by_name[CASES[k]], 30.0) for k in only}
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
