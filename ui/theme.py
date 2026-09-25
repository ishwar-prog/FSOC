"""Design system: a flat, grid-based light theme built on Inter.

One light scheme only. Panels are separated by 1px hairlines and background tone,
never by rounded corners or shadows. Colour is reserved for state — a lock, a pass,
a failure — so a glance at the window tells you what the tracker is doing.
"""

import os
import sys
from typing import Optional

from PySide6.QtGui import QColor, QFont, QFontDatabase, QLinearGradient

# --------------------------------------------------------------------------- tokens
P = {
    # surfaces — flat tones, contrast comes from the step between them
    "bg": "#F1F2F6", "surface": "#FFFFFF", "surface_alt": "#F7F8FA", "overlay": "#FFFFFF",
    # rules
    "border": "#E2E4EA", "border_strong": "#D3D7DF",
    # type ramp
    "head": "#0B1120", "text": "#181818", "muted": "#5A6070", "faint": "#8A909C", "ink": "#0B1120",
    # primary — navigation, selection, controls
    "accent": "#44B6FF", "accent_ink": "#0A5C96", "accent_hover": "#1C9AEE", "accent_soft": "#E9F5FE",
    # state
    "mint": "#08B44D", "mint_ink": "#067A36", "mint_soft": "#E4F6EB",
    "peach": "#C93B37", "peach_ink": "#A32E2B", "peach_soft": "#F9E8E7",
    "sky": "#2E9BE0", "sky_ink": "#0A5C96", "sky_soft": "#E9F5FE",
    "butter": "#B8801B", "butter_ink": "#8A5F12", "butter_soft": "#FBF1DF",
    "rose": "#C93B37", "rose_ink": "#A32E2B", "rose_soft": "#F9E8E7",
    "faint_soft": "#EDEFF3", "faint_ink": "#5A6070",
}

#: Gradients fade a live colour into the deep navy that anchors the palette.
GRAD_PRIMARY = ("#44B6FF", "#0B1120")
GRAD_SUCCESS = ("#08B44D", "#0B1120")
GRAD_INK = ("#181818", "#0B1120")

UNIT = 8          #: spacing grid — every margin and gap is a multiple of this
HAIRLINE = 1      #: the only divider we draw

FONT_UI = "Inter"
FONT_MONO = "Cascadia Mono"


def grad(stops=GRAD_PRIMARY, x0: float = 0.0, y0: float = 0.0, x1: float = 1.0, y1: float = 0.0) -> QLinearGradient:
    """QPainter gradient in object coordinates (0..1 on both axes)."""
    g = QLinearGradient(x0, y0, x1, y1)
    g.setCoordinateMode(QLinearGradient.CoordinateMode.ObjectBoundingMode)
    g.setColorAt(0.0, QColor(stops[0]))
    g.setColorAt(1.0, QColor(stops[1]))
    return g


def grad_px(stops, x0: float, x1: float, y0: float = 0.0, y1: float = 0.0) -> QLinearGradient:
    """Gradient spanning a fixed pixel range, so a partly filled bar shows only the
    part of the ramp it has actually reached."""
    g = QLinearGradient(x0, y0, x1, y1)
    g.setColorAt(0.0, QColor(stops[0]))
    g.setColorAt(1.0, QColor(stops[1]))
    return g


def qgrad(stops=GRAD_PRIMARY) -> str:
    """Same gradient as a Qt style-sheet value."""
    return f"qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {stops[0]}, stop:1 {stops[1]})"


STATE_COLOR = {
    "SEARCH": ("butter", "Searching"),
    "ACQUIRING": ("sky", "Acquiring"),
    "LOCKED": ("mint", "Locked"),
    "COASTING": ("butter", "Coasting"),
    "REACQUIRE": ("peach", "Re-acquiring"),
    "PAUSED": ("faint", "Paused"),
}

STATUS_COLOR = {"pass": "mint", "fail": "peach", "pending": "sky", "standby": "faint"}
STATUS_TEXT = {"pass": "PASS", "fail": "FAIL", "pending": "LIVE", "standby": "STANDBY"}

#: Hazards are categories, not severities — distinct but desaturated so they never
#: compete with the pass/fail colours.
HAZARD_COLOR = {
    "fog": "#9AA1AD", "rain": "#2E9BE0", "turbulence": "#B8801B", "noise": "#6B7280",
    "vibration": "#8C5A9E", "glare": "#C9A227", "occlusion": "#3F7A5A", "decoys": "#C93B37",
}


def c(key: str, alpha: int = 255) -> QColor:
    col = QColor(P.get(key, key))
    col.setAlpha(alpha)
    return col


def ink(tone: str) -> QColor:
    """Readable variant of a state colour, for text on a light tint."""
    return c(P.get(tone + "_ink", tone))


# --------------------------------------------------------------------------- type
def font(size: float = 9.5, weight: int = 400, family: str = FONT_UI, tracking: float = 0.0,
         caps: bool = False) -> QFont:
    f = QFont(family)
    f.setPointSizeF(size)
    f.setWeight(QFont.Weight(weight))
    if tracking:
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, tracking)
    if caps:
        f.setCapitalization(QFont.Capitalization.AllUppercase)
    return f


def num(size: float = 9.5, weight: int = 600) -> QFont:
    """Inter with tabular figures — live metrics keep their column width."""
    f = font(size, weight)
    try:
        f.setFeature(QFont.Tag("tnum"), 1)
    except (AttributeError, ValueError):     # Qt < 6.7 has no font-feature API
        pass
    return f


def mono(size: float = 9.0, weight: int = 500) -> QFont:
    f = QFont(FONT_MONO)
    if not f.exactMatch():
        f = QFont("Consolas")
    f.setPointSizeF(size)
    f.setWeight(QFont.Weight(weight))
    return f


def _asset_dir() -> str:
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "assets", "fonts")


def load_fonts() -> bool:
    """Register the bundled Inter weights. Falls back to the system UI font."""
    d = _asset_dir()
    loaded = False
    for name in ("Inter-Regular.ttf", "Inter-Medium.ttf", "Inter-SemiBold.ttf", "Inter-Bold.ttf"):
        path = os.path.join(d, name)
        if os.path.exists(path) and QFontDatabase.addApplicationFont(path) != -1:
            loaded = True
    if not loaded:
        global FONT_UI
        FONT_UI = "Segoe UI Variable Text" if "Segoe UI Variable Text" in QFontDatabase.families() else "Segoe UI"
    return loaded


def install(app) -> None:
    """Load fonts, set the application font and apply the style sheet."""
    load_fonts()
    app.setFont(font(9.5, 400))
    app.setStyleSheet(qss())


# --------------------------------------------------------------------------- style sheet
def qss() -> str:
    return f"""
    QWidget {{ color: {P['text']}; font-family: '{FONT_UI}'; font-size: 9.5pt; }}
    QMainWindow, QWidget#root {{ background: {P['bg']}; }}
    QToolTip {{
        background: {P['surface']}; color: {P['text']}; border: 1px solid {P['border_strong']};
        padding: 8px 10px; font-size: 9pt;
    }}

    /* ---- panels: flat cells on a tinted canvas, divided by hairlines ---- */
    QFrame#card {{ background: {P['surface']}; border: 1px solid {P['border']}; }}
    QFrame#softCard {{ background: {P['surface_alt']}; border: 1px solid {P['border']}; }}
    QFrame#flat {{ background: {P['surface']}; border: none; }}
    QFrame#row {{ background: transparent; border: none; border-top: 1px solid {P['border']}; }}
    QFrame#rule {{ background: {P['border']}; border: none; max-height: 1px; min-height: 1px; }}
    QFrame#vrule {{ background: {P['border']}; border: none; max-width: 1px; min-width: 1px; }}

    /* ---- type ladder ---- */
    QLabel#h1 {{ font-size: 15pt; font-weight: 700; color: {P['head']}; }}
    QLabel#h2 {{ font-size: 11pt; font-weight: 600; color: {P['head']}; }}
    QLabel#h3 {{ font-size: 8pt; font-weight: 600; color: {P['muted']}; letter-spacing: 1.1px; }}
    QLabel#caption {{ font-size: 9pt; font-weight: 400; color: {P['muted']}; }}
    QLabel#faint {{ font-size: 8.5pt; font-weight: 400; color: {P['faint']}; }}
    QLabel#metric {{ font-size: 16pt; font-weight: 600; color: {P['head']}; }}

    /* ---- scrollbars: thin, square, no arrows ---- */
    QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
    QScrollBar::handle:vertical {{ background: {P['border_strong']}; min-height: 32px; border: 3px solid transparent;
        background-clip: padding; }}
    QScrollBar::handle:vertical:hover {{ background: {P['faint']}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
    QScrollBar:horizontal {{ height: 0; }}
    QSplitter::handle {{ background: {P['border']}; }}
    QSplitter::handle:hover {{ background: {P['accent']}; }}
    QSplitter::handle:horizontal {{ width: 1px; }}
    QSplitter::handle:vertical {{ height: 1px; }}

    /* ---- controls ---- */
    QPushButton {{
        background: {P['surface']}; color: {P['text']}; border: 1px solid {P['border_strong']};
        padding: 7px 14px; font-weight: 500;
    }}
    QPushButton:hover {{ background: {P['bg']}; border-color: {P['faint']}; }}
    QPushButton:pressed {{ background: {P['border']}; }}
    QPushButton:disabled {{ color: {P['faint']}; background: {P['surface_alt']}; border-color: {P['border']}; }}
    QPushButton#primary {{ background: {qgrad(GRAD_PRIMARY)}; color: #FFFFFF; border: none; font-weight: 600; }}
    QPushButton#primary:hover {{ background: {qgrad(('#5FC0FF', '#101A2E'))}; }}
    QPushButton#primary:disabled {{ background: {P['border']}; color: {P['faint']}; }}
    QPushButton#ghost {{ background: transparent; border: 1px solid transparent; color: {P['muted']}; }}
    QPushButton#ghost:hover {{ color: {P['head']}; border-color: {P['border_strong']}; }}
    QPushButton#icon {{ background: {P['surface']}; border: 1px solid {P['border']};
        padding: 4px 9px; color: {P['muted']}; font-weight: 500; }}
    QPushButton#icon:hover {{ color: {P['head']}; border-color: {P['border_strong']}; }}
    QPushButton#icon:checked {{ background: {P['accent_soft']}; color: {P['accent_ink']}; border-color: {P['accent']}; }}

    QComboBox, QSpinBox, QDoubleSpinBox {{
        background: {P['surface']}; border: 1px solid {P['border_strong']};
        padding: 5px 10px; min-height: 20px; selection-background-color: {P['accent_soft']};
    }}
    QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover {{ border-color: {P['faint']}; }}
    QComboBox:focus {{ border-color: {P['accent']}; }}
    QComboBox::drop-down {{ border: none; width: 22px; }}
    QComboBox QAbstractItemView {{
        background: {P['surface']}; border: 1px solid {P['border_strong']};
        selection-background-color: {P['accent_soft']}; selection-color: {P['head']}; outline: none;
    }}

    QSlider::groove:horizontal {{ height: 2px; background: {P['border_strong']}; }}
    QSlider::sub-page:horizontal {{ background: {P['accent']}; }}
    QSlider::handle:horizontal {{
        background: {P['head']}; border: none; width: 3px; height: 14px; margin: -6px 0;
    }}
    QSlider::handle:horizontal:hover {{ background: {P['accent_ink']}; width: 5px; margin: -6px -1px; }}

    QTableWidget {{
        background: {P['surface']}; border: none; gridline-color: {P['border']};
        selection-background-color: {P['accent_soft']}; selection-color: {P['head']};
    }}
    QHeaderView::section {{
        background: {P['surface']}; color: {P['muted']}; border: none;
        border-bottom: 1px solid {P['border_strong']}; padding: 7px 8px;
        font-weight: 600; font-size: 8pt; letter-spacing: 1.1px;
    }}
    QProgressBar {{ background: {P['border']}; border: none; height: 6px; color: transparent; }}
    QProgressBar::chunk {{ background: {P['accent']}; }}
    """
