#!/usr/bin/env python3
"""Motor control for JetAuto using jetauto_sdk.MecanumChassis.

Usage:
    python3 move.py forward 0.3 1.0
    python3 move.py stop
"""

import json
import math
import sys
import time
import traceback

# Path to the real SDK inside the ROS workspace
JETAUTO_SDK_PATH = "/home/jetauto/jetauto_ws/src/jetauto_driver/jetauto_sdk/src"

VALID_DIRECTIONS = {"forward", "back", "left", "right", "stop"}
WHEEL_BASE = 0.15        # metres (a+b = 103+97 = 200 mm — used for normalised math)
MAX_SPEED_MM_S = 150.0   # mm/s at normalised speed 1.0 (safe for development)

# Cached MecanumChassis instance — created once, reused across calls
_chassis_cache = None


def _get_chassis():
    """Return MecanumChassis instance, or None if hardware is unavailable."""
    global _chassis_cache
    if _chassis_cache is not None:
        return _chassis_cache
    try:
        if JETAUTO_SDK_PATH not in sys.path:
            sys.path.insert(0, JETAUTO_SDK_PATH)
        from jetauto_sdk.mecanum import MecanumChassis  # type: ignore
        chassis = MecanumChassis()
        chassis.reset_motors()
        _chassis_cache = chassis
        return chassis
    except Exception:
        return None


def _wheel_speeds_to_chassis(chassis, speed_left, speed_right):
    """Send normalised wheel speeds to MecanumChassis.

    Converts differential-drive (speed_left, speed_right) in [-1, 1]
    to polar (speed_mm_s, direction_rad, angular_rate_rad_s).
    """
    avg = (speed_left + speed_right) / 2.0
    speed_mm_s = abs(avg) * MAX_SPEED_MM_S
    direction = 0.0 if avg >= 0.0 else math.pi
    # angular_rate: (a + b) = 200 mm converts mm/s difference to rad/s
    angular_rate = (speed_right - speed_left) * MAX_SPEED_MM_S / 200.0
    chassis.set_velocity(speed_mm_s, direction, angular_rate)


def move(direction, speed, duration=1.0, turn=0.0, blocking=False):
    # type: (str, float, float, float, bool) -> dict
    """Command the robot to move in a direction.

    Args:
        direction: One of forward/back/left/right/stop.
        speed:     Normalised speed 0.0–1.0.
        duration:  Seconds to move (only used when blocking=True).
        turn:      Differential turn offset -1..1. Positive = turn right.
        blocking:  If True, sleep(duration) then stop. CLI uses True.

    Returns:
        JSON-compatible result dict with speed_left, speed_right, vx, vy.
    """
    if direction not in VALID_DIRECTIONS:
        return {"error": "Invalid direction '{}'. Use: {}".format(direction, VALID_DIRECTIONS)}
    speed = max(0.0, min(1.0, float(speed)))
    turn = max(-1.0, min(1.0, float(turn)))

    _base = {
        "forward": ( speed,  speed),
        "back":    (-speed, -speed),
        "left":    (-speed,  speed),
        "right":   ( speed, -speed),
        "stop":    (0.0,    0.0),
    }
    base_sl, base_sr = _base[direction]
    sl = max(-1.0, min(1.0, base_sl - turn))
    sr = max(-1.0, min(1.0, base_sr + turn))

    vx = (sl + sr) / 2.0
    vy = 0.0

    chassis = _get_chassis()
    stub = chassis is None

    try:
        if not stub:
            _wheel_speeds_to_chassis(chassis, sl, sr)
        if blocking and duration > 0:
            time.sleep(duration)
    finally:
        if blocking and not stub and direction != "stop":
            chassis.reset_motors()

    return {
        "ok": True,
        "direction": direction,
        "speed": speed,
        "duration": duration,
        "stub": stub,
        "speed_left": sl,
        "speed_right": sr,
        "vx": vx,
        "vy": vy,
    }


def set_velocity(speed_left, speed_right):
    # type: (float, float) -> dict
    """Set wheel velocities directly. For use by dataset recorder.

    Args:
        speed_left:  Normalised left-wheel speed  -1.0..1.0.
        speed_right: Normalised right-wheel speed -1.0..1.0.

    Returns:
        dict with speed_left, speed_right, stub flag.
    """
    speed_left  = max(-1.0, min(1.0, float(speed_left)))
    speed_right = max(-1.0, min(1.0, float(speed_right)))

    chassis = _get_chassis()
    stub = chassis is None
    if not stub:
        _wheel_speeds_to_chassis(chassis, speed_left, speed_right)

    return {"ok": True, "speed_left": speed_left, "speed_right": speed_right, "stub": stub}


def stop_motors():
    # type: () -> dict
    """Immediate stop. Always safe to call."""
    chassis = _get_chassis()
    if chassis is not None:
        chassis.reset_motors()
    return {"ok": True, "speed_left": 0.0, "speed_right": 0.0, "stub": chassis is None}


def main():
    # type: () -> None
    """Parse CLI args and execute move command (blocking mode)."""
    args = sys.argv[1:]
    if not args:
        print(json.dumps({"error": "Usage: move.py <direction> [speed] [duration]"}))
        sys.exit(1)

    direction = args[0]
    speed = float(args[1]) if len(args) > 1 else 0.3
    duration = float(args[2]) if len(args) > 2 else 1.0

    try:
        result = move(direction, speed, duration, blocking=True)
    except Exception as exc:
        result = {"error": str(exc), "traceback": traceback.format_exc()}

    print(json.dumps(result))


if __name__ == "__main__":
    main()
