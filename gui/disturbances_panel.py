"""
gui/disturbances_panel.py — Disturbances & Conditions Control Panel (Stage 2).

Provides controls for:
  - Atmospheric conditions (Clear/Haze/Fog/Rain/Low Light)
  - Sensor noise (Off/Low/Medium/High/Custom)
  - Turbulence (Off/Low/Medium/High)
  - Camera jitter (Off/Low/Medium/High/Custom)
  - Platform motion (None/Linear/Circular/Random/Figure Eight)
  - Target dropout (Off/0.5s/Random)
  - Starfield density (Sparse/Normal/Dense)
  - Beacon count (1/3)
  - Search pattern (Spiral/Raster)

Also provides debug overlay toggles:
  - Show Ground Truth
  - Show Detection Centroid
  - Show Tracker Prediction
  - Show Detection Candidates
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QComboBox, QSlider, QGroupBox, QCheckBox, QFrame, QScrollArea,
)


class DisturbancesPanel(QWidget):
    """Disturbances & Conditions Control Panel for Stage 2."""

    # Signals to engine
    atmosphere_changed      = Signal(str)
    noise_level_changed     = Signal(str)
    noise_sigma_changed     = Signal(float)
    turbulence_changed      = Signal(str)
    jitter_level_changed    = Signal(str)
    jitter_custom_changed   = Signal(float)
    platform_motion_changed = Signal(str)
    platform_strength_changed = Signal(float)
    fog_density_changed     = Signal(float)
    rain_intensity_changed  = Signal(float)
    dropout_changed         = Signal(str)
    starfield_density_changed = Signal(str)
    beacon_count_changed    = Signal(int)
    search_mode_changed     = Signal(str)
    beacon_intensity_changed = Signal(float)

    # Debug overlay toggle signals
    show_gt_changed         = Signal(bool)
    show_detection_changed  = Signal(bool)
    show_prediction_changed = Signal(bool)
    show_candidates_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(8, 6, 8, 8)
        layout.setSpacing(7)

        # ── 1. Atmospheric Conditions ─────────────────────────────────────
        atm_grp = QGroupBox("ATMOSPHERIC CONDITIONS")
        atm_layout = QVBoxLayout(atm_grp)
        atm_layout.setContentsMargins(8, 10, 8, 8)
        atm_layout.setSpacing(5)

        self.combo_atm = self._combo(["Clear", "Haze", "Fog", "Rain", "Low Light"])
        self.combo_atm.currentTextChanged.connect(self._on_atm_changed)
        atm_layout.addLayout(self._labeled_row("Atmosphere:", self.combo_atm))

        # Fog density
        self._fog_row, self.slider_fog_density, self.lbl_fog_val = self._make_slider(
            "Fog/Haze Density:", "0.50", 0, 100, 50, self._on_fog_density
        )
        atm_layout.addLayout(self._fog_row)

        # Rain intensity
        self._rain_row, self.slider_rain, self.lbl_rain_val = self._make_slider(
            "Rain Intensity:", "0.50", 0, 100, 50, self._on_rain_intensity
        )
        atm_layout.addLayout(self._rain_row)

        layout.addWidget(atm_grp)

        # ── 2. Sensor Noise ───────────────────────────────────────────────
        noise_grp = QGroupBox("SENSOR NOISE")
        noise_layout = QVBoxLayout(noise_grp)
        noise_layout.setContentsMargins(8, 10, 8, 8)
        noise_layout.setSpacing(5)

        self.combo_noise = self._combo(["Off", "Low", "Medium", "High", "Custom"])
        self.combo_noise.setCurrentText("Low")
        self.combo_noise.currentTextChanged.connect(self._on_noise_level)
        noise_layout.addLayout(self._labeled_row("Noise Level:", self.combo_noise))

        self._noise_sigma_row, self.slider_noise_sigma, self.lbl_noise_sigma = self._make_slider(
            "Custom σ:", "5.0", 0, 50, 5, self._on_noise_sigma
        )
        atm_layout.setSpacing(5)
        noise_layout.addLayout(self._noise_sigma_row)

        layout.addWidget(noise_grp)

        # ── 3. Turbulence ─────────────────────────────────────────────────
        turb_grp = QGroupBox("TURBULENCE")
        turb_layout = QVBoxLayout(turb_grp)
        turb_layout.setContentsMargins(8, 10, 8, 8)

        self.combo_turb = self._combo(["Off", "Low", "Medium", "High"])
        self.combo_turb.currentTextChanged.connect(
            lambda t: self.turbulence_changed.emit(t.lower())
        )
        turb_layout.addLayout(self._labeled_row("Turbulence:", self.combo_turb))

        layout.addWidget(turb_grp)

        # ── 4. Camera Jitter ──────────────────────────────────────────────
        jitter_grp = QGroupBox("CAMERA JITTER")
        jitter_layout = QVBoxLayout(jitter_grp)
        jitter_layout.setContentsMargins(8, 10, 8, 8)
        jitter_layout.setSpacing(5)

        self.combo_jitter = self._combo(["Off", "Low", "Medium", "High", "Custom"])
        self.combo_jitter.currentTextChanged.connect(self._on_jitter_level)
        jitter_layout.addLayout(self._labeled_row("Jitter:", self.combo_jitter))

        self._jitter_row, self.slider_jitter, self.lbl_jitter_val = self._make_slider(
            "Custom ±px:", "5 px", 0, 25, 5, self._on_jitter_custom
        )
        jitter_layout.addLayout(self._jitter_row)

        layout.addWidget(jitter_grp)

        # ── 5. Platform Motion ────────────────────────────────────────────
        plat_grp = QGroupBox("PLATFORM DISTURBANCE")
        plat_layout = QVBoxLayout(plat_grp)
        plat_layout.setContentsMargins(8, 10, 8, 8)
        plat_layout.setSpacing(5)

        self.combo_platform = self._combo(
            ["None", "Linear", "Circular", "Random", "Figure Eight"]
        )
        self.combo_platform.currentTextChanged.connect(self._on_platform)
        plat_layout.addLayout(self._labeled_row("Platform Motion:", self.combo_platform))

        self._plat_row, self.slider_platform, self.lbl_platform_val = self._make_slider(
            "Strength:", "50%", 0, 100, 50, self._on_platform_strength
        )
        plat_layout.addLayout(self._plat_row)

        layout.addWidget(plat_grp)

        # ── 6. Beacon & Starfield ─────────────────────────────────────────
        scene_grp = QGroupBox("SCENE CONFIGURATION")
        scene_layout = QVBoxLayout(scene_grp)
        scene_layout.setContentsMargins(8, 10, 8, 8)
        scene_layout.setSpacing(5)

        # Beacon intensity
        self._bi_row, self.slider_bi, self.lbl_bi_val = self._make_slider(
            "Beacon Intensity:", "1.0×", 2, 30, 10, self._on_bi
        )
        scene_layout.addLayout(self._bi_row)

        # Target dropout
        self.combo_dropout = self._combo(["Off", "0.5s Dropout", "Random Dropout"])
        self.combo_dropout.currentTextChanged.connect(self._on_dropout)
        scene_layout.addLayout(self._labeled_row("Target Dropout:", self.combo_dropout))

        # Starfield density
        self.combo_stars = self._combo(["Sparse", "Normal", "Dense"])
        self.combo_stars.setCurrentText("Normal")
        self.combo_stars.currentTextChanged.connect(
            lambda t: self.starfield_density_changed.emit(t.lower())
        )
        scene_layout.addLayout(self._labeled_row("Starfield:", self.combo_stars))

        # Beacon count
        self.combo_beacons = self._combo(["1 Beacon (primary)", "3 Beacons (+ distractors)"])
        self.combo_beacons.currentTextChanged.connect(self._on_beacon_count)
        scene_layout.addLayout(self._labeled_row("Active Beacons:", self.combo_beacons))

        # Search pattern
        self.combo_search = self._combo(["Spiral Search", "Raster Search"])
        self.combo_search.currentTextChanged.connect(self._on_search)
        scene_layout.addLayout(self._labeled_row("Search Mode:", self.combo_search))

        layout.addWidget(scene_grp)

        # ── 7. Debug Overlays ─────────────────────────────────────────────
        dbg_grp = QGroupBox("DEBUG OVERLAYS")
        dbg_layout = QVBoxLayout(dbg_grp)
        dbg_layout.setContentsMargins(8, 10, 8, 8)
        dbg_layout.setSpacing(3)

        self.chk_gt = self._checkbox("Show Ground Truth (green)", True)
        self.chk_gt.toggled.connect(self.show_gt_changed.emit)
        self.chk_det = self._checkbox("Show Detection Centroid (cyan)", True)
        self.chk_det.toggled.connect(self.show_detection_changed.emit)
        self.chk_pred = self._checkbox("Show Tracker Prediction (yellow)", True)
        self.chk_pred.toggled.connect(self.show_prediction_changed.emit)
        self.chk_cand = self._checkbox("Show All Candidates (dim dots)", False)
        self.chk_cand.toggled.connect(self.show_candidates_changed.emit)

        dbg_layout.addWidget(self.chk_gt)
        dbg_layout.addWidget(self.chk_det)
        dbg_layout.addWidget(self.chk_pred)
        dbg_layout.addWidget(self.chk_cand)

        layout.addWidget(dbg_grp)
        layout.addStretch()

        scroll.setWidget(content)
        main_layout.addWidget(scroll)

    # ── Slot handlers ─────────────────────────────────────────────────────

    def _on_atm_changed(self, text: str) -> None:
        mapping = {
            "Clear": "clear", "Haze": "haze", "Fog": "fog",
            "Rain": "rain", "Low Light": "low_light"
        }
        self.atmosphere_changed.emit(mapping.get(text, "clear"))

    def _on_noise_level(self, text: str) -> None:
        self.noise_level_changed.emit(text.lower().replace(" ", "_"))

    def _on_noise_sigma(self, value: int) -> None:
        sigma = float(value)
        self.lbl_noise_sigma.setText(f"{sigma:.0f}")
        self.noise_sigma_changed.emit(sigma)

    def _on_fog_density(self, value: int) -> None:
        v = value / 100.0
        self.lbl_fog_val.setText(f"{v:.2f}")
        self.fog_density_changed.emit(v)

    def _on_rain_intensity(self, value: int) -> None:
        v = value / 100.0
        self.lbl_rain_val.setText(f"{v:.2f}")
        self.rain_intensity_changed.emit(v)

    def _on_jitter_level(self, text: str) -> None:
        self.jitter_level_changed.emit(text.lower())

    def _on_jitter_custom(self, value: int) -> None:
        px = float(value)
        self.lbl_jitter_val.setText(f"{px:.0f} px")
        self.jitter_custom_changed.emit(px)

    def _on_platform(self, text: str) -> None:
        mapping = {
            "None": "none", "Linear": "linear", "Circular": "circular",
            "Random": "random", "Figure Eight": "figure_eight"
        }
        self.platform_motion_changed.emit(mapping.get(text, "none"))

    def _on_platform_strength(self, value: int) -> None:
        v = value / 100.0
        self.lbl_platform_val.setText(f"{int(value)}%")
        self.platform_strength_changed.emit(v)

    def _on_bi(self, value: int) -> None:
        v = value / 10.0
        self.lbl_bi_val.setText(f"{v:.1f}×")
        self.beacon_intensity_changed.emit(v)

    def _on_dropout(self, text: str) -> None:
        mapping = {"Off": "off", "0.5s Dropout": "0.5s", "Random Dropout": "random"}
        self.dropout_changed.emit(mapping.get(text, "off"))

    def _on_beacon_count(self, text: str) -> None:
        count = 3 if "3" in text else 1
        self.beacon_count_changed.emit(count)

    def _on_search(self, text: str) -> None:
        mode = "raster" if "Raster" in text else "spiral"
        self.search_mode_changed.emit(mode)

    # ── Factory helpers ───────────────────────────────────────────────────

    @staticmethod
    def _combo(items) -> QComboBox:
        cb = QComboBox()
        cb.addItems(items)
        cb.setFixedHeight(26)
        return cb

    @staticmethod
    def _labeled_row(label: str, widget) -> QHBoxLayout:
        row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setStyleSheet("color: #8b949e; font-size: 11px;")
        row.addWidget(lbl)
        row.addStretch()
        row.addWidget(widget)
        row.setContentsMargins(0, 0, 0, 0)
        return row

    @staticmethod
    def _make_slider(label, default_val, min_v, max_v, init_v, callback):
        box = QVBoxLayout()
        box.setSpacing(1)
        hdr = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setStyleSheet("color: #8b949e; font-size: 11px;")
        val_lbl = QLabel(default_val)
        val_lbl.setStyleSheet("color: #e6edf3; font-weight: bold; font-size: 11px;")
        hdr.addWidget(lbl)
        hdr.addStretch()
        hdr.addWidget(val_lbl)
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(min_v, max_v)
        slider.setValue(init_v)
        slider.valueChanged.connect(callback)
        box.addLayout(hdr)
        box.addWidget(slider)
        return box, slider, val_lbl

    @staticmethod
    def _checkbox(label: str, default: bool) -> QCheckBox:
        cb = QCheckBox(label)
        cb.setChecked(default)
        cb.setStyleSheet("font-size: 11px; color: #c9d1d9;")
        return cb
