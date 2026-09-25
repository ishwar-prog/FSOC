from collections import deque
from typing import Deque
import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel


class DistancePlotWidget(QWidget):
    """Real-time distance-over-time scrolling line plot using PyQtGraph."""

    MAX_POINTS = 400

    def __init__(self, parent=None):
        super().__init__(parent)

        # Set PyQtGraph configuration for clean dark styling
        pg.setConfigOption("background", "#0d1117")
        pg.setConfigOption("foreground", "#8b949e")
        pg.setConfigOption("antialias", True)

        self.time_buffer: Deque[float] = deque(maxlen=self.MAX_POINTS)
        self.dist_buffer: Deque[float] = deque(maxlen=self.MAX_POINTS)

        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        # Header title
        title = QLabel("TRACKING DISTANCE OVER TIME")
        title.setStyleSheet(
            "color: #8b949e; font-size: 10px; font-weight: bold; letter-spacing: 0.5px;"
        )
        layout.addWidget(title)

        # Plot widget
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setMenuEnabled(False)
        self.plot_widget.showGrid(x=True, y=True, alpha=0.15)
        self.plot_widget.setMouseEnabled(x=False, y=False)

        # Style axes
        styles = {"color": "#8b949e", "font-size": "9px"}
        self.plot_widget.setLabel("bottom", "Time", units="s", **styles)
        self.plot_widget.setLabel("left", "Dist", units="px", **styles)
        self.plot_widget.getAxis("bottom").setStyle(tickTextOffset=4)
        self.plot_widget.getAxis("left").setStyle(tickTextOffset=4)

        # Neon cyan curve
        self.curve = self.plot_widget.plot(
            pen=pg.mkPen(color="#00d2ff", width=2),
            shadowPen=pg.mkPen(color="#0077aa", width=4),
        )

        layout.addWidget(self.plot_widget)

    def add_point(self, sim_time: float, distance: float) -> None:
        """Append a new telemetry data point and update graph."""
        self.time_buffer.append(sim_time)
        self.dist_buffer.append(distance)

        times = np.array(self.time_buffer, dtype=np.float64)
        dists = np.array(self.dist_buffer, dtype=np.float64)

        self.curve.setData(times, dists)

        # Scroll X axis to keep the latest points visible
        if len(times) > 1:
            x_min = max(0.0, times[-1] - 12.0)
            x_max = max(12.0, times[-1] + 1.0)
            self.plot_widget.setXRange(x_min, x_max, padding=0.02)

    def reset(self) -> None:
        """Clear historical points from graph."""
        self.time_buffer.clear()
        self.dist_buffer.clear()
        self.curve.setData([], [])
        self.plot_widget.setXRange(0, 12, padding=0.02)
