"""World view.

Ground / sea link: interactive perspective scene — drag Terminal B to steer it, drag Terminal A
to move the station, drag empty space to orbit, wheel to zoom.
Space link: schematic of the pass over the ground station (not to scale) plus a live sky plot.
"""

import math
import random
import time
from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient
from PySide6.QtWidgets import QWidget

from fsoc.core.geometry import direction_to_los, gimbal_basis
from fsoc.sim.terminals import RE, OrbitPass
from .theme import HAZARD_COLOR, STATE_COLOR, c, font, is_dark, mono
from .widgets import draw_platform

ALT_EX = 2.2
DEG = math.pi / 180.0


class WorldView(QWidget):
    DEFAULT = (-24.0, 13.0, 3300.0)

    def __init__(self, engine, parent=None) -> None:
        super().__init__(parent)
        self.engine = engine
        self.snap = None
        self.setMinimumSize(360, 220)
        self.setMouseTracking(True)
        self.yaw, self.pitch, self.dist = self.DEFAULT
        self._goal = list(self.DEFAULT)
        self._press: Optional[QPointF] = None
        self._mode = None
        self._ghost = None
        self._scr_a = self._scr_b = None
        self.focus = (0.0, 120.0, 1350.0)
        rng = random.Random(7)
        self._hills = [(a, 120 + 260 * rng.random() ** 1.7) for a in range(-80, 81, 4)]
        self._rain = [(rng.random(), rng.random(), 0.5 + rng.random()) for _ in range(140)]
        self._stars = [(rng.random(), rng.random(), rng.random()) for _ in range(160)]
        self._t0 = time.perf_counter()
        self._bg = None
        self._bg_key = None

    # ------------------------------------------------------------- interaction
    def _space(self) -> bool:
        return self.engine.world.remote.space

    def mousePressEvent(self, e) -> None:
        pos = e.position()
        self._press = pos
        self._mode = "orbit"
        if self._space():
            return
        if self._scr_b is not None and math.dist((pos.x(), pos.y()), (self._scr_b.x(), self._scr_b.y())) < 28:
            self._mode = "B"
        elif self._scr_a is not None and math.dist((pos.x(), pos.y()), (self._scr_a.x(), self._scr_a.y())) < 30:
            self._mode = "A"

    def mouseReleaseEvent(self, e) -> None:
        if self._mode == "B" and self._ghost:
            x, z = self._ghost
            rng = math.hypot(x, z)
            if rng > 4500:
                x, z = x * 4500 / rng, z * 4500 / rng
            self.engine.remote_goto(x, z)
        elif self._mode == "A" and self._ghost:
            x, z = self._ghost
            self.engine.set_ground(x=max(-1500, min(1500, x)), z=max(-1000, min(1500, z)))
        self._mode, self._ghost, self._press = None, None, None

    def mouseMoveEvent(self, e) -> None:
        pos = e.position()
        if self._mode == "orbit" and self._press is not None:
            d = pos - self._press
            self._press = pos
            self._goal[0] = max(-75, min(75, self._goal[0] + d.x() * 0.25))
            self._goal[1] = max(4, min(55, self._goal[1] + d.y() * 0.15))
        elif self._mode in ("A", "B"):
            _, tpos, _, _, _ = self.engine.live_pose()
            plane = tpos[1] * ALT_EX if self._mode == "B" else 0.0
            self._ghost = self.unproject(pos.x(), pos.y(), plane)
        elif not self._space():
            near = any(s is not None and math.dist((pos.x(), pos.y()), (s.x(), s.y())) < 28
                       for s in (self._scr_a, self._scr_b))
            self.setCursor(Qt.CursorShape.OpenHandCursor if near else Qt.CursorShape.ArrowCursor)

    def wheelEvent(self, e) -> None:
        f = 0.88 if e.angleDelta().y() > 0 else 1.14
        self._goal[2] = max(1400, min(7000, self._goal[2] * f))

    def mouseDoubleClickEvent(self, e) -> None:
        self._goal = list(self.DEFAULT)

    def reset_view(self) -> None:
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

    def unproject(self, sx: float, sy: float, plane_y: float):
        a, b = (sx - self.W / 2) / self.fpx, (self.cy0 - sy) / self.fpx
        d = [self.fwd[i] + self.right[i] * a + self.up[i] * b for i in range(3)]
        if abs(d[1]) < 1e-9:
            return None
        tt = (plane_y - self.eye[1]) / d[1]
        if tt <= 0:
            return None
        return (self.eye[0] + tt * d[0], self.eye[2] + tt * d[2])

    def _polyline(self, pts) -> QPainterPath:
        path = QPainterPath()
        down = False
        for pt in pts:
            if pt is None:
                down = False
                continue
            if down:
                path.lineTo(pt)
            else:
                path.moveTo(pt)
                down = True
        return path

    # ------------------------------------------------------------------ paint
    def paintEvent(self, e) -> None:
        self.engine.report_render_frame()
        s = self.snap
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.W, self.H = self.width(), self.height()
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(self.rect()), 12, 12)
        p.setClipPath(clip)
        t, tpos, gaz, gel, cam = self.engine.live_pose()
        state = "PAUSED" if (s and s.paused) else (s.out.state if s else "SEARCH")
        scol = c(STATE_COLOR.get(state, ("faint", ""))[0])
        if self._space():
            self._paint_space(p, s, t, tpos, gaz, gel, cam, state, scol)
        else:
            self._paint_ground(p, s, t, tpos, gaz, gel, cam, state, scol)

    # ================================================================ ground
    def _paint_ground(self, p, s, t, tpos, gaz, gel, cam, state, scol) -> None:
        self._setup()
        world = self.engine.world
        levels = s.hazard_levels if s else {}
        tod = world.time_of_day
        sea = world.remote.info.platform == "ship"
        anim = time.perf_counter() - self._t0

        horizon = self.proj(self.eye[0] + self.fwd[0] * 1e6, self.eye[1], self.eye[2] + self.fwd[2] * 1e6, False)
        hy = horizon.y() if horizon else self.H * 0.45
        key = (self.W, self.H, round(self.yaw, 2), round(self.pitch, 2), round(self.dist), tod, sea, is_dark())
        if key != self._bg_key or self._bg is None:
            dpr = self.devicePixelRatioF()
            self._bg = QPixmap(int(self.W * dpr), int(self.H * dpr))
            self._bg.setDevicePixelRatio(dpr)
            self._bg.fill(Qt.GlobalColor.transparent)
            bp = QPainter(self._bg)
            bp.setRenderHint(QPainter.RenderHint.Antialiasing)
            self._sky(bp, hy, tod)
            self._hills_and_ground(bp, hy, tod, sea)
            self._grid(bp, sea)
            self._rings(bp)
            bp.end()
            self._bg_key = key
        p.drawPixmap(0, 0, self._bg)
        self._sun(p, world, t, levels, tod)

        if levels.get("decoys", 0) > 0.01:
            for pos, inten in world.decoys(t):
                q = self.proj(*pos)
                if q:
                    self._glow(p, q, 5 + 8 * min(1.5, inten), QColor(HAZARD_COLOR["decoys"]), 160)

        info = world.remote.info
        past = [world.target_pos(t - i * 0.25) for i in range(60, -1, -1)]
        fut = [world.target_pos(t + i * 0.5) for i in range(0, 41)]
        p.setPen(QPen(c("accent", 110), 1.4, Qt.PenStyle.DotLine))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(self._polyline([self.proj(*q) for q in fut]))
        pts = [self.proj(*q) for q in past]
        for i in range(1, len(pts)):
            if pts[i] is None or pts[i - 1] is None:
                continue
            p.setPen(QPen(c("accent", int(30 + 190 * i / len(pts))), 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(pts[i - 1], pts[i])

        wp = world.remote.waypoint()
        if wp is not None:
            q = self.proj(wp[0], 0, wp[2])
            if q:
                p.setPen(QPen(c("accent"), 1.6))
                p.setBrush(c("accent", 50))
                p.drawEllipse(q, 10, 4)
                p.drawLine(q, q + QPointF(0, -18))

        qa = self.proj(cam[0], 0, cam[2])
        qh = self.proj(*cam)
        self._scr_a = qa
        vib = levels.get("vibration", 0.0)
        if qa and qh:
            jit = QPointF(math.sin(anim * 71) * 2.2 * vib, math.cos(anim * 57) * 1.6 * vib)
            self._terminal_a(p, qa, qh + jit, gaz, world.ground.mount)

        rng_t = math.dist(tpos, cam)
        f, r, u = gimbal_basis(gaz, gel)
        if qh:
            end = self.proj(cam[0] + f[0] * rng_t, cam[1] + f[1] * rng_t, cam[2] + f[2] * rng_t)
            if end:
                p.setPen(QPen(c("accent", 150), 1.2, Qt.PenStyle.DashLine))
                p.drawLine(qh, end)
            tx, ty = math.tan(2.0 * DEG), math.tan(1.5 * DEG)
            corners = []
            for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
                d = [f[i] + r[i] * sx * tx + u[i] * sy * ty for i in range(3)]
                corners.append(self.proj(cam[0] + d[0] * rng_t, cam[1] + d[1] * rng_t, cam[2] + d[2] * rng_t))
            if all(corners):
                path = QPainterPath()
                path.moveTo(corners[0])
                for q in corners[1:]:
                    path.lineTo(q)
                path.closeSubpath()
                p.setPen(QPen(c("accent", 200), 1.2))
                p.setBrush(c("accent", 45))
                p.drawPath(path)

        if s and s.out.state in ("SEARCH", "REACQUIRE") and qh:
            self._spiral(p, s, rng_t, cam)

        qt = self.proj(*tpos)
        qs = self.proj(tpos[0], 0, tpos[2])
        self._scr_b = qt
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
                self._occluder(p, qh + (qt - qh) * 0.82, s.truth.occlusion_kind, anim)
        if qt:
            v = world.target_vel(t)
            q2 = self.proj(tpos[0] + v[0] * 3, tpos[1] + v[1] * 3, tpos[2] + v[2] * 3)
            heading = math.atan2(q2.y() - qt.y(), q2.x() - qt.x()) if q2 else 0.0
            on = world.beacon.modulation(t) > 0.5
            self._glow(p, qt, 20 if on else 12, QColor(255, 236, 170), 210 if on else 90)
            draw_platform(p, info.platform, qt.x(), qt.y(), 30, heading, QColor("#221E2E"),
                          roll=world.remote.ship_roll(t))
            self._label(p, qt + QPointF(20, -26), "Terminal B",
                        f"{rng_t / 1000:.2f} km · {tpos[1]:.0f} m alt · {math.sqrt(sum(x * x for x in v)):.0f} m/s")

        if self._ghost and self._mode in ("A", "B"):
            gx, gz = self._ghost
            gq = self.proj(gx, 0, gz)
            if gq:
                p.setPen(QPen(c("accent"), 1.6, Qt.PenStyle.DashLine))
                p.setBrush(c("accent", 60))
                p.drawEllipse(gq, 12, 5)
                src = qt if self._mode == "B" else qa
                if src:
                    p.drawLine(src, gq)
                self._label(p, gq + QPointF(14, -40), "Move Terminal " + self._mode,
                            f"release to go · {math.hypot(gx, gz) / 1000:.2f} km")

        self._atmosphere(p, hy, levels, anim)
        self._minimap(p, t, tpos, gaz, scol, world, cam)
        self._legend(p, s, info, world)
        p.setPen(c("faint"))
        p.setFont(font(8))
        p.drawText(QRectF(14, self.H - 24, 520, 18), Qt.AlignmentFlag.AlignLeft,
                   "Drag B to steer · drag A to move · drag empty space to orbit · scroll to zoom")

    def _sky(self, p, hy, tod) -> None:
        g = QLinearGradient(0, 0, 0, max(hy, 1))
        top, bottom = {"day": ("#BFD7EE", "#EEF1F8"), "dusk": ("#8D8BB8", "#F2C9B8"),
                       "night": ("#2B2F4A", "#4A4E6E")}[tod]
        if is_dark() and tod == "day":
            top, bottom = "#6F8FB2", "#AFC2D6"
        g.setColorAt(0, QColor(top))
        g.setColorAt(1, QColor(bottom))
        p.fillRect(QRectF(0, 0, self.W, hy + 2), g)
        if tod == "night":
            p.setPen(Qt.PenStyle.NoPen)
            for x, y, b in self._stars[:70]:
                p.setBrush(QColor(255, 255, 255, int(60 + 120 * b)))
                p.drawEllipse(QPointF(x * self.W, y * hy * 0.9), 1.0, 1.0)

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

    def _hills_and_ground(self, p, hy, tod, sea) -> None:
        gcol = {"day": ("#DDE7D6", "#C9D8C3"), "dusk": ("#C9B9C3", "#A99AA8"), "night": ("#3C3F52", "#2E3142")}[tod]
        if sea:
            gcol = {"day": ("#CFE2EE", "#A9C8DC"), "dusk": ("#B7AFC6", "#8F8AA8"), "night": ("#34405A", "#262E44")}[tod]
        if is_dark() and tod == "day":
            gcol = ("#8FA08A", "#6F806C") if not sea else ("#7C98AE", "#5E7A90")
        g = QLinearGradient(0, hy, 0, self.H)
        g.setColorAt(0, QColor(gcol[0]))
        g.setColorAt(1, QColor(gcol[1]))
        p.fillRect(QRectF(0, hy, self.W, self.H - hy), g)
        if sea:
            return
        pts = [self.proj(9000 * math.sin(a * DEG), h / ALT_EX, 9000 * math.cos(a * DEG)) for a, h in self._hills]
        pts = [q for q in pts if q is not None]
        if len(pts) > 2:
            path = QPainterPath()
            path.moveTo(pts[0].x(), hy + 1)
            for q in pts:
                path.lineTo(q)
            path.lineTo(pts[-1].x(), hy + 1)
            path.closeSubpath()
            hc = {"day": "#C3D1C6", "dusk": "#A897AE", "night": "#34374B"}[tod]
            if is_dark() and tod == "day":
                hc = "#7E927F"
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(hc))
            p.drawPath(path)

    def _grid(self, p, sea) -> None:
        p.setPen(QPen(QColor(30, 30, 50, 22 if not sea else 16), 1))
        for x in range(-2500, 2501, 250):
            p.drawPath(self._polyline([self.proj(x, 0, z) for z in range(-1250, 4251, 500)]))
        for z in range(-1000, 4001, 250):
            p.drawPath(self._polyline([self.proj(x, 0, z) for x in range(-2500, 2501, 500)]))

    def _rings(self, p) -> None:
        p.setFont(mono(7.8, 600))
        for rkm in (0.5, 1, 2, 3):
            R = rkm * 1000
            pts = [self.proj(R * math.sin(a * DEG), 0, R * math.cos(a * DEG)) for a in range(-70, 71, 5)]
            p.setPen(QPen(QColor(139, 124, 200, 80), 1.1, Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(self._polyline(pts))
            q = self.proj(R * math.sin(-60 * DEG), 0, R * math.cos(-60 * DEG))
            if q:
                p.setPen(QColor(90, 86, 110))
                p.drawText(q + QPointF(-10, -4), f"{rkm:g} km")

    def _terminal_a(self, p, base: QPointF, head: QPointF, gaz: float, mount: str) -> None:
        ink = QColor("#2E2A3B")
        if mount == "vehicle":
            draw_platform(p, "vehicle", base.x(), base.y() - 8, 34, 0.0, ink)
        elif mount == "ship":
            draw_platform(p, "ship", base.x(), base.y() - 4, 34, 0.0, ink)
        top = QPointF(base.x(), base.y() - 34)
        p.setPen(QPen(ink, 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        if mount == "fixed":
            p.drawLine(base + QPointF(-10, 0), top)
            p.drawLine(base + QPointF(10, 0), top)
        p.drawLine(base, top)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c("accent"))
        p.drawRoundedRect(QRectF(top.x() - 9, top.y() - 9, 18, 12), 4, 4)
        p.setBrush(ink)
        a = -gaz * 0.8
        p.drawEllipse(top + QPointF(math.sin(a) * 6, -3), 3, 3)
        self._label(p, top + QPointF(-120, -34), "Terminal A", {"fixed": "fixed station", "vehicle": "vehicle mount",
                                                                 "ship": "ship deck"}[mount] + " · drag to move")

    def _spiral(self, p, s, rng_t, cam) -> None:
        caz, cel, b, rmax, _ = s.search
        pts = []
        n = 90
        for i in range(n + 1):
            th = (rmax / b) * i / n
            rr = b * th
            az, el = caz + rr * math.cos(th), cel + rr * math.sin(th)
            d = (math.cos(el) * math.sin(az), math.sin(el), math.cos(el) * math.cos(az))
            pts.append(self.proj(cam[0] + d[0] * rng_t, cam[1] + d[1] * rng_t, cam[2] + d[2] * rng_t))
        p.setPen(QPen(c("peach", 160), 1.2, Qt.PenStyle.DotLine))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(self._polyline(pts))

    def _occluder(self, p, q: QPointF, kind: str, anim: float) -> None:
        p.setPen(QPen(QColor(34, 30, 46, 210), 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
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
            g.setColorAt(max(0.01, min(0.99, hy / max(1, self.H))), QColor(245, 246, 250, int(215 * lf)))
            g.setColorAt(1.0, QColor(245, 246, 250, int(120 * lf)))
            p.fillRect(self.rect(), g)
        lr = levels.get("rain", 0.0)
        if lr > 0.01:
            p.setPen(QPen(QColor(110, 140, 175, int(120 * lr)), 1.1))
            for x, y, spd in self._rain[:int(len(self._rain) * lr)]:
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
        w1 = p.fontMetrics().horizontalAdvance(title)
        p.setFont(font(7.8, 500))
        w2 = p.fontMetrics().horizontalAdvance(sub)
        rect = QRectF(at.x(), at.y(), max(w1, w2) + 18, 36)
        if rect.right() > self.W - 8:
            rect.moveRight(self.W - 8)
        rect.moveLeft(max(8, rect.left()))
        if rect.top() < 8:
            rect.moveTop(8)
        p.setPen(QPen(c("border"), 1))
        p.setBrush(c("surface", 232))
        p.drawRoundedRect(rect, 8, 8)
        p.setPen(c("text"))
        p.setFont(font(8.6, 700))
        p.drawText(rect.adjusted(9, 3, 0, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, title)
        p.setPen(c("muted"))
        p.setFont(font(7.8, 500))
        p.drawText(rect.adjusted(9, 0, 0, -4), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom, sub)

    def _legend(self, p, s, info, world) -> None:
        rect = QRectF(12, 12, 250, 50)
        p.setPen(QPen(c("border"), 1))
        p.setBrush(c("surface", 232))
        p.drawRoundedRect(rect, 10, 10)
        p.setPen(c("text"))
        p.setFont(font(9.4, 700))
        plat = world.remote.platform.name
        p.drawText(rect.adjusted(12, 7, 0, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                   f"{plat} · {info.name}")
        p.setPen(c("muted"))
        p.setFont(font(8, 500))
        active = [k for k, v in (s.hazard_levels.items() if s else []) if v > 0.02]
        sub = f"{world.remote.warp.speed(world.remote.warp._seg[-1][0] + 99):.2f}× speed · " + \
              (f"{len(active)} hazard(s)" if active else "clear conditions")
        p.drawText(rect.adjusted(12, 0, 0, -8), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom, sub)

    def _minimap(self, p, t, tpos, gaz, scol, world, cam) -> None:
        size = 132
        box = QRectF(self.W - size - 12, self.H - size - 12, size, size)
        p.setPen(QPen(c("border"), 1))
        p.setBrush(c("surface", 232))
        p.drawRoundedRect(box, 12, 12)
        scale = (size / 2 - 12) / 3600.0
        o = QPointF(box.center().x(), box.bottom() - 18)

        def mp(x, z):
            return QPointF(o.x() + x * scale, o.y() - z * scale)
        oa = mp(cam[0], cam[2])
        p.setBrush(Qt.BrushStyle.NoBrush)
        for rkm in (1, 2, 3):
            rr = rkm * 1000 * scale
            p.setPen(QPen(c("accent", 60), 1, Qt.PenStyle.DashLine))
            p.drawArc(QRectF(oa.x() - rr, oa.y() - rr, 2 * rr, 2 * rr), 0, 180 * 16)
        wedge = QPainterPath(oa)
        L = 3300 * scale
        for a in (gaz - 2 * DEG, gaz + 2 * DEG):
            wedge.lineTo(oa + QPointF(math.sin(a) * L, -math.cos(a) * L))
        wedge.closeSubpath()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c("accent", 70))
        p.drawPath(wedge)
        trail = [world.target_pos(t - i * 0.5) for i in range(40)]
        p.setPen(QPen(c("accent", 150), 1.4))
        p.drawPath(self._polyline([mp(q[0], q[2]) for q in trail]))
        q = mp(tpos[0], tpos[2])
        p.setPen(QPen(scol, 1.2))
        p.drawLine(oa, q)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(scol)
        p.drawEllipse(q, 4, 4)
        p.setBrush(c("text"))
        p.drawEllipse(oa, 3.5, 3.5)
        p.setPen(c("muted"))
        p.setFont(font(7.4, 600))
        p.drawText(box.adjusted(8, 5, 0, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, "TOP VIEW")

    # ================================================================= space
    def _paint_space(self, p, s, t, tpos, gaz, gel, cam, state, scol) -> None:
        W, H = self.W, self.H
        world = self.engine.world
        remote = world.remote
        g = QLinearGradient(0, 0, 0, H)
        g.setColorAt(0, QColor("#0B0D1F"))
        g.setColorAt(0.7, QColor("#1A1D3A"))
        g.setColorAt(1, QColor("#26294A"))
        p.fillRect(self.rect(), g)
        p.setPen(Qt.PenStyle.NoPen)
        for x, y, b in self._stars:
            p.setBrush(QColor(255, 255, 255, int(40 + 150 * b)))
            p.drawEllipse(QPointF(x * W, y * H * 0.8), 0.6 + b, 0.6 + b)

        # Earth arc and orbit ring (schematic)
        sky_w = W - 200
        R_e = max(sky_w * 1.1, 600.0)
        station = QPointF(sky_w * 0.5, H * 0.84)
        centre = QPointF(station.x(), station.y() + R_e)
        orbit_top = max(H * 0.14, 40.0)
        R_o = centre.y() - orbit_top
        atm = QRadialGradient(centre, R_e + 30)
        atm.setColorAt((R_e - 4) / (R_e + 30), QColor(120, 170, 255, 90))
        atm.setColorAt(1.0, QColor(120, 170, 255, 0))
        p.setBrush(atm)
        p.drawEllipse(centre, R_e + 30, R_e + 30)
        eg = QLinearGradient(0, station.y(), 0, H)
        eg.setColorAt(0, QColor("#3E6FA8"))
        eg.setColorAt(1, QColor("#1F3B63"))
        p.setBrush(eg)
        p.drawEllipse(centre, R_e, R_e)
        p.setPen(QPen(QColor(255, 255, 255, 40), 1, Qt.PenStyle.DashLine))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(centre, R_o, R_o)
        # station local horizon
        p.setPen(QPen(QColor(255, 220, 160, 90), 1, Qt.PenStyle.DashLine))
        p.drawLine(QPointF(station.x() - sky_w * 0.48, station.y()), QPointF(station.x() + sky_w * 0.48, station.y()))

        key = remote.key
        heading = remote.heading * DEG
        vdir = (math.sin(heading), 0.0, math.cos(heading))

        # Exaggerate the geocentric angle just enough that horizon-to-horizon fills the visible sky:
        # the whole pass (rise → culmination → set) stays on screen at any orbit altitude.
        span = math.asin(min(0.95, 0.46 * sky_w / max(R_o, 1.0)))
        orb_obj = getattr(remote, "orbit", None)
        if isinstance(orb_obj, OrbitPass):
            gain = span / max(1e-3, math.acos(RE / orb_obj.r))
        else:
            gain = 1.4

        def to_screen(pos):
            along = pos[0] * vdir[0] + pos[2] * vdir[2]
            up = pos[1] + RE
            psi = math.atan2(along, up)
            psi_s = psi * gain
            return QPointF(centre.x() + R_o * math.sin(psi_s), centre.y() - R_o * math.cos(psi_s))

        if isinstance(getattr(remote, "orbit", None), OrbitPass):
            orb = remote.orbit
            path_vis, path_hid = [], []
            for i in range(121):
                th = orb.theta0 * 1.8 * (1 - 2 * i / 120)
                pos = orb._pos(th)
                q = to_screen(pos)
                (path_vis if OrbitPass.elevation(pos) > 0 else path_hid).append(q)
            p.setPen(QPen(QColor(168, 151, 234, 200), 2.0))
            p.drawPath(self._polyline(path_vis))
        sat = to_screen(tpos)
        # beam and FOV
        locked = state in ("LOCKED", "COASTING")
        p.setPen(QPen(QColor(scol.red(), scol.green(), scol.blue(), 80 if locked else 40), 7, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap))
        p.drawLine(station, sat)
        p.setPen(QPen(scol, 1.8 if locked else 1.0, Qt.PenStyle.SolidLine if locked else Qt.PenStyle.DashLine))
        p.drawLine(station, sat)
        # observatory dome
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#E8E4F5"))
        p.drawRect(QRectF(station.x() - 12, station.y() - 6, 24, 8))
        dome = QPainterPath()
        dome.moveTo(station.x() - 12, station.y() - 6)
        dome.arcTo(QRectF(station.x() - 12, station.y() - 18, 24, 24), 180, -180)
        dome.closeSubpath()
        p.drawPath(dome)
        on = world.beacon.modulation(t) > 0.5
        self._glow(p, sat, 22 if on else 12, QColor(255, 236, 170), 220 if on else 90)
        draw_platform(p, remote.info.platform, sat.x(), sat.y(), 34, 0.0, QColor("#F2EEFF"))

        az, el = direction_to_los(tpos[0] - cam[0], tpos[1] - cam[1], tpos[2] - cam[2])
        v = world.target_vel(t)
        rng_m = math.dist(tpos, cam)
        los2 = direction_to_los(tpos[0] + v[0] - cam[0], tpos[1] + v[1] - cam[1], tpos[2] + v[2] - cam[2])
        rate = math.degrees(math.hypot((los2[0] - az) * math.cos(el), los2[1] - el))
        alt_km = (math.sqrt(tpos[0] ** 2 + (tpos[1] + RE) ** 2 + tpos[2] ** 2) - RE) / 1000
        self._label(p, sat + QPointF(24, -30), f"{remote.platform.name} · {remote.info.name}",
                    f"{alt_km:,.0f} km alt · {rng_m / 1000:,.0f} km range · {rate:.2f} °/s")
        self._label(p, station + QPointF(-150, -58), "Terminal A · ground station",
                    f"el {math.degrees(el):.1f}° · az {math.degrees(az) % 360:.1f}°")
        prog = remote.orbit_phase(t)
        if key != "geo_relay":
            bar = QRectF(16, H - 44, min(260, sky_w * 0.45), 8)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 40))
            p.drawRoundedRect(bar, 4, 4)
            p.setBrush(c("accent"))
            p.drawRoundedRect(QRectF(bar.left(), bar.top(), bar.width() * prog, bar.height()), 4, 4)
            p.setPen(QColor(230, 226, 245))
            p.setFont(font(8, 600))
            p.drawText(QPointF(bar.left(), bar.top() - 6), f"Pass progress {prog * 100:.0f} %  (rise → set)")
        p.setPen(QColor(200, 196, 220))
        p.setFont(font(8))
        p.drawText(QRectF(16, 12, sky_w, 18), Qt.AlignmentFlag.AlignLeft,
                   "Schematic — not to scale · the station points from the predicted orbit, then locks on the beacon")
        self._skyplot(p, s, t, az, el, gaz, gel, scol)

    def _skyplot(self, p, s, t, az, el, gaz, gel, scol) -> None:
        size = min(180.0, self.H - 30.0)
        box = QRectF(self.W - size - 12, 12, size, size + 16)
        p.setPen(QPen(QColor(255, 255, 255, 40), 1))
        p.setBrush(QColor(20, 22, 44, 220))
        p.drawRoundedRect(box, 12, 12)
        ctr = QPointF(box.center().x(), box.top() + 16 + size / 2)
        R = size / 2 - 16

        def sp(a, e):
            rr = R * (1 - max(e, 0.0) / (math.pi / 2))
            return QPointF(ctr.x() + rr * math.sin(a), ctr.y() - rr * math.cos(a))
        p.setBrush(Qt.BrushStyle.NoBrush)
        for e_deg in (0, 30, 60):
            rr = R * (1 - e_deg / 90)
            p.setPen(QPen(QColor(255, 255, 255, 50), 1, Qt.PenStyle.DashLine if e_deg else Qt.PenStyle.SolidLine))
            p.drawEllipse(ctr, rr, rr)
        p.setPen(QColor(200, 196, 220))
        p.setFont(font(7.4, 700))
        for txt, a in (("N", 0), ("E", 90), ("S", 180), ("W", 270)):
            q = sp(a * DEG, -0.12)
            p.drawText(QRectF(q.x() - 8, q.y() - 8, 16, 16), Qt.AlignmentFlag.AlignCenter, txt)
        remote = self.engine.world.remote
        cam = self.engine.world.camera_pos(t)
        if isinstance(getattr(remote, "orbit", None), OrbitPass):
            orb = remote.orbit
            pts = []
            for i in range(61):
                pos = orb._pos(orb.theta0 * (1 - 2 * i / 60))
                a2, e2 = direction_to_los(pos[0] - cam[0], pos[1] - cam[1], pos[2] - cam[2])
                pts.append(sp(a2, e2) if e2 >= 0 else None)
            p.setPen(QPen(QColor(168, 151, 234, 200), 1.6))
            p.drawPath(self._polyline(pts))
        for oaz, oel, _ in self.engine.world.space_objects(t, az, el)[:-1]:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(242, 156, 138, 180))
            p.drawEllipse(sp(oaz, oel), 2.2, 2.2)
        g = sp(gaz, gel)
        p.setPen(QPen(QColor(230, 226, 245), 1.4))
        p.drawLine(g + QPointF(-6, 0), g + QPointF(6, 0))
        p.drawLine(g + QPointF(0, -6), g + QPointF(0, 6))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(scol)
        p.drawEllipse(sp(az, el), 4.5, 4.5)
        p.setPen(QColor(200, 196, 220))
        p.setFont(font(7.4, 700))
        p.drawText(box.adjusted(10, 5, 0, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                   "SKY PLOT  · + gimbal  · ● target")
