"""
gui/pipeline_strip.py — Visual Pipeline Strip & Alpha Badge Widget (Stage 3).

Displays the end-to-end processing pipeline at the top of the interface:
  3D WORLD → CAMERA → SENSOR → DISTURBANCES → DETECTOR → TRACKER → CONTROLLER
Dynamically highlights stages based on pipeline execution status.
Includes prominent [ ALPHA BUILD v0.3 | SIH26169 ] badge.
"""

from typing import Dict, Any
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QFont
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QFrame


class PipelineStripWidget(QFrame):
    """Horizontal banner showing data pipeline flow & system state."""

    STAGES = [
        ("3D WORLD",     "#4a9eff"),
        ("VIRT. CAMERA", "#4a9eff"),
        ("SENSOR",       "#4a9eff"),
        ("DISTURBANCE",  "#f1c40f"),
        ("DETECTOR",     "#00d2ff"),
        ("TRACKER",      "#2ecc71"),
        ("CONTROLLER",   "#9b59b6"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("pipelineStrip")
        self.setFixedHeight(36)
        self.setStyleSheet(
            "QFrame#pipelineStrip { "
            "  background-color: #0b1019; "
            "  border-bottom: 1px solid #1c2738; "
            "} "
        )
        self.sim_state: Dict[str, Any] = {}
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(6)

        # Alpha Build Badge
        self.lbl_badge = QLabel("ALPHA BUILD v0.3")
        self.lbl_badge.setStyleSheet(
            "background-color: #1f6feb; color: #ffffff; font-weight: bold; "
            "font-size: 10px; border-radius: 3px; padding: 3px 8px; letter-spacing: 0.5px;"
        )
        layout.addWidget(self.lbl_badge)

        self.lbl_sih = QLabel("SIH26169")
        self.lbl_sih.setStyleSheet(
            "background-color: #21262d; color: #8b949e; font-weight: bold; "
            "font-size: 10px; border-radius: 3px; padding: 3px 6px;"
        )
        layout.addWidget(self.lbl_sih)

        layout.addSpacing(10)

        # Stage labels
        self.stage_labels = []
        for i, (name, col) in enumerate(self.STAGES):
            lbl = QLabel(name)
            lbl.setStyleSheet(
                "color: #48546a; font-size: 10px; font-weight: 600; "
                "padding: 2px 6px; border-radius: 2px;"
            )
            layout.addWidget(lbl)
            self.stage_labels.append((lbl, col))

            if i < len(self.STAGES) - 1:
                arrow = QLabel("→")
                arrow.setStyleSheet("color: #253346; font-size: 11px; font-weight: bold;")
                layout.addWidget(arrow)

        layout.addStretch()

        # FSM state indicator on far right
        self.lbl_fsm = QLabel("STATE: SEARCH")
        self.lbl_fsm.setStyleSheet(
            "color: #ff5555; font-size: 10px; font-weight: bold; font-family: Consolas;"
        )
        layout.addWidget(self.lbl_fsm)

    def update_state(self, state: Dict[str, Any]) -> None:
        self.sim_state = state
        fsm = state.get("fsm_state", "SEARCH")
        detected = state.get("detected", False)
        is_run = state.get("is_running", True)

        # Update FSM text
        col = "#00ff88" if fsm == "LOCKED" else ("#00d2ff" if fsm == "ACQUIRING" else ("#ffaa00" if fsm == "COASTING" else "#ff5555"))
        self.lbl_fsm.setText(f"STATE: {fsm if is_run else 'PAUSED'}")
        self.lbl_fsm.setStyleSheet(f"color: {col}; font-size: 10px; font-weight: bold; font-family: Consolas;")

        # Active stage highlighting
        for i, (lbl, active_col) in enumerate(self.stage_labels):
            active = True
            if i == 3:  # DISTURBANCE
                active = True
            elif i == 4:  # DETECTOR
                active = detected
            elif i == 5:  # TRACKER
                active = fsm in ("ACQUIRING", "LOCKED", "COASTING")
            elif i == 6:  # CONTROLLER
                active = fsm in ("LOCKED", "COASTING", "SEARCH", "REACQUIRE") and is_run

            if active:
                lbl.setStyleSheet(
                    f"color: #ffffff; background-color: {active_col}33; "
                    f"border: 1px solid {active_col}; font-size: 10px; font-weight: bold; "
                    "padding: 2px 6px; border-radius: 2px;"
                )
            else:
                lbl.setStyleSheet(
                    "color: #48546a; background-color: transparent; "
                    "font-size: 10px; font-weight: 600; padding: 2px 6px; border-radius: 2px;"
                )
