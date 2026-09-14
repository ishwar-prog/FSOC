"""World view: interactive perspective scene of the FSOC link (drag to orbit, wheel to zoom)."""

import math
import random
import time
from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
                           QRadialGradient)
from PySide6.QtWidgets import QWidget

from fsoc.core.geometry import gimbal_basis
from fsoc.sim.patterns import INFO_BY_KEY
from fsoc.sim.world import CAMERA_POS
from .theme import HAZARD_COLOR, P, STATE_COLOR, c, font, mono
from .widgets import draw_platform

ALT_EX = 2.2          # vertical exaggeration so altitude reads clearly
DEG = math.pi / 180.0


class WorldView(QWidget):
    DEFAULT = (-24.0, 13.0, 3300.0)

    def __init__(self, engine, parent=None) -> None:
        super().__init__(parent)
        self.engine = engine
        self.snap = None
        self.setMinimumSize(420, 240)
        self.setMouseTracking(True)
        self.yaw, self.pitch, self.dist = self.DEFAULT
        self._goal = list(self.DEFAULT)
        self._drag: Optional[QPointF] = None
        self.focus = (0.0, 120.0, 1350.0)
        rng = random.Random(7)
        self._hills = [(a, 120 + 260 * rng.random() ** 1.7) for a in range(-80, 81, 4)]
        self._rain = [(rng.random(), rng.random(), 0.5 + rng.random()) for _ in range(140)]
        self._t0 = time.perf_counter()
        self._bg = None
        self._bg_key = None

    # ------------------------------------------------------------- interaction
    def mousePressEvent(self, e) -> None:
        self._drag = e.position()

    def mouseReleaseEvent(self, e) -> None:
        self._drag = None

    def mouseMoveEvent(self, e) -> None:
        if self._drag is not None:
            d = e.position() - self._drag
            self._drag = e.position()
            self._goal[0] = max(-75, min(75, self._goal[0] + d.x() * 0.25))
            self._goal[1] = max(4, min(55, self._goal[1] + d.y() * 0.15))

    def wheelEvent(self, e) -> None:
        f = 0.88 if e.angleDelta().y() > 0 else 1.14
        self._goal[2] = max(1400, min(7000, self._goal[2] * f))

    def mouseDoubleClickEvent(self, e) -> None:
        self._goal = list(self.DEFAULT)

    def set_snapshot(self, snap) -> None:
        self.snap = snap

    # ------------------------------------------------------------- projection
    def _setup(self):
        k = 0.16
        self.yaw += (self._goal[0] - self.yaw) * k
        self.pitch += (self._goal[1] - self.pitch) * k
        self.dist += (self._goal[2] - self.dist) * k
        yaw, pitch = self.yaw * DEG, self.pitch * DEG
        fx, fy, fz = self.focus
        cp = math.cos(pitch)
        self.eye = (fx - self.dist * math.sin(yaw) * cp, fy + self.dist * math.sin(pitch), fz - self.dist * math.cos(yaw) * cp)
        f = (fx - self.eye[0], fy - self.eye[1], fz - self.eye[2])
        n = math.sqrt(f[0] ** 2 + f[1] ** 2 + f[2] ** 2)
        self.fwd = (f[0] / n, f[1] / n, f[2] / n)
        r = (self.fwd[2], 0.0, -self.fwd[0])
        rn = math.hypot(r[0], r[2])
        self.right = (r[0] / rn, 0.0, r[2] / rn)
        fw, rt = self.fwd, self.right
        self.up = (fw[1] * rt[2] - fw[2] * rt[1], fw[2] * rt[0] - fw[0] * rt[2], fw[0] * rt[1] - fw[1] * rt[0])
        self.W, self.H = self.width(), self.height()
        self.fpx = (self.H / 2) / math.tan(19 * DEG)
        self.cy0 = self.H * 0.5

    def proj(self, x, y, z, exaggerate=True):
        if exaggerate:
            y = y * ALT_EX
        d0, d1, d2 = x - self.eye[0], y - self.eye[1], z - self.eye[2]
        zc = d0 * self.fwd[0] + d1 * self.fwd[1] + d2 * self.fwd[2]
        if zc < 5.0:
            return None
        xc = d0 * self.right[0] + d2 * self.right[2]
        yc = d0 * self.up[0] + d1 * self.up[1] + d2 * self.up[2]
        return QPointF(self.W / 2 + self.fpx * xc / zc, self.cy0 - self.fpx * yc / zc)

    def _polyline(self, pts) -> QPainterPath:
        path = QPainterPath()
        pen_down = False
        for pt in pts:
            if pt is None:
                pen_down = False
                continue
            if pen_down:
                path.lineTo(pt)
            else:
                path.moveTo(pt)
                pen_down = True
        return path

    # ------------------------------------------------------------------ paint
    def paintEvent(self, e) -> None:
        self.engine.report_render_frame()
        s = self.snap
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._setup()
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(self.rect()), 12, 12)
        p.setClipPath(clip)

        t, tpos, gaz, gel = self.engine.live_pose()
        world = self.engine.world
        levels = s.hazard_levels if s else {}
        tod = world.time_of_day
        maritime = world.patterns.key == "maritime"
        anim = time.perf_counter() - self._t0

        horizon = self.proj(self.eye[0] + self.fwd[0] * 1e6, self.eye[1], self.eye[2] + self.fwd[2] * 1e6, False)
        hy = horizon.y() if horizon else self.H * 0.45
        # Static layers are cached and only re-rendered when the viewpoint or scene type changes.
        key = (self.W, self.H, round(self.yaw, 2), round(self.pitch, 2), round(self.dist), tod, maritime)
        if key != self._bg_key or self._bg is None:
            dpr = self.devicePixelRatioF()
            self._bg = QPixmap(int(self.W * dpr), int(self.H * dpr))
            self._bg.setDevicePixelRatio(dpr)
            self._bg.fill(Qt.GlobalColor.transparent)
            bp = QPainter(self._bg)
            bp.setRenderHint(QPainter.RenderHint.Antialiasing)
            self._sky(bp, hy, tod, levels)
            self._hills_and_ground(bp, hy, tod, maritime)
            self._grid(bp, maritime)
            self._rings(bp)
            bp.end()
            self._bg_key = key
        p.drawPixmap(0, 0, self._bg)
        self._sun(p, world, t, levels, tod)

        state = "PAUSED" if (s and s.paused) else (s.out.state if s else "SEARCH")
        scol = c(STATE_COLOR.get(state, ("faint", ""))[0])

        # decoys
        if levels.get("decoys", 0) > 0.01:
            for pos, inten in world.decoys(t):
                q = self.proj(*pos)
                if q:
                    self._glow(p, q, 7 + 8 * min(1, inten), QColor(HAZARD_COLOR["decoys"]), 150)

        # trail & future path
        info = INFO_BY_KEY[world.patterns.key]
        past = [world.target_pos(t - i * 0.25) for i in range(60, -1, -1)]
        fut = [world.target_pos(t + i * 0.5) for i in range(0, 41)]
        path_fut = self._polyline([self.proj(*q) for q in fut])
        p.setPen(QPen(c("accent", 110), 1.4, Qt.PenStyle.DotLine))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path_fut)
        pts = [self.proj(*q) for q in past]
        for i in range(1, len(pts)):
            if pts[i] is None or pts[i - 1] is None:
                continue
            a = int(30 + 190 * i / len(pts))
            p.setPen(QPen(c("accent", a), 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(pts[i - 1], pts[i])

        # terminal A
        head = CAMERA_POS
        qa = self.proj(0, 0, 0)
        qh = self.proj(*head)
        vib = levels.get("vibration", 0.0)
        if qa and qh:
            jit = QPointF(math.sin(anim * 71) * 2.2 * vib, math.cos(anim * 57) * 1.6 * vib)
            self._terminal_a(p, qa, qh + jit, gaz)

        # boresight ray + FOV footprint at target range
        rng_t = math.dist(tpos, head)
        f, r, u = gimbal_basis(gaz, gel)
        if qh:
            end = self.proj(head[0] + f[0] * rng_t, head[1] + f[1] * rng_t, head[2] + f[2] * rng_t)
            if end:
                p.setPen(QPen(c("accent", 150), 1.2, Qt.PenStyle.DashLine))
                p.drawLine(qh, end)
            tx, ty = math.tan(2.0 * DEG) * 1.0, math.tan(1.5 * DEG) * 1.0
            corners = []
            for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
                d = (f[0] + r[0] * sx * tx + u[0] * sy * ty, f[1] + r[1] * sx * tx + u[1] * sy * ty,
                     f[2] + r[2] * sx * tx + u[2] * sy * ty)
                corners.append(self.proj(head[0] + d[0] * rng_t, head[1] + d[1] * rng_t, head[2] + d[2] * rng_t))
            if all(corners):
                path = QPainterPath()
                path.moveTo(corners[0])
                for q in corners[1:]:
                    path.lineTo(q)
                path.closeSubpath()
                p.setPen(QPen(c("accent", 200), 1.2))
                p.setBrush(c("accent", 45))
                p.drawPath(path)

        # search spiral in the world
        if s and s.out.state in ("SEARCH", "REACQUIRE") and qh:
            self._spiral(p, s, rng_t)

        # target: shadow, drop line, LOS beam, occluders, icon
        qt = self.proj(*tpos)
        qs = self.proj(tpos[0], 0, tpos[2])
        if qt and qs:
            p.setPen(QPen(c("text", 50), 1, Qt.PenStyle.DashLine))
            p.drawLine(qs, qt)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c("text", 40))
            p.drawEllipse(qs, 9, 3.5)
        if qt and qh:
            locked = state in ("LOCKED", "COASTING")
            p.setPen(QPen(QColor(scol.red(), scol.green(), scol.blue(), 70 if locked else 35), 7,
                          Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(qh, qt)
            p.setPen(QPen(scol, 1.8 if locked else 1.0, Qt.PenStyle.SolidLine if locked else Qt.PenStyle.DashLine))
            p.drawLine(qh, qt)
            if s and s.truth.occluded:
                mid = qh + (qt - qh) * 0.82
                self._occluder(p, mid, s.truth.occlusion_kind, anim)
        if qt:
            v = world.target_vel(t)
            q2 = self.proj(tpos[0] + v[0] * 3, tpos[1] + v[1] * 3, tpos[2] + v[2] * 3)
            heading = math.atan2(q2.y() - qt.y(), q2.x() - qt.x()) if q2 else 0.0
            pulse = 0.5 + 0.5 * math.sin(anim * 5.0)
            self._glow(p, qt, 18 + 6 * pulse, QColor(255, 236, 170), 200)
            draw_platform(p, info.platform, qt.x(), qt.y(), 30, heading, c("ink"),
                          roll=world.patterns.ship_roll(t))
            self._label(p, qt + QPointF(20, -26), "Terminal B",
                        f"{rng_t / 1000:.2f} km · {tpos[1]:.0f} m alt · {math.sqrt(sum(x * x for x in v)):.0f} m/s")

        # atmosphere overlays
        self._atmosphere(p, hy, levels, anim)
        self._minimap(p, t, tpos, gaz, scol, world)
        self._legend(p, s, info)
        p.setPen(c("faint"))
        p.setFont(font(8))
        p.drawText(QRectF(14, self.H - 24, 400, 18), Qt.AlignmentFlag.AlignLeft,
                   "Drag to orbit · scroll to zoom · double-click to reset   (altitude ×2.2)")

    # --------------------------------------------------------------- pieces
    def _sky(self, p, hy, tod, levels) -> None:
        g = QLinearGradient(0, 0, 0, max(hy, 1))
        top, bottom = {"day": ("#BFD7EE", "#EEF1F8"), "dusk": ("#8D8BB8", "#F2C9B8"),
                       "night": ("#2B2F4A", "#4A4E6E")}[tod]
        g.setColorAt(0, QColor(top))
        g.setColorAt(1, QColor(bottom))
        p.fillRect(QRectF(0, 0, self.W, hy + 2), g)
        if tod == "night":
            rng = random.Random(3)
            p.setPen(Qt.PenStyle.NoPen)
            for _ in range(70):
                p.setBrush(QColor(255, 255, 255, rng.randint(60, 180)))
                p.drawEllipse(QPointF(rng.random() * self.W, rng.random() * hy * 0.9), 1.0, 1.0)

    def _sun(self, p, world, t, levels, tod) -> None:
        if tod == "night":
            return
        d = world.sun_direction(t)
        q = self.proj(self.eye[0] + d[0] * 1e6, self.eye[1] + d[1] * 1e6, self.eye[2] + d[2] * 1e6, False)
        if q is None:
            return
        lg = levels.get("glare", 0.0)
        rad = 60 + 160 * lg
        g = QRadialGradient(q, rad)
        g.setColorAt(0, QColor(255, 244, 214, int(120 + 120 * lg)))
        g.setColorAt(0.25, QColor(255, 232, 190, int(50 + 90 * lg)))
        g.setColorAt(1, QColor(255, 230, 190, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.drawEllipse(q, rad, rad)
        p.setBrush(QColor(255, 250, 235, 240))
        p.drawEllipse(q, 12, 12)

    def _hills_and_ground(self, p, hy, tod, maritime) -> None:
        gcol = {"day": ("#DDE7D6", "#C9D8C3"), "dusk": ("#C9B9C3", "#A99AA8"), "night": ("#3C3F52", "#2E3142")}[tod]
        if maritime:
            gcol = {"day": ("#CFE2EE", "#A9C8DC"), "dusk": ("#B7AFC6", "#8F8AA8"), "night": ("#34405A", "#262E44")}[tod]
        g = QLinearGradient(0, hy, 0, self.H)
        g.setColorAt(0, QColor(gcol[0]))
        g.setColorAt(1, QColor(gcol[1]))
        p.fillRect(QRectF(0, hy, self.W, self.H - hy), g)
        if maritime:
            return
        path = QPainterPath()
        pts = []
        R = 9000.0
        for a, h in self._hills:
            ang = a * DEG
            pts.append(self.proj(R * math.sin(ang), h / ALT_EX * 1.0, R * math.cos(ang)))
        pts = [q for q in pts if q is not None]
        if len(pts) > 2:
            path.moveTo(pts[0].x(), hy + 1)
            for q in pts:
                path.lineTo(q)
            path.lineTo(pts[-1].x(), hy + 1)
            path.closeSubpath()
            hc = {"day": "#C3D1C6", "dusk": "#A897AE", "night": "#34374B"}[tod]
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(hc))
            p.drawPath(path)

    def _grid(self, p, maritime) -> None:
        pen = QPen(c("text", 22 if not maritime else 16), 1)
        p.setPen(pen)
        for x in range(-2500, 2501, 250):
            p.drawPath(self._polyline([self.proj(x, 0, z) for z in range(-250, 4251, 500)]))
        for z in range(0, 4001, 250):
            p.drawPath(self._polyline([self.proj(x, 0, z) for x in range(-2500, 2501, 500)]))

    def _rings(self, p) -> None:
        p.setFont(mono(7.8, 600))
        for rkm in (0.5, 1, 2, 3):
            R = rkm * 1000
            pts = [self.proj(R * math.sin(a * DEG), 0, R * math.cos(a * DEG)) for a in range(-70, 71, 5)]
            p.setPen(QPen(c("accent", 70), 1.1, Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(self._polyline(pts))
            q = self.proj(R * math.sin(-60 * DEG), 0, R * math.cos(-60 * DEG))
            if q:
                p.setPen(c("muted"))
                p.drawText(q + QPointF(-10, -4), f"{rkm:g} km")

    def _terminal_a(self, p, base: QPointF, head: QPointF, gaz: float) -> None:
        top = QPointF(base.x(), base.y() - 34)
        p.setPen(QPen(c("text", 200), 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(base + QPointF(-10, 0), top)
        p.drawLine(base + QPointF(10, 0), top)
        p.drawLine(base, top)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c("accent"))
        p.drawRoundedRect(QRectF(top.x() - 9, top.y() - 9, 18, 12), 4, 4)
        p.setBrush(c("ink"))
        a = -gaz * 0.8
        p.drawEllipse(top + QPointF(math.sin(a) * 6, -3), 3, 3)
        self._label(p, top + QPointF(-110, -34), "Terminal A", "gimbal camera · 6 m mast")

    def _spiral(self, p, s, rng_t) -> None:
        caz, cel, b, rmax, _ = s.search
        pts = []
        head = CAMERA_POS
        n = 90
        for i in range(n + 1):
            th = (rmax / b) * i / n
            rr = b * th
            az = caz + rr * math.cos(th)
            el = cel + rr * math.sin(th)
            d = (math.cos(el) * math.sin(az), math.sin(el), math.cos(el) * math.cos(az))
            pts.append(self.proj(head[0] + d[0] * rng_t, head[1] + d[1] * rng_t, head[2] + d[2] * rng_t))
        p.setPen(QPen(c("peach", 160), 1.2, Qt.PenStyle.DotLine))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(self._polyline(pts))

    def _occluder(self, p, q: QPointF, kind: str, anim: float) -> None:
        p.setPen(QPen(c("ink", 210), 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.setBrush(Qt.BrushStyle.NoBrush)
        if kind == "cloud":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 200))
            for dx, dy, rr in ((-14, 2, 12), (0, -4, 16), (16, 2, 11)):
                p.drawEllipse(q + QPointF(dx, dy), rr, rr * 0.75)
            return
        for i, (dx, dy) in enumerate(((0, 0), (-16, 8), (14, 10), (-4, -12))):
            flap = 3 * math.sin(anim * 9 + i)
            b = q + QPointF(dx, dy)
            path = QPainterPath(b + QPointF(-7, -flap))
            path.quadTo(b + QPointF(-3, -4), b)
            path.quadTo(b + QPointF(3, -4), b + QPointF(7, -flap))
            p.drawPath(path)

    def _atmosphere(self, p, hy, levels, anim) -> None:
        lf = levels.get("fog", 0.0)
        if lf > 0.01:
            g = QLinearGradient(0, 0, 0, self.H)
            g.setColorAt(0.0, QColor(245, 246, 250, int(90 * lf)))
            g.setColorAt(max(0.01, min(0.99, hy / self.H)), QColor(245, 246, 250, int(215 * lf)))
            g.setColorAt(1.0, QColor(245, 246, 250, int(120 * lf)))
            p.fillRect(self.rect(), g)
        lr = levels.get("rain", 0.0)
        if lr > 0.01:
            p.setPen(QPen(QColor(110, 140, 175, int(120 * lr)), 1.1))
            n = int(len(self._rain) * lr)
            for x, y, spd in self._rain[:n]:
                yy = ((y + anim * 0.9 * spd) % 1.0) * self.H
                xx = ((x + anim * 0.18 * spd) % 1.0) * self.W
                p.drawLine(QPointF(xx, yy), QPointF(xx + 3.5, yy + 14 * spd))
        lt = levels.get("turbulence", 0.0)
        if lt > 0.01:
            p.setPen(QPen(QColor(227, 168, 107, int(110 * lt)), 1.2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            for k in range(3):
                path = QPainterPath()
                y0 = hy + 10 + k * 14
                path.moveTo(0, y0)
                for x in range(0, self.W + 20, 20):
                    path.lineTo(x, y0 + 3 * math.sin(x * 0.05 + anim * 4 + k))
                p.drawPath(path)

    def _glow(self, p, q: QPointF, rad: float, col: QColor, alpha: int) -> None:
        g = QRadialGradient(q, rad)
        g.setColorAt(0, QColor(col.red(), col.green(), col.blue(), alpha))
        g.setColorAt(1, QColor(col.red(), col.green(), col.blue(), 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.drawEllipse(q, rad, rad)

    def _label(self, p, at: QPointF, title: str, sub: str) -> None:
        p.setFont(font(8.6, 700))
        fm = p.fontMetrics()
        p.setFont(font(7.8, 500))
        fm2 = p.fontMetrics()
        w = max(fm.horizontalAdvance(title), fm2.horizontalAdvance(sub)) + 18
        rect = QRectF(at.x(), at.y(), w, 36)
        if rect.right() > self.W - 8:
            rect.moveRight(self.W - 8)
        if rect.top() < 8:
            rect.moveTop(8)
        p.setPen(QPen(c("border"), 1))
        p.setBrush(QColor(255, 255, 255, 225))
        p.drawRoundedRect(rect, 8, 8)
        p.setPen(c("text"))
        p.setFont(font(8.6, 700))
        p.drawText(rect.adjusted(9, 3, 0, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, title)
        p.setPen(c("muted"))
        p.setFont(font(7.8, 500))
        p.drawText(rect.adjusted(9, 0, 0, -4), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom, sub)

    def _legend(self, p, s, info) -> None:
        rect = QRectF(12, 12, 230, 50)
        p.setPen(QPen(c("border"), 1))
        p.setBrush(QColor(255, 255, 255, 225))
        p.drawRoundedRect(rect, 10, 10)
        p.setPen(c("text"))
        p.setFont(font(9.4, 700))
        p.drawText(rect.adjusted(12, 7, 0, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, info.name)
        p.setPen(c("muted"))
        p.setFont(font(8, 500))
        active = [k for k, v in (s.hazard_levels.items() if s else []) if v > 0.02]
        sub = f"{info.speed} · " + (f"{len(active)} hazard(s) active" if active else "clear conditions")
        p.drawText(rect.adjusted(12, 0, 0, -8), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom, sub)

    def _minimap(self, p, t, tpos, gaz, scol, world) -> None:
        size = 132
        box = QRectF(self.W - size - 12, self.H - size - 12, size, size)
        p.setPen(QPen(c("border"), 1))
        p.setBrush(QColor(255, 255, 255, 225))
        p.drawRoundedRect(box, 12, 12)
        scale = (size / 2 - 12) / 3200.0
        o = QPointF(box.center().x(), box.bottom() - 14)

        def mp(x, z):
            return QPointF(o.x() + x * scale, o.y() - z * scale)
        p.setBrush(Qt.BrushStyle.NoBrush)
        for rkm in (1, 2, 3):
            rr = rkm * 1000 * scale
            p.setPen(QPen(c("accent", 60), 1, Qt.PenStyle.DashLine))
            p.drawArc(QRectF(o.x() - rr, o.y() - rr, 2 * rr, 2 * rr), 0, 180 * 16)
        wedge = QPainterPath(o)
        L = 3300 * scale
        for a in (gaz - 2 * DEG, gaz + 2 * DEG):
            wedge.lineTo(o + QPointF(math.sin(a) * L, -math.cos(a) * L))
        wedge.closeSubpath()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c("accent", 70))
        p.drawPath(wedge)
        trail = [world.target_pos(t - i * 0.5) for i in range(40)]
        p.setPen(QPen(c("accent", 150), 1.4))
        p.drawPath(self._polyline([mp(q[0], q[2]) for q in trail]))
        q = mp(tpos[0], tpos[2])
        p.setPen(QPen(scol, 1.2))
        p.drawLine(o, q)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(scol)
        p.drawEllipse(q, 4, 4)
        p.setBrush(c("ink"))
        p.drawEllipse(o, 3.5, 3.5)
        p.setPen(c("muted"))
        p.setFont(font(7.4, 600))
        p.drawText(box.adjusted(8, 5, 0, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, "TOP VIEW")
