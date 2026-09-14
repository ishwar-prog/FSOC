import math
import random
from typing import Dict, Any, List, Tuple
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import (
    QPainter,
    QColor,
    QPen,
    QBrush,
    QRadialGradient,
    QLinearGradient,
    QFont,
    QPainterPath,
)
from PySide6.QtWidgets import QWidget


class SimulationWidget(QWidget):
    """Deep-space optical telescope camera view simulating Pointing, Acquisition,
    and Tracking (PAT) of an FSOC beacon through stars, cosmic dust, and space optics."""

    VIRTUAL_WIDTH = 1000.0
    VIRTUAL_HEIGHT = 600.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(480, 288)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)

        self.sim_state: Dict[str, Any] = {
            "x": 500.0,
            "y": 300.0,
            "true_x": 500.0,
            "true_y": 300.0,
            "center_x": 500.0,
            "center_y": 300.0,
            "distance": 0.0,
            "sim_time": 0.0,
            "is_running": True,
            "motion_type": "circle",
            "fog_density": 0.15,
            "sensor_noise": 0.18,
            "dust_density": 0.35,
            "turbulence_enabled": True,
            "snr_db": 27.0,
            "pat_mode": "auto",
            "pat_stage": "search",
            "stage_time": 0.0,
            "scan_angle": 0.0,
            "scan_radius": 150.0,
            "pointing_progress": 0.0,
            "stars": [],
            "dust_particles": [],
            "trail": [],
        }

    def update_telemetry(self, state: Dict[str, Any]) -> None:
        self.sim_state = state
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        # 1. Fill outer widget background
        painter.fillRect(self.rect(), QColor("#020306"))

        # 2. Compute 1000x600 virtual viewport transform
        w = float(self.width())
        h = float(self.height())
        scale = min(w / self.VIRTUAL_WIDTH, h / self.VIRTUAL_HEIGHT)

        offset_x = (w - self.VIRTUAL_WIDTH * scale) / 2.0
        offset_y = (h - self.VIRTUAL_HEIGHT * scale) / 2.0

        painter.save()
        painter.translate(offset_x, offset_y)
        painter.scale(scale, scale)

        world_rect = QRectF(0, 0, self.VIRTUAL_WIDTH, self.VIRTUAL_HEIGHT)

        # 3. Space Background
        space_grad = QRadialGradient(500, 300, 580)
        space_grad.setColorAt(0.0, QColor("#080c14"))
        space_grad.setColorAt(0.7, QColor("#04060a"))
        space_grad.setColorAt(1.0, QColor("#020306"))
        painter.fillRect(world_rect, QBrush(space_grad))

        # 4. Deep Space Layers
        self._draw_starfield(painter)
        self._draw_cosmic_dust(painter)
        self._draw_range_reticles(painter)
        self._draw_sensor_noise(painter)

        # 5. PAT Stage Specific Visuals
        stage = self.sim_state.get("pat_stage", "search")
        if stage == "search":
            self._draw_search_pattern(painter)
        elif stage == "acquisition":
            self._draw_acquisition_pattern(painter)
        elif stage == "pointing":
            self._draw_pointing_pattern(painter)
        elif stage == "fine_tracking":
            self._draw_fine_tracking_pattern(painter)
        elif stage == "lost":
            self._draw_lost_pattern(painter)

        # 6. Beacon & Optics
        self._draw_beacon_with_diffraction(painter)
        self._draw_camera_boresight(painter)
        self._draw_vignetting(painter)
        self._draw_telescope_osd(painter)

        # Border
        painter.setPen(QPen(QColor("#1f293d"), 1.8))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(world_rect)

        painter.restore()

    def _draw_starfield(self, painter: QPainter) -> None:
        """Render realistic background starfield with astronomical twinkle."""
        stars = self.sim_state.get("stars", [])
        sim_time = self.sim_state.get("sim_time", 0.0)

        for sx, sy, mag, speed, phase in stars:
            # Twinkle formula
            twinkle = 0.75 + 0.25 * math.sin(sim_time * speed + phase)
            alpha = int(min(255, max(40, 160 * twinkle * (mag / 2.0))))
            color = QColor(220, 235, 255, alpha)

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(color))
            radius = mag * (0.8 + 0.2 * twinkle)
            painter.drawEllipse(QPointF(sx, sy), radius, radius)

    def _draw_cosmic_dust(self, painter: QPainter) -> None:
        """Render illuminated cosmic dust motes and micro-debris drifting in space."""
        dust_particles = self.sim_state.get("dust_particles", [])
        bx = self.sim_state.get("x", 500.0)
        by = self.sim_state.get("y", 300.0)

        painter.setPen(Qt.PenStyle.NoPen)
        for dx, dy, _, _, size, base_alpha in dust_particles:
            # Distance to beacon light: dust glows brighter when near beacon
            dist_to_beacon = math.hypot(dx - bx, dy - by)
            light_boost = max(0.0, 1.0 - dist_to_beacon / 260.0)
            final_alpha = int(min(240, (base_alpha * 0.4 + light_boost * 0.6) * 255))

            if light_boost > 0.2:
                # Golden forward-scattered light from beacon laser
                p_color = QColor(255, 240, 200, final_alpha)
            else:
                # Faint cold space dust
                p_color = QColor(180, 200, 230, final_alpha)

            painter.setBrush(QBrush(p_color))
            painter.drawEllipse(QPointF(dx, dy), size, size)

    def _draw_range_reticles(self, painter: QPainter) -> None:
        """Render circular telescope range reticles."""
        cx = self.VIRTUAL_WIDTH / 2.0
        cy = self.VIRTUAL_HEIGHT / 2.0

        ring_pen = QPen(QColor(0, 210, 255, 20), 1.0, Qt.PenStyle.DashLine)
        font = QFont("Consolas", 8)
        painter.setFont(font)
        text_pen = QPen(QColor(0, 210, 255, 45))

        for r in (100.0, 200.0, 300.0):
            painter.setPen(ring_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QPointF(cx, cy), r, r)
            painter.setPen(text_pen)
            painter.drawText(QPointF(cx + r + 4, cy - 4), f"{int(r)}px")

    def _draw_sensor_noise(self, painter: QPainter) -> None:
        """Render focal plane array readout thermal noise grain."""
        noise_level = self.sim_state.get("sensor_noise", 0.18)
        if noise_level <= 0.02:
            return

        num_speckles = int(noise_level * 280)
        base_alpha = int(min(200, 30 + noise_level * 160))

        painter.setPen(Qt.PenStyle.NoPen)
        for _ in range(num_speckles):
            nx = random.uniform(0, self.VIRTUAL_WIDTH)
            ny = random.uniform(0, self.VIRTUAL_HEIGHT)
            val = random.randint(180, 255)
            alpha = random.randint(10, base_alpha)
            painter.setBrush(QBrush(QColor(val, val, val, alpha)))
            painter.drawRect(QRectF(nx, ny, 1.5, 1.5))

    def _draw_search_pattern(self, painter: QPainter) -> None:
        """STAGE 1: Sweeping uncertainty search cone / radar pattern."""
        cx = self.VIRTUAL_WIDTH / 2.0
        cy = self.VIRTUAL_HEIGHT / 2.0
        scan_angle = self.sim_state.get("scan_angle", 0.0)
        scan_radius = self.sim_state.get("scan_radius", 180.0)

        # 1. Sweeping radar cone sector
        cone_span = 0.45  # ~25 degrees
        cone_path = QPainterPath()
        cone_path.moveTo(QPointF(cx, cy))
        cone_path.arcTo(
            QRectF(cx - scan_radius, cy - scan_radius, scan_radius * 2, scan_radius * 2),
            math.degrees(-scan_angle),
            math.degrees(cone_span),
        )
        cone_path.closeSubpath()

        radar_grad = QRadialGradient(cx, cy, scan_radius)
        radar_grad.setColorAt(0.0, QColor(0, 210, 255, 60))
        radar_grad.setColorAt(0.8, QColor(0, 180, 255, 25))
        radar_grad.setColorAt(1.0, QColor(0, 150, 255, 0))

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(radar_grad))
        painter.drawPath(cone_path)

        # 2. Leading scan sweep line
        sweep_x = cx + scan_radius * math.cos(scan_angle)
        sweep_y = cy + scan_radius * math.sin(scan_angle)
        sweep_pen = QPen(QColor("#00d2ff"), 1.8)
        painter.setPen(sweep_pen)
        painter.drawLine(QPointF(cx, cy), QPointF(sweep_x, sweep_y))

        # 3. Expanding spiral search circle
        painter.setPen(QPen(QColor(0, 210, 255, 90), 1.2, Qt.PenStyle.DotLine))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPointF(cx, cy), scan_radius, scan_radius)

        # Search HUD banner
        painter.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
        painter.setPen(QPen(QColor("#00d2ff")))
        painter.drawText(
            QPointF(cx - 180, cy - 240),
            "▶ STAGE 1/4: SCANNING UNCERTAINTY CONE [FINDING BEACON]",
        )

    def _draw_acquisition_pattern(self, painter: QPainter) -> None:
        """STAGE 2: Beacon detected, verifying centroid & frequency."""
        bx = self.sim_state.get("x", 500.0)
        by = self.sim_state.get("y", 300.0)
        stage_time = self.sim_state.get("stage_time", 0.0)

        # Pulsing acquisition brackets
        pulse = 0.5 + 0.5 * math.sin(stage_time * 10.0)
        box_size = 28.0 + pulse * 6.0
        color = QColor(255, 190, 0, int(180 + 75 * pulse))

        self._draw_corner_brackets(painter, bx, by, box_size, 10.0, color, 2.0)

        # Expanding lock confirmation ring
        confirm_radius = (stage_time * 30.0) % 45.0
        painter.setPen(QPen(QColor(255, 200, 0, int(150 * (1.0 - confirm_radius / 45.0))), 1.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPointF(bx, by), confirm_radius, confirm_radius)

        painter.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        painter.setPen(QPen(QColor("#ffb700")))
        painter.drawText(
            QPointF(bx - 55, by - box_size - 8),
            f"▶ STAGE 2/4: ACQUIRING [{int((stage_time / 1.6) * 100)}%]",
        )

    def _draw_pointing_pattern(self, painter: QPainter) -> None:
        """STAGE 3: Gimbal slewing camera bore-sight toward beacon."""
        cx = self.VIRTUAL_WIDTH / 2.0
        cy = self.VIRTUAL_HEIGHT / 2.0
        bx = self.sim_state.get("x", cx)
        by = self.sim_state.get("y", cy)
        prog = self.sim_state.get("pointing_progress", 0.0)

        # Slewing guidance vector
        vector_pen = QPen(QColor("#38bdf8"), 2.0, Qt.PenStyle.DashLine)
        painter.setPen(vector_pen)
        painter.drawLine(QPointF(cx, cy), QPointF(bx, by))

        # Slewing gimbal marker moving toward beacon
        slew_x = cx + (bx - cx) * prog
        slew_y = cy + (by - cy) * prog

        slew_pen = QPen(QColor("#38bdf8"), 1.8)
        painter.setPen(slew_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPointF(slew_x, slew_y), 16, 16)
        painter.drawLine(QPointF(slew_x - 22, slew_y), QPointF(slew_x + 22, slew_y))
        painter.drawLine(QPointF(slew_x, slew_y - 22), QPointF(slew_x, slew_y + 22))

        painter.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        painter.setPen(QPen(QColor("#38bdf8")))
        painter.drawText(
            QPointF(slew_x + 20, slew_y - 12),
            f"▶ STAGE 3/4: COARSE SLEW [{int(prog * 100)}%]",
        )

    def _draw_fine_tracking_pattern(self, painter: QPainter) -> None:
        """STAGE 4: Closed-loop fine tracking with Fast Steering Mirror locked."""
        cx = self.VIRTUAL_WIDTH / 2.0
        cy = self.VIRTUAL_HEIGHT / 2.0
        bx = self.sim_state.get("x", cx)
        by = self.sim_state.get("y", cy)
        dist = self.sim_state.get("distance", 0.0)
        snr = self.sim_state.get("snr_db", 25.0)

        # Motion trail
        self._draw_trail(painter)

        # Guidance vector line
        vector_pen = QPen(QColor("#00ff88"), 1.4, Qt.PenStyle.DashLine)
        painter.setPen(vector_pen)
        painter.drawLine(QPointF(cx, cy), QPointF(bx, by))

        # Precision locked target box
        self._draw_corner_brackets(painter, bx, by, 22.0, 8.0, QColor("#00ff88"), 1.8)

        # Reticle tick marks inside box
        p_pen = QPen(QColor(0, 255, 136, 140), 1.0)
        painter.setPen(p_pen)
        painter.drawLine(QPointF(bx - 12, by), QPointF(bx + 12, by))
        painter.drawLine(QPointF(bx, by - 12), QPointF(bx, by + 12))

        # Target label
        painter.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        painter.setPen(QPen(QColor("#00ff88")))
        painter.drawText(
            QPointF(bx - 32, by - 26),
            f"LOCKED [SNR: {snr:.1f}dB]",
        )

        # Midpoint distance
        mx = (cx + bx) / 2.0
        my = (cy + by) / 2.0
        painter.drawText(QPointF(mx + 8, my - 6), f"Δr={dist:.1f}px")

    def _draw_lost_pattern(self, painter: QPainter) -> None:
        """Fallback: Signal lost warning."""
        cx = self.VIRTUAL_WIDTH / 2.0
        cy = self.VIRTUAL_HEIGHT / 2.0
        bx = self.sim_state.get("x", cx)
        by = self.sim_state.get("y", cy)
        stage_time = self.sim_state.get("stage_time", 0.0)

        pulse = 0.5 + 0.5 * math.sin(stage_time * 12.0)
        color = QColor(255, 60, 60, int(150 + 105 * pulse))

        self._draw_corner_brackets(painter, bx, by, 30.0, 10.0, color, 2.0)

        painter.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
        painter.setPen(QPen(QColor("#ff4d4d")))
        painter.drawText(
            QPointF(cx - 160, cy - 240),
            "⚠ SIGNAL LOST: RE-ACQUIRING BEACON...",
        )

    def _draw_corner_brackets(
        self,
        painter: QPainter,
        cx: float,
        cy: float,
        size: float,
        corner_len: float,
        color: QColor,
        width: float,
    ) -> None:
        """Helper to draw high-tech tactical corner brackets."""
        x1 = cx - size
        y1 = cy - size
        x2 = cx + size
        y2 = cy + size

        pen = QPen(color, width)
        painter.setPen(pen)

        # Top-left
        painter.drawLine(QPointF(x1, y1), QPointF(x1 + corner_len, y1))
        painter.drawLine(QPointF(x1, y1), QPointF(x1, y1 + corner_len))
        # Top-right
        painter.drawLine(QPointF(x2, y1), QPointF(x2 - corner_len, y1))
        painter.drawLine(QPointF(x2, y1), QPointF(x2, y1 + corner_len))
        # Bottom-left
        painter.drawLine(QPointF(x1, y2), QPointF(x1 + corner_len, y2))
        painter.drawLine(QPointF(x1, y2), QPointF(x1, y2 - corner_len))
        # Bottom-right
        painter.drawLine(QPointF(x2, y2), QPointF(x2 - corner_len, y2))
        painter.drawLine(QPointF(x2, y2), QPointF(x2, y2 - corner_len))

    def _draw_trail(self, painter: QPainter) -> None:
        """Render fading motion trail."""
        trail: List[Tuple[float, float]] = self.sim_state.get("trail", [])
        if len(trail) < 2:
            return

        total = len(trail)
        for i in range(1, total):
            p1 = trail[i - 1]
            p2 = trail[i]
            alpha = int((i / total) * 90)
            pen = QPen(QColor(0, 255, 180, alpha), 1.4)
            painter.setPen(pen)
            painter.drawLine(QPointF(p1[0], p1[1]), QPointF(p2[0], p2[1]))

    def _draw_beacon_with_diffraction(self, painter: QPainter) -> None:
        """Draw optical beacon with telescope spider diffraction spikes and anamorphic laser flare."""
        bx = self.sim_state.get("x", 500.0)
        by = self.sim_state.get("y", 300.0)
        fog = self.sim_state.get("fog_density", 0.15)
        dust = self.sim_state.get("dust_density", 0.35)

        transmission = math.exp(- (fog * 2.0 + dust * 0.7))
        core_alpha = int(max(40, transmission * 255))
        halo_radius = 22.0 + (fog * 30.0) + (dust * 15.0)

        # 1. 4-Point Telescope Spider Diffraction Spikes
        spike_len = 55.0 * transmission
        if spike_len > 10.0:
            spike_pen = QPen(QColor(255, 235, 120, int(core_alpha * 0.45)), 1.2)
            painter.setPen(spike_pen)
            # Vertical spike
            painter.drawLine(QPointF(bx, by - spike_len), QPointF(bx, by + spike_len))
            # Horizontal spike
            painter.drawLine(QPointF(bx - spike_len, by), QPointF(bx + spike_len, by))

            # 2. Horizontal anamorphic laser flare
            flare_len = 80.0 * transmission
            flare_pen = QPen(QColor(255, 255, 200, int(core_alpha * 0.3)), 1.8)
            painter.setPen(flare_pen)
            painter.drawLine(QPointF(bx - flare_len, by), QPointF(bx + flare_len, by))

        # 3. Radiant optical halo
        halo_grad = QRadialGradient(bx, by, halo_radius)
        halo_grad.setColorAt(0.0, QColor(255, 235, 60, int(core_alpha * 0.85)))
        halo_grad.setColorAt(0.5, QColor(255, 170, 0, int(core_alpha * 0.4)))
        halo_grad.setColorAt(1.0, QColor(255, 100, 0, 0))

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(halo_grad))
        painter.drawEllipse(QPointF(bx, by), halo_radius, halo_radius)

        # 4. Concentric ring
        painter.setPen(QPen(QColor(255, 255, 160, int(core_alpha * 0.7)), 1.2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPointF(bx, by), 10.0, 10.0)

        # 5. Intense laser core
        core_grad = QRadialGradient(bx, by, 6.0)
        core_grad.setColorAt(0.0, QColor(255, 255, 255, core_alpha))
        core_grad.setColorAt(0.7, QColor(255, 235, 60, core_alpha))
        core_grad.setColorAt(1.0, QColor(255, 140, 0, 0))

        painter.setBrush(QBrush(core_grad))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(bx, by), 5.5, 5.5)

    def _draw_camera_boresight(self, painter: QPainter) -> None:
        """Draw camera optical axis center reticle."""
        cx = self.VIRTUAL_WIDTH / 2.0
        cy = self.VIRTUAL_HEIGHT / 2.0

        reticle_pen = QPen(QColor(0, 210, 255, 170), 1.2)
        painter.setPen(reticle_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPointF(cx, cy), 24, 24)
        painter.drawEllipse(QPointF(cx, cy), 6, 6)

        ch_len = 45.0
        gap = 12.0
        painter.drawLine(QPointF(cx - ch_len, cy), QPointF(cx - gap, cy))
        painter.drawLine(QPointF(cx + gap, cy), QPointF(cx + ch_len, cy))
        painter.drawLine(QPointF(cx, cy - ch_len), QPointF(cx, cy - gap))
        painter.drawLine(QPointF(cx, cy + gap), QPointF(cx, cy + ch_len))

        painter.setBrush(QBrush(QColor("#00f0ff")))
        painter.drawEllipse(QPointF(cx, cy), 2.0, 2.0)

        painter.setPen(QPen(QColor(0, 210, 255, 130)))
        painter.setFont(QFont("Consolas", 8))
        painter.drawText(QPointF(cx + 10, cy + 18), "OPTICAL AXIS (500, 300)")

    def _draw_vignetting(self, painter: QPainter) -> None:
        """Simulate circular telescope barrel vignetting."""
        vig_grad = QRadialGradient(500, 300, 560)
        vig_grad.setColorAt(0.0, QColor(0, 0, 0, 0))
        vig_grad.setColorAt(0.72, QColor(0, 0, 0, 30))
        vig_grad.setColorAt(1.0, QColor(0, 0, 0, 190))

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(vig_grad))
        painter.drawRect(QRectF(0, 0, self.VIRTUAL_WIDTH, self.VIRTUAL_HEIGHT))

    def _draw_telescope_osd(self, painter: QPainter) -> None:
        """Render space optical payload On-Screen Display."""
        painter.setFont(QFont("Consolas", 9))
        painter.setPen(QPen(QColor(230, 240, 255, 150)))

        # Header
        painter.drawText(
            QPointF(16, 24),
            "FSOC SPACE TERMINAL - NIR 850nm | APERTURE: 200mm f/4.0 | FL: 800mm",
        )

        # Footer
        dust = int(self.sim_state.get("dust_density", 0.35) * 100)
        noise = int(self.sim_state.get("sensor_noise", 0.18) * 100)
        stage_str = self.sim_state.get("pat_stage", "search").upper()
        t_stage = self.sim_state.get("stage_time", 0.0)

        painter.drawText(
            QPointF(16, 582),
            f"PAT: {stage_str} ({t_stage:.1f}s) | COSMIC DUST: {dust}% | NOISE: {noise}%",
        )
