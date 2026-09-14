"""
gui/graph_widget.py — Live Tracking Error Graph (Stage 1 Alpha).

Plots Angular Error (°) and Pixel Error (px) vs simulation time using PyQtGraph.
Dual-curve plot with scrolling time window.
"""

from collections import deque
from typing import Deque
import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel


class TrackingErrorGraph(QWidget):
    """Real-time scrolling plot of Angular Error (°) and Pixel Error (px) vs Time."""

    MAX_POINTS = 500

    def __init__(self, parent=None):
        super().__init__(parent)

        pg.setConfigOption("background", "#090d16")
        pg.setConfigOption("foreground", "#8b949e")
        pg.setConfigOption("antialias", True)

        self.time_buffer: Deque[float] = deque(maxlen=self.MAX_POINTS)
        self.ang_error_buffer: Deque[float] = deque(maxlen=self.MAX_POINTS)
        self.pix_error_buffer: Deque[float] = deque(maxlen=self.MAX_POINTS)

        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        title = QLabel("TRACKING ERROR vs TIME")
        title.setStyleSheet(
            "color: #8b949e; font-size: 10px; font-weight: bold; letter-spacing: 0.5px;"
        )
        layout.addWidget(title)

        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setMenuEnabled(False)
        self.plot_widget.showGrid(x=True, y=True, alpha=0.15)
        self.plot_widget.setMouseEnabled(x=False, y=False)

        styles = {"color": "#8b949e", "font-size": "9px"}
        self.plot_widget.setLabel("bottom", "Time", units="s", **styles)
        self.plot_widget.setLabel("left", "Error", **styles)

        # Angular error curve (cyan)
        self.curve_ang = self.plot_widget.plot(
            pen=pg.mkPen(color="#00d2ff", width=2),
            shadowPen=pg.mkPen(color="#004455", width=4),
            name="Angular (°)",
        )

        # Pixel error curve (orange, scaled to degrees for comparison)
        self.curve_pix = self.plot_widget.plot(
            pen=pg.mkPen(color="#ff8c42", width=1.5, style=pg.QtCore.Qt.PenStyle.DashLine),
            name="Pixel (px/100)",
        )

        # Legend
        legend = self.plot_widget.addLegend(offset=(10, 10))
        legend.setLabelTextColor("#8b949e")

        layout.addWidget(self.plot_widget)

        # Legend note
        note = QLabel("Cyan = Angular Error (°)  |  Orange dashed = Pixel Error / 100")
        note.setStyleSheet("color: #4a5568; font-size: 9px;")
        layout.addWidget(note)

    def add_point(self, sim_time: float, ang_error_deg: float, pix_error: float = 0.0) -> None:
        """Append tracking error sample and update plot curves."""
        self.time_buffer.append(sim_time)
        self.ang_error_buffer.append(ang_error_deg)
        self.pix_error_buffer.append(pix_error / 100.0)  # scale pixel error to compare

        times = np.array(self.time_buffer, dtype=np.float64)
        ang_errors = np.array(self.ang_error_buffer, dtype=np.float64)
        pix_errors_scaled = np.array(self.pix_error_buffer, dtype=np.float64)

        self.curve_ang.setData(times, ang_errors)
        self.curve_pix.setData(times, pix_errors_scaled)

        if len(times) > 1:
            x_min = max(0.0, times[-1] - 20.0)
            x_max = max(20.0, times[-1] + 1.0)
            self.plot_widget.setXRange(x_min, x_max, padding=0.02)

    def reset(self) -> None:
        """Clear graph buffers."""
        self.time_buffer.clear()
        self.ang_error_buffer.clear()
        self.pix_error_buffer.clear()
        self.curve_ang.setData([], [])
        self.curve_pix.setData([], [])
        self.plot_widget.setXRange(0, 20, padding=0.02)
