"""
gui/reference_panel.py — SIH Reference Targets Comparison Panel (Stage 3 Alpha).

Compares actual measured performance against SIH Reference Targets:
  - Acquisition Time    Target ≤ 2.0 s
  - Tracking Error      Target ≤ 10.0 px
  - Target Loss Rate    Target < 5.0 %
  - Re-acquisition Time Target ≤ 1.0 s
  - Processing Rate     Target ≥ 20.0 FPS

Evaluations are computed honestly using internal ground-truth.
If the system fails a benchmark target, it is displayed as FAIL.
"""

from typing import Dict, Any
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QLabel, QGroupBox, QFrame
)


class ReferenceTargetsPanel(QGroupBox):
    """SIH Benchmark Targets vs Actual Performance Comparison Panel."""

    ROWS = [
        ("acquisition_time",   "Acquisition Time",    "≤ 2.0 s"),
        ("tracking_error",     "Tracking Error (Avg)","≤ 10.0 px"),
        ("target_loss",        "Target Loss Rate",    "< 5.0 %"),
        ("reacquisition_time", "Re-acquisition Time", "≤ 1.0 s"),
        ("processing_fps",     "Processing Rate",     "≥ 20.0 FPS"),
    ]

    def __init__(self, parent=None):
        super().__init__("SIH REFERENCE BENCHMARKS (HONEST EVALUATION)", parent)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 8, 6, 6)
        layout.setSpacing(4)

        # Explanatory note
        note = QLabel("Reference values from SIH FSOC specification. Evaluated honestly without cosmetic masking.")
        note.setStyleSheet("color: #6e7681; font-size: 9px; font-style: italic;")
        layout.addWidget(note)

        # Table
        self.table = QTableWidget(len(self.ROWS), 4)
        self.table.setHorizontalHeaderLabels(["Metric", "Target", "Actual", "Status"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setStyleSheet(
            "QTableWidget { background-color: #0b1019; border: 1px solid #1e2638; border-radius: 4px; gridline-color: #192434; font-size: 10px; } "
            "QHeaderView::section { background-color: #131b28; color: #8b949e; font-size: 9px; font-weight: bold; border: none; padding: 3px; } "
            "QTableWidget::item { padding: 3px; font-family: Consolas; } "
        )

        for row, (key, label, ref_val) in enumerate(self.ROWS):
            item_lbl = QTableWidgetItem(label)
            item_lbl.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            item_lbl.setForeground(Qt.GlobalColor.white)

            item_ref = QTableWidgetItem(ref_val)
            item_ref.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item_ref.setForeground(Qt.GlobalColor.gray)

            item_act = QTableWidgetItem("—")
            item_act.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item_act.setForeground(Qt.GlobalColor.white)

            item_stat = QTableWidgetItem("PENDING")
            item_stat.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item_stat.setForeground(Qt.GlobalColor.gray)

            self.table.setItem(row, 0, item_lbl)
            self.table.setItem(row, 1, item_ref)
            self.table.setItem(row, 2, item_act)
            self.table.setItem(row, 3, item_stat)

        layout.addWidget(self.table)

    def update_evaluation(self, eval_dict: Dict[str, Dict[str, Any]]) -> None:
        """Update actual values and PASS/FAIL badges from engine evaluation dict."""
        for row, (key, label, ref_val) in enumerate(self.ROWS):
            data = eval_dict.get(key)
            if not data:
                continue

            actual_str = data.get("actual", "—")
            passed = data.get("passed", False)

            item_act = self.table.item(row, 2)
            if item_act:
                item_act.setText(actual_str)

            item_stat = self.table.item(row, 3)
            if item_stat:
                if passed:
                    item_stat.setText("PASS ✓")
                    item_stat.setBackground(QColor("#238636"))
                    item_stat.setForeground(QColor("#ffffff"))
                else:
                    item_stat.setText("FAIL ✗")
                    item_stat.setBackground(QColor("#da3633"))
                    item_stat.setForeground(QColor("#ffffff"))
