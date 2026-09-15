"""Soft pastel design system with light and dark modes."""

from PySide6.QtGui import QColor, QFont

LIGHT = {
    "bg": "#F3F1F8", "surface": "#FFFFFF", "surface_alt": "#F8F7FC", "border": "#E8E4F1",
    "border_strong": "#D8D2E6", "text": "#2E2A3B", "muted": "#77728A", "faint": "#A9A4B8",
    "accent": "#8B7CC8", "accent_hover": "#7B6BBC", "accent_soft": "#ECE8F8",
    "mint": "#58B891", "mint_soft": "#E1F4EC", "peach": "#E58E7B", "peach_soft": "#FCE9E4",
    "butter": "#DDAE55", "butter_soft": "#FBF2DC", "sky": "#6CA6D6", "sky_soft": "#E3EFFA",
    "rose": "#C984AE", "rose_soft": "#F7E6F0", "ink": "#221E2E", "overlay": "#FFFFFF",
}

DARK = {
    "bg": "#15131C", "surface": "#1E1B28", "surface_alt": "#252232", "border": "#2F2B3E",
    "border_strong": "#3D3852", "text": "#ECE8F6", "muted": "#A8A2BF", "faint": "#6F6987",
    "accent": "#A897EA", "accent_hover": "#BAABF2", "accent_soft": "#2D2647",
    "mint": "#6FD3A9", "mint_soft": "#1D3A30", "peach": "#F29C8A", "peach_soft": "#3F2926",
    "butter": "#E9C471", "butter_soft": "#3A3221", "sky": "#86BCEB", "sky_soft": "#1D2E40",
    "rose": "#DD9AC4", "rose_soft": "#3A2534", "ink": "#0C0B12", "overlay": "#1E1B28",
}

P = dict(LIGHT)
_MODE = ["light"]


def set_mode(mode: str) -> None:
    _MODE[0] = "dark" if mode == "dark" else "light"
    P.clear()
    P.update(DARK if _MODE[0] == "dark" else LIGHT)


def mode() -> str:
    return _MODE[0]


def is_dark() -> bool:
    return _MODE[0] == "dark"


STATE_COLOR = {
    "SEARCH": ("peach", "Searching"),
    "ACQUIRING": ("sky", "Acquiring"),
    "LOCKED": ("mint", "Locked"),
    "COASTING": ("butter", "Coasting"),
    "REACQUIRE": ("rose", "Re-acquiring"),
    "PAUSED": ("faint", "Paused"),
}

STATUS_COLOR = {"pass": "mint", "fail": "peach", "pending": "sky", "standby": "faint"}
STATUS_TEXT = {"pass": "PASS", "fail": "FAIL", "pending": "LIVE", "standby": "STANDBY"}

HAZARD_COLOR = {
    "fog": "#9DB4C8", "rain": "#6CA6D6", "turbulence": "#E3A86B", "noise": "#9C92B8",
    "vibration": "#C984AE", "glare": "#E0B84F", "occlusion": "#7FA78F", "decoys": "#E58E7B",
}


def c(key: str, alpha: int = 255) -> QColor:
    col = QColor(P.get(key, key))
    col.setAlpha(alpha)
    return col


def font(size: float = 10, weight: int = 400, family: str = "Segoe UI") -> QFont:
    f = QFont(family)
    f.setPointSizeF(size)
    f.setWeight(QFont.Weight(weight))
    return f


def mono(size: float = 9.5, weight: int = 500) -> QFont:
    f = QFont("Cascadia Mono")
    if not f.exactMatch():
        f = QFont("Consolas")
    f.setPointSizeF(size)
    f.setWeight(QFont.Weight(weight))
    return f


def qss() -> str:
    return f"""
    QWidget {{ color: {P['text']}; font-family: 'Segoe UI'; font-size: 10pt; }}
    QMainWindow, QWidget#root {{ background: {P['bg']}; }}
    QToolTip {{
        background: {P['surface']}; color: {P['text']}; border: 1px solid {P['border_strong']};
        padding: 8px 10px; border-radius: 8px; font-size: 9.5pt;
    }}
    QFrame#card {{ background: {P['surface']}; border: 1px solid {P['border']}; border-radius: 14px; }}
    QFrame#softCard {{ background: {P['surface_alt']}; border: 1px solid {P['border']}; border-radius: 12px; }}
    QLabel#h1 {{ font-size: 15pt; font-weight: 650; color: {P['text']}; }}
    QLabel#h2 {{ font-size: 11pt; font-weight: 650; color: {P['text']}; }}
    QLabel#h3 {{ font-size: 9pt; font-weight: 700; color: {P['muted']}; letter-spacing: 0.6px; }}
    QLabel#caption {{ font-size: 8.8pt; color: {P['muted']}; }}
    QLabel#faint {{ font-size: 8.5pt; color: {P['faint']}; }}
    QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
    QScrollBar:vertical {{ background: transparent; width: 8px; margin: 4px 0; }}
    QScrollBar::handle:vertical {{ background: {P['border_strong']}; border-radius: 4px; min-height: 30px; }}
    QScrollBar::handle:vertical:hover {{ background: {P['faint']}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
    QScrollBar:horizontal {{ height: 0; }}
    QSplitter::handle {{ background: transparent; }}
    QSplitter::handle:hover {{ background: {P['accent_soft']}; border-radius: 3px; }}
    QPushButton {{
        background: {P['surface']}; color: {P['text']}; border: 1px solid {P['border_strong']};
        border-radius: 9px; padding: 7px 14px; font-weight: 600;
    }}
    QPushButton:hover {{ background: {P['accent_soft']}; border-color: {P['accent']}; }}
    QPushButton:pressed {{ background: {P['accent_soft']}; }}
    QPushButton:disabled {{ color: {P['faint']}; background: {P['surface_alt']}; border-color: {P['border']}; }}
    QPushButton#primary {{ background: {P['accent']}; color: white; border: 1px solid {P['accent']}; }}
    QPushButton#primary:hover {{ background: {P['accent_hover']}; }}
    QPushButton#ghost {{ background: transparent; border: 1px solid transparent; color: {P['muted']}; }}
    QPushButton#ghost:hover {{ background: {P['accent_soft']}; color: {P['text']}; }}
    QPushButton#icon {{ background: transparent; border: 1px solid {P['border']}; border-radius: 8px;
        padding: 3px 8px; color: {P['muted']}; font-weight: 700; }}
    QPushButton#icon:hover {{ background: {P['accent_soft']}; color: {P['text']}; }}
    QPushButton#icon:checked {{ background: {P['accent_soft']}; color: {P['accent']}; border-color: {P['accent']}; }}
    QComboBox, QSpinBox, QDoubleSpinBox {{
        background: {P['surface']}; border: 1px solid {P['border_strong']}; border-radius: 8px;
        padding: 5px 10px; min-height: 20px;
    }}
    QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover {{ border-color: {P['accent']}; }}
    QComboBox::drop-down {{ border: none; width: 22px; }}
    QComboBox QAbstractItemView {{
        background: {P['surface']}; border: 1px solid {P['border_strong']};
        selection-background-color: {P['accent_soft']}; selection-color: {P['text']}; outline: none;
    }}
    QSlider::groove:horizontal {{ height: 4px; background: {P['border']}; border-radius: 2px; }}
    QSlider::sub-page:horizontal {{ background: {P['accent']}; border-radius: 2px; }}
    QSlider::handle:horizontal {{
        background: {P['surface']}; border: 2px solid {P['accent']};
        width: 12px; height: 12px; margin: -6px 0; border-radius: 8px;
    }}
    QSlider::handle:horizontal:hover {{ background: {P['accent_soft']}; }}
    QTableWidget {{
        background: {P['surface']}; border: none; gridline-color: {P['border']};
        selection-background-color: {P['accent_soft']}; selection-color: {P['text']};
    }}
    QHeaderView::section {{
        background: {P['surface_alt']}; color: {P['muted']}; border: none;
        border-bottom: 1px solid {P['border']}; padding: 6px 8px; font-weight: 650; font-size: 8.8pt;
    }}
    QProgressBar {{ background: {P['border']}; border: none; border-radius: 4px; height: 8px; color: transparent; }}
    QProgressBar::chunk {{ background: {P['accent']}; border-radius: 4px; }}
    """
