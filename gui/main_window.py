"""Main window: top bar, Live Tracking / Analytics / System pages, 60 Hz render loop."""

import math

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QMainWindow, QPushButton, QSplitter, QStackedWidget,
                               QVBoxLayout, QWidget)

from fsoc import __version__
from fsoc.core.geometry import angular_separation
from fsoc.runtime.engine import Engine
from .analytics_page import AnalyticsPage
from .camera_view import CameraView
from .charts import ErrorTimeline, History
from .control_rail import ControlRail
from .kpi_panel import KpiPanel
from .system_page import SystemPage
from .theme import P, STATE_COLOR, c, font, mono, qss
from .widgets import Card, Pill, Segmented, StatRow, label
from .world_view import WorldView

DEG = math.pi / 180.0


def app_icon() -> QIcon:
    pm = QPixmap(64, 64)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(P["accent"]))
    p.drawRoundedRect(QRectF(2, 2, 60, 60), 16, 16)
    p.setPen(QPen(QColor("white"), 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawLine(QPointF(16, 46), QPointF(46, 18))
    p.setBrush(QColor("white"))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(QPointF(46, 18), 7, 7)
    p.drawEllipse(QPointF(16, 46), 5, 5)
    p.end()
    return QIcon(pm)


class Logo(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(38, 38)

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.drawPixmap(self.rect(), app_icon().pixmap(64, 64))


class ChipToggle(QPushButton):
    def __init__(self, text: str, on: bool = True, parent=None) -> None:
        super().__init__(text, parent)
        self.setCheckable(True)
        self.setChecked(on)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(
            f"QPushButton {{ padding: 3px 10px; border-radius: 10px; font-size: 8.4pt; font-weight: 600;"
            f" background: {P['surface']}; color: {P['muted']}; border: 1px solid {P['border']}; }}"
            f"QPushButton:checked {{ background: {P['accent_soft']}; color: {P['accent_hover']};"
            f" border: 1px solid {P['accent']}; }}")


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("FSOC Beacon Tracker — Coarse PAT · SIH26169")
        self.setWindowIcon(app_icon())
        self.setStyleSheet(qss())
        self.resize(1480, 900)
        self.setMinimumSize(1240, 740)

        self.engine = Engine(seed=42, pattern="orbit")
        self.history = History()
        self._tick = 0

        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        v = QVBoxLayout(root)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        v.addWidget(self._top_bar())

        self.pages = QStackedWidget()
        page_wrap = QWidget()
        pw = QVBoxLayout(page_wrap)
        pw.setContentsMargins(18, 16, 18, 16)
        pw.addWidget(self.pages)
        v.addWidget(page_wrap, 1)

        self.pages.addWidget(self._live_page())
        self.analytics = AnalyticsPage(self.engine, self.history)
        self.pages.addWidget(self.analytics)
        self.system = SystemPage(self.engine)
        self.pages.addWidget(self.system)
        self.nav.changed.connect(self._navigate)

        self.engine.start()
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._on_tick)
        self.timer.start()

    # ------------------------------------------------------------------ layout
    def _top_bar(self) -> QWidget:
        bar = QFrame()
        bar.setFixedHeight(66)
        bar.setStyleSheet(f"QFrame {{ background: {P['surface']}; border-bottom: 1px solid {P['border']}; }}"
                          f"QLabel {{ border: none; background: transparent; }}")
        h = QHBoxLayout(bar)
        h.setContentsMargins(20, 10, 20, 10)
        h.setSpacing(12)
        h.addWidget(Logo())
        tb = QVBoxLayout()
        tb.setSpacing(0)
        t = label("FSOC Beacon Tracker", "h1")
        t.setStyleSheet("font-size: 13pt; font-weight: 700;")
        tb.addWidget(t)
        tb.addWidget(label(f"Coarse pointing · acquisition · tracking   ·   SIH26169   ·   v{__version__}", "caption"))
        h.addLayout(tb)
        h.addStretch(1)
        self.nav = Segmented([("live", "Live tracking"), ("analytics", "Analytics"), ("system", "System && inputs")])
        h.addWidget(self.nav)
        h.addStretch(1)
        self.state_pill = Pill("SEARCHING", "peach", size=8.6)
        self.state_pill.setMinimumWidth(118)
        h.addWidget(self.state_pill)
        self.clock = QLabel("00:00.0")
        self.clock.setFont(mono(11, 600))
        self.clock.setStyleSheet(f"color: {P['muted']};")
        self.clock.setFixedWidth(84)
        self.clock.setAlignment(Qt.AlignmentFlag.AlignCenter)
        h.addWidget(self.clock)
        self.pause_btn = QPushButton("Pause")
        self.pause_btn.setObjectName("primary")
        self.pause_btn.setFixedWidth(96)
        self.pause_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pause_btn.clicked.connect(self._toggle_pause)
        h.addWidget(self.pause_btn)
        return bar

    def _live_page(self) -> QWidget:
        page = QWidget()
        h = QHBoxLayout(page)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(16)

        self.rail = ControlRail("orbit")
        self.rail.setFixedWidth(312)
        self.rail.pattern_changed.connect(self.engine.set_pattern)
        self.rail.hazard_toggled.connect(lambda k, on: self.engine.set_hazard(k, on))
        self.rail.hazard_intensity.connect(lambda k, v: self.engine.set_hazard(k, intensity=v))
        h.addWidget(self.rail)

        center = QSplitter(Qt.Orientation.Vertical)
        center.setHandleWidth(14)
        center.setChildrenCollapsible(False)
        center.setStyleSheet("QSplitter::handle { background: transparent; }")

        cam = Card("Camera sensor", "Exactly what the tracker sees — no ground truth used by the algorithm", pad=14,
                   spacing=10)
        self.layer_btns = {}
        for key, text, on in (("truth", "Truth", True), ("detections", "Detections", True),
                              ("search", "Scan path", True), ("zoom", "Zoom", True)):
            b = ChipToggle(text, on)
            b.toggled.connect(lambda v, k=key: self.camera.set_layer(k, v))
            cam.header.addWidget(b, 0, Qt.AlignmentFlag.AlignTop)
            self.layer_btns[key] = b
        body = QHBoxLayout()
        body.setSpacing(14)
        self.camera = CameraView(self.engine.K)
        body.addWidget(self.camera, 1)
        side = QVBoxLayout()
        side.setSpacing(0)
        self.readouts = {}
        for key, name in (("state", "State"), ("age", "Time in state"), ("snr", "Beacon SNR"),
                          ("conf", "Confidence"), ("cerr", "Centroid error"), ("perr", "Pointing error"),
                          ("gimbal", "Gimbal az / el"), ("rate", "Slew rate"), ("range", "Range"),
                          ("cands", "Candidates")):
            row = StatRow(name)
            side.addWidget(row)
            self.readouts[key] = row
        side.addSpacing(10)
        side.addWidget(label("Centroid error · last 10 s", "caption"))
        self.mini = ErrorTimeline(10.0, compact=True)
        side.addWidget(self.mini, 1)
        sidew = QWidget()
        sidew.setLayout(side)
        sidew.setFixedWidth(218)
        body.addWidget(sidew)
        cam.body.addLayout(body, 1)
        center.addWidget(cam)

        world = Card("World view", "Terminal A → Terminal B link geometry, live", pad=14, spacing=10)
        self.tod = Segmented([("day", "Day"), ("dusk", "Dusk"), ("night", "Night")])
        self.tod.changed.connect(self.engine.set_time_of_day)
        world.header.addWidget(self.tod, 0, Qt.AlignmentFlag.AlignTop)
        self.world = WorldView(self.engine)
        world.body.addWidget(self.world, 1)
        center.addWidget(world)
        center.setSizes([560, 380])
        h.addWidget(center, 1)

        self.kpis = KpiPanel()
        self.kpis.setFixedWidth(318)
        self.kpis.restart_clicked.connect(self.engine.cold_restart)
        self.kpis.block_clicked.connect(lambda: self.engine.block_beacon(2.5))
        h.addWidget(self.kpis)
        return page

    # -------------------------------------------------------------- behaviour
    def _navigate(self, key: str) -> None:
        self.pages.setCurrentIndex({"live": 0, "analytics": 1, "system": 2}[key])

    def _toggle_pause(self) -> None:
        self.engine.set_paused(not self.engine.paused)

    def _on_tick(self) -> None:
        self._tick += 1
        s = self.engine.snapshot()
        page = self.pages.currentIndex()
        new_frame = s is not None and self.history.add(s)

        if page == 0:
            self.world.set_snapshot(s)
            self.world.update()
            if s is not None and (new_frame or s.paused):
                self.camera.set_snapshot(s)
        else:
            self.engine.report_render_frame()

        if s is None:
            return
        if self._tick % 6 == 0:
            self._update_text(s)
            if page == 0:
                self.kpis.update_metrics(s.metrics)
        if self._tick % 3 == 0:
            if page == 0:
                self.mini.refresh(self.history)
            elif page == 1:
                self.analytics.refresh(s)
            elif page == 2 and self._tick % 6 == 0:
                self.system.refresh(s)

    def _update_text(self, s) -> None:
        o = s.out
        state = "PAUSED" if self.engine.paused else o.state
        tone, text = STATE_COLOR.get(state, ("faint", state))
        self.state_pill.set_tone(tone, text.upper())
        t = self.engine.clock.now()
        self.clock.setText(f"{int(t // 60):02d}:{t % 60:04.1f}")
        self.pause_btn.setText("Resume" if self.engine.paused else "Pause")
        if self.pages.currentIndex() != 0:
            return
        r = self.readouts
        r["state"].set(text)
        r["age"].set(f"{o.state_age:.1f} s")
        r["snr"].set(f"{o.snr:.0f}" if o.measurement else "—")
        r["conf"].set(f"{o.confidence * 100:.0f} %")
        r["cerr"].set(f"{s.centroid_err:.2f} px" if s.centroid_err is not None else "—")
        r["perr"].set(f"{s.pointing_err:.1f} px" if s.pointing_err is not None and s.truth.in_fov else "off-FOV")
        g = s.gimbal
        r["gimbal"].set(f"{g[0] / DEG:+.2f}° / {g[1] / DEG:+.2f}°")
        r["rate"].set(f"{math.hypot(g[2], g[3]) / DEG:.2f} °/s")
        r["range"].set(f"{s.range_m / 1000:.2f} km")
        r["cands"].set(str(len(o.candidates)))

    def closeEvent(self, e) -> None:
        self.timer.stop()
        self.engine.shutdown()
        super().closeEvent(e)
