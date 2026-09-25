"""Left sidebar: Remote terminal · Ground terminal · Environment."""

import os
import random
import sys

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, Signal
from PySide6.QtWidgets import (QButtonGroup, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QPushButton,
                               QScrollArea, QSlider, QStackedWidget, QVBoxLayout, QWidget)

from fsoc.sim.hazards import HAZARD_INFOS
from fsoc.sim.patterns import PATTERN_INFOS
from fsoc.sim.terminals import AERIAL_CENTER, MOUNTS, PLATFORMS
from .info_text import tip
from .theme import HAZARD_COLOR, P
from .widgets import Card, IconBadge, IconTile, InfoButton, PatternTile, Segmented, Switch, ValueSlider, label

HAZARD_SHORT = {
    "fog": "Visibility down to 2 km", "rain": "Streaks, drops, attenuation",
    "turbulence": "Twinkle & beam wander", "noise": "Grainy, hot pixels",
    "vibration": "Camera shake", "glare": "Bright haze near the sun",
    "occlusion": "Birds, branches, cloud", "decoys": "Other lights, satellites",
}


def _scroll(inner: QWidget) -> QScrollArea:
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setFrameShape(QFrame.Shape.NoFrame)
    sa.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    sa.setWidget(inner)
    return sa


class HazardRow(QFrame):
    toggled = Signal(str, bool)
    intensity = Signal(str, float)

    def __init__(self, info, enabled: bool, level: float, parent=None) -> None:
        super().__init__(parent)
        self.key = info.key
        self.setObjectName("hazRow")
        v = QVBoxLayout(self)
        v.setContentsMargins(8, 6, 8, 6)
        v.setSpacing(2)
        top = QHBoxLayout()
        top.setSpacing(10)
        self.badge = IconBadge("hazard", info.key, 32)
        top.addWidget(self.badge)
        txt = QVBoxLayout()
        txt.setSpacing(0)
        nrow = QHBoxLayout()
        nrow.setSpacing(5)
        name = label(info.name, "h2")
        name.setStyleSheet("font-size: 9.5pt; font-weight: 500;")
        nrow.addWidget(name)
        nrow.addWidget(InfoButton(f"<b>{info.name}</b><br>{info.summary}", size=14))
        nrow.addStretch(1)
        txt.addLayout(nrow)
        txt.addWidget(label(HAZARD_SHORT[info.key], "faint"))
        top.addLayout(txt, 1)
        self.switch = Switch(color=HAZARD_COLOR[info.key])
        top.addWidget(self.switch)
        v.addLayout(top)
        self.slider_box = QWidget()
        hl = QHBoxLayout(self.slider_box)
        hl.setContentsMargins(42, 2, 2, 2)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(5, 100)
        self.slider.setValue(int(level * 100))
        self.slider.setStyleSheet(
            f"QSlider::sub-page:horizontal {{ background: {HAZARD_COLOR[info.key]}; }}"
            f"QSlider::handle:horizontal {{ background: {HAZARD_COLOR[info.key]}; }}")
        self.val = label(f"{int(level * 100)} %", "caption")
        self.val.setFixedWidth(40)
        self.val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.slider.valueChanged.connect(self._on_slider)
        hl.addWidget(self.slider, 1)
        hl.addWidget(self.val)
        v.addWidget(self.slider_box)
        self._anim = QPropertyAnimation(self.slider_box, b"maximumHeight", self)
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.switch.setChecked(enabled)
        self.badge.active = enabled
        self.slider_box.setMaximumHeight(30 if enabled else 0)
        self._style(enabled)
        self.switch.toggled.connect(self._on_toggle)

    def _style(self, on: bool) -> None:
        self.setStyleSheet(
            f"QFrame#hazRow {{ background: {P['surface_alt'] if on else 'transparent'};"
            f" border-left: 2px solid {P['accent'] if on else 'transparent'}; }}")

    def _on_toggle(self, on: bool) -> None:
        self.badge.active = on
        self.badge.update()
        self._style(on)
        self._anim.stop()
        self._anim.setStartValue(self.slider_box.maximumHeight())
        self._anim.setEndValue(30 if on else 0)
        self._anim.start()
        self.toggled.emit(self.key, on)

    def _on_slider(self, v: int) -> None:
        self.val.setText(f"{v} %")
        self.intensity.emit(self.key, v / 100.0)

    def set_checked(self, on: bool) -> None:
        if self.switch.isChecked() != on:
            self.switch.setChecked(on)
            self._on_toggle(on)


class ControlRail(QWidget):
    def __init__(self, engine, tab: str = "remote", parent=None) -> None:
        super().__init__(parent)
        self.engine = engine
        self._rev = -1
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self.tabs = Segmented([("remote", "Remote B"), ("ground", "Ground A"), ("env", "Environment")],
                              compact=True, tabs=True)
        v.addWidget(self.tabs)
        self.stack = QStackedWidget()
        v.addWidget(self.stack, 1)
        self.stack.addWidget(self._remote_page())
        self.stack.addWidget(self._ground_page())
        self.stack.addWidget(self._env_page())
        self.tabs.changed.connect(self._tab)
        self.tabs.set_current(tab)
        self._tab(tab)
        self.sync(force=True)

    def current_tab(self) -> str:
        return ("remote", "ground", "env")[self.stack.currentIndex()]

    def _tab(self, key: str) -> None:
        self.stack.setCurrentIndex({"remote": 0, "ground": 1, "env": 2}[key])

    # ================================================================== remote
    def _remote_page(self) -> QWidget:
        inner = QWidget()
        col = QVBoxLayout(inner)
        col.setContentsMargins(0, 0, 6, 0)
        col.setSpacing(12)

        pc = Card("Terminal type", info=tip("platform"))
        grid = QGridLayout()
        grid.setSpacing(8)
        self.platform_tiles = {}
        grp = QButtonGroup(self)
        for i, plat in enumerate(PLATFORMS):
            tile = IconTile(plat.key, plat.name, plat.key)
            tile.setToolTip(plat.summary)
            tile.clicked.connect(lambda _=False, k=plat.key: self._choose_platform(k))
            grp.addButton(tile)
            grid.addWidget(tile, i // 3, i % 3)
            self.platform_tiles[plat.key] = tile
        pc.body.addLayout(grid)
        col.addWidget(pc)

        mc = Card("Movement", info=tip("motion"))
        self.pattern_grid = QGridLayout()
        self.pattern_grid.setSpacing(8)
        mc.body.addLayout(self.pattern_grid)
        self.pattern_desc = label("", "caption", wrap=True)
        mc.body.addWidget(self.pattern_desc)
        self.drag_hint = label("Tip: drag Terminal B in the world view to steer it yourself.", "faint", wrap=True)
        mc.body.addWidget(self.drag_hint)
        col.addWidget(mc)
        self._pattern_group = QButtonGroup(self)
        self.pattern_tiles = {}

        self.controls_card = Card("Motion controls", info=tip("controls"))
        self.controls_box = QVBoxLayout()
        self.controls_box.setSpacing(6)
        self.controls_card.body.addLayout(self.controls_box)
        col.addWidget(self.controls_card)
        self.sliders = {}

        bc = Card("Beacon signal", info=tip("beacon"))
        st = self.engine.remote_state()
        self.s_freq = ValueSlider("Blink rate", 2.0, 12.0, st["beacon_freq"], 0.1, lambda v: f"{v:.1f} Hz", tip("freq"))
        self.s_bright = ValueSlider("Brightness", 0.05, 1.0, st["beacon_brightness"], 0.01,
                                    lambda v: f"{v * 100:.0f} %", tip("brightness"))
        self.s_depth = ValueSlider("Blink depth", 0.0, 1.0, st["beacon_depth"], 0.01,
                                   lambda v: f"{v * 100:.0f} %", tip("depth"))
        self.s_freq.changed.connect(lambda v: self.engine.set_beacon(freq_hz=v))
        self.s_bright.changed.connect(lambda v: self.engine.set_beacon(brightness=v))
        self.s_depth.changed.connect(lambda v: self.engine.set_beacon(depth=v))
        for w in (self.s_freq, self.s_bright, self.s_depth):
            bc.body.addWidget(w)
        rnd = QPushButton("Randomise beacon")
        rnd.setToolTip("Pick a new blink rate — watch the tracker re-learn it.")
        rnd.clicked.connect(self._random_beacon)
        bc.body.addWidget(rnd)
        col.addWidget(bc)
        col.addStretch(1)
        return _scroll(inner)

    def _random_beacon(self) -> None:
        f = round(random.uniform(2.5, 9.5), 1)
        self.s_freq.set_value(f)
        self.engine.set_beacon(freq_hz=f)

    def _choose_platform(self, key: str) -> None:
        self.engine.set_platform(key)
        self._rebuild_patterns(key, None)
        self._rebuild_controls(key)

    def _choose_pattern(self, key: str) -> None:
        self.engine.set_pattern(key)
        info = next(p for p in PATTERN_INFOS if p.key == key)
        self.pattern_desc.setText(f"{info.summary}  ·  {info.speed}")

    def _rebuild_patterns(self, platform: str, current) -> None:
        while self.pattern_grid.count():
            w = self.pattern_grid.takeAt(0).widget()
            if w:
                self._pattern_group.removeButton(w)
                w.deleteLater()
        self.pattern_tiles = {}
        pats = [p for p in PATTERN_INFOS if p.platform == platform]
        defaults = {"quad": "hover", "fixedwing": "orbit", "ship": "maritime", "satellite": "leo_pass",
                    "station": "iss_pass"}
        current = current or defaults[platform]
        for i, info in enumerate(pats):
            tile = PatternTile(info.key, info.name, info.platform)
            tile.setToolTip(info.summary)
            tile.clicked.connect(lambda _=False, k=info.key: self._choose_pattern(k))
            self._pattern_group.addButton(tile)
            self.pattern_grid.addWidget(tile, i // 2, i % 2)
            self.pattern_tiles[info.key] = tile
            if info.key == current:
                tile.setChecked(True)
                self.pattern_desc.setText(f"{info.summary}  ·  {info.speed}")
        self.drag_hint.setVisible(platform in ("quad", "fixedwing", "ship"))

    def _rebuild_controls(self, platform: str) -> None:
        while self.controls_box.count():
            w = self.controls_box.takeAt(0).widget()
            if w:
                w.deleteLater()
        st = self.engine.remote_state()
        e = self.engine
        space = platform in ("satellite", "station")
        s = {}
        if space:
            s["speed"] = ValueSlider("Time speed", 1.0, 20.0, max(1.0, st["speed"]), 0.5, lambda v: f"{v:.1f}×",
                                     tip("time_warp"))
            s["speed"].changed.connect(lambda v: e.set_remote(speed=v))
            if platform == "satellite":
                s["alt"] = ValueSlider("Orbit altitude", 350, 1500, st["orbit_alt"], 10, lambda v: f"{v:.0f} km",
                                       tip("orbit_alt"))
                s["alt"].slider.sliderReleased.connect(lambda: e.set_orbit(alt_km=s["alt"].value()))
            s["max_el"] = ValueSlider("Highest point", 15, 78, st["max_el"], 1, lambda v: f"{v:.0f}°", tip("max_el"))
            s["max_el"].slider.sliderReleased.connect(lambda: e.set_orbit(max_el=s["max_el"].value()))
            s["heading"] = ValueSlider("Pass direction", 0, 355, st["heading"], 5, lambda v: f"{v:.0f}°", tip("heading"))
            s["heading"].slider.sliderReleased.connect(lambda: e.set_orbit(heading=s["heading"].value()))
            s["var"] = ValueSlider("Attitude wobble", 0.0, 1.0, st["variation"], 0.01, lambda v: f"{v * 100:.0f} %",
                                   tip("variation"))
            s["var"].changed.connect(lambda v: e.set_remote(variation=v))
        else:
            s["speed"] = ValueSlider("Speed", 0.25, 3.0, st["speed"], 0.05, lambda v: f"{v:.2f}×", tip("speed"))
            s["speed"].changed.connect(lambda v: e.set_remote(speed=v))
            key = st["pattern"]
            cen = AERIAL_CENTER.get(key, (0, 170, 1900))
            natural = (cen[0] ** 2 + cen[2] ** 2) ** 0.5 / 1000.0
            s["range"] = ValueSlider("Distance", 0.6, 4.5, st["range_km"] or natural, 0.05,
                                     lambda v: f"{v:.2f} km", tip("distance"))
            s["range"].changed.connect(lambda v: e.set_remote(range_km=v))
            s["bearing"] = ValueSlider("Direction", -45, 45, st["bearing"], 1, lambda v: f"{v:+.0f}°", tip("bearing"))
            s["bearing"].changed.connect(lambda v: e.set_remote(bearing=v))
            if platform != "ship":
                s["alt"] = ValueSlider("Altitude", -100, 400, st["altitude"], 5, lambda v: f"{v:+.0f} m",
                                       tip("altitude"))
                s["alt"].changed.connect(lambda v: e.set_remote(altitude=v))
            s["var"] = ValueSlider("Real-world variation", 0.0, 1.0, st["variation"], 0.01,
                                   lambda v: f"{v * 100:.0f} %", tip("variation"))
            s["var"].changed.connect(lambda v: e.set_remote(variation=v))
        for w in s.values():
            self.controls_box.addWidget(w)
        self.sliders = s

    def _rebuild_ground_position(self, mount: str) -> None:
        while self.pos_box.count():
            w = self.pos_box.takeAt(0).widget()
            if w:
                w.deleteLater()
        st = self.engine.remote_state()
        e = self.engine
        g = {}
        if mount == "satellite":
            g["alt"] = ValueSlider("Orbit altitude", 350, 1500, st["ground_orbit_alt"], 10,
                                   lambda v: f"{v:.0f} km", tip("orbit_alt"))
            g["alt"].slider.sliderReleased.connect(lambda: e.set_ground_orbit(alt_km=g["alt"].value()))
            g["incl"] = ValueSlider("Inclination", 0, 98, st["ground_incl"], 1, lambda v: f"{v:.0f}°", tip("incl"))
            g["incl"].slider.sliderReleased.connect(lambda: e.set_ground_orbit(incl=g["incl"].value()))
            g["heading"] = ValueSlider("Orbital heading", 0, 355, st["ground_heading"], 5,
                                       lambda v: f"{v:.0f}°", tip("heading"))
            g["heading"].slider.sliderReleased.connect(lambda: e.set_ground_orbit(heading=g["heading"].value()))
            self.pos_hint.setText("Your own terminal is now in orbit too — a satellite-to-satellite crosslink. "
                                  "Pick a satellite or space-station pattern for Remote B to complete the pair.")
        else:
            g["east"] = ValueSlider("East offset", -1500, 1500, st["ground_x"], 10, lambda v: f"{v:+.0f} m",
                                    tip("east"))
            g["east"].changed.connect(lambda v: e.set_ground(x=v))
            g["north"] = ValueSlider("North offset", -1000, 1500, st["ground_z"], 10, lambda v: f"{v:+.0f} m",
                                     tip("north"))
            g["north"].changed.connect(lambda v: e.set_ground(z=v))
            g["height"] = ValueSlider("Mast height", 2, 30, st["ground_h"], 0.5, lambda v: f"{v:.1f} m", tip("height"))
            g["height"].changed.connect(lambda v: e.set_ground(height=v))
            self.pos_hint.setText("Tip: drag Terminal A in the world view to move your station.")
        for w in g.values():
            self.pos_box.addWidget(w)
        self.ground_sliders = g

    # ================================================================== ground
    def _ground_page(self) -> QWidget:
        inner = QWidget()
        col = QVBoxLayout(inner)
        col.setContentsMargins(0, 0, 6, 0)
        col.setSpacing(12)
        st = self.engine.remote_state()

        mc = Card("Mount", info=tip("mount"))
        row = QHBoxLayout()
        row.setSpacing(8)
        grp = QButtonGroup(self)
        self.mount_tiles = {}
        for m in MOUNTS:
            tile = IconTile(m.key, m.name, "ship" if m.key == "ship" else m.key)
            tile.setToolTip(m.summary)
            tile.clicked.connect(lambda _=False, k=m.key: self.engine.set_ground(mount=k))
            grp.addButton(tile)
            row.addWidget(tile)
            self.mount_tiles[m.key] = tile
        mc.body.addLayout(row)
        col.addWidget(mc)

        self.pos_card = Card("Position", info=tip("position"))
        self.pos_box = QVBoxLayout()
        self.pos_card.body.addLayout(self.pos_box)
        self.pos_hint = label("", "faint", wrap=True)
        self.pos_card.body.addWidget(self.pos_hint)
        self._rebuild_ground_position(st["mount"])
        col.addWidget(self.pos_card)

        gc = Card("Gimbal", info=tip("gimbal"))
        self.g_slew = ValueSlider("Maximum turn speed", 5, 60, st["max_slew"], 1, lambda v: f"{v:.0f} °/s", tip("slew"))
        self.g_slew.changed.connect(self.engine.set_max_slew)
        gc.body.addWidget(self.g_slew)
        col.addWidget(gc)
        col.addStretch(1)
        return _scroll(inner)

    # ============================================================== environment
    def _env_page(self) -> QWidget:
        inner = QWidget()
        col = QVBoxLayout(inner)
        col.setContentsMargins(0, 0, 6, 0)
        col.setSpacing(12)

        ic = Card("Input source", "The exact same tracking pipeline — simulator or a real recording",
                  info=tip("input_source"))
        row = QHBoxLayout()
        row.setSpacing(8)
        self.video_btn = QPushButton("Load video…")
        self.video_btn.clicked.connect(self._pick_video)
        self.sim_btn = QPushButton("Back to simulation")
        self.sim_btn.setObjectName("ghost")
        self.sim_btn.clicked.connect(self.engine.use_simulation)
        row.addWidget(self.video_btn)
        row.addWidget(self.sim_btn)
        ic.body.addLayout(row)
        self.video_status = label("Simulation running.", "faint", wrap=True)
        ic.body.addWidget(self.video_status)
        col.addWidget(ic)

        tc = Card("Time of day", info=tip("tod"))
        self.tod = Segmented([("day", "Day"), ("dusk", "Dusk"), ("night", "Night")])
        self.tod.changed.connect(self.engine.set_time_of_day)
        tc.body.addWidget(self.tod)
        col.addWidget(tc)

        hc = Card("Hazards", "Mix any combination — changes fade in smoothly", info=tip("hazards"))
        clear = QPushButton("Clear all")
        clear.setObjectName("ghost")
        clear.clicked.connect(self.clear_hazards)
        hc.header.addWidget(clear, 0, Qt.AlignmentFlag.AlignTop)
        hc.body.setSpacing(2)
        hz = self.engine.world.hazards
        self.rows = {}
        for info in HAZARD_INFOS:
            row = HazardRow(info, hz.enabled[info.key], hz.intensity[info.key])
            row.toggled.connect(lambda k, on: self.engine.set_hazard(k, on))
            row.intensity.connect(lambda k, val: self.engine.set_hazard(k, intensity=val))
            hc.body.addWidget(row)
            self.rows[info.key] = row
        col.addWidget(hc)
        col.addStretch(1)
        return _scroll(inner)

    def clear_hazards(self) -> None:
        for row in self.rows.values():
            row.set_checked(False)

    def _pick_video(self) -> None:
        start = ""
        for base in (os.path.dirname(os.path.abspath(sys.executable)) if getattr(sys, "frozen", False)
                     else os.getcwd(),):
            cand = os.path.join(base, "demo_videos")
            if os.path.isdir(cand):
                start = cand
                break
        path, _ = QFileDialog.getOpenFileName(self, "Load a recorded video", start,
                                              "Video files (*.mp4 *.avi *.mov *.mkv *.webm);;All files (*)")
        if path:
            self.engine.load_video(path)

    def _refresh_video_status(self) -> None:
        e = self.engine
        if e.video_error:
            self.video_status.setText(f"Could not open that file: {e.video_error}")
        elif e.is_video:
            self.video_status.setText(f"Tracking “{os.path.basename(e._video_path)}” — loops when it ends. "
                                      "Click the light you want in the camera view to pick the target by hand. "
                                      "A recording has no ground truth, so tracking error is measured against "
                                      "the detected spot instead.")
        else:
            self.video_status.setText("Simulation running.")

    # ==================================================================== sync
    def sync(self, force: bool = False) -> None:
        """Reflect engine-side changes (e.g. drag switched to Manual, space switched to night)."""
        if not force and self._rev == self.engine.ui_revision:
            return
        self._rev = self.engine.ui_revision
        st = self.engine.remote_state()
        plat = st["platform"]
        self.platform_tiles[plat].setChecked(True)
        self._rebuild_patterns(plat, st["pattern"])
        self._rebuild_controls(plat)
        self.mount_tiles[st["mount"]].setChecked(True)
        self._rebuild_ground_position(st["mount"])
        self.tod.set_current(st["time_of_day"])
        self._refresh_video_status()
