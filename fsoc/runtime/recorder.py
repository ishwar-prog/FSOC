"""Per-frame telemetry recorder with CSV + JSON summary export."""

import csv
import json
import math
import os
import sys
import threading
from collections import deque
from datetime import datetime
from typing import Dict, Optional

FIELDS = ["t", "frame", "state", "meas_x", "meas_y", "truth_x", "truth_y", "track_x", "track_y",
          "centroid_err_px", "pointing_err_px", "track_los_err_px", "snr", "confidence", "candidates",
          "gimbal_az_deg", "gimbal_el_deg", "range_m", "occluded", "render_ms", "detect_ms", "track_ms"]


def default_log_dir() -> str:
    base = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.getcwd()
    path = os.path.join(base, "logs")
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, ".probe")
        with open(probe, "w") as f:
            f.write("")
        os.remove(probe)
        return path
    except OSError:
        path = os.path.join(os.path.expanduser("~"), "Documents", "FSOC_Tracker_logs")
        os.makedirs(path, exist_ok=True)
        return path


def _r(v, n=3):
    return "" if v is None else round(v, n)


class Recorder:
    MAX_ROWS = 60 * 30 * 30   # 30 minutes at 30 FPS

    def __init__(self) -> None:
        self._rows = deque(maxlen=self.MAX_ROWS)
        self._lock = threading.Lock()

    def clear(self) -> None:
        with self._lock:
            self._rows.clear()

    def add(self, out, truth, ev, stage_ms) -> None:
        m = out.measurement or (None, None)
        tr = truth.target_px or (None, None)
        tk = out.track_px or (None, None)
        row = (round(out.t, 4), out.frame_id, out.state, _r(m[0], 2), _r(m[1], 2), _r(tr[0], 2), _r(tr[1], 2),
               _r(tk[0], 2), _r(tk[1], 2), _r(ev.last_centroid_err), _r(ev.last_pointing_err, 2),
               _r(ev.last_track_sep_px, 2), round(out.snr, 1), round(out.confidence, 3), len(out.candidates),
               round(math.degrees(out_gaz(out, truth)), 4), round(math.degrees(truth.cam_el), 4),
               round(truth.range_m, 1), int(truth.occluded), round(stage_ms[0], 2), round(stage_ms[1], 2),
               round(stage_ms[2], 2))
        with self._lock:
            self._rows.append(row)

    def export(self, name: str, summary: Dict, directory: Optional[str] = None) -> Dict[str, str]:
        directory = directory or default_log_dir()
        os.makedirs(directory, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = os.path.join(directory, f"{name}_{stamp}")
        with self._lock:
            rows = list(self._rows)
        with open(base + ".csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(FIELDS)
            w.writerows(rows)
        with open(base + "_summary.json", "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)
        return {"csv": base + ".csv", "json": base + "_summary.json"}


def out_gaz(out, truth) -> float:
    return truth.cam_az
