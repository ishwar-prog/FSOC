"""Right rail: the six SIH reference numbers, live, plus one-click tests."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QPushButton, QScrollArea, QVBoxLayout, QWidget

from fsoc.runtime.evaluator import KPI_META, KPI_ORDER
from .widgets import Card, KpiCard, Pill, label


class KpiPanel(QScrollArea):
    restart_clicked = Signal()
    block_clicked = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        col = QVBoxLayout(inner)
        col.setContentsMargins(6, 0, 0, 0)
        col.setSpacing(14)

        card = Card("Mission targets", "SIH26169 reference numbers · scored live")
        self.summary = Pill("0 / 6", "faint")
        card.header.addWidget(self.summary, 0, Qt.AlignmentFlag.AlignTop)
        card.body.setSpacing(8)
        self.cards = {}
        for key in KPI_ORDER:
            name, target, meaning = KPI_META[key]
            kc = KpiCard(name, target, meaning)
            card.body.addWidget(kc)
            self.cards[key] = kc
        col.addWidget(card)

        tests = Card("Test the targets", "Trigger the events the numbers measure")
        row = QHBoxLayout()
        row.setSpacing(8)
        b1 = QPushButton("Cold restart")
        b1.setToolTip("Park the gimbal and drop the track: measures acquisition time")
        b1.clicked.connect(self.restart_clicked)
        b2 = QPushButton("Block beacon 2.5 s")
        b2.setToolTip("Occlude the beacon longer than the coast window: measures re-acquisition")
        b2.clicked.connect(self.block_clicked)
        for b in (b1, b2):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            row.addWidget(b)
        tests.body.addLayout(row)
        tests.body.addWidget(label("Coasting bridges gaps up to 1.5 s using the Kalman prediction; longer "
                                   "blockages trigger a local re-acquisition scan.", "faint", wrap=True))
        col.addWidget(tests)
        col.addStretch(1)
        self.setWidget(inner)

    def update_metrics(self, metrics: dict) -> None:
        passing = 0
        failing = 0
        for key, card in self.cards.items():
            k = metrics.get(key)
            if not k:
                continue
            card.update_kpi(k)
            passing += k["status"] == "pass"
            failing += k["status"] == "fail"
        tone = "peach" if failing else ("mint" if passing == 6 else "sky")
        self.summary.set_tone(tone, f"{passing} / 6 passing")
