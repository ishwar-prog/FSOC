"""
simulation/logger.py — Data Logging & Run Summary Reporter (Stage 3 Alpha).

Records per-frame simulation telemetry during active runs:
  frame, timestamp, scenario, seed, ground_truth_x, ground_truth_y,
  detected_x, detected_y, predicted_x, predicted_y, tracking_error,
  angular_error, camera_pan, camera_tilt, camera_command_pan, camera_command_tilt,
  state, confidence, processing_time

Saves runs into `logs/`:
  - `{scenario}_{timestamp}.csv`
  - `{scenario}_{timestamp}_summary.json`
"""

import os
import csv
import json
import time
from typing import Dict, Any, List, Optional
from datetime import datetime


LOG_FIELDS = [
    "frame",
    "timestamp",
    "scenario",
    "seed",
    "ground_truth_x",
    "ground_truth_y",
    "detected_x",
    "detected_y",
    "predicted_x",
    "predicted_y",
    "tracking_error",
    "angular_error",
    "camera_pan",
    "camera_tilt",
    "camera_command_pan",
    "camera_command_tilt",
    "state",
    "confidence",
    "processing_time",
]


class SimulationLogger:
    """In-memory telemetry buffer and report exporter."""

    def __init__(self, log_dir: str = "logs") -> None:
        self.log_dir = log_dir
        self.is_logging: bool = False
        self.active_scenario: str = "MANUAL"
        self.active_seed: int = 42
        self.frame_records: List[Dict[str, Any]] = []
        self._frame_counter: int = 0
        self._start_time: float = 0.0

    def start_run(self, scenario_name: str, seed: int) -> None:
        """Begin a new logging run."""
        self.active_scenario = scenario_name
        self.active_seed = seed
        self.frame_records.clear()
        self._frame_counter = 0
        self._start_time = time.time()
        self.is_logging = True

    def record_frame(self, state: Dict[str, Any], dt: float) -> None:
        """Capture one frame's telemetry snapshot."""
        if not self.is_logging:
            return

        self._frame_counter += 1

        row = {
            "frame": self._frame_counter,
            "timestamp": round(state.get("sim_time", 0.0), 4),
            "scenario": self.active_scenario,
            "seed": self.active_seed,
            "ground_truth_x": round(state.get("gt_screen_x", 320.0), 2),
            "ground_truth_y": round(state.get("gt_screen_y", 240.0), 2),
            "detected_x": round(state.get("detection_x", 320.0), 2),
            "detected_y": round(state.get("detection_y", 240.0), 2),
            "predicted_x": round(state.get("tracker_x", 320.0), 2),
            "predicted_y": round(state.get("tracker_y", 240.0), 2),
            "tracking_error": round(state.get("pixel_error_total", 0.0), 2),
            "angular_error": round(state.get("angular_error_deg", 0.0), 4),
            "camera_pan": round(state.get("camera_pan_deg", 0.0), 3),
            "camera_tilt": round(state.get("camera_tilt_deg", 0.0), 3),
            "camera_command_pan": round(state.get("cmd_pan_deg", 0.0), 4),
            "camera_command_tilt": round(state.get("cmd_tilt_deg", 0.0), 4),
            "state": state.get("fsm_state", "SEARCH"),
            "confidence": round(state.get("detection_confidence", 0.0), 3),
            "processing_time": round(state.get("processing_time_ms", 0.0), 2),
        }
        self.frame_records.append(row)

    def stop_run(self, summary_data: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, str]]:
        """Stop logging and flush records to CSV and summary JSON."""
        if not self.is_logging or not self.frame_records:
            self.is_logging = False
            return None

        self.is_logging = False
        os.makedirs(self.log_dir, exist_ok=True)

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        clean_scenario = self.active_scenario.replace(" ", "_").replace("/", "_")
        base_name = f"{clean_scenario}_{stamp}"

        csv_path = os.path.join(self.log_dir, f"{base_name}.csv")
        json_path = os.path.join(self.log_dir, f"{base_name}_summary.json")

        # 1. Write CSV
        with open(csv_path, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=LOG_FIELDS)
            writer.writeheader()
            writer.writerows(self.frame_records)

        # 2. Write Summary JSON
        report = {
            "metadata": {
                "scenario": self.active_scenario,
                "seed": self.active_seed,
                "timestamp": stamp,
                "total_frames": len(self.frame_records),
                "duration_seconds": round(
                    self.frame_records[-1]["timestamp"] - self.frame_records[0]["timestamp"], 3
                ) if len(self.frame_records) > 1 else 0.0,
            },
            "parameters": summary_data.get("parameters", {}) if summary_data else {},
            "results": summary_data.get("results", {}) if summary_data else {},
        }

        with open(json_path, mode="w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

        return {"csv_path": csv_path, "json_path": json_path}
