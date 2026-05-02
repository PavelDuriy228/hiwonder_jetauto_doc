#!/usr/bin/env python3
"""Motor control for JetAuto. Callable as a standalone CLI script.

Usage:
    python3 move.py forward 0.3 1.0
    python3 move.py stop
"""

import json
import sys
import time
import traceback

VALID_DIRECTIONS = {"forward", "back", "left", "right", "stop"}
WHEEL_BASE = 0.15  # metres between left and right wheels

# Cached chassis instance — avoids re-init (and the safety zero) on every call
_chassis_cache = None


def _get_chassis():
    """Return the real chassis object, or None if hardware is unavailable."""
    global _chassis_cache
    if _chassis_cache is not None:
        return _chassis_cache
    try:
        from hiwonder.jetauto import Board  # type: ignore
        board = Board()
        board.set_car_motion(0, 0, 0)
        _chassis_cache = board
        return board
    except Exception:
        return None


def move(direction, speed, duration=1.0, turn=0.0, blocking=False):
    # type: (str, float, float, float, bool) -> dict
    """Command the robot to move in a direction.

    Args:
        direction: One of forward/back/left/right/stop.
        speed:     Normalised speed 0.0–1.0.
        duration:  Seconds to move (ignored unless blocking=True).
        turn:      Differential turn offset (-1..1). Positive = turn right.
                   speed_left  = base_speed - turn
                   speed_right = base_speed + turn
        blocking:  If True, sleep(duration) then stop. CLI uses True.

    Returns:
        JSON-compatible result dict with speed_left, speed_right, vx, vy.
    """
    if direction not in VALID_DIRECTIONS:
        return {"error": "Invalid direction '{}'. Use: {}".format(direction, VALID_DIRECTIONS)}
    speed = max(0.0, min(1.0, float(speed)))
    turn = max(-1.0, min(1.0, float(turn)))

    # Map direction → base (speed_left, speed_right)
    _base = {
        "forward": ( speed,  speed),
        "back":    (-speed, -speed),
        "left":    (-speed,  speed),
        "right":   ( speed, -speed),
        "stop":    (0.0,    0.0),
    }
    base_sl, base_sr = _base[direction]

    # Apply turn offset
    sl = max(-1.0, min(1.0, base_sl - turn))
    sr = max(-1.0, min(1.0, base_sr + turn))

    # Convert differential wheel speeds → chassis vx / vz
    vx = (sl + sr) / 2.0
    vy = 0.0
    vz = (sr - sl) / WHEEL_BASE

    chassis = _get_chassis()
    stub = chassis is None

    try:
        if not stub:
            chassis.set_car_motion(vx, vy, vz)
        if blocking and duration > 0:
            time.sleep(duration)
    finally:
        if blocking and not stub and direction != "stop":
            chassis.set_car_motion(0, 0, 0)

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
    """Set wheel velocities directly, without duration. For use by recorder.

    Args:
        speed_left:  Normalised left-wheel speed  -1.0..1.0.
        speed_right: Normalised right-wheel speed -1.0..1.0.

    Returns:
        JSON-compatible dict with speed_left, speed_right, stub flag.
    """
    speed_left  = max(-1.0, min(1.0, float(speed_left)))
    speed_right = max(-1.0, min(1.0, float(speed_right)))

    vx = (speed_left + speed_right) / 2.0
    vy = 0.0
    vz = (speed_right - speed_left) / WHEEL_BASE

    chassis = _get_chassis()
    stub = chassis is None
    if not stub:
        chassis.set_car_motion(vx, vy, vz)

    return {"ok": True, "speed_left": speed_left, "speed_right": speed_right, "stub": stub}


def stop_motors():
    # type: () -> dict
    """Immediate stop. Always safe to call."""
    return set_velocity(0.0, 0.0)


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
