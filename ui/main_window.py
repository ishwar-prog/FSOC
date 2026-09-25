"""Main window: top bar, Live tracking / Analytics pages, adjustable screens."""

import math

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QMainWindow, QPushButton, QSplitter,
                               QStackedWidget, QVBoxLayout, QWidget)

from fsoc import __version__
from fsoc.runtime.engine import Engine
from .analytics_page import AnalyticsPage
from .camera_view import CameraView
from .charts import History
from .control_rail import ControlRail
from .info_text import tip
from .kpi_panel import KpiPanel
from .theme import P, STATE_COLOR, UNIT, num
from .widgets import Card, GridCanvas, Pill, StatRow, TabBar, label
from .world_view import WorldView

DEG = math.pi / 180.0


def app_icon() -> QIcon:
    pm = QPixmap(64, 64)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(P["head"]))
    p.drawRect(QRectF(2, 2, 60, 60))
    p.setPen(QPen(QColor(P["accent"]), 4))
    p.drawLine(QPointF(14, 48), QPointF(44, 20))
    p.setBrush(QColor(P["accent"]))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRect(QRectF(38, 14, 14, 14))
    p.drawRect(QRectF(12, 44, 8, 8))
    p.end()
    return QIcon(pm)


class Logo(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(32, 32)

    def paintEvent(self, e) -> None:
        QPainter(self).drawPixmap(self.rect(), app_icon().pixmap(64, 64))


class ChipToggle(QPushButton):
    def __init__(self, text: str, on: bool = True, parent=None) -> None:
        super().__init__(text, parent)
        self.setCheckable(True)
        self.setChecked(on)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(
            f"QPushButton {{ padding: 4px 10px; font-size: 8.4pt; font-weight: 500;"
            f" background: {P['surface']}; color: {P['muted']}; border: 1px solid {P['border']}; }}"
            f"QPushButton:hover {{ color: {P['head']}; border-color: {P['border_strong']}; }}"
            f"QPushButton:checked {{ background: {P['accent_soft']}; color: {P['accent_ink']}; font-weight: 600;"
            f" border: 1px solid {P['accent']}; }}")


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("FSOC Beacon Tracker — Coarse PAT · SIH26169")
        self.setWindowIcon(app_icon())
        self.resize(1520, 920)
        self.setMinimumSize(1200, 720)
        self.engine = Engine(seed=42, pattern="orbit")
        self.history = History()
        self._tick = 0
        self._ui_state = {"page": "live", "tab": "remote", "layers": {}, "h_sizes": None, "v_sizes": None,
                          "expand": None}
        self._build()
        self.engine.start()
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._on_tick)
        self.timer.start()

    # ================================================================ build
    def _build(self) -> None:
        root = GridCanvas()
        v = QVBoxLayout(root)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        v.addWidget(self._top_bar())
        self.pages = QStackedWidget()
        v.addWidget(self.pages, 1)
        self.pages.addWidget(self._live_page())
        self.analytics = AnalyticsPage(self.engine, self.history)
        self.pages.addWidget(self.analytics)
        self.nav.changed.connect(self._navigate)
        self.nav.set_current(self._ui_state["page"])
        self._navigate(self._ui_state["page"])
        old = self.centralWidget()
        self.setCentralWidget(root)
        if old is not None:
            old.deleteLater()

    def _top_bar(self) -> QWidget:
        bar = QFrame()
        bar.setFixedHeight(56)
        bar.setStyleSheet(f"QFrame {{ background: {P['surface']}; border-bottom: 1px solid {P['border_strong']}; }}"
                          f"QLabel {{ border: none; background: transparent; }}")
        h = QHBoxLayout(bar)
        h.setContentsMargins(UNIT * 2, 0, UNIT * 2, 0)
        h.setSpacing(UNIT * 2)
        h.addWidget(Logo())
        tb = QVBoxLayout()
        tb.setSpacing(1)
        t = label("FSOC BEACON TRACKER", "h1")
        t.setStyleSheet(f"font-size: 12pt; font-weight: 700; letter-spacing: -0.2px; color: {P['head']};")
        tb.addWidget(t)
        tb.addWidget(label(f"SIH26169 · Pointing, acquisition, tracking · v{__version__}", "faint"))
        h.addLayout(tb)
        h.addSpacing(UNIT * 3)
        self.nav = TabBar([("live", "Live tracking"), ("analytics", "Analytics")])
        h.addWidget(self.nav, 0, Qt.AlignmentFlag.AlignBottom)
        h.addStretch(1)
        self.state_pill = Pill("SEARCHING", "butter", size=8.4)
        self.state_pill.setMinimumWidth(112)
        self.state_pill.setFixedHeight(26)
        h.addWidget(self.state_pill, 0, Qt.AlignmentFlag.AlignVCenter)
        self.clock = QLabel("00:00.0")
        self.clock.setFont(num(11.5, 600))
        self.clock.setStyleSheet(f"color: {P['head']};")
        self.clock.setFixedWidth(76)
        self.clock.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        h.addWidget(self.clock, 0, Qt.AlignmentFlag.AlignVCenter)
        self.pause_btn = QPushButton("Pause")
        self.pause_btn.setObjectName("primary")
        self.pause_btn.setFixedWidth(96)
        self.pause_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pause_btn.setFixedHeight(32)
        self.pause_btn.clicked.connect(lambda: self.engine.set_paused(not self.engine.paused))
        h.addWidget(self.pause_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        return bar

    def _live_page(self) -> QWidget:
        self.hsplit = QSplitter(Qt.Orientation.Horizontal)
        self.hsplit.setHandleWidth(1)
        self.hsplit.setChildrenCollapsible(False)

        self.rail = ControlRail(self.engine, self._ui_state["tab"])
        self.rail.setMinimumWidth(320)
        self.hsplit.addWidget(self.rail)

        self.vsplit = QSplitter(Qt.Orientation.Vertical)
        self.vsplit.setHandleWidth(1)
        self.vsplit.setChildrenCollapsible(False)

        self.cam_card = Card("Camera sensor", "What the tracker sees — no hidden truth is used",
                             pad=UNIT * 2, spacing=UNIT, info=tip("camera"))
        layers = self._ui_state["layers"]
        self.layer_btns = {}
        for key, text in (("truth", "Truth"), ("detections", "Detections"), ("identity", "Identity"),
                          ("search", "Scan path"), ("zoom", "Zoom")):
            b = ChipToggle(text, layers.get(key, True))
            b.toggled.connect(lambda val, k=key: self.camera.set_layer(k, val))
            self.cam_card.header.addWidget(b, 0, Qt.AlignmentFlag.AlignTop)
            self.layer_btns[key] = b
        self.cam_expand = QPushButton("Expand")
        self.cam_expand.setObjectName("icon")
        self.cam_expand.setCheckable(True)
        self.cam_expand.setToolTip("Enlarge the camera screen")
        self.cam_expand.toggled.connect(lambda on: self._expand("camera" if on else None))
        self.cam_card.header.addWidget(self.cam_expand, 0, Qt.AlignmentFlag.AlignTop)
        self.camera = CameraView(self.engine.K)
        self.camera.seeded.connect(self.engine.seed_target)
        self.camera.set_clickable(self.engine.is_video)
        for k, b in self.layer_btns.items():
            self.camera.set_layer(k, b.isChecked())
        self.cam_card.body.addWidget(self.camera, 1)
        strip = QGridLayout()
        strip.setHorizontalSpacing(UNIT * 3)
        strip.setVerticalSpacing(2)
        self.readouts = {}
        items = (("state", "State"), ("snr", "Beacon SNR"), ("cerr", "Centroid error"), ("gimbal", "Gimbal az / el"),
                 ("range", "Range"), ("age", "Time in state"), ("idp", "Beacon identity"), ("perr", "Pointing error"),
                 ("rate", "Slew rate"), ("cands", "Lights in view"))
        for i, (key, name) in enumerate(items):
            row = StatRow(name, info=tip("ro_" + key))
            strip.addWidget(row, i // 5, i % 5)
            self.readouts[key] = row
        self.cam_card.body.addLayout(strip)
        self.vsplit.addWidget(self.cam_card)

        self.world_card = Card("World view", "Terminal A → Terminal B, live", pad=UNIT * 2, spacing=UNIT,
                               info=tip("world"))
        reset = QPushButton("Reset view")
        reset.setObjectName("ghost")
        reset.clicked.connect(lambda: self.world.reset_view())
        self.world_card.header.addWidget(reset, 0, Qt.AlignmentFlag.AlignTop)
        self.world_expand = QPushButton("Expand")
        self.world_expand.setObjectName("icon")
        self.world_expand.setCheckable(True)
        self.world_expand.setToolTip("Enlarge the world view")
        self.world_expand.toggled.connect(lambda on: self._expand("world" if on else None))
        self.world_card.header.addWidget(self.world_expand, 0, Qt.AlignmentFlag.AlignTop)
        self.world = WorldView(self.engine)
        self.world_card.body.addWidget(self.world, 1)
        self.vsplit.addWidget(self.world_card)
        self.hsplit.addWidget(self.vsplit)

        self.kpis = KpiPanel(self.engine)
        self.kpis.setMinimumWidth(280)
        self.kpis.restart_clicked.connect(self.engine.cold_restart)
        self.kpis.block_clicked.connect(lambda: self.engine.block_beacon(2.5))
        self.hsplit.addWidget(self.kpis)
        self.hsplit.setStretchFactor(1, 1)
        QTimer.singleShot(0, self._apply_sizes)
        QTimer.singleShot(120, self._apply_sizes)       # again once the rebuilt window has its real size
        return self.hsplit

    def _apply_sizes(self) -> None:
        # Sizes are kept as fractions so a theme rebuild or window resize keeps the same proportions.
        st = self._ui_state
        W = max(1000, self.hsplit.width())
        hf = st["h_sizes"] or [0.20, 0.60, 0.20]
        self.hsplit.setSizes([int(W * f) for f in hf])
        H = max(500, self.vsplit.height())
        vf = st["v_sizes"] or [0.56, 0.44]
        self.vsplit.setSizes([int(H * f) for f in vf])
        if st["expand"]:
            (self.cam_expand if st["expand"] == "camera" else self.world_expand).setChecked(True)

    def _expand(self, which) -> None:
        self._ui_state["expand"] = which
        for btn, name in ((self.cam_expand, "camera"), (self.world_expand, "world")):
            btn.blockSignals(True)
            btn.setChecked(which == name)
            btn.blockSignals(False)
        self.cam_card.setVisible(which in (None, "camera"))
        self.world_card.setVisible(which in (None, "world"))

    # ============================================================ behaviour
    def _navigate(self, key: str) -> None:
        self._ui_state["page"] = key
        self.pages.setCurrentIndex({"live": 0, "analytics": 1}[key])

    def _on_tick(self) -> None:
        self._tick += 1
        s = self.engine.snapshot()
        page = self.pages.currentIndex()
        new_frame = s is not None and self.history.add(s)
        if page == 0:
            self.world.set_snapshot(s)
            if self.world.isVisible():
                self.world.update()
            else:
                self.engine.report_render_frame()
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
                self.kpis.update_identity(s)
                self.rail.sync()
                # A loaded video has its own resolution: follow it, or every overlay would be
                # drawn at the simulator sensor's scale and the lock would look nowhere near
                # the beacon. Clicking to pick a target only means something on real footage.
                self.camera.set_intrinsics(self.engine.K)
                self.camera.set_clickable(self.engine.is_video)
        if self._tick % 3 == 0 and page == 1:
            self.analytics.refresh(s)

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
        r["idp"].set(f"{o.lock_p * 100:.0f} %" if o.lock_p > 0 else "—")
        r["cerr"].set(f"{s.centroid_err:.2f} px" if s.centroid_err is not None else "—")
        r["perr"].set(f"{s.pointing_err:.1f} px" if s.pointing_err is not None and s.truth.in_fov else "off-view")
        g = s.gimbal
        r["gimbal"].set(f"{g[0] / DEG:+.1f}° / {g[1] / DEG:+.1f}°")
        r["rate"].set(f"{math.hypot(g[2], g[3]) / DEG:.2f} °/s")
        rng = s.range_m / 1000
        r["range"].set(f"{rng:,.0f} km" if rng > 100 else f"{rng:.2f} km")
        r["cands"].set(str(o.signature.get("sources", len(o.candidates))))

    def closeEvent(self, e) -> None:
        self.timer.stop()
        self.engine.shutdown()
        super().closeEvent(e)
