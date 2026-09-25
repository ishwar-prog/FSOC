"""
gui/metrics_panel.py — Live Telemetry & Controls Panel (Stage 2 Alpha).

Displays:
  - FSM State Badge: SEARCH / ACQUIRING / LOCKED / COASTING / REACQUIRE / PAUSED
  - Primary metric card: Angular Error (° and mrad)
  - Detection & Tracking Performance:
      * Confidence, Detection Error, Processing Time
      * Acquisition Time, Lock Retention, Re-acquisition Time, Target Loss Events
      * RMSE, Max Error
  - Telemetry grid: Pan/Tilt, Tracker Centroid, Target 3D Position, FPS, Sim Time
  - Simulation controls: Start/Pause, Reset, Motion dropdown, Speed & Rate sliders
"""

from typing import Dict, Any
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QPushButton,
    QSlider,
    QComboBox,
    QCheckBox,
    QFrame,
    QGroupBox,
    QScrollArea,
)


class MetricsPanel(QWidget):
    """Control & Telemetry panel for Stage 3 FSOC Tracking Pipeline."""

    # Signals emitted to engine
    start_pause_clicked = Signal()
    reset_clicked = Signal()
    motion_changed = Signal(str)
    target_speed_changed = Signal(float)
    camera_speed_changed = Signal(float)   # max rate in deg/s
    debug_mode_changed = Signal(bool)

    # Motion mode key map
    MOTION_MODES = {
        "Circle":       "circle",
        "Figure Eight": "figure_eight",
        "Straight":     "straight",
        "Random":       "random",
    }

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

        # ── 1. Status Banner ──────────────────────────────────────────────
        self.status_frame = QFrame()
        self.status_frame.setObjectName("statusFrame")
        status_layout = QHBoxLayout(self.status_frame)
        status_layout.setContentsMargins(8, 5, 8, 5)

        status_title = QLabel("PIPELINE STATE")
        status_title.setStyleSheet("font-weight: bold; color: #8b949e; font-size: 10px;")

        self.status_badge = QLabel("SEARCH")
        self.status_badge.setObjectName("statusBadge")
        self.status_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_badge.setStyleSheet(
            "background-color: #da3633; color: #ffffff; border-radius: 4px; "
            "padding: 3px 8px; font-weight: bold; font-size: 11px;"
        )

        status_layout.addWidget(status_title)
        status_layout.addStretch()
        status_layout.addWidget(self.status_badge)
        layout.addWidget(self.status_frame)

        # ── 2. Primary Metric Card: Angular Error ─────────────────────────
        ang_card = QFrame()
        ang_card.setObjectName("errorCard")
        ang_card.setStyleSheet(
            "QFrame#errorCard { background-color: #0d1726; border: 1px solid #1f6feb; "
            "border-radius: 6px; padding: 5px; }"
        )
        ac_layout = QVBoxLayout(ang_card)
        ac_layout.setContentsMargins(6, 4, 6, 4)
        ac_layout.setSpacing(1)

        ac_title = QLabel("BORE-SIGHT ANGULAR ERROR")
        ac_title.setStyleSheet("color: #58a6ff; font-size: 9px; font-weight: bold;")

        self.val_ang_main = QLabel("0.000°")
        self.val_ang_main.setStyleSheet(
            "color: #00ff88; font-size: 18px; font-weight: bold; font-family: Consolas;"
        )

        self.val_ang_mrad = QLabel("0.0 mrad")
        self.val_ang_mrad.setStyleSheet(
            "color: #8b949e; font-size: 10px; font-family: Consolas;"
        )

        ac_layout.addWidget(ac_title)
        ac_layout.addWidget(self.val_ang_main)
        ac_layout.addWidget(self.val_ang_mrad)
        layout.addWidget(ang_card)

        # ── 3. Detection & Tracking Performance ───────────────────────────
        perf_group = QGroupBox("DETECTION & TRACKING PERFORMANCE")
        perf_group.setObjectName("telemetryGroup")
        pgrid = QGridLayout(perf_group)
        pgrid.setContentsMargins(6, 8, 6, 6)
        pgrid.setHorizontalSpacing(6)
        pgrid.setVerticalSpacing(4)

        self.val_conf     = self._create_cell(pgrid, 0, 0, "CONFIDENCE", "0.0%")
        self.val_proc_ms  = self._create_cell(pgrid, 0, 1, "PROC TIME", "0.0 ms")

        self.val_det_err  = self._create_cell(pgrid, 1, 0, "DET ERROR", "0.0 px")
        self.val_rmse     = self._create_cell(pgrid, 1, 1, "RMSE", "0.0 px")

        self.val_acq_t    = self._create_cell(pgrid, 2, 0, "ACQ TIME", "0.00 s")
        self.val_lock_ret = self._create_cell(pgrid, 2, 1, "LOCK RETENTION", "100.0%")

        self.val_loss_cnt = self._create_cell(pgrid, 3, 0, "LOSS EVENTS", "0")
        self.val_reacq_t  = self._create_cell(pgrid, 3, 1, "RE-ACQ TIME", "0.00 s")

        layout.addWidget(perf_group)

        # ── 4. Live Telemetry Grid ────────────────────────────────────────
        tel_group = QGroupBox("CAMERA & TARGET TELEMETRY")
        tel_group.setObjectName("telemetryGroup")
        grid = QGridLayout(tel_group)
        grid.setContentsMargins(6, 8, 6, 6)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(4)

        # Row 0: Camera Pan / Tilt
        self.val_pan = self._create_cell(grid, 0, 0, "CAM PAN", "0.00°")
        self.val_tilt = self._create_cell(grid, 0, 1, "CAM TILT", "0.00°")

        # Row 1: Camera Pan / Tilt Rates
        self.val_pan_rate = self._create_cell(grid, 1, 0, "PAN RATE", "0.00 °/s")
        self.val_tilt_rate = self._create_cell(grid, 1, 1, "TILT RATE", "0.00 °/s")

        # Row 2: Tracker estimate
        self.val_trk_x = self._create_cell(grid, 2, 0, "TRACK X", "320.0 px")
        self.val_trk_y = self._create_cell(grid, 2, 1, "TRACK Y", "240.0 px")

        # Row 3: Target 3D Position
        self.val_tgt_x = self._create_cell(grid, 3, 0, "TARGET X", "0.0 m")
        self.val_tgt_z = self._create_cell(grid, 3, 1, "RANGE (Z)", "1000.0 m")

        # Row 4: Control Effort & Max Error
        self.val_control_effort = self._create_cell(grid, 4, 0, "CONTROL EFFORT", "0.0 °")
        self.val_max_err = self._create_cell(grid, 4, 1, "MAX ERROR", "0.0 px")

        # Row 5: FPS / Sim Time
        self.val_fps = self._create_cell(grid, 5, 0, "FRAME RATE", "60.0 FPS")
        self.val_time = self._create_cell(grid, 5, 1, "SIM TIME", "0.00 s")

        layout.addWidget(tel_group)

        # ── 5. Simulation Controls ────────────────────────────────────────
        ctrl_group = QGroupBox("SIMULATION CONTROLS")
        ctrl_group.setObjectName("controlsGroup")
        ctrl_layout = QVBoxLayout(ctrl_group)
        ctrl_layout.setContentsMargins(6, 8, 6, 6)
        ctrl_layout.setSpacing(5)

        # Start/Pause & Reset buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        self.btn_start_pause = QPushButton("Pause")
        self.btn_start_pause.setObjectName("primaryBtn")
        self.btn_start_pause.setFixedHeight(26)
        self.btn_start_pause.clicked.connect(self.start_pause_clicked.emit)

        self.btn_reset = QPushButton("Reset")
        self.btn_reset.setObjectName("secondaryBtn")
        self.btn_reset.setFixedHeight(26)
        self.btn_reset.clicked.connect(self.reset_clicked.emit)

        btn_row.addWidget(self.btn_start_pause)
        btn_row.addWidget(self.btn_reset)
        ctrl_layout.addLayout(btn_row)

        # Motion Trajectory dropdown
        motion_box = QVBoxLayout()
        motion_box.setSpacing(1)
        motion_lbl = QLabel("Target Motion Trajectory:")
        motion_lbl.setStyleSheet("color: #8b949e; font-size: 11px;")
        self.combo_motion = QComboBox()
        self.combo_motion.addItems(list(self.MOTION_MODES.keys()))
        self.combo_motion.setFixedHeight(24)
        self.combo_motion.currentTextChanged.connect(self._on_motion_changed)
        motion_box.addWidget(motion_lbl)
        motion_box.addWidget(self.combo_motion)
        ctrl_layout.addLayout(motion_box)

        # Target Speed slider
        ctrl_layout.addLayout(
            self._make_slider_row(
                "Target Speed:", "1.0×", "tgt_speed_val_lbl",
                "slider_tgt_speed", 2, 30, 10, self._on_tgt_speed_changed,
                color="#ff7b72"
            )
        )

        # Camera Max Rate slider
        ctrl_layout.addLayout(
            self._make_slider_row(
                "Camera Max Rate:", "5.0 °/s", "cam_rate_val_lbl",
                "slider_cam_rate", 5, 200, 50, self._on_cam_rate_changed,
                color="#58a6ff"
            )
        )

        # Debug Mode toggle
        self.chk_debug = QCheckBox("Enable Diagnostic Debug Mode")
        self.chk_debug.setStyleSheet("color: #00d2ff; font-weight: bold; font-size: 11px; margin-top: 4px;")
        self.chk_debug.toggled.connect(self.debug_mode_changed.emit)
        ctrl_layout.addWidget(self.chk_debug)

        layout.addWidget(ctrl_group)
        layout.addStretch()

        scroll.setWidget(content)
        main_layout.addWidget(scroll)

    # ------------------------------------------------------------------ #
    # Helper factories
    # ------------------------------------------------------------------ #

    def _make_slider_row(
        self, label: str, default_val: str, val_attr: str, slider_attr: str,
        min_v: int, max_v: int, init_v: int, callback, color: str = "#e6edf3"
    ) -> QVBoxLayout:
        box = QVBoxLayout()
        box.setSpacing(1)
        hdr = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setStyleSheet("color: #8b949e; font-size: 10px;")
        val_lbl = QLabel(default_val)
        val_lbl.setStyleSheet(f"color: {color}; font-weight: bold; font-size: 10px;")
        setattr(self, val_attr, val_lbl)
        hdr.addWidget(lbl)
        hdr.addStretch()
        hdr.addWidget(val_lbl)

        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(min_v, max_v)
        slider.setValue(init_v)
        slider.valueChanged.connect(callback)
        setattr(self, slider_attr, slider)

        box.addLayout(hdr)
        box.addWidget(slider)
        return box

    def _create_cell(
        self, grid: QGridLayout, row: int, col: int, title: str, default_val: str
    ) -> QLabel:
        frame = QFrame()
        frame.setObjectName("metricCell")
        cell_layout = QVBoxLayout(frame)
        cell_layout.setContentsMargins(5, 3, 5, 3)
        cell_layout.setSpacing(1)

        lbl_title = QLabel(title)
        lbl_title.setStyleSheet("color: #8b949e; font-size: 8px; font-weight: bold;")
        lbl_val = QLabel(default_val)
        lbl_val.setStyleSheet(
            "color: #f0f6fc; font-size: 10px; font-weight: bold; font-family: Consolas;"
        )

        cell_layout.addWidget(lbl_title)
        cell_layout.addWidget(lbl_val)
        grid.addWidget(frame, row, col)
        return lbl_val

    # ------------------------------------------------------------------ #
    # Slot handlers
    # ------------------------------------------------------------------ #

    def _on_motion_changed(self, text: str) -> None:
        mode_key = self.MOTION_MODES.get(text, "circle")
        self.motion_changed.emit(mode_key)

    def _on_tgt_speed_changed(self, value: int) -> None:
        mult = value / 10.0
        self.tgt_speed_val_lbl.setText(f"{mult:.1f}×")
        self.target_speed_changed.emit(mult)

    def _on_cam_rate_changed(self, value: int) -> None:
        rate = value / 10.0
        self.cam_rate_val_lbl.setText(f"{rate:.1f} °/s")
        self.camera_speed_changed.emit(rate)

    # ------------------------------------------------------------------ #
    # Public update
    # ------------------------------------------------------------------ #

    def update_metrics(self, state: Dict[str, Any], fps: float) -> None:
        """Update telemetry labels from simulation state."""
        pan_d    = state.get("camera_pan_deg", 0.0)
        tilt_d   = state.get("camera_tilt_deg", 0.0)
        ang_deg  = state.get("angular_error_deg", 0.0)
        ang_mrad = state.get("angular_error_mrad", 0.0)
        tgt_x    = state.get("target_world_x", 0.0)
        tgt_z    = state.get("target_world_z", 1000.0)
        sim_t    = state.get("sim_time", 0.0)
        fsm      = state.get("fsm_state", "SEARCH")
        is_run   = state.get("is_running", True)

        # Stage 2 tracking & detection metrics
        conf     = state.get("detection_confidence", 0.0)
        proc_ms  = state.get("processing_time_ms", 0.0)
        det_err  = state.get("detection_error_px", 0.0)
        rmse     = state.get("rmse_px", 0.0)
        acq_t    = state.get("acquisition_time", 0.0)
        lock_ret = state.get("lock_retention", 1.0)
        losses   = state.get("target_loss_events", 0)
        reacq_t  = state.get("reacquisition_time", 0.0)
        trk_x    = state.get("tracker_x", 320.0)
        trk_y    = state.get("tracker_y", 240.0)

        # Primary angular error
        self.val_ang_main.setText(f"{ang_deg:.3f}°")
        self.val_ang_mrad.setText(f"{ang_mrad:.1f} mrad")

        if ang_deg <= 0.15:
            color = "#00ff88"
        elif ang_deg <= 0.6:
            color = "#f1c40f"
        else:
            color = "#ff4d4d"
        self.val_ang_main.setStyleSheet(
            f"color: {color}; font-size: 18px; font-weight: bold; font-family: Consolas;"
        )

        # Performance cells
        self.val_conf.setText(f"{conf * 100:.0f}%")
        self.val_proc_ms.setText(f"{proc_ms:.1f} ms")
        self.val_det_err.setText(f"{det_err:.1f} px")
        self.val_rmse.setText(f"{rmse:.1f} px")
        self.val_acq_t.setText(f"{acq_t:.2f} s")
        self.val_lock_ret.setText(f"{lock_ret * 100:.1f}%")
        self.val_loss_cnt.setText(str(losses))
        self.val_reacq_t.setText(f"{reacq_t:.2f} s")

        pan_rate  = state.get("pan_rate_deg_s", 0.0)
        tilt_rate = state.get("tilt_rate_deg_s", 0.0)
        effort    = state.get("control_effort", 0.0)
        max_err   = state.get("max_error_px", 0.0)

        # Telemetry cells
        self.val_pan.setText(f"{pan_d:+.2f}°")
        self.val_tilt.setText(f"{tilt_d:+.2f}°")
        self.val_pan_rate.setText(f"{pan_rate:.2f} °/s")
        self.val_tilt_rate.setText(f"{tilt_rate:.2f} °/s")
        self.val_trk_x.setText(f"{trk_x:.1f} px")
        self.val_trk_y.setText(f"{trk_y:.1f} px")
        self.val_tgt_x.setText(f"{tgt_x:.1f} m")
        self.val_tgt_z.setText(f"{tgt_z:.1f} m")
        self.val_control_effort.setText(f"{effort:.1f} °")
        self.val_max_err.setText(f"{max_err:.1f} px")
        self.val_fps.setText(f"{fps:.1f} FPS")
        self.val_time.setText(f"{sim_t:.2f} s")

        # Button label
        self.btn_start_pause.setText("Resume" if not is_run else "Pause")

        # Status badge
        if not is_run:
            self._set_badge("PAUSED", "#484f58")
        elif fsm == "LOCKED":
            self._set_badge("LOCKED ✓", "#238636")
        elif fsm == "ACQUIRING":
            self._set_badge("ACQUIRING", "#1f6feb")
        elif fsm == "COASTING":
            self._set_badge("COASTING", "#d29922")
        elif fsm == "REACQUIRE":
            self._set_badge("REACQUIRE", "#bd561d")
        else:
            self._set_badge("SEARCHING", "#da3633")

    def _set_badge(self, text: str, bg: str) -> None:
        self.status_badge.setText(text)
        self.status_badge.setStyleSheet(
            f"background-color: {bg}; color: #ffffff; border-radius: 4px; "
            "padding: 3px 8px; font-weight: bold; font-size: 11px;"
        )
