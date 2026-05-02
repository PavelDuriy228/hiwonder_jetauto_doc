#!/usr/bin/env python3
"""Dataset recorder for JetAuto — синхронная запись кадров и команд моторов.

Usage:
    python3 dataset_recorder.py record [--fps 10] [--resolution 160x120]
    python3 dataset_recorder.py finalize --session data/raw/session_20250430_143022
    python3 dataset_recorder.py stats
    python3 dataset_recorder.py preview --session data/raw/session_20250430_143022
"""

import argparse
import csv
import json
import logging
import os
import queue
import select
import shutil
import signal
import sys
import termios
import threading
import time
import tty
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np

# ── Constants ─────────────────────────────────────────────────────────────────
BASE_SPEED = 0.4
MIN_FREE_DISK_MB = 100
JPEG_QUALITY = 85
BASE_DATA_DIR = Path("data/raw")
LOG_INTERVAL_SEC = 5.0
KEY_HOLD_SEC = 0.15  # seconds before a held key state expires

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("dataset_recorder")
logger.setLevel(logging.INFO)
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    ))
    logger.addHandler(_handler)
logger.propagate = False


# ── Motor API (robot_api.move) ────────────────────────────────────────────────
# Import from sibling package when running on the robot; fall back to stubs.
def _stub_set_velocity(sl, sr):
    return {"ok": True, "speed_left": float(sl), "speed_right": float(sr), "stub": True}

def _stub_stop():
    return _stub_set_velocity(0.0, 0.0)

try:
    _api_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    sys.path.insert(0, _api_dir)
    from robot_api.move import set_velocity, stop_motors  # type: ignore
    logger.debug("robot_api.move imported OK")
except Exception:
    set_velocity = _stub_set_velocity  # type: ignore
    stop_motors = _stub_stop           # type: ignore
    logger.debug("robot_api.move not found — using stubs")


# ── Camera (optional) ─────────────────────────────────────────────────────────
try:
    from camera import open_camera as _open_camera  # type: ignore
except ImportError:
    _open_camera = None  # type: ignore


# ── Keyboard helper (works in SSH via termios raw mode) ───────────────────────
class RawKeyboard:
    """Non-blocking single-character reader using termios raw mode."""

    def __init__(self):
        self._old_settings = None

    def __enter__(self):
        self._old_settings = termios.tcgetattr(sys.stdin)
        tty.setraw(sys.stdin.fileno())
        return self

    def __exit__(self, *_):
        if self._old_settings:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self._old_settings)

    def read(self, timeout=0.0):
        # type: (float) -> str
        """Return one character or '' if nothing available within timeout."""
        rlist, _, _ = select.select([sys.stdin], [], [], timeout)
        if rlist:
            return sys.stdin.read(1)
        return ""


# ── Hardware stubs ─────────────────────────────────────────────────────────────
def _get_ultrasonic():
    # type: () -> float
    """Read ultrasonic sensor in cm; -1.0 if unavailable."""
    try:
        from hiwonder.jetauto import Board  # type: ignore
        board = Board()
        dist = board.get_distance()
        return float(dist) if dist is not None else -1.0
    except Exception:
        return -1.0


# ── SessionMeta ───────────────────────────────────────────────────────────────
@dataclass
class SessionMeta:
    session_dir: str
    total_frames: int
    duration_sec: float
    fps_actual: float
    size_mb: float


# ── DatasetRecorder ───────────────────────────────────────────────────────────
class DatasetRecorder:
    """Records camera frames and motor commands to disk synchronously."""

    def __init__(self, session_dir, resolution=(160, 120), fps=10):
        # type: (str, Tuple[int, int], int) -> None
        self.session_dir = Path(session_dir)
        self.resolution = resolution
        self.fps = fps

        self._frames_dir = self.session_dir / "frames"
        self._csv_path = self.session_dir / "controls.csv"
        self._meta_path = self.session_dir / "meta.json"

        self._frame_count = 0
        self._start_time = None  # type: Optional[float]
        self._recording = False
        self._paused = False

        # Queue for async CSV writes so they don't block the capture loop
        self._csv_queue = queue.Queue()  # type: queue.Queue
        self._csv_thread = None  # type: Optional[threading.Thread]
        self._csv_file = None
        self._csv_writer = None

        self._last_fps_log = 0.0
        self._fps_window_frames = 0
        self._fps_window_start = 0.0

    def start(self):
        # type: () -> None
        """Begin a recording session."""
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self._frames_dir.mkdir(exist_ok=True)

        self._csv_file = open(str(self._csv_path), "w", newline="")
        self._csv_writer = csv.writer(self._csv_file)
        self._csv_writer.writerow(
            ["timestamp_ns", "frame_id", "speed_left", "speed_right", "ultrasonic_cm"]
        )

        self._csv_thread = threading.Thread(target=self._csv_worker, daemon=True)
        self._csv_thread.start()

        self._start_time = time.time()
        self._last_fps_log = self._start_time
        self._fps_window_start = self._start_time
        self._recording = True
        logger.info("Recording started -> %s", self.session_dir)

    def stop(self):
        # type: () -> SessionMeta
        """Stop recording and return session metadata."""
        self._recording = False
        elapsed = time.time() - (self._start_time or time.time())

        # Flush CSV queue
        self._csv_queue.put(None)  # sentinel
        if self._csv_thread:
            self._csv_thread.join(timeout=5.0)
        if self._csv_file:
            self._csv_file.close()

        fps_actual = self._frame_count / elapsed if elapsed > 0 else 0.0
        size_mb = _dir_size_mb(self.session_dir)

        meta = SessionMeta(
            session_dir=str(self.session_dir),
            total_frames=self._frame_count,
            duration_sec=round(elapsed, 2),
            fps_actual=round(fps_actual, 2),
            size_mb=round(size_mb, 2),
        )
        self._write_meta(meta)
        logger.info(
            "Recording stopped: %d frames, %.1f sec, %.1f fps, %.1f MB",
            meta.total_frames, meta.duration_sec, meta.fps_actual, meta.size_mb,
        )
        return meta

    def record_frame(self, frame, speed_left, speed_right):
        # type: (np.ndarray, float, float) -> None
        """Write one frame + motor command atomically."""
        if not self._recording or self._paused:
            return

        if _free_disk_mb() < MIN_FREE_DISK_MB:
            logger.warning("Disk almost full (<100 MB free). Stopping recording.")
            self.stop()
            return

        import cv2  # lazy import

        ts_ns = int(time.time() * 1e9)
        frame_id = self._frame_count
        frame_name = "{:06d}.jpg".format(frame_id)

        resized = cv2.resize(frame, self.resolution)
        cv2.imwrite(
            str(self._frames_dir / frame_name),
            resized,
            [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY],
        )

        ultrasonic_cm = _get_ultrasonic()
        self._csv_queue.put(
            (ts_ns, "{:06d}".format(frame_id), speed_left, speed_right, ultrasonic_cm)
        )

        self._frame_count += 1
        self._fps_window_frames += 1

        now = time.time()
        if now - self._last_fps_log >= LOG_INTERVAL_SEC:
            window_elapsed = now - self._fps_window_start
            fps = self._fps_window_frames / window_elapsed if window_elapsed > 0 else 0.0
            logger.info("FPS: %.1f  |  frames: %d", fps, self._frame_count)
            self._fps_window_frames = 0
            self._fps_window_start = now
            self._last_fps_log = now

    def get_stats(self):
        # type: () -> Dict
        """Return current recording statistics."""
        elapsed = time.time() - (self._start_time or time.time())
        fps_actual = self._frame_count / elapsed if elapsed > 0 else 0.0
        return {
            "frames": self._frame_count,
            "size_mb": round(_dir_size_mb(self.session_dir), 2),
            "fps_actual": round(fps_actual, 2),
            "elapsed_sec": round(elapsed, 1),
            "paused": self._paused,
        }

    def toggle_pause(self):
        # type: () -> None
        self._paused = not self._paused
        logger.info("Recording %s", "PAUSED" if self._paused else "RESUMED")

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _csv_worker(self):
        # type: () -> None
        while True:
            item = self._csv_queue.get()
            if item is None:
                break
            self._csv_writer.writerow(item)
            self._csv_file.flush()

    def _write_meta(self, meta):
        # type: (SessionMeta) -> None
        data = asdict(meta)
        data["resolution"] = list(self.resolution)
        data["fps"] = self.fps
        data["robot_id"] = "jetauto"
        with open(str(self._meta_path), "w") as f:
            json.dump(data, f, indent=2)


# ── Utilities ─────────────────────────────────────────────────────────────────
def _free_disk_mb():
    # type: () -> float
    usage = shutil.disk_usage(".")
    return usage.free / (1024 * 1024)


def _dir_size_mb(path):
    # type: (Path) -> float
    total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    return total / (1024 * 1024)


def _new_session_dir():
    # type: () -> Path
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return BASE_DATA_DIR / "session_{}".format(ts)


def _gray_frame(resolution):
    # type: (Tuple[int, int]) -> np.ndarray
    return np.full((resolution[1], resolution[0], 3), 128, dtype=np.uint8)


# ── Key → speeds helper ───────────────────────────────────────────────────────
def _key_to_speeds(fwd_key, turn_key):
    # type: (Optional[str], Optional[str]) -> Tuple[float, float]
    """Compute (speed_left, speed_right) from currently active key state."""
    if fwd_key == "w" and turn_key == "a":
        return BASE_SPEED * 0.3, BASE_SPEED
    if fwd_key == "w" and turn_key == "d":
        return BASE_SPEED, BASE_SPEED * 0.3
    if fwd_key == "w":
        return BASE_SPEED, BASE_SPEED
    if fwd_key == "s":
        return -BASE_SPEED, -BASE_SPEED
    if turn_key == "a":
        return -BASE_SPEED, BASE_SPEED
    if turn_key == "d":
        return BASE_SPEED, -BASE_SPEED
    return 0.0, 0.0


# ── KeyController — 50 Hz keyboard thread ─────────────────────────────────────
KEY_POLL_HZ = 50  # motor response < 20 ms

class KeyController(threading.Thread):
    """Polls keyboard at KEY_POLL_HZ and drives motors immediately on each keypress.

    The recording loop reads current_sl / current_sr at its own (slower) rate.
    """

    def __init__(self, stop_flag, recorder_ref):
        # type: (threading.Event, DatasetRecorder) -> None
        super(KeyController, self).__init__(daemon=True)
        self.stop_flag = stop_flag
        self._recorder = recorder_ref
        self._lock = threading.Lock()
        self._sl = 0.0
        self._sr = 0.0

    def get_speeds(self):
        # type: () -> Tuple[float, float]
        with self._lock:
            return self._sl, self._sr

    def run(self):
        # type: () -> None
        fwd_key = None   # type: Optional[str]
        turn_key = None  # type: Optional[str]
        fwd_time = 0.0
        turn_time = 0.0
        poll_interval = 1.0 / KEY_POLL_HZ

        try:
            with RawKeyboard() as kb:
                while not self.stop_flag.is_set():
                    t0 = time.time()
                    key = kb.read(timeout=0.0)
                    now = time.time()

                    if key:
                        k = key.lower()
                        if k in ("w", "s"):
                            fwd_key = k
                            fwd_time = now
                        elif k in ("a", "d"):
                            turn_key = k
                            turn_time = now
                        elif k == "q":
                            sl, sr = _key_to_speeds(fwd_key, turn_key)
                            for _ in range(6):
                                sl *= 0.5
                                sr *= 0.5
                                set_velocity(sl, sr)
                                time.sleep(0.05)
                            fwd_key = turn_key = None
                            stop_motors()
                        elif k == "e":
                            fwd_key = turn_key = None
                            stop_motors()
                            logger.info("EMERGENCY STOP")
                        elif k == "p":
                            self._recorder.toggle_pause()
                        elif k == "i":
                            logger.info("Stats: %s", self._recorder.get_stats())
                        elif key in ("\x1b", "\x03"):  # ESC or Ctrl-C
                            self.stop_flag.set()
                            break

                    # Expire key state if no new event within KEY_HOLD_SEC
                    if now - fwd_time > KEY_HOLD_SEC:
                        fwd_key = None
                    if now - turn_time > KEY_HOLD_SEC:
                        turn_key = None

                    sl, sr = _key_to_speeds(fwd_key, turn_key)
                    vel = set_velocity(sl, sr)

                    with self._lock:
                        self._sl = vel["speed_left"]
                        self._sr = vel["speed_right"]

                    elapsed = time.time() - t0
                    sleep = poll_interval - elapsed
                    if sleep > 0:
                        time.sleep(sleep)

        except Exception as exc:
            logger.error("KeyController error: %s", exc)
            self.stop_flag.set()


# ── record command ────────────────────────────────────────────────────────────
def cmd_record(fps, resolution, duration=None):
    # type: (int, Tuple[int, int], Optional[float]) -> None
    """Interactive WASD recording session.

    If duration is set (or stdin is not a TTY), runs headlessly for N seconds.
    """
    # Warn once about motor stub mode
    _probe = set_velocity(0.0, 0.0)
    if _probe.get("stub"):
        logger.warning("Motors stubbed — no hardware detected")

    cap = _open_camera(resolution) if _open_camera is not None else None
    if cap is None:
        logger.warning(
            "Camera unavailable — grey stub frames will be recorded.\n"
            "  To enable the camera, start ROS first:\n"
            "    roslaunch jetauto_peripherals astrapro.launch"
        )

    session_dir = _new_session_dir()
    recorder = DatasetRecorder(str(session_dir), resolution=resolution, fps=fps)
    recorder.start()

    interval = 1.0 / fps
    meta = None
    stop_flag = threading.Event()

    def _sigterm_handler(sig, frame):
        stop_flag.set()

    signal.signal(signal.SIGTERM, _sigterm_handler)

    # ── Headless / timed mode ─────────────────────────────────────────────────
    if duration is not None or not sys.stdin.isatty():
        if duration is None:
            duration = 10.0
        logger.info("Headless mode: recording %.0f seconds at %d fps", duration, fps)
        deadline = time.time() + duration
        try:
            while time.time() < deadline and not stop_flag.is_set():
                t0 = time.time()
                if cap is not None:
                    frame = cap.read()
                    if frame is None:
                        frame = _gray_frame(resolution)
                else:
                    frame = _gray_frame(resolution)
                recorder.record_frame(frame, 0.0, 0.0)
                sleep_time = interval - (time.time() - t0)
                if sleep_time > 0:
                    time.sleep(sleep_time)
        except KeyboardInterrupt:
            logger.info("Ctrl+C — stopping")
        finally:
            stop_motors()
            if cap is not None:
                cap.release()
            meta = recorder.stop()
            logger.info("Session saved: %s", meta.session_dir)
        if meta and meta.total_frames > 0:
            logger.info("Finalizing -> dataset.h5 ...")
            cmd_finalize(meta.session_dir)
        return

    # ── Interactive keyboard mode (50 Hz key thread + 10 fps recording) ─────────
    print(
        "\nW/S -- forward/back   A/D -- left/right   W+A/W+D -- diagonal\n"
        "Q -- smooth stop      E -- emergency stop\n"
        "P -- pause/resume     I -- stats\n"
        "ESC or Ctrl-C -- stop & finalize\n"
        "Motor response: <20 ms (keys run at {}Hz)\n".format(KEY_POLL_HZ)
    )
    sys.stdout.flush()

    key_ctrl = KeyController(stop_flag, recorder)
    key_ctrl.start()

    try:
        while not stop_flag.is_set():
            t0 = time.time()

            if cap is not None:
                frame = cap.read()
                if frame is None:
                    frame = _gray_frame(resolution)
            else:
                frame = _gray_frame(resolution)

            # Read speeds set by key thread (already sent to motors)
            sl, sr = key_ctrl.get_speeds()
            recorder.record_frame(frame, sl, sr)

            sleep_time = interval - (time.time() - t0)
            if sleep_time > 0:
                time.sleep(sleep_time)

    except KeyboardInterrupt:
        logger.info("Ctrl+C — stopping")
        stop_flag.set()
    finally:
        stop_motors()
        key_ctrl.join(timeout=1.0)
        if cap is not None:
            cap.release()
        meta = recorder.stop()
        logger.info("Session saved: %s", meta.session_dir)

    if meta and meta.total_frames > 0:
        logger.info("Finalizing -> dataset.h5 ...")
        cmd_finalize(meta.session_dir)
    else:
        logger.warning("No frames recorded — skipping finalize")


# ── finalize command ──────────────────────────────────────────────────────────
def cmd_finalize(session_dir):
    # type: (str) -> None
    """Convert session folder -> dataset.h5."""
    import cv2
    import h5py  # type: ignore

    path = Path(session_dir)
    csv_path = path / "controls.csv"
    frames_dir = path / "frames"
    h5_path = path / "dataset.h5"

    if not csv_path.exists():
        logger.error("controls.csv not found in %s", session_dir)
        return

    rows = []
    with open(str(csv_path)) as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)

    n = len(rows)
    logger.info("Finalizing %d frames from %s", n, session_dir)

    meta = {}
    meta_path = path / "meta.json"
    if meta_path.exists():
        with open(str(meta_path)) as f:
            meta = json.load(f)

    res = meta.get("resolution", [160, 120])
    w, h = int(res[0]), int(res[1])

    frames_arr = np.zeros((n, h, w, 3), dtype=np.uint8)
    ts_arr = np.zeros(n, dtype=np.int64)
    sl_arr = np.zeros(n, dtype=np.float32)
    sr_arr = np.zeros(n, dtype=np.float32)
    ult_arr = np.zeros(n, dtype=np.float32)

    for i, row in enumerate(rows):
        frame_file = frames_dir / "{}.jpg".format(row["frame_id"])
        if frame_file.exists():
            img = cv2.imread(str(frame_file))
            if img is not None:
                frames_arr[i] = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        ts_arr[i] = int(row["timestamp_ns"])
        sl_arr[i] = float(row["speed_left"])
        sr_arr[i] = float(row["speed_right"])
        ult_arr[i] = float(row["ultrasonic_cm"])

    with h5py.File(str(h5_path), "w") as f:
        f.create_dataset("frames", data=frames_arr, compression="gzip", compression_opts=4)
        f.create_dataset("speed_left", data=sl_arr)
        f.create_dataset("speed_right", data=sr_arr)
        f.create_dataset("timestamp_ns", data=ts_arr)
        f.create_dataset("ultrasonic_cm", data=ult_arr)
        f.attrs["session_dir"] = str(session_dir)
        f.attrs["total_frames"] = n

    size_mb = h5_path.stat().st_size / (1024 * 1024)
    logger.info("dataset.h5 written: %.1f MB", size_mb)


# ── stats command ─────────────────────────────────────────────────────────────
def cmd_stats():
    # type: () -> None
    """Print statistics for all recorded sessions."""
    if not BASE_DATA_DIR.exists():
        logger.info("No sessions found (data/raw/ does not exist)")
        return

    sessions = sorted(BASE_DATA_DIR.glob("session_*"))
    if not sessions:
        logger.info("No sessions found in %s", BASE_DATA_DIR)
        return

    total_frames = 0
    total_mb = 0.0
    print("\n{:<35} {:>8} {:>10} {:>6} {:>9}".format(
        "Session", "Frames", "Duration", "FPS", "Size MB"))
    print("-" * 72)

    for s in sessions:
        meta_path = s / "meta.json"
        if meta_path.exists():
            with open(str(meta_path)) as f:
                m = json.load(f)
            frames = m.get("total_frames", 0)
            dur = m.get("duration_sec", 0)
            fps = m.get("fps_actual", 0)
            mb = _dir_size_mb(s)
            total_frames += frames
            total_mb += mb
            print("{:<35} {:>8} {:>9.1f}s {:>6.1f} {:>8.1f}".format(
                s.name, frames, dur, fps, mb))
        else:
            mb = _dir_size_mb(s)
            total_mb += mb
            print("{:<35} {:>8} {:>10} {:>6} {:>8.1f}".format(
                s.name, "?", "?", "?", mb))

    print("-" * 72)
    print("{:<35} {:>8} {:>10} {:>6} {:>8.1f}".format(
        "TOTAL", total_frames, "", "", total_mb))
    print()


# ── preview command ───────────────────────────────────────────────────────────
def cmd_preview(session_dir):
    # type: (str) -> None
    """Replay frames and motor commands from a session."""
    import cv2

    path = Path(session_dir)
    csv_path = path / "controls.csv"
    frames_dir = path / "frames"

    if not csv_path.exists():
        logger.error("controls.csv not found")
        return

    with open(str(csv_path)) as f:
        rows = list(csv.DictReader(f))

    if not rows:
        logger.info("No frames in session")
        return

    fps = 10.0
    meta_path = path / "meta.json"
    if meta_path.exists():
        with open(str(meta_path)) as f:
            m = json.load(f)
            fps = float(m.get("fps_actual", 10) or 10)

    delay_ms = max(1, int(1000.0 / fps))
    logger.info("Preview: %d frames at %.1f fps (press Q to quit)", len(rows), fps)

    for row in rows:
        frame_file = frames_dir / "{}.jpg".format(row["frame_id"])
        if not frame_file.exists():
            continue
        frame = cv2.imread(str(frame_file))
        if frame is None:
            continue

        sl = float(row["speed_left"])
        sr = float(row["speed_right"])
        ult = float(row["ultrasonic_cm"])

        label = "L:{:+.2f} R:{:+.2f} ult:{:.0f}cm".format(sl, sr, ult)
        cv2.putText(frame, label, (4, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)
        cv2.imshow("Preview", frame)

        key = cv2.waitKey(delay_ms) & 0xFF
        if key == ord("q"):
            break

    cv2.destroyAllWindows()


# ── CLI ───────────────────────────────────────────────────────────────────────
def main():
    # type: () -> None
    parser = argparse.ArgumentParser(description="JetAuto Dataset Recorder")
    sub = parser.add_subparsers(dest="cmd")
    sub.required = True

    p_rec = sub.add_parser("record", help="Record a new session")
    p_rec.add_argument("--fps", type=int, default=10)
    p_rec.add_argument("--resolution", default="160x120")
    p_rec.add_argument("--duration", type=float, default=None,
                       help="Record for N seconds then stop (headless mode)")

    p_fin = sub.add_parser("finalize", help="Convert session folder to HDF5")
    p_fin.add_argument("--session", required=True)

    sub.add_parser("stats", help="Show statistics for all sessions")

    p_prev = sub.add_parser("preview", help="Replay a session")
    p_prev.add_argument("--session", required=True)

    args = parser.parse_args()

    if args.cmd == "record":
        try:
            parts = args.resolution.split("x")
            w, h = int(parts[0]), int(parts[1])
        except (ValueError, IndexError):
            logger.error("Invalid resolution format. Use WxH, e.g. 160x120")
            sys.exit(1)
        cmd_record(fps=args.fps, resolution=(w, h), duration=args.duration)

    elif args.cmd == "finalize":
        cmd_finalize(args.session)

    elif args.cmd == "stats":
        cmd_stats()

    elif args.cmd == "preview":
        cmd_preview(args.session)


if __name__ == "__main__":
    main()
