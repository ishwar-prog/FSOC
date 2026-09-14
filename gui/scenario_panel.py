"""
gui/scenario_panel.py — Scenario Runner & Benchmark Controller (Stage 3 Alpha).

Provides controls for:
  - Selecting and loading scenario presets S01 to S12
  - Setting and randomizing the deterministic random seed
  - Run / Stop / Reset scenario execution
  - Exporting telemetry CSV and JSON run summaries to `logs/`
  - Displaying active scenario parameters and runtime status
"""

import random
from typing import Dict, Any, List
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QComboBox, QPushButton, QSpinBox, QGroupBox,
    QFrame, QTextEdit, QMessageBox, QScrollArea,
)

from simulation.scenarios import list_scenarios, get_scenario


class ScenarioPanel(QWidget):
    """Scenario execution runner and deterministic benchmarking controller."""

    scenario_selected   = Signal(str)    # scenario_id (e.g. "S01")
    seed_changed        = Signal(int)    # seed integer
    run_scenario_clicked = Signal()
    stop_scenario_clicked = Signal()
    reset_clicked       = Signal()
    export_log_clicked  = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(8, 6, 8, 8)
        layout.setSpacing(6)

        # ── 1. Scenario Selector & Description ────────────────────────────
        scen_grp = QGroupBox("SCENARIO PRESETS (SIH FSOC LIBRARY)")
        scen_layout = QVBoxLayout(scen_grp)
        scen_layout.setContentsMargins(8, 8, 8, 8)
        scen_layout.setSpacing(5)

        self.combo_scen = QComboBox()
        self.combo_scen.setFixedHeight(26)
        presets = list_scenarios()
        for p in presets:
            self.combo_scen.addItem(f"{p.id} — {p.name[4:]}", p.id)
        self.combo_scen.currentIndexChanged.connect(self._on_scenario_changed)
        scen_layout.addWidget(self.combo_scen)

        self.lbl_desc = QLabel()
        self.lbl_desc.setWordWrap(True)
        self.lbl_desc.setStyleSheet(
            "color: #8b949e; font-size: 10px; background-color: #0b1019; "
            "border: 1px solid #1c2738; border-radius: 4px; padding: 6px;"
        )
        scen_layout.addWidget(self.lbl_desc)

        layout.addWidget(scen_grp)

        # ── 2. Random Seed Controller ─────────────────────────────────────
        seed_grp = QGroupBox("REPRODUCIBLE RANDOM SEED")
        seed_layout = QHBoxLayout(seed_grp)
        seed_layout.setContentsMargins(8, 8, 8, 8)
        seed_layout.setSpacing(6)

        lbl_s = QLabel("Seed:")
        lbl_s.setStyleSheet("color: #8b949e; font-size: 11px;")
        seed_layout.addWidget(lbl_s)

        self.spin_seed = QSpinBox()
        self.spin_seed.setRange(0, 999999)
        self.spin_seed.setValue(42)
        self.spin_seed.setFixedHeight(24)
        self.spin_seed.setStyleSheet(
            "background-color: #131b28; color: #58a6ff; font-weight: bold; "
            "border: 1px solid #25354d; border-radius: 3px; padding: 2px 5px;"
        )
        self.spin_seed.valueChanged.connect(self.seed_changed.emit)
        seed_layout.addWidget(self.spin_seed)

        self.btn_rand_seed = QPushButton("Randomize")
        self.btn_rand_seed.setObjectName("secondaryBtn")
        self.btn_rand_seed.setFixedHeight(24)
        self.btn_rand_seed.clicked.connect(self._randomize_seed)
        seed_layout.addWidget(self.btn_rand_seed)

        layout.addWidget(seed_grp)

        # ── 3. Runner Controls & Status ───────────────────────────────────
        run_grp = QGroupBox("SCENARIO EXECUTION RUNNER")
        run_layout = QVBoxLayout(run_grp)
        run_layout.setContentsMargins(8, 8, 8, 8)
        run_layout.setSpacing(6)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)

        self.btn_run = QPushButton("Run Scenario")
        self.btn_run.setObjectName("primaryBtn")
        self.btn_run.setFixedHeight(28)
        self.btn_run.clicked.connect(self.run_scenario_clicked.emit)

        self.btn_stop = QPushButton("Stop Scenario")
        self.btn_stop.setObjectName("secondaryBtn")
        self.btn_stop.setFixedHeight(28)
        self.btn_stop.clicked.connect(self.stop_scenario_clicked.emit)

        self.btn_reset = QPushButton("Reset")
        self.btn_reset.setObjectName("secondaryBtn")
        self.btn_reset.setFixedHeight(28)
        self.btn_reset.clicked.connect(self.reset_clicked.emit)

        btn_row.addWidget(self.btn_run)
        btn_row.addWidget(self.btn_stop)
        btn_row.addWidget(self.btn_reset)
        run_layout.addLayout(btn_row)

        # Status readout row
        stat_row = QHBoxLayout()
        self.lbl_run_status = QLabel("STATUS: IDLE")
        self.lbl_run_status.setStyleSheet("color: #8b949e; font-size: 10px; font-weight: bold; font-family: Consolas;")

        self.lbl_run_time = QLabel("TIME: 0.00 s")
        self.lbl_run_time.setStyleSheet("color: #8b949e; font-size: 10px; font-weight: bold; font-family: Consolas;")

        stat_row.addWidget(self.lbl_run_status)
        stat_row.addStretch()
        stat_row.addWidget(self.lbl_run_time)
        run_layout.addLayout(stat_row)

        # Export log button
        self.btn_export = QPushButton("Export Log & Summary Report (CSV / JSON)")
        self.btn_export.setObjectName("secondaryBtn")
        self.btn_export.setFixedHeight(26)
        self.btn_export.clicked.connect(self.export_log_clicked.emit)
        run_layout.addWidget(self.btn_export)

        self.lbl_log_msg = QLabel("Logs saved automatically to logs/ directory upon stopping.")
        self.lbl_log_msg.setStyleSheet("color: #6e7681; font-size: 9px; font-style: italic;")
        run_layout.addWidget(self.lbl_log_msg)

        layout.addWidget(run_grp)
        layout.addStretch()

        scroll.setWidget(content)
        main_layout.addWidget(scroll)

        # Initialize first description
        self._on_scenario_changed(0)

    def _on_scenario_changed(self, index: int) -> None:
        scen_id = self.combo_scen.currentData()
        preset = get_scenario(scen_id)
        if preset:
            self.lbl_desc.setText(
                f"<b>{preset.name}</b><br>{preset.description}<br><br>"
                f"<b>Motion:</b> {preset.motion_mode.title()} ({preset.target_speed}×) | "
                f"<b>Atmosphere:</b> {preset.atmosphere.title()} | "
                f"<b>Noise:</b> {preset.noise_level.title()} | "
                f"<b>Beacons:</b> {preset.beacon_count}"
            )
            self.scenario_selected.emit(scen_id)

    def _randomize_seed(self) -> None:
        new_seed = random.randint(1, 99999)
        self.spin_seed.setValue(new_seed)

    def update_runner_state(self, state: Dict[str, Any]) -> None:
        """Update active scenario name, time, and logging status."""
        is_run = state.get("is_running", True)
        is_log = state.get("is_logging", False)
        t = state.get("sim_time", 0.0)

        if is_log:
            self.lbl_run_status.setText("STATUS: LOGGING RUN")
            self.lbl_run_status.setStyleSheet("color: #2ea043; font-weight: bold; font-family: Consolas; font-size: 10px;")
        elif is_run:
            self.lbl_run_status.setText("STATUS: RUNNING")
            self.lbl_run_status.setStyleSheet("color: #58a6ff; font-weight: bold; font-family: Consolas; font-size: 10px;")
        else:
            self.lbl_run_status.setText("STATUS: STOPPED / IDLE")
            self.lbl_run_status.setStyleSheet("color: #8b949e; font-weight: bold; font-family: Consolas; font-size: 10px;")

        self.lbl_run_time.setText(f"TIME: {t:.2f} s")

    def show_log_saved(self, paths: Dict[str, str]) -> None:
        csv_file = paths.get("csv_path", "")
        json_file = paths.get("json_path", "")
        self.lbl_log_msg.setText(f"Saved: {csv_file}")
        self.lbl_log_msg.setStyleSheet("color: #00ff88; font-size: 9px;")
