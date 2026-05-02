#!/usr/bin/env python3
"""Camera backends for Orbbec Astra Pro Plus on JetAuto.

Tries backends in order:
  1. ROSCamera      — /camera/rgb/image_raw (requires: roslaunch jetauto_peripherals astrapro.launch)
  2. OpenNI2Camera  — subprocess-isolated (segfault-safe)
  3. None           — caller uses grey stub frames

Usage:
    from camera import open_camera
    cap = open_camera(resolution=(160, 120))
    if cap is None:
        frame = grey_stub_frame
    else:
        frame = cap.read()   # BGR numpy (H, W, 3) or None
        cap.release()
"""

import logging
import os
import struct
import subprocess
import sys
import threading
import time
from typing import Optional, Tuple

import numpy as np

logger = logging.getLogger("dataset_recorder")

_WORKER_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "openni2_worker.py")


def open_camera(resolution=(160, 120)):
    # type: (Tuple[int, int]) -> Optional[object]
    """Try camera backends in order; return first that works, or None.

    Priority:
      1. ROS /camera/rgb/image_raw  (requires astrapro.launch)
      2. cv2.VideoCapture           (direct V4L2, /dev/video*)
      3. OpenNI2 subprocess         (libOpenNI2 fallback)
    """
    cap = _try_ros_camera(resolution)
    if cap is not None:
        return cap
    cap = _try_cv2_camera(resolution)
    if cap is not None:
        return cap
    cap = _try_openni2_camera(resolution)
    if cap is not None:
        return cap
    return None


# ── ROS backend ────────────────────────────────────────────────────────────────

def _ros_master_running():
    # type: () -> bool
    try:
        import xmlrpc.client
        master_uri = os.environ.get("ROS_MASTER_URI", "http://localhost:11311")
        proxy = xmlrpc.client.ServerProxy(master_uri)
        proxy.getSystemState("/check")
        return True
    except Exception:
        return False


def _try_ros_camera(resolution):
    # type: (Tuple[int, int]) -> Optional[object]
    if not _ros_master_running():
        logger.debug("ROS master not running — skipping ROS camera")
        return None
    for topic in _ROS_TOPIC_CANDIDATES:
        try:
            cam = _ROSCamera(resolution, topic)
            if cam.wait_for_frame(timeout=2.0):
                logger.info("Camera: ROS %s", topic)
                return cam
            cam.release()
            logger.debug("ROS camera %s: no frames within 2s", topic)
        except Exception as exc:
            logger.debug("ROS camera %s failed: %s", topic, exc)
    return None


_ROS_TOPIC_CANDIDATES = [
    "/astra_cam/rgb/image_raw",
    "/camera/rgb/image_raw",
]


class _ROSCamera(object):
    """Subscribe to a ROS image topic; deliver resized BGR frames."""

    def __init__(self, resolution, topic):
        # type: (Tuple[int, int], str) -> None
        self._resolution = resolution
        self._frame = None   # type: Optional[np.ndarray]
        self._lock = threading.Lock()
        self._sub = None
        self._spin_thread = None  # type: Optional[threading.Thread]

        import rospy
        from sensor_msgs.msg import Image as ROSImage  # type: ignore

        try:
            rospy.init_node("dataset_recorder_cam", anonymous=True, disable_signals=True)
        except Exception:
            pass  # already initialized

        self._sub = rospy.Subscriber(
            topic, ROSImage, self._callback, queue_size=1,
        )

        # rospy callbacks need spin() — run it in a daemon thread
        def _spin():
            try:
                rospy.spin()
            except Exception:
                pass

        self._spin_thread = threading.Thread(target=_spin, daemon=True)
        self._spin_thread.start()

    def _callback(self, msg):
        # type: (object) -> None
        try:
            import cv2
            arr = np.frombuffer(msg.data, dtype=np.uint8)
            if msg.encoding in ("rgb8", "RGB8"):
                frame = arr.reshape(msg.height, msg.width, 3)
                frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            elif msg.encoding in ("bgr8", "BGR8"):
                frame = arr.reshape(msg.height, msg.width, 3).copy()
            else:
                logger.debug("Unsupported image encoding: %s", msg.encoding)
                return
            with self._lock:
                self._frame = frame
        except Exception as exc:
            logger.debug("ROS frame callback error: %s", exc)

    def wait_for_frame(self, timeout=3.0):
        # type: (float) -> bool
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                if self._frame is not None:
                    return True
            time.sleep(0.05)
        return False

    def read(self):
        # type: () -> Optional[np.ndarray]
        import cv2
        with self._lock:
            if self._frame is None:
                return None
            frame = self._frame.copy()
        return cv2.resize(frame, self._resolution)

    def release(self):
        # type: () -> None
        if self._sub is not None:
            try:
                self._sub.unregister()
            except Exception:
                pass
            self._sub = None


# ── cv2.VideoCapture backend ──────────────────────────────────────────────────

# Candidates: Astra Pro Plus typically appears as /dev/video1 or /dev/video2
_CV2_CANDIDATES = [0, 1, 2]


def _try_cv2_camera(resolution):
    # type: (Tuple[int, int]) -> Optional[object]
    try:
        import cv2  # type: ignore
    except ImportError:
        logger.debug("cv2 not available — skipping VideoCapture backend")
        return None

    for idx in _CV2_CANDIDATES:
        try:
            cap = cv2.VideoCapture(idx)
            if not cap.isOpened():
                cap.release()
                continue
            # Try reading a test frame to confirm the device streams
            ok, frame = cap.read()
            if not ok or frame is None:
                cap.release()
                continue
            logger.info("Camera: cv2.VideoCapture(%d)  (%dx%d native)", idx,
                        int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                        int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
            return _CV2Camera(cap, resolution)
        except Exception as exc:
            logger.debug("VideoCapture(%d) failed: %s", idx, exc)
    return None


class _CV2Camera(object):
    """Thin wrapper around cv2.VideoCapture that resizes on read()."""

    def __init__(self, cap, resolution):
        # type: (object, Tuple[int, int]) -> None
        self._cap = cap
        self._resolution = resolution

    def read(self):
        # type: () -> Optional[np.ndarray]
        import cv2
        ok, frame = self._cap.read()
        if not ok or frame is None:
            return None
        return cv2.resize(frame, self._resolution)

    def release(self):
        # type: () -> None
        try:
            self._cap.release()
        except Exception:
            pass


# ── OpenNI2 subprocess backend ─────────────────────────────────────────────────

def _try_openni2_camera(resolution):
    # type: (Tuple[int, int]) -> Optional[object]
    if not os.path.exists(_WORKER_SCRIPT):
        logger.debug("OpenNI2 worker not found: %s", _WORKER_SCRIPT)
        return None
    try:
        cam = _OpenNI2Camera(resolution)
        if cam.wait_for_frame(timeout=5.0):
            logger.info("Camera: OpenNI2 subprocess")
            return cam
        cam.release()
        logger.debug("OpenNI2 subprocess produced no frames (may have segfaulted)")
        return None
    except Exception as exc:
        logger.debug("OpenNI2 camera error: %s", exc)
        return None


class _OpenNI2Camera(object):
    """Subprocess-isolated OpenNI2 capture.

    The worker writes: 4-byte LE uint32 (JPEG size) + JPEG bytes, repeated.
    Subprocess isolation ensures any segfault in OpenNI2 doesn't kill the recorder.
    """

    _HDR = struct.Struct("<I")

    def __init__(self, resolution):
        # type: (Tuple[int, int]) -> None
        self._resolution = resolution
        self._frame = None   # type: Optional[np.ndarray]
        self._lock = threading.Lock()
        self._stop = threading.Event()

        self._proc = subprocess.Popen(
            [sys.executable, _WORKER_SCRIPT],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()

    def _reader(self):
        # type: () -> None
        import cv2
        stream = self._proc.stdout
        while not self._stop.is_set():
            try:
                hdr = stream.read(4)
                if len(hdr) < 4:
                    break
                (size,) = self._HDR.unpack(hdr)
                if size == 0 or size > 5 * 1024 * 1024:
                    break
                data = stream.read(size)
                if len(data) < size:
                    break
                arr = np.frombuffer(data, dtype=np.uint8)
                frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if frame is not None:
                    frame = cv2.resize(frame, self._resolution)
                    with self._lock:
                        self._frame = frame
            except Exception:
                break

    def wait_for_frame(self, timeout=5.0):
        # type: (float) -> bool
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                if self._frame is not None:
                    return True
            if self._proc.poll() is not None:  # subprocess died
                return False
            time.sleep(0.1)
        return False

    def read(self):
        # type: () -> Optional[np.ndarray]
        with self._lock:
            if self._frame is None:
                return None
            return self._frame.copy()

    def release(self):
        # type: () -> None
        self._stop.set()
        if self._proc is not None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=2.0)
            except Exception:
                pass
