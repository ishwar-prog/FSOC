"""Frame sources. The simulator implements the same interface in fsoc.sim.renderer."""

import threading
import time
from abc import ABC, abstractmethod
from typing import Optional, Tuple

import numpy as np

import math

import cv2

from ..core.geometry import CameraIntrinsics
from .frame import Frame
from .gimbal import GimbalInterface, StaticMount


class FrameSource(ABC):
    intrinsics: CameraIntrinsics

    @abstractmethod
    def read(self) -> Optional[Frame]: ...

    def close(self) -> None:
        pass


class VideoFileSource(FrameSource):
    """Recorded benchmark video (MP4/AVI). Timestamps come from the container, the mount
    is static unless a gimbal log is supplied, so the same LOS tracker applies."""

    def __init__(self, path: str, hfov_deg: float = 4.0, mount: GimbalInterface = None) -> None:
        self.cap = cv2.VideoCapture(path)
        if not self.cap.isOpened():
            raise IOError(f"Cannot open video: {path}")
        w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 30.0
        self.intrinsics = CameraIntrinsics.from_fov(w, h, hfov_deg, hfov_deg * h / w)
        self.mount = mount or StaticMount()
        self._n = 0

    def read(self) -> Optional[Frame]:
        ok, img = self.cap.read()
        if not ok:
            return None
        t = self.cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0 or self._n / self.fps
        g = self.mount.read_state(t)
        self._n += 1
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        return Frame(gray, t, self._n, g.az, g.el)

    def close(self) -> None:
        self.cap.release()


class LiveCameraSource(FrameSource):
    """USB webcam, captured on its own thread.

    A blocking `cap.read()` in the tracking loop returns whatever frame is queued, not the one
    just exposed — up to a frame of extra lag, which a closed pointing loop turns straight into
    overshoot. Here a grabber thread keeps only the newest frame and the time it arrived, and the
    tracker takes that. Frames are converted to grey and scaled to `process_width` (a 720p
    webcam at 640 px still resolves ~0.1 deg per pixel — finer than a hobby servo can step —
    and detection runs ~4x faster).
    """

    def __init__(self, index: int = 0, gimbal: GimbalInterface = None, hfov_deg: float = 60.0,
                 width: int = 1280, height: int = 720, fps: int = 30, process_width: int = 640,
                 exposure: Optional[float] = None) -> None:
        self.cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
        if not self.cap.isOpened():
            self.cap = cv2.VideoCapture(index)
        if not self.cap.isOpened():
            raise IOError(f"Cannot open camera {index}")
        self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))   # 720p30 over USB 2.0
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self.cap.set(cv2.CAP_PROP_FPS, fps)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if exposure is not None:
            self.cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)
            self.cap.set(cv2.CAP_PROP_EXPOSURE, exposure)
        ok, img = self.cap.read()
        if not ok or img is None:
            self.cap.release()
            raise IOError(f"Camera {index} opened but delivers no frames")
        h, w = img.shape[:2]
        self.size = (min(process_width, w), int(round(h * min(process_width, w) / w)))
        pw, ph = self.size
        vfov = 2.0 * math.degrees(math.atan(math.tan(math.radians(hfov_deg) / 2.0) * ph / pw))
        self.intrinsics = CameraIntrinsics.from_fov(pw, ph, hfov_deg, vfov)
        self.gimbal = gimbal
        self._lock = threading.Lock()
        self._latest: Optional[Tuple[np.ndarray, float, int]] = None
        self._n = 0
        self._taken = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._grab, name="camera", daemon=True)
        self._thread.start()

    def _grab(self) -> None:
        while not self._stop.is_set():
            ok, img = self.cap.read()
            t = time.perf_counter()
            if not ok or img is None:
                time.sleep(0.01)
                continue
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            if gray.shape[1] != self.size[0]:
                gray = cv2.resize(gray, self.size, interpolation=cv2.INTER_AREA)
            with self._lock:
                self._n += 1
                self._latest = (gray, t, self._n)

    def latest(self, now: Optional[float] = None) -> Optional[Tuple[np.ndarray, float, int]]:
        """Newest frame not handed out before: (grey image, age in seconds, frame number)."""
        with self._lock:
            if self._latest is None or self._latest[2] == self._taken:
                return None
            img, t, n = self._latest
            self._taken = n
        return img, time.perf_counter() - t, n

    def read(self) -> Optional[Frame]:
        got = self.latest()
        if got is None:
            return None
        img, age, n = got
        t = time.perf_counter() - age
        g = self.gimbal.read_state(t) if self.gimbal is not None else None
        return Frame(img, t, n, g.az if g else 0.0, g.el if g else 0.0)

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=1.0)
        self.cap.release()
