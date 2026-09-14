"""
gui/world_map.py — Engineering World Map (Stage 1 Alpha).

Top-down (XZ plane) engineering schematic showing:
  - Terminal A at origin (fixed)
  - Terminal B current position
  - LOS line from A to B
  - Camera FOV wedge (projected into XZ plane)
  - Terminal B trajectory (preview path and recent trail)
  - Grid and axis labels

Coordinate mapping: World X → screen X, World Z → screen Y (depth = vertical in top-down)
"""

import math
from typing import Dict, Any, List, Optional
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import (
    QPainter,
    QColor,
    QPen,
    QBrush,
    QFont,
    QPolygonF,
)
from PySide6.QtWidgets import QWidget


# Map view parameters
MAP_X_RANGE = (-1200.0, 1200.0)   # World X range
MAP_Z_RANGE = (-200.0, 1800.0)    # World Z range (depth)
MAP_PAD = 30.0                    # Padding pixels inside widget


class WorldMapWidget(QWidget):
    """Engineering top-down world map (XZ plane view)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(240, 240)
        self.sim_state: Dict[str, Any] = {}

    def update_state(self, state: Dict[str, Any]) -> None:
        self.sim_state = state
        self.update()

    # ------------------------------------------------------------------ #
    # Coordinate helpers
    # ------------------------------------------------------------------ #

    def _world_to_map(self, wx: float, wz: float,
                      map_w: float, map_h: float) -> QPointF:
        """Convert 3D world (X, Z) to 2D map pixel coordinates."""
        xr = MAP_X_RANGE
        zr = MAP_Z_RANGE
        px = MAP_PAD + (wx - xr[0]) / (xr[1] - xr[0]) * (map_w - 2 * MAP_PAD)
        # Z increases downward in screen (farther = lower)
        py = MAP_PAD + (wz - zr[0]) / (zr[1] - zr[0]) * (map_h - 2 * MAP_PAD)
        return QPointF(px, py)

    # ------------------------------------------------------------------ #
    # Paint
    # ------------------------------------------------------------------ #

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        mw = float(self.width())
        mh = float(self.height())

        # Background
        painter.fillRect(self.rect(), QColor("#04070d"))

        if not self.sim_state:
            return

        # Draw components in order
        self._draw_grid(painter, mw, mh)
        self._draw_trajectory(painter, mw, mh)
        self._draw_fov_wedge(painter, mw, mh)
        self._draw_los_line(painter, mw, mh)
        self._draw_terminal_a(painter, mw, mh)
        self._draw_terminal_b(painter, mw, mh)
        self._draw_hud(painter, mw, mh)

    def _draw_grid(self, painter: QPainter, mw: float, mh: float) -> None:
        """Draw coordinate grid (every 200 world units)."""
        grid_pen = QPen(QColor(255, 255, 255, 9), 1.0, Qt.PenStyle.DotLine)
        axis_pen = QPen(QColor(0, 210, 255, 22), 1.2, Qt.PenStyle.DashLine)
        label_pen = QPen(QColor(80, 100, 130, 100))
        painter.setFont(QFont("Consolas", 7))

        for x in range(-1000, 1200, 200):
            p1 = self._world_to_map(float(x), MAP_Z_RANGE[0], mw, mh)
            p2 = self._world_to_map(float(x), MAP_Z_RANGE[1], mw, mh)
            painter.setPen(axis_pen if x == 0 else grid_pen)
            painter.drawLine(p1, p2)
            if x % 400 == 0:
                painter.setPen(label_pen)
                painter.drawText(QPointF(p1.x() - 12, mh - 6), f"{x}")

        for z in range(0, 1800, 200):
            p1 = self._world_to_map(MAP_X_RANGE[0], float(z), mw, mh)
            p2 = self._world_to_map(MAP_X_RANGE[1], float(z), mw, mh)
            painter.setPen(axis_pen if z == 0 else grid_pen)
            painter.drawLine(p1, p2)
            if z % 400 == 0:
                painter.setPen(label_pen)
                painter.drawText(QPointF(6, p1.y() + 4), f"Z={z}")

    def _draw_trajectory(self, painter: QPainter, mw: float, mh: float) -> None:
        """Draw Terminal B preview path (dashed) and recent trail (solid)."""
        # Preview path
        path = self.sim_state.get("target_preview_path", [])
        if len(path) > 1:
            preview_pen = QPen(QColor(0, 200, 255, 40), 1.5, Qt.PenStyle.DashLine)
            painter.setPen(preview_pen)
            for i in range(1, len(path)):
                p0 = self._world_to_map(path[i-1][0], path[i-1][2], mw, mh)
                p1 = self._world_to_map(path[i][0],   path[i][2],   mw, mh)
                painter.drawLine(p0, p1)

        # Recent motion trail (gradient opacity)
        trail = self.sim_state.get("target_trail", [])
        n = len(trail)
        if n > 1:
            for i in range(1, n):
                alpha = int((i / n) * 160)
                pen = QPen(QColor(255, 85, 45, alpha), 2.0)
                painter.setPen(pen)
                p0 = self._world_to_map(trail[i-1][0], trail[i-1][2], mw, mh)
                p1 = self._world_to_map(trail[i][0],   trail[i][2],   mw, mh)
                painter.drawLine(p0, p1)

    def _draw_fov_wedge(self, painter: QPainter, mw: float, mh: float) -> None:
        """Draw camera FOV wedge projected onto XZ plane."""
        pan_rad = self.sim_state.get("camera_pan_rad", 0.0)
        fov_h_half = math.radians(2.0)  # half of 4° horizontal FOV
        wedge_len = 700.0               # visual length of FOV wedge in world units

        # Origin (Terminal A at 0,0,0 → map position)
        origin = self._world_to_map(0.0, 0.0, mw, mh)

        # Left & right edges of FOV wedge
        angle_l = pan_rad - fov_h_half
        angle_r = pan_rad + fov_h_half

        wx_l = math.sin(angle_l) * wedge_len
        wz_l = math.cos(angle_l) * wedge_len
        wx_r = math.sin(angle_r) * wedge_len
        wz_r = math.cos(angle_r) * wedge_len

        p_l = self._world_to_map(wx_l, wz_l, mw, mh)
        p_r = self._world_to_map(wx_r, wz_r, mw, mh)

        # Filled FOV wedge
        wedge_poly = QPolygonF([origin, p_l, p_r])
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(0, 210, 255, 18)))
        painter.drawPolygon(wedge_poly)

        # Wedge outline
        painter.setPen(QPen(QColor(0, 210, 255, 130), 1.8))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawLine(origin, p_l)
        painter.drawLine(origin, p_r)

        # Boresight center line
        wx_c = math.sin(pan_rad) * wedge_len
        wz_c = math.cos(pan_rad) * wedge_len
        p_c = self._world_to_map(wx_c, wz_c, mw, mh)
        painter.setPen(QPen(QColor(0, 255, 200, 100), 1.2, Qt.PenStyle.DotLine))
        painter.drawLine(origin, p_c)

    def _draw_los_line(self, painter: QPainter, mw: float, mh: float) -> None:
        """Draw Line-of-Sight from Terminal A to Terminal B."""
        tpos = self.sim_state.get("target_pos_3d", [0.0, 100.0, 1000.0])
        origin = self._world_to_map(0.0, 0.0, mw, mh)
        target = self._world_to_map(tpos[0], tpos[2], mw, mh)

        los_pen = QPen(QColor(255, 200, 50, 100), 1.4, Qt.PenStyle.DashLine)
        painter.setPen(los_pen)
        painter.drawLine(origin, target)

        # Range annotation
        dist = math.sqrt(tpos[0]**2 + tpos[1]**2 + tpos[2]**2)
        mid = QPointF((origin.x() + target.x()) / 2.0, (origin.y() + target.y()) / 2.0)
        painter.setFont(QFont("Consolas", 7))
        painter.setPen(QPen(QColor(200, 175, 80, 140)))
        painter.drawText(QPointF(mid.x() + 5, mid.y() - 5), f"{dist:.0f} m")

    def _draw_terminal_a(self, painter: QPainter, mw: float, mh: float) -> None:
        """Draw Terminal A marker at world origin."""
        p = self._world_to_map(0.0, 0.0, mw, mh)

        # Cross
        painter.setPen(QPen(QColor("#00f0ff"), 1.8))
        painter.drawLine(QPointF(p.x() - 14, p.y()), QPointF(p.x() + 14, p.y()))
        painter.drawLine(QPointF(p.x(), p.y() - 14), QPointF(p.x(), p.y() + 14))

        # Box
        hs = 8.0
        painter.setPen(QPen(QColor(0, 220, 255, 200), 1.5))
        painter.setBrush(QBrush(QColor(0, 180, 220, 60)))
        painter.drawRect(QRectF(p.x() - hs, p.y() - hs, hs * 2, hs * 2))

        # Label
        painter.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        painter.setPen(QPen(QColor("#00d2ff")))
        painter.drawText(QPointF(p.x() + 12, p.y() - 8), "TERM-A")
        painter.setFont(QFont("Consolas", 7))
        painter.setPen(QPen(QColor(0, 180, 220, 130)))
        painter.drawText(QPointF(p.x() + 12, p.y() + 6), "(Host Camera)")

    def _draw_terminal_b(self, painter: QPainter, mw: float, mh: float) -> None:
        """Draw Terminal B (mobile) marker at current position."""
        tpos = self.sim_state.get("target_pos_3d", [0.0, 100.0, 1000.0])
        p = self._world_to_map(tpos[0], tpos[2], mw, mh)

        # Halo
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(255, 60, 20, 70)))
        painter.drawEllipse(p, 16.0, 16.0)

        # Core
        painter.setBrush(QBrush(QColor("#ff3a00")))
        painter.drawEllipse(p, 7.0, 7.0)

        # White center
        painter.setBrush(QBrush(QColor(255, 255, 255)))
        painter.drawEllipse(p, 2.5, 2.5)

        # Label
        painter.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        painter.setPen(QPen(QColor("#ff6b4a")))
        painter.drawText(QPointF(p.x() + 12, p.y() - 8), "TERM-B")
        painter.setFont(QFont("Consolas", 7))
        painter.setPen(QPen(QColor(255, 130, 80, 140)))
        painter.drawText(
            QPointF(p.x() + 12, p.y() + 6),
            f"({tpos[0]:.0f}, {tpos[1]:.0f}, {tpos[2]:.0f})"
        )

    def _draw_hud(self, painter: QPainter, mw: float, mh: float) -> None:
        """Map title and mode info HUD."""
        motion = self.sim_state.get("motion_mode", "circle")
        pan_d = self.sim_state.get("camera_pan_deg", 0.0)
        tilt_d = self.sim_state.get("camera_tilt_deg", 0.0)

        painter.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        painter.setPen(QPen(QColor(220, 235, 255, 175)))
        painter.drawText(QPointF(MAP_PAD, MAP_PAD - 8), "WORLD MAP — XZ PLANE (TOP-DOWN)")

        painter.setFont(QFont("Consolas", 8))
        painter.setPen(QPen(QColor(100, 130, 170, 130)))
        painter.drawText(
            QPointF(MAP_PAD, MAP_PAD + 7),
            f"Mode: {motion.replace('_', ' ').title()}  |  Pan: {pan_d:+.1f}°  Tilt: {tilt_d:+.1f}°"
        )

        # Border
        painter.setPen(QPen(QColor("#1f2d42"), 1.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(QRectF(1, 1, mw - 2, mh - 2))
