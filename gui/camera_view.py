"""Camera sensor view: the raw NIR frame the tracker sees, with clean analytical overlays."""

import math
import time
from typing import Optional

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from fsoc.core.geometry import CameraIntrinsics, los_to_pixel
from .theme import STATE_COLOR, c, font, mono

DEG = math.pi / 180.0


class CameraView(QWidget):
    """The sensor image with analytical overlays. Click it to tell the tracker which light to
    follow — indispensable on real video, where there is no telemetry cue to point the way."""

    seeded = Signal(float, float)          # target picked, in image pixel coordinates

    def __init__(self, K: CameraIntrinsics, parent=None) -> None:
        super().__init__(parent)
        self.K = K
        self.snap = None
        self._qimg: Optional[QImage] = None
        self._buf = None
        self._frame_id = -1
        self.clickable = False
        self._seed_px: Optional[tuple] = None
        self._seed_t = 0.0
        self.layers = {"truth": True, "detections": True, "identity": True, "track": True, "roi": True,
                       "search": True, "zoom": True}
        self.setMinimumSize(360, 270)

    def set_intrinsics(self, K: CameraIntrinsics) -> None:
        """Follow the engine when it swaps cameras (simulator <-> a video of a different size),
        otherwise every overlay would be drawn at the previous sensor's scale."""
        if K is not self.K:
            self.K = K
            self._frame_id = -1
            self.update()

    def set_clickable(self, on: bool) -> None:
        self.clickable = on
        self.setCursor(Qt.CursorShape.CrossCursor if on else Qt.CursorShape.ArrowCursor)
        self.setToolTip("Click the light you want tracked" if on else "")

    def mousePressEvent(self, e) -> None:
        if not self.clickable or self._qimg is None:
            return
        r = self._image_rect()
        if not r.contains(e.position()):
            return
        k = self.K.width / max(r.width(), 1e-6)
        x = (e.position().x() - r.left()) * k
        y = (e.position().y() - r.top()) * (self.K.height / max(r.height(), 1e-6))
        self._seed_px = (x, y)
        self._seed_t = time.monotonic()
        self.seeded.emit(x, y)
        self.update()

    def set_layer(self, key: str, on: bool) -> None:
        self.layers[key] = on
        self.update()

    def set_snapshot(self, snap) -> None:
        if snap is None or snap is self.snap:
            return
        self.snap = snap
        if snap.out.frame_id != self._frame_id:
            self._frame_id = snap.out.frame_id
            img = np.ascontiguousarray(snap.image)
            self._buf = img
            h, w = img.shape
            self._qimg = QImage(img.data, w, h, w, QImage.Format.Format_Grayscale8)
        self.update()

    def _img_wh(self):
        """Dimensions of the frame actually on screen — never assume it matches the intrinsics,
        or a video of a different size to the simulator draws every overlay at the wrong scale."""
        if self._buf is not None:
            return float(self._buf.shape[1]), float(self._buf.shape[0])
        return float(self.K.width), float(self.K.height)

    def _image_rect(self) -> QRectF:
        W, H = self.width(), self.height()
        iw, ih = self._img_wh()
        s = min(W / iw, H / ih)
        w, h = iw * s, ih * s
        return QRectF((W - w) / 2, (H - h) / 2, w, h)

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = self._image_rect()
        clip = QPainterPath()
        clip.addRoundedRect(r, 12, 12)
        p.setClipPath(clip)
        p.fillRect(r, QColor("#0C0B12"))
        s = self.snap
        if s is None or self._qimg is None:
            p.setPen(c("faint"))
            p.setFont(font(10))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, "Waiting for sensor…")
            return
        p.drawImage(r, self._qimg)
        iw, ih = self._img_wh()
        k = r.width() / iw
        ky = r.height() / ih
        o = s.out

        def pt(u, v):
            return QPointF(r.left() + u * k, r.top() + v * ky)

        state = "PAUSED" if s.paused else o.state
        scol = c(STATE_COLOR.get(state, ("faint", state))[0])

        if self.layers["search"] and o.state in ("SEARCH", "REACQUIRE"):
            self._draw_search(p, s, pt)

        cx, cy = self.K.cx, self.K.cy
        p.setPen(QPen(QColor(255, 255, 255, 120), 1))
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            p.drawLine(pt(cx + dx * 10, cy + dy * 10), pt(cx + dx * 34, cy + dy * 34))
        p.setPen(QPen(c("mint", 190), 1.2, Qt.PenStyle.DashLine))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(pt(cx, cy), 10 * k, 10 * k)

        x0, y0, x1, y1 = o.roi
        if self.layers["roi"] and (x1 - x0) < self.K.width:
            p.setPen(QPen(c("accent", 200), 1.2, Qt.PenStyle.DashLine))
            p.drawRoundedRect(QRectF(pt(x0, y0), pt(x1, y1)), 6, 6)

        if self.layers["detections"]:
            p.setPen(QPen(QColor(255, 255, 255, 110), 1))
            for (u, v, snr) in o.candidates[:24]:
                p.drawEllipse(pt(u, v), 7 * max(k, 0.8), 7 * max(k, 0.8))
            p.setPen(QPen(c("sky", 220), 1.3, Qt.PenStyle.DashLine))
            for (u, v) in o.hypotheses_px:
                p.drawEllipse(pt(u, v), 11, 11)
            if o.measurement:
                m = pt(*o.measurement)
                p.setPen(QPen(c("sky"), 1.6))
                p.drawLine(m + QPointF(-6, 0), m + QPointF(6, 0))
                p.drawLine(m + QPointF(0, -6), m + QPointF(0, 6))

        if self.layers["identity"]:
            p.setFont(mono(7.4, 600))
            for (u, v, prob, freq, locked) in o.sources[:6]:
                if prob < 0.05 and not locked:
                    continue
                q = pt(u, v)
                col = c("mint") if locked else (c("sky") if prob >= 0.6 else QColor(255, 255, 255, 150))
                self._tag(p, q + QPointF(10, 14), f"{prob * 100:.0f}% · {freq:.1f} Hz", col, small=True)

        if self.layers["truth"] and s.truth.target_px and s.truth.in_fov:
            q = pt(*s.truth.target_px)
            p.setPen(QPen(c("mint"), 1.4))
            p.setBrush(Qt.BrushStyle.NoBrush)
            d = 5
            p.drawPolygon([q + QPointF(0, -d), q + QPointF(d, 0), q + QPointF(0, d), q + QPointF(-d, 0)])

        if self.layers["track"] and o.track_px and o.state in ("LOCKED", "COASTING", "ACQUIRING"):
            q = pt(*o.track_px)
            self._brackets(p, q, 18, scol, o.state == "COASTING")
            p.setFont(font(8.2, 650))
            if o.state == "LOCKED":
                txt = f"LOCK · ID {o.lock_p * 100:.0f}%" if o.lock_p > 0 else "LOCK · learning ID"
            else:
                txt = {"COASTING": "COAST · predicted", "ACQUIRING": "confirming…"}[o.state]
            self._tag(p, q + QPointF(22, -22), txt, scol)
        elif o.track_px is None and o.state in ("SEARCH", "REACQUIRE"):
            self._offscreen(p, s, r, pt)

        if self._seed_px is not None and time.monotonic() - self._seed_t < 2.5:
            q = pt(*self._seed_px)
            p.setPen(QPen(c("butter"), 1.6, Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(q, 26, 26)
            p.setFont(font(8, 650))
            self._tag(p, q + QPointF(30, 0), "track this", c("butter"))

        self._hud(p, s, r, state, scol)
        if self.layers["zoom"]:
            self._zoom(p, s, r)

    def _brackets(self, p, q, size, col, dashed=False) -> None:
        p.setPen(QPen(col, 2.0, Qt.PenStyle.DashLine if dashed else Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        L = size * 0.45
        for sx in (-1, 1):
            for sy in (-1, 1):
                corner = q + QPointF(sx * size, sy * size)
                p.drawLine(corner, corner + QPointF(-sx * L, 0))
                p.drawLine(corner, corner + QPointF(0, -sy * L))

    def _tag(self, p, at: QPointF, text: str, col: QColor, small: bool = False) -> None:
        fm = p.fontMetrics()
        w = fm.horizontalAdvance(text) + (10 if small else 14)
        h = 16 if small else 20
        rect = QRectF(at.x(), at.y() - h / 2, w, h)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(20, 18, 30, 170))
        p.drawRoundedRect(rect, h / 2, h / 2)
        p.setPen(col)
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    def _draw_search(self, p, s, pt) -> None:
        caz, cel, b, rmax, _ = s.search
        gaz, gel = s.gimbal[0], s.gimbal[1]
        path = QPainterPath()
        started = False
        n = 160
        theta_max = rmax / b
        for i in range(n + 1):
            th = theta_max * i / n
            rr = b * th
            px = los_to_pixel(caz + rr * math.cos(th) / max(0.2, math.cos(cel)), cel + rr * math.sin(th), gaz, gel, self.K)
            if px is None or not (-200 < px[0] < self.K.width + 200 and -200 < px[1] < self.K.height + 200):
                started = False
                continue
            q = pt(*px)
            if started:
                path.lineTo(q)
            else:
                path.moveTo(q)
                started = True
        p.setPen(QPen(c("peach", 150), 1.4, Qt.PenStyle.DotLine))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)

    def _offscreen(self, p, s, r, pt) -> None:
        cue = s.cue
        px = los_to_pixel(cue[0], cue[1], s.gimbal[0], s.gimbal[1], self.K)
        if px is None:
            return
        u, v = px
        cue_name = "ephemeris" if s.domain == "space" else "GPS cue"
        if 0 <= u < self.K.width and 0 <= v < self.K.height:
            q = pt(u, v)
            p.setPen(QPen(c("peach", 200), 1.2, Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(q, 26, 26)
            p.setFont(font(8, 600))
            self._tag(p, q + QPointF(30, -10), cue_name, c("peach"))
            return
        ang = math.atan2(v - self.K.cy, u - self.K.cx)
        rad = min(r.width(), r.height()) * 0.42
        tip = r.center() + QPointF(math.cos(ang) * rad, math.sin(ang) * rad)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c("peach", 220))
        a1, a2 = ang + 2.6, ang - 2.6
        p.drawPolygon([tip, tip + QPointF(math.cos(a1) * 16, math.sin(a1) * 16),
                       tip + QPointF(math.cos(a2) * 16, math.sin(a2) * 16)])
        p.setFont(font(8, 600))
        self._tag(p, tip + QPointF(-40 if math.cos(ang) > 0 else 12, 22 if math.sin(ang) < 0 else -22), cue_name,
                  c("peach"))

    def _hud(self, p, s, r, state, scol) -> None:
        p.setFont(font(8.6, 700))
        text = STATE_COLOR.get(state, ("faint", state))[1].upper()
        w = p.fontMetrics().horizontalAdvance(text) + 34
        rect = QRectF(r.left() + 12, r.top() + 12, w, 24)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(20, 18, 30, 175))
        p.drawRoundedRect(rect, 12, 12)
        p.setBrush(scol)
        p.drawEllipse(QPointF(rect.left() + 13, rect.center().y()), 4.5, 4.5)
        p.setPen(QColor(255, 255, 255, 235))
        p.drawText(rect.adjusted(22, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter, text)

        info = f"NIR · 4°×3° · {s.rates['vision'] or 0:.0f} FPS"
        p.setFont(mono(8, 500))
        w2 = p.fontMetrics().horizontalAdvance(info) + 18
        rect2 = QRectF(r.right() - w2 - 12, r.top() + 12, w2, 24)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(20, 18, 30, 150))
        p.drawRoundedRect(rect2, 12, 12)
        p.setPen(QColor(255, 255, 255, 200))
        p.drawText(rect2, Qt.AlignmentFlag.AlignCenter, info)

        k = r.width() / self.K.width
        L = self.K.px_per_deg * 0.1 * k
        y, x = r.bottom() - 18, r.left() + 16
        p.setPen(QPen(QColor(255, 255, 255, 200), 2))
        p.drawLine(QPointF(x, y), QPointF(x + L, y))
        p.drawLine(QPointF(x, y - 4), QPointF(x, y + 4))
        p.drawLine(QPointF(x + L, y - 4), QPointF(x + L, y + 4))
        p.setFont(mono(8, 500))
        p.drawText(QPointF(x + L + 8, y + 4), "0.1°  ·  ○ ±10 px")

    def _zoom(self, p, s, r) -> None:
        o = s.out
        center = o.track_px if (o.track_px and o.state in ("LOCKED", "COASTING")) else None
        if center is None or self._buf is None:
            return
        u, v = int(round(center[0])), int(round(center[1]))
        half = 14
        H, W = self._buf.shape
        if not (half <= u < W - half and half <= v < H - half):
            return
        crop = np.ascontiguousarray(self._buf[v - half:v + half, u - half:u + half])
        qi = QImage(crop.data, 2 * half, 2 * half, 2 * half, QImage.Format.Format_Grayscale8)
        size = min(132.0, r.width() * 0.2)
        box = QRectF(r.right() - size - 14, r.bottom() - size - 14, size, size)
        p.save()
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        path = QPainterPath()
        path.addRoundedRect(box, 10, 10)
        p.setClipPath(path)
        p.drawImage(box, qi)
        zk = size / (2 * half)

        def zp(x, y):
            return QPointF(box.left() + (x - (u - half)) * zk, box.top() + (y - (v - half)) * zk)
        if o.measurement:
            m = zp(*o.measurement)
            p.setPen(QPen(c("sky"), 1.5))
            p.drawLine(m + QPointF(-7, 0), m + QPointF(7, 0))
            p.drawLine(m + QPointF(0, -7), m + QPointF(0, 7))
        if self.layers["truth"] and s.truth.target_px:
            p.setPen(QPen(c("mint"), 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(zp(*s.truth.target_px), 4, 4)
        p.restore()
        p.setPen(QPen(QColor(255, 255, 255, 170), 1.2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(box, 10, 10)
        p.setFont(mono(7.6, 600))
        err = s.centroid_err
        txt = f"×{zk:.1f}   Δ {err:.2f} px" if err is not None else f"×{zk:.1f}"
        p.setPen(QColor(255, 255, 255, 220))
        p.drawText(QRectF(box.left(), box.top() - 18, box.width(), 16), Qt.AlignmentFlag.AlignRight, txt)
