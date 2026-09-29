"""Record the README demo clip: a LEO pass through a busy star field, cold start, beacon blocked, re-acquired.

    python tools/record_demo.py [out.mp4]

Opens the app, scripts the scenario through the engine (no clicks) and records the window's own
pixels with QWidget.grab(), so nothing else on the screen can end up in the clip. Frames are piped
to ffmpeg (must be on PATH).
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

DURATION_S = 75
COLD_AT_S = 3        # cold restart: measures acquisition
BLOCK_AT_S = 20      # 2.5 s blockage: measures re-acquisition
FPS = 30
SIZE = (1920, 1080)


def main() -> int:
    out = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "demo_raw.mp4")
    app = QApplication(sys.argv)
    app.setApplicationName("COSTA")
    app.setStyle("Fusion")
    from ui import theme
    theme.install(app)
    from ui.main_window import MainWindow

    win = MainWindow()
    eng = win.engine
    eng.set_pattern("leo_pass")
    eng.set_hazard("decoys", True, 0.8)
    eng.set_hazard("turbulence", True, 0.3)
    win.resize(*SIZE)
    win.show()

    ffmpeg = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgra",
         "-s", f"{SIZE[0]}x{SIZE[1]}", "-r", str(FPS), "-i", "-",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", out],
        stdin=subprocess.PIPE)
    state = {"n": 0}
    timer = QTimer()

    def grab():
        img = win.grab().toImage().convertToFormat(QImage.Format_ARGB32)
        if (img.width(), img.height()) != SIZE:
            img = img.scaled(*SIZE)
        ffmpeg.stdin.write(bytes(img.constBits()))
        state["n"] += 1
        if state["n"] >= DURATION_S * FPS:
            timer.stop()
            ffmpeg.stdin.close()
            ffmpeg.wait()
            win.close()
            app.quit()

    def start():
        timer.timeout.connect(grab)
        timer.start(1000 // FPS)
        QTimer.singleShot(COLD_AT_S * 1000, eng.cold_restart)
        QTimer.singleShot(BLOCK_AT_S * 1000, lambda: eng.block_beacon(2.5))

    QTimer.singleShot(2500, start)  # let the window settle and the pass start
    app.exec()
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
