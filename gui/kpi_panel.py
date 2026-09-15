"""Right rail: the six SIH reference numbers, the learned beacon identity, and one-click tests."""

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QPushButton, QScrollArea, QVBoxLayout, QWidget

from fsoc.runtime.evaluator import KPI_META, KPI_ORDER
from fsoc.runtime.recorder import default_log_dir
from .info_text import tip
from .widgets import Card, Gauge, KpiCard, Pill, SourceBars, StatRow, label


class KpiPanel(QScrollArea):
    restart_clicked = Signal()
    block_clicked = Signal()

    def __init__(self, engine, parent=None) -> None:
        super().__init__(parent)
        self.engine = engine
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        col = QVBoxLayout(inner)
        col.setContentsMargins(6, 0, 0, 0)
        col.setSpacing(12)

        card = Card("Mission targets", "SIH26169 reference numbers · scored live", info=tip("targets"))
        self.summary = Pill("0 / 6", "faint")
        card.header.addWidget(self.summary, 0, Qt.AlignmentFlag.AlignTop)
        card.body.setSpacing(8)
        self.cards = {}
        for key in KPI_ORDER:
            name, target, meaning = KPI_META[key]
            kc = KpiCard(name, target, meaning, info=tip(key))
            card.body.addWidget(kc)
            self.cards[key] = kc
        col.addWidget(card)

        ic = Card("Beacon identity", "Recognised by its blink signature, not brightness", info=tip("identity"))
        self.id_pill = Pill("PRIOR", "faint", size=7.8)
        ic.header.addWidget(self.id_pill, 0, Qt.AlignmentFlag.AlignTop)
        ic.body.setSpacing(4)
        self.id_rate = StatRow("Learned blink rate")
        self.id_duty = StatRow("On-time / depth")
        self.id_lock = StatRow("Locked light is beacon")
        for w in (self.id_rate, self.id_duty, self.id_lock):
            ic.body.addWidget(w)
        self.id_gauge = Gauge(span=1.0, marker=False)
        ic.body.addWidget(self.id_gauge)
        ic.body.addSpacing(4)
        ic.body.addWidget(label("Lights in view — chance each is the beacon", "caption"))
        self.bars = SourceBars()
        ic.body.addWidget(self.bars)
        brow = QHBoxLayout()
        relearn = QPushButton("Relearn")
        relearn.setToolTip("Forget the learned signature and learn it again from scratch.")
        relearn.clicked.connect(self.engine.reset_identity)
        save = QPushButton("Save signature")
        save.setToolTip("Save the learned signature so a video or hardware session can start with it.")
        save.clicked.connect(self._save)
        brow.addWidget(relearn)
        brow.addWidget(save)
        ic.body.addLayout(brow)
        self.id_msg = label("", "faint", wrap=True)
        ic.body.addWidget(self.id_msg)
        col.addWidget(ic)

        tests = Card("Test the targets", "Trigger the events the numbers measure", info=tip("tests"))
        row = QHBoxLayout()
        row.setSpacing(8)
        b1 = QPushButton("Cold restart")
        b1.setToolTip("Drop the lock and start searching again: measures acquisition time.")
        b1.clicked.connect(self.restart_clicked)
        b2 = QPushButton("Block beacon 2.5 s")
        b2.setToolTip("Hide the beacon for longer than the tracker can predict: measures re-acquisition.")
        b2.clicked.connect(self.block_clicked)
        for b in (b1, b2):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            row.addWidget(b)
        tests.body.addLayout(row)
        col.addWidget(tests)
        col.addStretch(1)
        self.setWidget(inner)

    def _save(self) -> None:
        path = os.path.join(default_log_dir(), "beacon_signature.json")
        self.engine.pipeline.identifier.save_signature(path)
        self.id_msg.setText(f"Saved to {path}")

    def update_metrics(self, metrics: dict) -> None:
        passing = failing = 0
        for key, card in self.cards.items():
            k = metrics.get(key)
            if not k:
                continue
            card.update_kpi(k)
            passing += k["status"] == "pass"
            failing += k["status"] == "fail"
        tone = "peach" if failing else ("mint" if passing == 6 else "sky")
        self.summary.set_tone(tone, f"{passing} / 6 passing")

    def update_identity(self, snap) -> None:
        o = snap.out
        sig = o.signature or {}
        if sig.get("learned"):
            self.id_pill.set_tone("mint", "LEARNED")
            self.id_rate.set(f"{sig['freq_hz']:.2f} ± {max(0.05, sig['freq_sd']):.2f} Hz")
            self.id_duty.set(f"{sig['duty'] * 100:.0f} % / {sig['depth'] * 100:.0f} %")
        elif sig.get("observed_s", 0) > 0:
            self.id_pill.set_tone("sky", f"LEARNING {min(99, sig['observed_s'] / 2.0 * 100):.0f}%")
            self.id_rate.set(f"~{sig['freq_hz']:.1f} Hz")
            self.id_duty.set("…")
        else:
            self.id_pill.set_tone("faint", "PRIOR")
            self.id_rate.set("not yet learned")
            self.id_duty.set("—")
        if o.state in ("LOCKED", "COASTING") and o.lock_p > 0:
            self.id_lock.set(f"{o.lock_p * 100:.0f} %")
            self.id_gauge.set_value(o.lock_p, "mint" if o.lock_p >= 0.6 else "butter")
        else:
            self.id_lock.set("—")
            self.id_gauge.set_value(0.0, "faint")
        self.bars.set_sources(o.sources)
