"""System & inputs page: input sources, live pipeline, design rationale and tuning."""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (QDoubleSpinBox, QFrame, QGridLayout, QHBoxLayout, QPushButton, QScrollArea, QSpinBox,
                               QVBoxLayout, QWidget)

from .theme import P, c, font, mono
from .widgets import Card, Pill, label


class SourceCard(QFrame):
    def __init__(self, title: str, text: str, status: str, tone: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("softCard")
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 14, 16, 14)
        v.setSpacing(6)
        top = QHBoxLayout()
        top.addWidget(label(title, "h2"))
        top.addStretch(1)
        top.addWidget(Pill(status, tone, size=7.8))
        v.addLayout(top)
        v.addWidget(label(text, "caption", wrap=True))
        v.addStretch(1)


class PipelineDiagram(QWidget):
    STAGES = [("Frame source", "sim · video · camera", "sky"), ("Detector", "top-hat · CFAR", "accent"),
              ("LOS Kalman", "gating · coast", "mint"), ("Acquisition FSM", "cue spiral · MHT", "rose"),
              ("Controller", "FF + PI · 60 Hz", "butter"), ("Gimbal", "rate command", "peach")]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(170)
        self.values = ["", "", "", "", "", ""]
        self.rates = (0.0, 0.0, 0.0)

    def set_live(self, stage_ms, rates) -> None:
        r, d, t = stage_ms
        self.values = [f"{r:.1f} ms", f"{d:.2f} ms", f"{t:.2f} ms", "", f"{rates['control'] or 0:.0f} Hz", ""]
        self.rates = (rates["vision"] or 0, rates["control"] or 0, rates["render"] or 0)
        self.update()

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        n = len(self.STAGES)
        gap = 18
        w = (self.width() - gap * (n - 1)) / n
        h = 70
        y = 10
        for i, (name, sub, col) in enumerate(self.STAGES):
            x = i * (w + gap)
            r = QRectF(x, y, w, h)
            p.setPen(QPen(c(col), 1.4))
            p.setBrush(c(col + "_soft") if (col + "_soft") in P else c("surface_alt"))
            p.drawRoundedRect(r, 12, 12)
            p.setPen(c("text"))
            p.setFont(font(9.2, 700))
            p.drawText(r.adjusted(0, 8, 0, 0), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, name)
            p.setPen(c("muted"))
            p.setFont(font(7.8, 500))
            p.drawText(r.adjusted(0, 0, 0, -22), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom, sub)
            p.setPen(c(col))
            p.setFont(mono(8.4, 700))
            p.drawText(r.adjusted(0, 0, 0, -6), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
                       self.values[i])
            if i < n - 1:
                ax = x + w + 3
                p.setPen(QPen(c("border_strong"), 1.6))
                p.drawLine(QPointF(ax, y + h / 2), QPointF(ax + gap - 6, y + h / 2))
                p.drawLine(QPointF(ax + gap - 6, y + h / 2), QPointF(ax + gap - 11, y + h / 2 - 4))
                p.drawLine(QPointF(ax + gap - 6, y + h / 2), QPointF(ax + gap - 11, y + h / 2 + 4))
        # thread lanes
        lanes = [("Vision thread", self.rates[0], "≥ 20 FPS", 0, 3, "accent"),
                 ("Control thread", self.rates[1], "≥ 20 Hz", 3, 6, "mint"),
                 ("GUI render (60 Hz timer)", self.rates[2], "≥ 30 Hz", 0, 6, "sky")]
        for k, (name, rate, target, a, b, col) in enumerate(lanes):
            ly = y + h + 14 + k * 26
            x0 = a * (w + gap)
            x1 = b * (w + gap) - gap
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c(col, 40))
            p.drawRoundedRect(QRectF(x0, ly, x1 - x0, 20), 10, 10)
            p.setPen(c("text"))
            p.setFont(font(8.4, 600))
            p.drawText(QRectF(x0 + 12, ly, x1 - x0, 20), Qt.AlignmentFlag.AlignVCenter,
                       f"{name}  ·  {rate:.1f} Hz  (target {target})")


RATIONALE = [
    ("Detector", "White top-hat + Gaussian matched filter + MAD-based CFAR threshold, connected components with "
                 "moment elongation and ring-contrast tests.",
     "Removes sky gradients, glare and fog veil without tuning; the threshold follows the real noise floor of any "
     "camera; rain streaks and edges are rejected by shape. Runs in ~1 ms so there is no need for deep learning "
     "to hit 20 FPS, and it needs no training data for new hardware."),
    ("Tracker", "Constant-velocity Kalman filter in line-of-sight angles (az/el), timestamp driven, adaptive "
                "measurement noise, manoeuvre-adaptive process noise.",
     "Tracking in LOS angles (encoder + pixel offset) makes the estimate independent of the camera's own motion — "
     "the same filter works on a real gimbal, on recorded video and in simulation. Prediction bridges occlusions "
     "(target loss) and feeds the controller ahead of latency."),
    ("Acquisition", "External cue (GPS/telemetry bearing) → Archimedean spiral over the cue uncertainty → "
                    "multi-hypothesis confirmation scored on cue distance, rate consistency, brightness stability.",
     "This is the standard FSOC PAT procedure. Scoring hypotheses instead of taking the brightest blob is what "
     "rejects decoy lights and sun glints; confirmation over N frames prevents false locks."),
    ("Controller", "Velocity feed-forward from the Kalman rate + PI feedback, rate and acceleration limited, "
                   "60 Hz on its own thread.",
     "Feed-forward removes the steady lag a pure proportional loop has against a moving target; slew limiting "
     "protects real mechanics and makes motion visibly smooth. Rate commands are native to pan/tilt drives."),
    ("Architecture", "Vision (30 Hz), control (60 Hz) and GUI (60 Hz) are decoupled; the GUI reads immutable "
                     "snapshots. FrameSource / GimbalInterface abstract the hardware.",
     "Render and control rates never limit each other. Swapping the simulator for a video file or a camera + "
     "gimbal is a new FrameSource / GimbalInterface implementation — the tracking core is untouched."),
]


class SystemPage(QScrollArea):
    def __init__(self, engine, parent=None) -> None:
        super().__init__(parent)
        self.engine = engine
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        col = QVBoxLayout(inner)
        col.setContentsMargins(0, 0, 8, 8)
        col.setSpacing(16)

        src = Card("Input source", "The tracking core is identical for every source")
        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(SourceCard("Simulation", "Physically-motivated NIR sensor model: 8 beacon patterns, 8 hazards, "
                                               "encoder-accurate simulated gimbal. Ground truth is used only for "
                                               "scoring.", "ACTIVE", "mint"))
        row.addWidget(SourceCard("Video file", "VideoFileSource reads MP4/AVI with container timestamps; a static "
                                               "mount (or a gimbal log) provides the pointing. Plugs into the same "
                                               "pipeline.", "INTERFACE READY", "sky"))
        row.addWidget(SourceCard("Camera + gimbal", "LiveCameraSource timestamps frames on arrival and pairs them "
                                                    "with GimbalInterface encoder reads; SerialPanTiltGimbal driver "
                                                    "is the hardware-stage deliverable.", "INTERFACE READY", "sky"))
        src.body.addLayout(row)
        col.addWidget(src)

        pc = Card("Processing pipeline", "Live per-stage latency and loop rates")
        self.diagram = PipelineDiagram()
        pc.body.addWidget(self.diagram)
        col.addWidget(pc)

        rc = Card("Why these algorithms", "Design choices and the reason for each")
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(14)
        for i, (name, what, why) in enumerate(RATIONALE):
            nm = label(name, "h2")
            nm.setAlignment(Qt.AlignmentFlag.AlignTop)
            nm.setFixedWidth(110)
            grid.addWidget(nm, i, 0)
            box = QVBoxLayout()
            box.setSpacing(3)
            w1 = label(what, None, wrap=True)
            w1.setStyleSheet(f"color: {P['text']}; font-weight: 600;")
            box.addWidget(w1)
            box.addWidget(label(why, "caption", wrap=True))
            grid.addLayout(box, i, 1)
        grid.setColumnStretch(1, 1)
        rc.body.addLayout(grid)
        col.addWidget(rc)

        tc = Card("Tuning", "Changes apply live")
        tg = QGridLayout()
        tg.setHorizontalSpacing(14)
        tg.setVerticalSpacing(10)
        self.seed = QSpinBox()
        self.seed.setRange(0, 999999)
        self.seed.setValue(engine.seed)
        new_run = QPushButton("New run with seed")
        new_run.clicked.connect(lambda: engine.new_run(self.seed.value()))
        tg.addWidget(label("Random seed", "caption"), 0, 0)
        tg.addWidget(self.seed, 0, 1)
        tg.addWidget(new_run, 0, 2)

        def spin(lo, hi, val, step, suffix, fn, dec=1):
            s = QDoubleSpinBox()
            s.setRange(lo, hi)
            s.setDecimals(dec)
            s.setSingleStep(step)
            s.setValue(val)
            s.setSuffix(suffix)
            s.valueChanged.connect(fn)
            return s
        cfg = engine.pipeline.cfg
        items = [
            ("Gimbal max slew", spin(5, 90, 40, 5, " °/s", engine.set_max_slew, 0)),
            ("Coast window", spin(0.2, 3.0, cfg.coast_window_s, 0.1, " s", lambda v: setattr(cfg, "coast_window_s", v))),
            ("Detector threshold", spin(4, 15, engine.pipeline.detector.k_sigma, 0.5, " σ",
                                        lambda v: setattr(engine.pipeline.detector, "k_sigma", v))),
            ("Search scan speed", spin(4, 30, cfg.search_speed_deg, 1, " °/s",
                                       lambda v: setattr(cfg, "search_speed_deg", v), 0)),
            ("Lock confirmation", spin(2, 10, cfg.confirm_hits_search, 1, " frames",
                                       lambda v: setattr(cfg, "confirm_hits_search", int(v)), 0)),
        ]
        for i, (name, w) in enumerate(items):
            r, cc = 1 + i // 2, (i % 2) * 3
            tg.addWidget(label(name, "caption"), r, cc)
            tg.addWidget(w, r, cc + 1)
        tg.setColumnStretch(2, 1)
        tg.setColumnStretch(5, 1)
        tc.body.addLayout(tg)
        col.addWidget(tc)
        col.addStretch(1)
        self.setWidget(inner)

    def refresh(self, snap) -> None:
        if snap is not None:
            self.diagram.set_live(snap.stage_ms, self.engine.rates())
