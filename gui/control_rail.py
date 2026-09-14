"""Left rail: beacon pattern picker and hazard mixer."""

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, Signal
from PySide6.QtWidgets import (QButtonGroup, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
                               QSlider, QVBoxLayout, QWidget)

from fsoc.sim.hazards import HAZARD_INFOS
from fsoc.sim.patterns import PATTERN_INFOS
from .theme import HAZARD_COLOR, P
from .widgets import Card, IconBadge, PatternTile, Pill, Switch, label

HAZARD_SHORT = {
    "fog": "Visibility down to 2 km",
    "rain": "Streaks, drops, attenuation",
    "turbulence": "Scintillation & beam wander",
    "noise": "Read noise, hot pixels",
    "vibration": "11–21 Hz LOS jitter",
    "glare": "Veiling glare near the sun",
    "occlusion": "Birds, branches, cloud",
    "decoys": "False lights near target",
}


class HazardRow(QFrame):
    toggled = Signal(str, bool)
    intensity = Signal(str, float)

    def __init__(self, info, parent=None) -> None:
        super().__init__(parent)
        self.key = info.key
        self.setObjectName("hazRow")
        self.setToolTip(info.summary)
        v = QVBoxLayout(self)
        v.setContentsMargins(8, 6, 8, 6)
        v.setSpacing(2)
        top = QHBoxLayout()
        top.setSpacing(10)
        self.badge = IconBadge("hazard", info.key, 32)
        top.addWidget(self.badge)
        txt = QVBoxLayout()
        txt.setSpacing(0)
        name = label(info.name, "h2")
        name.setStyleSheet("font-size: 9.6pt;")
        txt.addWidget(name)
        txt.addWidget(label(HAZARD_SHORT[info.key], "faint"))
        top.addLayout(txt, 1)
        self.switch = Switch(color=HAZARD_COLOR[info.key])
        self.switch.toggled.connect(self._on_toggle)
        top.addWidget(self.switch)
        v.addLayout(top)

        self.slider_box = QWidget()
        hl = QHBoxLayout(self.slider_box)
        hl.setContentsMargins(42, 2, 2, 2)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(5, 100)
        self.slider.setValue(int(info.default * 100))
        self.slider.setStyleSheet(
            f"QSlider::sub-page:horizontal {{ background: {HAZARD_COLOR[info.key]}; border-radius: 2px; }}"
            f"QSlider::handle:horizontal {{ border-color: {HAZARD_COLOR[info.key]}; }}")
        self.val = label(f"{int(info.default * 100)} %", "caption")
        self.val.setFixedWidth(40)
        self.val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.slider.valueChanged.connect(self._on_slider)
        hl.addWidget(self.slider, 1)
        hl.addWidget(self.val)
        self.slider_box.setMaximumHeight(0)
        v.addWidget(self.slider_box)
        self._anim = QPropertyAnimation(self.slider_box, b"maximumHeight", self)
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._style(False)

    def _style(self, on: bool) -> None:
        bg = P["surface_alt"] if on else "transparent"
        self.setStyleSheet(f"QFrame#hazRow {{ background: {bg}; border-radius: 10px; }}")

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


class ControlRail(QScrollArea):
    pattern_changed = Signal(str)
    hazard_toggled = Signal(str, bool)
    hazard_intensity = Signal(str, float)

    def __init__(self, initial_pattern: str = "orbit", parent=None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        col = QVBoxLayout(inner)
        col.setContentsMargins(0, 0, 6, 0)
        col.setSpacing(14)

        # ---- patterns
        pc = Card("Beacon pattern", "How the remote terminal moves")
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        self.tiles = {}
        group = QButtonGroup(self)
        group.setExclusive(True)
        for i, info in enumerate(PATTERN_INFOS):
            tile = PatternTile(info.key, info.name, info.platform)
            tile.setToolTip(info.summary)
            tile.clicked.connect(lambda _=False, k=info.key: self._select(k))
            group.addButton(tile)
            grid.addWidget(tile, i // 2, i % 2)
            self.tiles[info.key] = tile
        pc.body.addLayout(grid)
        self.desc = label("", "caption", wrap=True)
        self.speed = Pill("", "accent", size=7.8)
        drow = QHBoxLayout()
        drow.addWidget(self.desc, 1)
        pc.body.addLayout(drow)
        srow = QHBoxLayout()
        srow.addWidget(self.speed)
        srow.addStretch(1)
        pc.body.addLayout(srow)
        col.addWidget(pc)

        # ---- hazards
        hc = Card("Hazards", "Mix any combination — changes fade in smoothly")
        self.clear_btn = QPushButton("Clear all")
        self.clear_btn.setObjectName("ghost")
        self.clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_btn.clicked.connect(self.clear_hazards)
        hc.header.addWidget(self.clear_btn, 0, Qt.AlignmentFlag.AlignTop)
        hc.body.setSpacing(2)
        self.rows = {}
        for info in HAZARD_INFOS:
            row = HazardRow(info)
            row.toggled.connect(self.hazard_toggled)
            row.intensity.connect(self.hazard_intensity)
            hc.body.addWidget(row)
            self.rows[info.key] = row
        col.addWidget(hc)
        col.addStretch(1)
        self.setWidget(inner)
        self._select(initial_pattern, emit=False)

    def _select(self, key: str, emit: bool = True) -> None:
        info = next(p for p in PATTERN_INFOS if p.key == key)
        self.tiles[key].setChecked(True)
        self.desc.setText(info.summary)
        self.speed.setText(f"speed {info.speed}")
        if emit:
            self.pattern_changed.emit(key)

    def clear_hazards(self) -> None:
        for row in self.rows.values():
            row.set_checked(False)
