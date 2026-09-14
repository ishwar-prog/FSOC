"""Reusable pastel widgets and vector icons (no image assets needed in the .exe)."""

import math
from typing import Dict, List, Optional

from PySide6.QtCore import (QEasingCurve, QPointF, QRectF, QSize, Qt, QVariantAnimation, Signal, Property)
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (QAbstractButton, QButtonGroup, QFrame, QGraphicsDropShadowEffect, QHBoxLayout,
                               QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget)

from .theme import HAZARD_COLOR, P, STATUS_COLOR, STATUS_TEXT, c, font, mono


def label(text: str = "", obj: Optional[str] = None, wrap: bool = False) -> QLabel:
    lb = QLabel(text)
    if obj:
        lb.setObjectName(obj)
    lb.setWordWrap(wrap)
    return lb


def soft_shadow(w: QWidget, blur: int = 24, alpha: int = 22, dy: int = 4) -> None:
    eff = QGraphicsDropShadowEffect(w)
    eff.setBlurRadius(blur)
    eff.setOffset(0, dy)
    eff.setColor(QColor(80, 60, 130, alpha))
    w.setGraphicsEffect(eff)


class Card(QFrame):
    def __init__(self, title: str = "", subtitle: str = "", parent=None, pad: int = 16, spacing: int = 12,
                 obj: str = "card") -> None:
        super().__init__(parent)
        self.setObjectName(obj)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(pad, pad - 2, pad, pad)
        lay.setSpacing(spacing)
        self.header = QHBoxLayout()
        self.header.setSpacing(8)
        if title:
            tbox = QVBoxLayout()
            tbox.setSpacing(1)
            self.title_label = label(title, "h2")
            tbox.addWidget(self.title_label)
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
        key = (tone,)
        if getattr(self, "_key", None) == key:
            return
        self._key = key
        fg = P.get(tone, tone)
        bg = P.get(tone + "_soft", P["surface_alt"])
        if tone == "faint":
            bg, fg = P["surface_alt"], P["muted"]
        self.setStyleSheet(
            f"QLabel {{ background: {bg}; color: {fg}; border-radius: 10px; padding: 3px 10px;"
            f" font-weight: 700; font-size: {self._size}pt; letter-spacing: 0.4px; }}")


class Switch(QAbstractButton):
    def __init__(self, parent=None, color: str = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pos = 0.0
        self._color = QColor(color or P["accent"])
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
        r = QRectF(1, 2, 36, 18)
        off, on = QColor(P["border_strong"]), self._color
        col = QColor(
            int(off.red() + (on.red() - off.red()) * self._pos),
            int(off.green() + (on.green() - off.green()) * self._pos),
            int(off.blue() + (on.blue() - off.blue()) * self._pos))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(col)
        p.drawRoundedRect(r, 9, 9)
        x = r.left() + 9 + self._pos * 18
        p.setBrush(QColor("white"))
        p.drawEllipse(QPointF(x, r.center().y()), 7, 7)


class Segmented(QWidget):
    changed = Signal(str)

    def __init__(self, options: List[tuple], parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("segmented")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(2)
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
        self.setStyleSheet(
            f"QWidget#segmented {{ background: {P['surface_alt']}; border: 1px solid {P['border']}; border-radius: 11px; }}"
            f"QPushButton#seg {{ background: transparent; border: none; border-radius: 8px; padding: 6px 14px;"
            f" color: {P['muted']}; font-weight: 600; }}"
            f"QPushButton#seg:hover {{ color: {P['text']}; }}"
            f"QPushButton#seg:checked {{ background: {P['surface']}; color: {P['text']};"
            f" border: 1px solid {P['border_strong']}; }}")
        if options:
            self.set_current(options[0][0])

    def set_current(self, key: str) -> None:
        if key in self.buttons:
            self.buttons[key].setChecked(True)


class Gauge(QWidget):
    """Horizontal gauge: fill = measured / threshold, threshold marker at 62.5 %."""
    SPAN = 1.6

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(8)
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
        p.drawRoundedRect(QRectF(0, 0, w, h), h / 2, h / 2)
        fw = w * self._ratio / self.SPAN
        if fw > 1:
            p.setBrush(c(self._tone))
            p.drawRoundedRect(QRectF(0, 0, fw, h), h / 2, h / 2)
        x = w / self.SPAN
        p.setBrush(c("text", 150))
        p.drawRoundedRect(QRectF(x - 1, -1, 2, h + 2), 1, 1)


class KpiCard(QFrame):
    def __init__(self, name: str, target: str, meaning: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("softCard")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 12)
        lay.setSpacing(5)
        top = QHBoxLayout()
        top.setSpacing(6)
        self.name = label(name, "h2")
        self.name.setStyleSheet("font-size: 10pt;")
        self.pill = Pill("LIVE", "sky", size=7.8)
        top.addWidget(self.name)
        top.addStretch(1)
        top.addWidget(self.pill)
        lay.addLayout(top)
        mid = QHBoxLayout()
        self.value = QLabel("—")
        self.value.setFont(font(17, 650))
        self.target = label(f"target {target}", "caption")
        mid.addWidget(self.value)
        mid.addStretch(1)
        mid.addWidget(self.target, 0, Qt.AlignmentFlag.AlignBottom)
        lay.addLayout(mid)
        self.gauge = Gauge()
        lay.addWidget(self.gauge)
        self.detail = label(meaning, "faint", wrap=True)
        lay.addWidget(self.detail)
        self.setToolTip(meaning)
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
    def __init__(self, name: str, value: str = "—", parent=None) -> None:
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        self.name = label(name, "caption")
        self.value = QLabel(value)
        self.value.setFont(mono(9.5, 600))
        self.value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(self.name)
        lay.addStretch(1)
        lay.addWidget(self.value)

    def set(self, text: str) -> None:
        if self.value.text() != text:
            self.value.setText(text)


# ----------------------------------------------------------------------------- icons
def draw_platform(p: QPainter, kind: str, cx: float, cy: float, size: float,
                  heading: float = 0.0, color: QColor = None, roll: float = 0.0) -> None:
    """Small vector silhouettes. heading in radians, 0 = pointing right on screen."""
    color = color or c("text")
    p.save()
    p.translate(cx, cy)
    s = size / 24.0
    p.scale(s, s)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    if kind == "quad":
        p.rotate(math.degrees(heading) * 0.15)
        p.setPen(QPen(color, 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(-8, -5), QPointF(8, 5))
        p.drawLine(QPointF(-8, 5), QPointF(8, -5))
        p.setPen(QPen(color, 1.6))
        p.setBrush(QColor(color.red(), color.green(), color.blue(), 60))
        for x, y in ((-9, -6), (9, 6), (-9, 6), (9, -6)):
            p.drawEllipse(QPointF(x, y), 4.8, 1.8)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawRoundedRect(QRectF(-3.5, -2.5, 7, 5), 2, 2)
    elif kind == "fixedwing":
        p.rotate(math.degrees(heading))
        path = QPainterPath()
        path.moveTo(12, 0)
        path.lineTo(4, -1.8)
        path.lineTo(1, -11)
        path.lineTo(-2, -11)
        path.lineTo(-1, -2)
        path.lineTo(-8, -2)
        path.lineTo(-11, -6)
        path.lineTo(-12.5, -6)
        path.lineTo(-11, 0)
        path.lineTo(-12.5, 6)
        path.lineTo(-11, 6)
        path.lineTo(-8, 2)
        path.lineTo(-1, 2)
        path.lineTo(-2, 11)
        path.lineTo(1, 11)
        path.lineTo(4, 1.8)
        path.closeSubpath()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawPath(path)
    elif kind == "ship":
        p.rotate(math.degrees(roll) * 1.5)
        hull = QPolygonF([QPointF(-13, 2), QPointF(13, 2), QPointF(9, 8), QPointF(-10, 8)])
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawPolygon(hull)
        p.drawRect(QRectF(-6, -3, 10, 5))
        p.setPen(QPen(color, 1.6))
        p.drawLine(QPointF(0, -3), QPointF(0, -14))
        p.drawLine(QPointF(-4, -10), QPointF(4, -10))
    p.restore()


def draw_hazard(p: QPainter, key: str, r: QRectF, color: QColor) -> None:
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    cx, cy, s = r.center().x(), r.center().y(), min(r.width(), r.height()) / 20.0
    pen = QPen(color, 1.7 * s, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
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
        if self.kind == "hazard":
            col = QColor(HAZARD_COLOR[self.key])
            bg = QColor(col)
            bg.setAlpha(46 if self.active else 26)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(bg)
            p.drawRoundedRect(r, 10, 10)
            draw_hazard(p, self.key, r.adjusted(4, 4, -4, -4), col if self.active else c("faint"))
        else:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c("accent_soft") if self.active else c("surface_alt"))
            p.drawRoundedRect(r, 10, 10)
            draw_platform(p, self.key, r.center().x(), r.center().y(), r.width() * 0.62,
                          0.0, c("accent") if self.active else c("muted"))


class PatternTile(QAbstractButton):
    def __init__(self, key: str, name: str, platform: str, parent=None) -> None:
        super().__init__(parent)
        self.key, self.name, self.platform = key, name, platform
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(56)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._hover = False

    def enterEvent(self, e) -> None:
        self._hover = True
        self.update()

    def leaveEvent(self, e) -> None:
        self._hover = False
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(120, 56)

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        on = self.isChecked()
        p.setPen(QPen(c("accent") if on else (c("border_strong") if self._hover else c("border")), 1.4 if on else 1))
        p.setBrush(c("accent_soft") if on else (c("surface_alt") if self._hover else c("surface")))
        p.drawRoundedRect(r, 11, 11)
        ic = QRectF(r.left() + 8, r.center().y() - 15, 30, 30)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c("surface") if on else c("surface_alt"))
        p.drawRoundedRect(ic, 9, 9)
        draw_platform(p, self.platform, ic.center().x(), ic.center().y(), 20, 0.0,
                      c("accent") if on else c("muted"))
        p.setPen(c("text") if on else c("text", 220))
        p.setFont(font(9.2, 650 if on else 550))
        tr = QRectF(ic.right() + 8, r.top(), r.right() - ic.right() - 10, r.height())
        p.drawText(tr, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap, self.name)
