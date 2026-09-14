"""Live charts (pyqtgraph, pastel light theme) fed from a fixed-size frame history."""

import math

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QGraphicsEllipseItem, QVBoxLayout, QWidget

from .theme import P, STATE_COLOR, c, font, mono

pg.setConfigOptions(antialias=True, foreground=P["muted"], background=P["surface"])

STATES = ["SEARCH", "ACQUIRING", "LOCKED", "COASTING", "REACQUIRE"]
STATE_IDX = {s: i for i, s in enumerate(STATES)}


class History:
    N = 1800  # 60 s at 30 FPS

    def __init__(self) -> None:
        self.run_id = None
        self.clear()

    def clear(self) -> None:
        n = self.N
        self.cols = {k: np.full(n, np.nan) for k in
                     ("t", "err", "point", "snr", "conf", "vision", "control", "render",
                      "render_ms", "detect_ms", "track_ms", "dx", "dy", "state")}
        self.i = 0
        self.last_frame = -1

    def add(self, s) -> bool:
        if s.run_id != self.run_id:
            self.run_id = s.run_id
            self.clear()
        if s.out.frame_id == self.last_frame or s.paused:
            return False
        self.last_frame = s.out.frame_id
        k = self.i % self.N
        o = s.out
        C = self.cols
        C["t"][k] = s.t
        C["err"][k] = s.centroid_err if s.centroid_err is not None else np.nan
        C["point"][k] = s.pointing_err if (s.pointing_err is not None and o.state == "LOCKED") else np.nan
        C["snr"][k] = 20 * math.log10(max(o.snr, 1.0)) if o.measurement else np.nan
        C["conf"][k] = o.confidence * 100
        C["vision"][k] = s.rates["vision"] or np.nan
        C["control"][k] = s.rates["control"] or np.nan
        C["render"][k] = s.rates["render"] or np.nan
        C["render_ms"][k], C["detect_ms"][k], C["track_ms"][k] = s.stage_ms
        C["state"][k] = STATE_IDX.get(o.state, 0)
        if o.measurement and s.truth.target_px and o.state == "LOCKED":
            C["dx"][k] = o.measurement[0] - s.truth.target_px[0]
            C["dy"][k] = o.measurement[1] - s.truth.target_px[1]
        else:
            C["dx"][k] = C["dy"][k] = np.nan
        self.i += 1
        return True

    def get(self, key: str, last: int = None) -> np.ndarray:
        a = self.cols[key]
        n = min(self.i, self.N)
        k = self.i % self.N
        out = a[:n] if self.i <= self.N else np.concatenate((a[k:], a[:k]))
        return out[-last:] if last else out


def make_plot(left: str = "", bottom: str = "") -> pg.PlotWidget:
    pw = pg.PlotWidget()
    pw.setBackground(P["surface"])
    pw.setMenuEnabled(False)
    pw.setMouseEnabled(False, False)
    pw.hideButtons()
    pi = pw.getPlotItem()
    pi.showGrid(x=True, y=True, alpha=0.10)
    for ax in ("left", "bottom"):
        a = pi.getAxis(ax)
        a.setPen(pg.mkPen(P["border_strong"]))
        a.setTextPen(pg.mkPen(P["muted"]))
        a.setStyle(tickFont=font(8), tickLength=-4)
    pi.getAxis("left").setWidth(38)
    if left:
        pi.setLabel("left", left, color=P["muted"], size="8pt")
    if bottom:
        pi.setLabel("bottom", bottom, color=P["muted"], size="8pt")
    pw.setMinimumHeight(120)
    return pw


def _smooth(prev, new, k=0.2):
    return new if prev is None else prev + (new - prev) * k


class StateStrip(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(14)
        self.t = np.array([])
        self.s = np.array([])
        self.window = 30.0

    def set_data(self, t, s, window) -> None:
        self.t, self.s, self.window = t, s, window
        self.update()

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width() - 46, self.height()
        x0 = 40
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c("surface_alt"))
        p.drawRoundedRect(QRectF(x0, 2, w, h - 4), 4, 4)
        if len(self.t) < 2:
            return
        t1 = self.t[-1]
        t0 = t1 - self.window
        start = 0
        for i in range(1, len(self.t) + 1):
            if i == len(self.t) or self.s[i] != self.s[start]:
                a, b = max(self.t[start], t0), self.t[i - 1]
                if b > t0:
                    xa = x0 + (a - t0) / self.window * w
                    xb = x0 + (b - t0) / self.window * w + 1
                    p.setBrush(c(STATE_COLOR[STATES[int(self.s[start])]][0], 210))
                    p.drawRect(QRectF(xa, 3, max(1.0, xb - xa), h - 6))
                start = i


class ErrorTimeline(QWidget):
    def __init__(self, window_s: float = 30.0, compact: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.window = window_s
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        self.plot = make_plot("px")
        if compact:
            self.plot.setMinimumHeight(90)
            self.plot.getPlotItem().getAxis("bottom").setStyle(showValues=False)
        band = pg.LinearRegionItem((0, 10), orientation="horizontal", movable=False,
                                   brush=pg.mkBrush(QColor(88, 184, 145, 26)), pen=pg.mkPen(None))
        self.plot.addItem(band)
        thr = pg.InfiniteLine(pos=10, angle=0, pen=pg.mkPen(P["peach"], width=1.3, style=Qt.PenStyle.DashLine))
        self.plot.addItem(thr)
        if not compact:
            txt = pg.TextItem("10 px target", color=P["peach"], anchor=(0, 1))
            txt.setFont(font(8, 600))
            self.plot.addItem(txt)
            self._thr_txt = txt
        else:
            self._thr_txt = None
        self.point = self.plot.plot(pen=pg.mkPen(P["sky"], width=1.2), connect="finite")
        self.err = self.plot.plot(pen=pg.mkPen(P["accent"], width=2.0), connect="finite")
        lay.addWidget(self.plot, 1)
        self.strip = StateStrip()
        lay.addWidget(self.strip)
        self._ymax = None

    def refresh(self, h: History) -> None:
        t = h.get("t")
        if len(t) < 2:
            return
        n = int(self.window * 30) + 5
        t = t[-n:]
        err = h.get("err", n)
        pt = h.get("point", n)
        self.err.setData(t, err)
        self.point.setData(t, pt)
        t1 = t[-1]
        self.plot.setXRange(t1 - self.window, t1, padding=0)
        vals = np.concatenate((err[np.isfinite(err)], pt[np.isfinite(pt)]))
        top = max(14.0, float(np.percentile(vals, 98)) * 1.25) if vals.size else 14.0
        self._ymax = _smooth(self._ymax, min(top, 80.0))
        self.plot.setYRange(0, self._ymax, padding=0)
        if self._thr_txt is not None:
            self._thr_txt.setPos(t1 - self.window + 0.3, 10)
        self.strip.set_data(t, h.get("state", n), self.window)


class Bullseye(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.plot = make_plot("Δy px", "Δx px")
        self.plot.setAspectLocked(True)
        R = 11
        self.plot.setXRange(-R, R, padding=0)
        self.plot.setYRange(-R, R, padding=0)
        for r, key in ((1, "mint"), (5, "sky"), (10, "peach")):
            it = QGraphicsEllipseItem(-r, -r, 2 * r, 2 * r)
            it.setPen(pg.mkPen(P[key], width=1.3, style=Qt.PenStyle.DashLine))
            self.plot.addItem(it)
        self.scatter = pg.ScatterPlotItem(size=6, pen=None)
        self.plot.addItem(self.scatter)
        self.label = pg.TextItem("", color=P["text"], anchor=(0, 0))
        self.label.setFont(mono(8.5, 600))
        self.label.setPos(-R + 0.5, R - 0.5)
        self.plot.addItem(self.label)
        lay.addWidget(self.plot)
        base = QColor(P["accent"])
        self._brushes = [pg.mkBrush(base.red(), base.green(), base.blue(), a) for a in (40, 90, 150, 230)]

    def refresh(self, h: History) -> None:
        dx, dy = h.get("dx", 300), h.get("dy", 300)
        m = np.isfinite(dx)
        dx, dy = dx[m], -dy[m]
        if dx.size == 0:
            self.scatter.setData([], [])
            self.label.setText("no locked detections yet")
            return
        n = dx.size
        idx = np.minimum(3, (np.arange(n) * 4) // max(n, 1))
        self.scatter.setData(dx, dy, brush=[self._brushes[i] for i in idx])
        rr = np.hypot(dx, dy)
        self.label.setText(f"mean {rr.mean():.2f} px   p95 {np.percentile(rr, 95):.2f} px")


class LineChart(QWidget):
    def __init__(self, series, y_label: str, thresholds=(), y_range=None, window_s: float = 30.0,
                 parent=None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.window = window_s
        self.plot = make_plot(y_label)
        self.plot.addLegend(offset=(8, 4), labelTextColor=P["muted"], brush=pg.mkBrush(255, 255, 255, 210))
        for val, key in thresholds:
            self.plot.addItem(pg.InfiniteLine(pos=val, angle=0,
                                              pen=pg.mkPen(P[key], width=1.1, style=Qt.PenStyle.DashLine)))
        self.curves = {}
        for key, name, col, width in series:
            self.curves[key] = self.plot.plot(pen=pg.mkPen(P.get(col, col), width=width), name=name, connect="finite")
        self.y_range = y_range
        lay.addWidget(self.plot)
        self._ymax = None

    def refresh(self, h: History) -> None:
        n = int(self.window * 30) + 5
        t = h.get("t", n)
        if len(t) < 2:
            return
        top = 0.0
        for key, curve in self.curves.items():
            y = h.get(key, n)
            curve.setData(t, y)
            if np.isfinite(y).any():
                top = max(top, float(np.nanmax(y)))
        self.plot.setXRange(t[-1] - self.window, t[-1], padding=0)
        if self.y_range:
            lo, hi = self.y_range
            self._ymax = _smooth(self._ymax, max(hi, top * 1.15))
            self.plot.setYRange(lo, self._ymax, padding=0)


class LatencyBars(QWidget):
    STAGES = (("render_ms", "Capture / render", "sky"), ("detect_ms", "Detect", "accent"), ("track_ms", "Track + FSM", "mint"))

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(96)
        self.vals = (0.0, 0.0, 0.0)

    def refresh(self, h: History) -> None:
        self.vals = tuple(float(np.nanmean(h.get(k, 30))) if h.i else 0.0 for k, _, _ in self.STAGES)
        self.update()

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        total = sum(v for v in self.vals if math.isfinite(v))
        budget = 1000.0 / 20.0
        p.setFont(font(8.6, 600))
        p.setPen(c("muted"))
        cap = 1000.0 / total if total > 0 else 0
        p.drawText(QRectF(0, 0, w, 18), Qt.AlignmentFlag.AlignLeft,
                   f"End-to-end {total:.1f} ms / frame  ·  capacity {cap:.0f} FPS  ·  budget for 20 FPS = 50 ms")
        bar = QRectF(0, 26, w, 18)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c("surface_alt"))
        p.drawRoundedRect(bar, 9, 9)
        x = 0.0
        for (key, name, col), v in zip(self.STAGES, self.vals):
            if not math.isfinite(v) or v <= 0:
                continue
            ww = bar.width() * min(v, budget) / budget
            p.setBrush(c(col))
            p.drawRoundedRect(QRectF(x, bar.top(), max(ww, 3), bar.height()), 6, 6)
            x += ww
        lx = 0
        for (key, name, col), v in zip(self.STAGES, self.vals):
            p.setBrush(c(col))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(lx + 6, 64), 4.5, 4.5)
            p.setPen(c("text"))
            p.setFont(font(8.4, 500))
            txt = f"{name}  {v:.2f} ms" if math.isfinite(v) else name
            p.drawText(QPointF(lx + 16, 68), txt)
            lx += p.fontMetrics().horizontalAdvance(txt) + 34
