"""Frame sources. The simulator implements the same interface in fsoc.sim.renderer."""

import time
from abc import ABC, abstractmethod
from typing import Optional

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
    """USB / DirectShow camera paired with a gimbal. Frames are timestamped on arrival."""

    def __init__(self, index: int, gimbal: GimbalInterface, hfov_deg: float = 4.0,
                 exposure: Optional[float] = None) -> None:
        self.cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
        if not self.cap.isOpened():
            raise IOError(f"Cannot open camera index {index}")
        if exposure is not None:
            self.cap.set(cv2.CAP_PROP_EXPOSURE, exposure)
        w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.intrinsics = CameraIntrinsics.from_fov(w, h, hfov_deg, hfov_deg * h / w)
        self.gimbal = gimbal
        self._n = 0

    def read(self) -> Optional[Frame]:
        ok, img = self.cap.read()
        t = time.perf_counter()
        if not ok:
            return None
        g = self.gimbal.read_state(t)
        self._n += 1
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        return Frame(gray, t, self._n, g.az, g.el)

    def close(self) -> None:
        self.cap.release()
