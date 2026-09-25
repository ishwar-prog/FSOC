"""Reusable widgets and vector icons (no image assets needed in the .exe).

Everything here is square-edged and hairline-bordered: shape carries no meaning, so
the eye is free to follow colour, which only ever marks state.
"""

import math
from typing import Callable, Dict, List, Optional

from PySide6.QtCore import QEasingCurve, QPoint, QPointF, QRectF, QSize, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (QAbstractButton, QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton,
                               QSizePolicy, QSlider, QToolTip, QVBoxLayout, QWidget)

from .theme import (GRAD_PRIMARY, GRAD_SUCCESS, HAZARD_COLOR, P, STATUS_COLOR, STATUS_TEXT, UNIT, c, font,
                    grad, grad_px, ink, num)


def label(text: str = "", obj: Optional[str] = None, wrap: bool = False) -> QLabel:
    lb = QLabel(text)
    if obj:
        lb.setObjectName(obj)
    lb.setWordWrap(wrap)
    return lb


class InfoButton(QLabel):
    """Small (i) badge: hover to read a plain-language explanation."""

    def __init__(self, html: str, parent=None, size: int = 17) -> None:
        super().__init__("i", parent)
        self._html = f"<div style='max-width: 300px'>{html}</div>"
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.WhatsThisCursor)
        self.setToolTip(self._html)
        self.setStyleSheet(
            f"QLabel {{ color: {P['faint']}; border: 1px solid {P['border_strong']};"
            f" font-weight: 600; font-size: 7.5pt; background: transparent; }}"
            f"QLabel:hover {{ color: {P['accent_ink']}; border-color: {P['accent']}; background: {P['accent_soft']}; }}")

    def enterEvent(self, e) -> None:
        QToolTip.showText(self.mapToGlobal(QPoint(0, self.height() + 4)), self._html, self)
        super().enterEvent(e)


class Card(QFrame):
    def __init__(self, title: str = "", subtitle: str = "", parent=None, pad: int = UNIT * 2, spacing: int = UNIT,
                 obj: str = "card", info: Optional[str] = None) -> None:
        super().__init__(parent)
        self.setObjectName(obj)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(pad, pad, pad, pad)
        lay.setSpacing(spacing)
        self.header = QHBoxLayout()
        self.header.setSpacing(8)
        if title:
            tbox = QVBoxLayout()
            tbox.setSpacing(2)
            trow = QHBoxLayout()
            trow.setSpacing(6)
            self.title_label = label(title, "h2")
            trow.addWidget(self.title_label)
            if info:
                trow.addWidget(InfoButton(info))
            trow.addStretch(1)
            tbox.addLayout(trow)
            if subtitle:
                self.subtitle_label = label(subtitle, "caption", wrap=True)
                tbox.addWidget(self.subtitle_label)
            self.header.addLayout(tbox, 1)
            lay.addLayout(self.header)
        self.body = lay


class Pill(QLabel):
    def __init__(self, text: str = "", tone: str = "accent", parent=None, size: float = 8.6) -> None:
        super().__init__(text, parent)
        self._size = size
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set_tone(tone, text)

    def set_tone(self, tone: str, text: Optional[str] = None) -> None:
        if text is not None and text != self.text():
            self.setText(text)
        if getattr(self, "_key", None) == tone:
            return
        self._key = tone
        fg = P.get(tone + "_ink", P.get(tone, tone))
        bg = P.get(tone + "_soft", P["surface_alt"])
        self.setStyleSheet(
            f"QLabel {{ background: {bg}; color: {fg}; padding: 3px 8px;"
            f" font-weight: 600; font-size: {self._size}pt; letter-spacing: 1.0px; }}")


class Switch(QAbstractButton):
    def __init__(self, parent=None, color: str = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pos = 0.0
        self._color = QColor(color or P["accent_ink"])
        self._anim = QVariantAnimation(self, duration=180, easingCurve=QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._on_anim)
        self.toggled.connect(self._animate)

    def sizeHint(self) -> QSize:
        return QSize(38, 22)

    def _on_anim(self, v) -> None:
        self._pos = float(v)
        self.update()

    def _animate(self, on: bool) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def setChecked(self, on: bool) -> None:
        super().setChecked(on)
        self._pos = 1.0 if on else 0.0
        self.update()

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(1, 4, 36, 16)
        off, on = QColor(P["border_strong"]), self._color
        col = QColor(int(off.red() + (on.red() - off.red()) * self._pos),
                     int(off.green() + (on.green() - off.green()) * self._pos),
                     int(off.blue() + (on.blue() - off.blue()) * self._pos))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(col)
        p.drawRect(r)
        p.setBrush(QColor("white"))
        p.drawRect(QRectF(r.left() + 2 + self._pos * 18, r.top() + 2, 14, 12))


class Segmented(QWidget):
    changed = Signal(str)

    def __init__(self, options: List[tuple], parent=None, compact: bool = False, tabs: bool = False) -> None:
        super().__init__(parent)
        self.setObjectName("segmented")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(1, 1, 1, 1)
        lay.setSpacing(1)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: Dict[str, QPushButton] = {}
        for key, text in options:
            b = QPushButton(text)
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setObjectName("seg")
            b.clicked.connect(lambda _=False, k=key: self.changed.emit(k))
            self.group.addButton(b)
            lay.addWidget(b)
            self.buttons[key] = b
        pad = "5px 9px" if compact else "6px 14px"
        if tabs:
            self.setStyleSheet(
                f"QWidget#segmented {{ background: transparent; border: none;"
                f" border-bottom: 1px solid {P['border_strong']}; }}"
                f"QPushButton#seg {{ background: transparent; border: none; border-bottom: 2px solid transparent;"
                f" padding: 7px 12px; color: {P['muted']}; font-weight: 500; }}"
                f"QPushButton#seg:hover {{ color: {P['head']}; }}"
                f"QPushButton#seg:checked {{ color: {P['head']}; font-weight: 600;"
                f" border-bottom: 2px solid {P['accent']}; }}")
            if options:
                self.set_current(options[0][0])
            return
        self.setStyleSheet(
            f"QWidget#segmented {{ background: {P['surface_alt']}; border: 1px solid {P['border']}; }}"
            f"QPushButton#seg {{ background: transparent; border: none; padding: {pad};"
            f" color: {P['muted']}; font-weight: 500; }}"
            f"QPushButton#seg:hover {{ color: {P['head']}; }}"
            f"QPushButton#seg:checked {{ background: {P['surface']}; color: {P['head']}; font-weight: 600;"
            f" border: 1px solid {P['border_strong']}; }}")
        if options:
            self.set_current(options[0][0])

    def set_current(self, key: str) -> None:
        if key in self.buttons:
            self.buttons[key].setChecked(True)


class ValueSlider(QWidget):
    """Named slider with an (i) explanation and a live value readout."""
    changed = Signal(float)

    def __init__(self, name: str, lo: float, hi: float, value: float, step: float = 1.0,
                 fmt: Callable[[float], str] = None, info: Optional[str] = None, parent=None) -> None:
        super().__init__(parent)
        self.lo, self.step = lo, step
        self.fmt = fmt or (lambda v: f"{v:.0f}")
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 2, 0, 2)
        v.setSpacing(3)
        top = QHBoxLayout()
        top.setSpacing(6)
        top.addWidget(label(name, "caption"))
        if info:
            top.addWidget(InfoButton(info, size=15))
        top.addStretch(1)
        self.value_label = QLabel(self.fmt(value))
        self.value_label.setFont(num(9, 600))
        top.addWidget(self.value_label)
        v.addLayout(top)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, int(round((hi - lo) / step)))
        self.slider.setValue(int(round((value - lo) / step)))
        self.slider.valueChanged.connect(self._on)
        v.addWidget(self.slider)

    def value(self) -> float:
        return self.lo + self.slider.value() * self.step

    def _on(self, _i: int) -> None:
        val = self.value()
        self.value_label.setText(self.fmt(val))
        self.changed.emit(val)

    def set_value(self, val: float) -> None:
        self.slider.blockSignals(True)
        self.slider.setValue(int(round((val - self.lo) / self.step)))
        self.slider.blockSignals(False)
        self.value_label.setText(self.fmt(self.value()))


class Gauge(QWidget):
    SPAN = 1.6

    def __init__(self, parent=None, span: float = 1.6, marker: bool = True) -> None:
        super().__init__(parent)
        self.SPAN = span
        self.marker = marker
        self.setFixedHeight(6)
        self._ratio = 0.0
        self._tone = "faint"
        self._anim = QVariantAnimation(self, duration=350, easingCurve=QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._set)

    def _set(self, v) -> None:
        self._ratio = float(v)
        self.update()

    def set_value(self, ratio: Optional[float], tone: str) -> None:
        ratio = 0.0 if ratio is None else max(0.0, min(self.SPAN, ratio))
        self._tone = tone
        if abs(ratio - self._ratio) < 1e-3:
            self.update()
            return
        self._anim.stop()
        self._anim.setStartValue(self._ratio)
        self._anim.setEndValue(ratio)
        self._anim.start()

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c("border"))
        p.drawRect(QRectF(0, 0, w, h))
        fw = w * self._ratio / self.SPAN
        if fw > 1:
            if self._tone == "mint":
                p.setBrush(grad_px(GRAD_SUCCESS, 0, w))
            elif self._tone in ("sky", "accent"):
                p.setBrush(grad_px(GRAD_PRIMARY, 0, w))
            else:
                p.setBrush(c(self._tone))
            p.drawRect(QRectF(0, 0, fw, h))
        if self.marker:
            x = w / self.SPAN
            p.setBrush(c("head"))
            p.drawRect(QRectF(x - 1, -2, 1, h + 4))


class KpiCard(QFrame):
    def __init__(self, name: str, target: str, meaning: str, info: Optional[str] = None, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("row")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, UNIT + 2, 0, UNIT + 2)
        lay.setSpacing(6)
        top = QHBoxLayout()
        top.setSpacing(6)
        self.name = label(name, "h2")
        self.name.setStyleSheet("font-size: 10pt; font-weight: 600;")
        top.addWidget(self.name)
        if info:
            top.addWidget(InfoButton(info, size=15))
        top.addStretch(1)
        self.pill = Pill("LIVE", "sky", size=7.5)
        top.addWidget(self.pill)
        lay.addLayout(top)
        mid = QHBoxLayout()
        self.value = QLabel("—")
        self.value.setFont(num(16, 600))
        self.value.setStyleSheet(f"color: {P['head']};")
        self.target = label(f"target {target}", "caption")
        mid.addWidget(self.value)
        mid.addStretch(1)
        mid.addWidget(self.target, 0, Qt.AlignmentFlag.AlignBottom)
        lay.addLayout(mid)
        self.gauge = Gauge()
        lay.addWidget(self.gauge)
        self.detail = label(meaning, "faint", wrap=True)
        lay.addWidget(self.detail)
        self._last = None

    def update_kpi(self, k: dict) -> None:
        key = (k["text"], k["status"], k["detail"], round(k["ratio"] or 0, 3))
        if key == self._last:
            return
        self._last = key
        tone = STATUS_COLOR[k["status"]]
        self.value.setText(k["text"])
        self.pill.set_tone(tone, STATUS_TEXT[k["status"]])
        self.gauge.set_value(k["ratio"], tone)
        self.detail.setText(k["detail"] or k["meaning"])


class StatRow(QWidget):
    def __init__(self, name: str, value: str = "—", parent=None, info: Optional[str] = None) -> None:
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        lay.setSpacing(5)
        self.name = label(name, "caption")
        lay.addWidget(self.name)
        if info:
            lay.addWidget(InfoButton(info, size=14))
        lay.addStretch(1)
        self.value = QLabel(value)
        self.value.setFont(num(10, 600))
        self.value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(self.value)

    def set(self, text: str) -> None:
        if self.value.text() != text:
            self.value.setText(text)


class SourceBars(QWidget):
    """Ranking of light sources by beacon probability."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.rows = []
        self.setMinimumHeight(118)

    def set_sources(self, sources) -> None:
        rows = [(p, f, lk) for (_x, _y, p, f, lk) in sources[:5]]
        if rows != self.rows:
            self.rows = rows
            self.update()

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        if not self.rows:
            p.setPen(c("faint"))
            p.setFont(font(9))
            p.drawText(QRectF(0, 0, w, 40), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       "Watching lights… (needs ~1 s of history each)")
            return
        for i, (prob, freq, locked) in enumerate(self.rows):
            y = 4 + i * 23
            tone = "mint" if locked else ("sky" if prob >= 0.6 else "faint")
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(ink(tone) if tone != "faint" else c("faint"))
            p.drawRect(QRectF(3, y + 5, 6, 6))
            p.setPen(c("head") if locked else c("text"))
            p.setFont(font(9, 600 if locked else 400))
            name = "Locked beacon" if locked else f"Light {i + 1}"
            p.drawText(QRectF(16, y, 104, 16), Qt.AlignmentFlag.AlignVCenter, name)
            bx, bw = 118, max(40, w - 118 - 92)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c("border"))
            p.drawRect(QRectF(bx, y + 5, bw, 6))
            p.setBrush(grad_px(GRAD_SUCCESS, bx, bx + bw) if tone == "mint" else c(tone))
            p.drawRect(QRectF(bx, y + 5, max(3, bw * prob), 6))
            p.setPen(c("muted"))
            p.setFont(num(8.5, 600))
            p.drawText(QRectF(bx + bw + 6, y, 86, 16), Qt.AlignmentFlag.AlignVCenter,
                       f"{prob * 100:3.0f}% {freq:4.1f}Hz")


# ----------------------------------------------------------------------------- icons
def draw_platform(p: QPainter, kind: str, cx: float, cy: float, size: float,
                  heading: float = 0.0, color: QColor = None, roll: float = 0.0) -> None:
    color = color or c("text")
    p.save()
    p.translate(cx, cy)
    s = size / 24.0
    p.scale(s, s)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    soft = QColor(color.red(), color.green(), color.blue(), 70)
    if kind == "quad":
        p.rotate(math.degrees(heading) * 0.15)
        p.setPen(QPen(color, 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(-8, -5), QPointF(8, 5))
        p.drawLine(QPointF(-8, 5), QPointF(8, -5))
        p.setPen(QPen(color, 1.6))
        p.setBrush(soft)
        for x, y in ((-9, -6), (9, 6), (-9, 6), (9, -6)):
            p.drawEllipse(QPointF(x, y), 4.8, 1.8)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawRoundedRect(QRectF(-3.5, -2.5, 7, 5), 2, 2)
    elif kind == "fixedwing":
        p.rotate(math.degrees(heading))
        path = QPainterPath()
        for i, (x, y) in enumerate(((12, 0), (4, -1.8), (1, -11), (-2, -11), (-1, -2), (-8, -2), (-11, -6),
                                    (-12.5, -6), (-11, 0), (-12.5, 6), (-11, 6), (-8, 2), (-1, 2), (-2, 11),
                                    (1, 11), (4, 1.8))):
            (path.moveTo if i == 0 else path.lineTo)(x, y)
        path.closeSubpath()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawPath(path)
    elif kind == "ship":
        p.rotate(math.degrees(roll) * 1.5)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawPolygon(QPolygonF([QPointF(-13, 2), QPointF(13, 2), QPointF(9, 8), QPointF(-10, 8)]))
        p.drawRect(QRectF(-6, -3, 10, 5))
        p.setPen(QPen(color, 1.6))
        p.drawLine(QPointF(0, -3), QPointF(0, -14))
        p.drawLine(QPointF(-4, -10), QPointF(4, -10))
    elif kind == "satellite":
        p.rotate(-25)
        p.setPen(QPen(color, 1.2))
        p.setBrush(soft)
        for sx in (-1, 1):
            r = QRectF(4 if sx > 0 else -14, -3.5, 10, 7)
            p.drawRect(r)
            p.drawLine(QPointF(r.center().x(), r.top()), QPointF(r.center().x(), r.bottom()))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawRoundedRect(QRectF(-4, -4.5, 8, 9), 1.5, 1.5)
        p.setPen(QPen(color, 1.4))
        p.drawLine(QPointF(0, -4.5), QPointF(0, -9))
        p.drawEllipse(QPointF(0, -10), 1.6, 1.6)
    elif kind == "station":
        p.setPen(QPen(color, 1.6))
        p.drawLine(QPointF(-13, 0), QPointF(13, 0))
        p.setBrush(soft)
        p.setPen(QPen(color, 1.0))
        for x in (-12, -7, 7, 12):
            p.drawRect(QRectF(x - 1.8, -9, 3.6, 7))
            p.drawRect(QRectF(x - 1.8, 2, 3.6, 7))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawRoundedRect(QRectF(-3.5, -2.5, 7, 5), 2, 2)
        p.drawRoundedRect(QRectF(-1.5, -6, 3, 12), 1, 1)
    elif kind == "fixed":
        p.setPen(QPen(color, 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(0, -3), QPointF(-8, 11))
        p.drawLine(QPointF(0, -3), QPointF(8, 11))
        p.drawLine(QPointF(0, -3), QPointF(0, 11))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawRoundedRect(QRectF(-7, -11, 14, 8), 2, 2)
    elif kind == "vehicle":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawRoundedRect(QRectF(-13, 0, 18, 7), 1.5, 1.5)
        p.drawRoundedRect(QRectF(5, 2, 8, 5), 1.5, 1.5)
        p.drawEllipse(QPointF(-8, 8.5), 2.6, 2.6)
        p.drawEllipse(QPointF(8, 8.5), 2.6, 2.6)
        p.setPen(QPen(color, 1.6))
        p.drawLine(QPointF(-4, 0), QPointF(-4, -9))
        p.setBrush(soft)
        p.drawRoundedRect(QRectF(-9, -13, 10, 5), 1.5, 1.5)
    p.restore()


def draw_hazard(p: QPainter, key: str, r: QRectF, color: QColor) -> None:
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    cx, cy, s = r.center().x(), r.center().y(), min(r.width(), r.height()) / 20.0
    p.setPen(QPen(color, 1.7 * s, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.setBrush(Qt.BrushStyle.NoBrush)
    if key == "fog":
        for i, y in enumerate((-4, 0, 4)):
            path = QPainterPath()
            path.moveTo(cx - 7 * s + i * s, cy + y * s)
            path.cubicTo(cx - 3 * s, cy + (y - 2) * s, cx + 1 * s, cy + (y + 2) * s, cx + (7 - i) * s, cy + y * s)
            p.drawPath(path)
    elif key == "rain":
        for dx, dy in ((-5, -3), (0, -6), (5, -3), (-2, 3), (3, 2)):
            p.drawLine(QPointF(cx + dx * s, cy + dy * s), QPointF(cx + (dx - 1.2) * s, cy + (dy + 3.5) * s))
    elif key == "turbulence":
        for x in (-4.5, 0, 4.5):
            path = QPainterPath()
            path.moveTo(cx + x * s, cy + 7 * s)
            path.cubicTo(cx + (x - 3) * s, cy + 3 * s, cx + (x + 3) * s, cy - 1 * s, cx + x * s, cy - 7 * s)
            p.drawPath(path)
    elif key == "noise":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        for i, (dx, dy) in enumerate(((-6, -5), (-1, -6), (5, -4), (-4, 0), (2, 1), (6, 3), (-6, 5), (0, 6), (4, -1))):
            rr = (1.1 + (i % 3) * 0.45) * s
            p.drawEllipse(QPointF(cx + dx * s, cy + dy * s), rr, rr)
    elif key == "vibration":
        path = QPainterPath()
        path.moveTo(cx - 8 * s, cy)
        for i, x in enumerate(range(-6, 9, 2)):
            path.lineTo(cx + x * s, cy + (-4 if i % 2 == 0 else 4) * s)
        p.drawPath(path)
    elif key == "glare":
        p.drawEllipse(QPointF(cx, cy), 3.3 * s, 3.3 * s)
        for k in range(8):
            a = k * math.pi / 4
            p.drawLine(QPointF(cx + math.cos(a) * 5.5 * s, cy + math.sin(a) * 5.5 * s),
                       QPointF(cx + math.cos(a) * 8 * s, cy + math.sin(a) * 8 * s))
    elif key == "occlusion":
        for ox, oy, k in ((-3, 1, 1.0), (4, -3, 0.7)):
            path = QPainterPath()
            path.moveTo(cx + (ox - 5 * k) * s, cy + (oy - 1) * s)
            path.quadTo(cx + (ox - 2 * k) * s, cy + (oy - 3.5 * k) * s, cx + ox * s, cy + oy * s)
            path.quadTo(cx + (ox + 2 * k) * s, cy + (oy - 3.5 * k) * s, cx + (ox + 5 * k) * s, cy + (oy - 1) * s)
            p.drawPath(path)
    elif key == "decoys":
        p.setPen(Qt.PenStyle.NoPen)
        for dx, dy, rr, a in ((-5, 3, 2.2, 150), (0, -4, 3.0, 255), (5, 3, 2.2, 150)):
            col = QColor(color)
            col.setAlpha(a)
            p.setBrush(col)
            p.drawEllipse(QPointF(cx + dx * s, cy + dy * s), rr * s, rr * s)
    p.restore()


class IconBadge(QWidget):
    def __init__(self, kind: str, key: str, size: int = 34, parent=None) -> None:
        super().__init__(parent)
        self.kind, self.key = kind, key
        self.setFixedSize(size, size)
        self.active = False

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        col = QColor(HAZARD_COLOR[self.key])
        bg = QColor(col)
        bg.setAlpha(46 if self.active else 18)
        p.setPen(QPen(col if self.active else c("border"), 1))
        p.setBrush(bg)
        p.drawRect(r)
        draw_hazard(p, self.key, r.adjusted(4, 4, -4, -4), col if self.active else c("faint"))


class _Tile(QAbstractButton):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hover = False

    def enterEvent(self, e) -> None:
        self._hover = True
        self.update()

    def leaveEvent(self, e) -> None:
        self._hover = False
        self.update()

    def _frame(self, p: QPainter) -> QRectF:
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        on = self.isChecked()
        p.setPen(QPen(c("accent") if on else (c("border_strong") if self._hover else c("border")), 1))
        p.setBrush(c("accent_soft") if on else (c("bg") if self._hover else c("surface")))
        p.drawRect(r)
        return r


class PatternTile(_Tile):
    def __init__(self, key: str, name: str, platform: str, parent=None) -> None:
        super().__init__(parent)
        self.key, self.name, self.platform = key, name, platform
        self.setMinimumHeight(52)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def sizeHint(self) -> QSize:
        return QSize(120, 52)

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self._frame(p)
        on = self.isChecked()
        ic = QRectF(r.left() + 8, r.center().y() - 14, 28, 28)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c("surface") if on else c("surface_alt"))
        p.drawRect(ic)
        glyph = "manual" if self.key.startswith("manual") else self.platform
        if glyph == "manual":
            p.setPen(QPen(c("accent_ink") if on else c("muted"), 1.8, Qt.PenStyle.SolidLine,
                          Qt.PenCapStyle.RoundCap))
            ctr = ic.center()
            for a in (0, 90, 180, 270):
                rad = math.radians(a)
                tip = ctr + QPointF(math.cos(rad) * 8, math.sin(rad) * 8)
                p.drawLine(ctr, tip)
            p.drawEllipse(ctr, 3, 3)
        else:
            draw_platform(p, glyph, ic.center().x(), ic.center().y(), 19, 0.0,
                          c("accent_ink") if on else c("muted"))
        p.setPen(c("head") if on else c("text"))
        p.setFont(font(9.0, 600 if on else 400))
        tr = QRectF(ic.right() + 8, r.top(), r.right() - ic.right() - 10, r.height())
        p.drawText(tr, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap, self.name)


class IconTile(_Tile):
    """Large vertical tile: icon above a name (terminal type, mount)."""

    def __init__(self, key: str, name: str, glyph: str, parent=None) -> None:
        super().__init__(parent)
        self.key, self.name, self.glyph = key, name, glyph
        self.setMinimumHeight(74)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def sizeHint(self) -> QSize:
        return QSize(84, 74)

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self._frame(p)
        on = self.isChecked()
        draw_platform(p, self.glyph, r.center().x(), r.top() + 26, 28, 0.0,
                      c("accent_ink") if on else c("muted"))
        p.setPen(c("head") if on else c("text"))
        p.setFont(font(8.8, 600 if on else 400))
        p.drawText(QRectF(r.left() + 2, r.bottom() - 26, r.width() - 4, 22),
                   Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self.name)


class TabBar(QWidget):
    """Page tabs: a text row with a gradient rule under the active item."""
    changed = Signal(str)

    PAD = 14

    def __init__(self, items: List[tuple], parent=None) -> None:
        super().__init__(parent)
        self.items = items
        self.current = items[0][0] if items else ""
        self._hover = -1
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(40)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setFixedWidth(sum(self._widths()))

    def _widths(self) -> List[int]:
        fm = self.fontMetrics()
        return [fm.horizontalAdvance(text) + self.PAD * 2 for _k, text in self.items]

    def set_current(self, key: str) -> None:
        if key != self.current and any(k == key for k, _t in self.items):
            self.current = key
            self.update()

    def _hit(self, x: float) -> int:
        acc = 0
        for i, w in enumerate(self._widths()):
            if acc <= x < acc + w:
                return i
            acc += w
        return -1

    def mouseMoveEvent(self, e) -> None:
        i = self._hit(e.position().x())
        if i != self._hover:
            self._hover = i
            self.update()

    def leaveEvent(self, e) -> None:
        self._hover = -1
        self.update()

    def mousePressEvent(self, e) -> None:
        i = self._hit(e.position().x())
        if i >= 0 and self.items[i][0] != self.current:
            self.current = self.items[i][0]
            self.update()
            self.changed.emit(self.current)

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        h, x = self.height(), 0
        for i, ((key, text), w) in enumerate(zip(self.items, self._widths())):
            on = key == self.current
            p.setFont(font(10.5, 600 if on else 400))
            p.setPen(c("head") if on else (c("text") if i == self._hover else c("muted")))
            p.drawText(QRectF(x, 0, w, h - 3), Qt.AlignmentFlag.AlignCenter, text)
            if on:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(grad(GRAD_SUCCESS))
                p.drawRect(QRectF(x, h - 2, w, 2))
            x += w
