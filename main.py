"""FSOC Beacon Tracker — entry point (also the PyInstaller target)."""

import os
import sys
import traceback
from datetime import datetime


def _crash_log(text: str) -> str:
    base = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.getcwd()
    path = os.path.join(base, "fsoc_crash.log")
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"\n==== {datetime.now():%Y-%m-%d %H:%M:%S} ====\n{text}\n")
    except OSError:
        pass
    return path


def main() -> int:
    from PySide6.QtWidgets import QApplication, QMessageBox

    app = QApplication(sys.argv)
    app.setApplicationName("FSOC Beacon Tracker")
    app.setOrganizationName("SIH26169")
    app.setStyle("Fusion")

    from ui import theme
    theme.install(app)

    def excepthook(etype, value, tb):
        text = "".join(traceback.format_exception(etype, value, tb))
        path = _crash_log(text)
        QMessageBox.critical(None, "FSOC Beacon Tracker", f"Unexpected error — details saved to\n{path}\n\n{value}")

    sys.excepthook = excepthook

    from ui.main_window import MainWindow
    win = MainWindow()
    win.showMaximized()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
