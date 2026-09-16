"""Analytics page: rich live charts, session statistics, export and the validation suite."""

import os
import threading
import time

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (QComboBox, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QProgressBar, QPushButton,
                               QScrollArea, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from fsoc.runtime.evaluator import KPI_ORDER
from fsoc.runtime.validation import default_cases, run_suite
from .camera_view import CameraView
from .charts import Bullseye, ErrorTimeline, LatencyBars, LineChart
from .theme import P
from .info_text import tip
from .widgets import Card, Pill, label


class _Bridge(QObject):
    progress = Signal(int, int, object)
    done = Signal(bool)
    case_started = Signal(int, int, str)
    frame = Signal(object)


class StatTile(QFrame):
    def __init__(self, name: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("softCard")
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 10, 14, 10)
        v.setSpacing(2)
        v.addWidget(label(name, "caption"))
        self.value = label("—", "h1")
        self.value.setStyleSheet("font-size: 14pt;")
        v.addWidget(self.value)

    def set(self, text: str) -> None:
        if self.value.text() != text:
            self.value.setText(text)


class AnalyticsPage(QScrollArea):
    def __init__(self, engine, history, parent=None) -> None:
        super().__init__(parent)
        self.engine = engine
        self.history = history
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        col = QVBoxLayout(inner)
        col.setContentsMargins(0, 0, 8, 8)
        col.setSpacing(16)

        # ---- stat tiles
        tiles = QGridLayout()
        tiles.setHorizontalSpacing(12)
        tiles.setVerticalSpacing(12)
        self.tiles = {}
        for i, (key, name) in enumerate((("elapsed", "Session time"), ("err", "Mean centroid error"),
                                         ("rmse", "RMSE / max error"), ("point", "Mean pointing error"),
                                         ("loss", "Loss events"), ("reacq", "Worst re-acquisition"),
                                         ("cap", "Pipeline capacity"))):
            t = StatTile(name)
            tiles.addWidget(t, 0, i)
            tiles.setColumnStretch(i, 1)
            self.tiles[key] = t
        col.addLayout(tiles)

        # ---- charts grid
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(16)
        c1 = Card("Tracking error over time", "Centroid error (lavender) vs 10 px target · pointing error (blue) · "
                                              "state band below", info=tip("timeline"))
        self.timeline = ErrorTimeline(30.0)
        self.timeline.setMinimumHeight(250)
        c1.body.addWidget(self.timeline)
        grid.addWidget(c1, 0, 0, 1, 2)

        c2 = Card("Centroid scatter", "Detected − true centre, last 10 s · rings at 1, 5, 10 px", info=tip("scatter"))
        self.bull = Bullseye()
        self.bull.setMinimumHeight(260)
        c2.body.addWidget(self.bull)
        grid.addWidget(c2, 0, 2)

        c3 = Card("Signal quality", "Beacon SNR, track confidence and how sure the tracker is it holds the beacon",
                  info=tip("signal"))
        self.signal = LineChart([("snr", "SNR (dB)", "accent", 2.0), ("conf", "Confidence (%)", "mint", 1.4),
                                 ("idp", "Beacon identity (%)", "butter", 1.4)],
                                "", y_range=(0, 60))
        self.signal.setMinimumHeight(210)
        c3.body.addWidget(self.signal)
        grid.addWidget(c3, 1, 0)

        c4 = Card("Loop rates", "Vision pipeline FPS, control loop Hz and GUI render Hz vs 20 / 30 thresholds",
                  info=tip("rates"))
        self.rates = LineChart([("vision", "Vision FPS", "accent", 2.0), ("control", "Control Hz", "mint", 1.6),
                                ("render", "Render Hz", "sky", 1.6)], "",
                               thresholds=((20, "peach"), (30, "butter")), y_range=(0, 70))
        self.rates.setMinimumHeight(210)
        c4.body.addWidget(self.rates)
        grid.addWidget(c4, 1, 1)

        c5 = Card("Processing budget", "Per-frame latency of each pipeline stage", info=tip("budget"))
        self.latency = LatencyBars()
        c5.body.addWidget(self.latency)
        exp = QHBoxLayout()
        self.export_btn = QPushButton("Export session log")
        self.export_btn.setObjectName("primary")
        self.export_btn.clicked.connect(self._export)
        self.open_btn = QPushButton("Open logs folder")
        self.open_btn.clicked.connect(self._open_logs)
        exp.addWidget(self.export_btn)
        exp.addWidget(self.open_btn)
        exp.addStretch(1)
        c5.body.addLayout(exp)
        self.export_msg = label("CSV (per frame) + JSON summary are written next to the application.", "faint",
                                wrap=True)
        c5.body.addWidget(self.export_msg)
        grid.addWidget(c5, 1, 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)
        col.addLayout(grid)

        # ---- validation suite
        vc = Card("Validation suite", "Deterministic cold-start runs of every terminal type, pattern and hazard, "
                                      "each with an injected 2.4 s blockage · scored against all SIH targets",
                  info=tip("suite"))
        self.suite_pill = Pill("not run", "faint")
        vc.header.addWidget(self.suite_pill, 0, Qt.AlignmentFlag.AlignTop)
        ctl = QHBoxLayout()
        self.duration = QComboBox()
        self.duration.addItem("Quick · 20 s per case", 20.0)
        self.duration.addItem("Standard · 40 s per case", 40.0)
        self.run_btn = QPushButton("Run validation suite")
        self.run_btn.setObjectName("primary")
        self.run_btn.clicked.connect(self._run_suite)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setObjectName("ghost")
        self.stop_btn.setEnabled(False)
        self.stop_btn.setToolTip("Abort the running suite immediately — right in the middle of a case if need be.")
        self.stop_btn.clicked.connect(self._stop_suite)
        self.progress = QProgressBar()
        self.progress.setFixedHeight(8)
        self.progress.setTextVisible(False)
        ctl.addWidget(self.duration)
        ctl.addWidget(self.run_btn)
        ctl.addWidget(self.stop_btn)
        ctl.addWidget(self.progress, 1)
        vc.body.addLayout(ctl)
        vc.body.addWidget(label("The live simulation pauses while the suite runs so each case gets the CPU.",
                                "faint"))

        # ---- live preview: watch the suite actually run, case by case
        prev_row = QHBoxLayout()
        prev_row.setSpacing(12)
        pcol = QVBoxLayout()
        self.suite_case_lbl = label("Not running", "h2")
        pcol.addWidget(self.suite_case_lbl)
        self.suite_state_lbl = label("Press “Run validation suite” to watch it work through every case live.",
                                     "faint", wrap=True)
        pcol.addWidget(self.suite_state_lbl)
        pcol.addStretch(1)
        prev_row.addLayout(pcol, 1)
        self.suite_preview = CameraView(self.engine.K)
        self.suite_preview.setFixedHeight(190)
        self.suite_preview.setMinimumWidth(260)
        for k in ("truth", "detections", "identity", "search", "zoom"):
            self.suite_preview.set_layer(k, True)
        prev_row.addWidget(self.suite_preview, 1)
        vc.body.addLayout(prev_row)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(["Case", "Group", "Acquisition", "Error", "Loss", "Re-acq",
                                              "Capacity", "Result"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i in range(1, 8):
            hh.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setMinimumHeight(320)
        vc.body.addWidget(self.table)
        col.addWidget(vc)
        col.addStretch(1)
        self.setWidget(inner)

        self._bridge = _Bridge()
        self._bridge.progress.connect(self._on_progress)
        self._bridge.done.connect(self._on_done)
        self._bridge.case_started.connect(self._on_case_started)
        self._bridge.frame.connect(self._on_suite_frame)
        self._suite_thread = None
        self._stop_event = None
        self._was_paused = False
        self._passed = 0

    # ----------------------------------------------------------------- refresh
    def refresh(self, snap) -> None:
        h = self.history
        self.timeline.refresh(h)
        self.bull.refresh(h)
        self.signal.refresh(h)
        self.rates.refresh(h)
        self.latency.refresh(h)
        if snap is None:
            return
        sm = self.engine.evaluator.summary()
        self.tiles["elapsed"].set(f"{sm['elapsed_s']:.0f} s")
        e = sm["tracking_error_mean_px"]
        self.tiles["err"].set("—" if e is None else f"{e:.2f} px")
        r = sm["tracking_error_rmse_px"]
        self.tiles["rmse"].set("—" if r is None else f"{r:.2f} / {sm['tracking_error_max_px']:.1f}")
        pe = sm["pointing_error_mean_px"]
        self.tiles["point"].set("—" if pe is None else f"{pe:.1f} px")
        self.tiles["loss"].set(str(snap.out.loss_events))
        w = sm["reacquisition_worst_s"]
        self.tiles["reacq"].set("—" if w is None else f"{w:.2f} s")
        cap = sm["processing_capacity_fps"]
        self.tiles["cap"].set("—" if cap is None else f"{cap:.0f} FPS")

    # ------------------------------------------------------------------ export
    def _export(self) -> None:
        summary = {"summary": self.engine.evaluator.summary(),
                   "pattern": self.engine.world.patterns.key,
                   "hazards": {k: round(v, 2) for k, v in self.engine.world.hazards.levels().items()},
                   "time_of_day": self.engine.world.time_of_day, "seed": self.engine.seed}
        paths = self.engine.recorder.export(f"session_{self.engine.world.patterns.key}", summary)
        self._last_dir = os.path.dirname(paths["csv"])
        self.export_msg.setText(f"Saved {os.path.basename(paths['csv'])} and summary JSON to {self._last_dir}")

    def _open_logs(self) -> None:
        from fsoc.runtime.recorder import default_log_dir
        QDesktopServices.openUrl(QUrl.fromLocalFile(getattr(self, "_last_dir", default_log_dir())))

    # ------------------------------------------------------------------- suite
    def _run_suite(self) -> None:
        if self._suite_thread and self._suite_thread.is_alive():
            return
        cases = default_cases()
        dur = float(self.duration.currentData())
        self.table.setRowCount(0)
        self.progress.setRange(0, len(cases))
        self.progress.setValue(0)
        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self._passed = 0
        self.suite_pill.set_tone("sky", f"running 0 / {len(cases)}")
        self.suite_state_lbl.setText("Starting…")
        self._was_paused = self.engine.paused
        self.engine.set_paused(True)
        stop_event = threading.Event()
        self._stop_event = stop_event
        last_emit = [0.0]

        def on_frame(snap):
            now = time.perf_counter()
            if now - last_emit[0] < 0.1:            # ~10 Hz is plenty for a human to watch
                return
            last_emit[0] = now
            self._bridge.frame.emit(snap)

        def progress(i, n, res):
            self._bridge.progress.emit(i, n, res)
            if i < n and not stop_event.is_set():
                self._bridge.case_started.emit(i, n, cases[i].name)

        self._bridge.case_started.emit(0, len(cases), cases[0].name)

        def work():
            try:
                run_suite(cases, dur, progress=progress, should_stop=stop_event.is_set, on_frame=on_frame)
            except Exception:
                pass  # keep the GUI alive whatever happens; the table shows what completed
            self._bridge.done.emit(stop_event.is_set())

        self._suite_thread = threading.Thread(target=work, daemon=True, name="validation")
        self._suite_thread.start()

    def _stop_suite(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()
            self.stop_btn.setEnabled(False)
            self.suite_state_lbl.setText("Stopping…")

    def _on_case_started(self, i: int, n: int, name: str) -> None:
        self.suite_case_lbl.setText(f"Case {i + 1} / {n} — {name}")
        self.suite_state_lbl.setText("Running…")

    def _on_suite_frame(self, snap) -> None:
        self.suite_preview.set_snapshot(snap)
        o = snap.out
        self.suite_state_lbl.setText(f"t = {snap.t:5.1f} s · {o.state}")

    def _on_progress(self, i: int, n: int, res: dict) -> None:
        self.progress.setValue(i)
        case = res["case"]
        row = self.table.rowCount()
        self.table.insertRow(row)
        stopped = res.get("summary", {}).get("stopped") if "summary" in res else None
        if "error" in res:
            vals = [case.name, case.group, "—", "—", "—", "—", "—", "ERROR"]
        elif stopped:
            vals = [case.name, case.group, "—", "—", "—", "—", "—", "STOPPED"]
        else:
            s = res["summary"]

            def f(v, fmt):
                return "—" if v is None else fmt.format(v)
            vals = [case.name, case.group, f(s["acquisition_time_s"], "{:.2f} s"),
                    f(s["tracking_error_mean_px"], "{:.2f} px"), f(s["target_loss_pct"], "{:.2f} %"),
                    f(s["reacquisition_worst_s"], "{:.2f} s"), f(s["processing_capacity_fps"], "{:.0f} FPS"),
                    "PASS" if res["passed"] else "FAIL"]
        self._passed += bool(res.get("passed"))
        for col, v in enumerate(vals):
            it = QTableWidgetItem(v)
            if col == 7:
                tone = P["mint"] if v == "PASS" else (P["muted"] if v == "STOPPED" else P["peach"])
                it.setForeground(QColor(tone))
                it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            elif col >= 2:
                it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row, col, it)
        self.suite_pill.set_tone("sky", f"running {i} / {n}")

    def _on_done(self, was_stopped: bool) -> None:
        n = self.table.rowCount()
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self._stop_event = None
        if was_stopped:
            self.suite_pill.set_tone("peach", f"stopped · {self._passed} / {n} cases pass")
            self.suite_state_lbl.setText("Stopped by user.")
        else:
            self.suite_pill.set_tone("mint" if self._passed == n else "peach", f"{self._passed} / {n} cases pass")
            self.suite_state_lbl.setText("Finished.")
        self.suite_case_lbl.setText("Not running")
        if not self._was_paused:
            self.engine.set_paused(False)
