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


def _get_chassis():
    """Return the real chassis object, or None if hardware is unavailable."""
    try:
        from hiwonder.jetauto import Board
        board = Board()
        board.set_car_motion(0, 0, 0)
        return board
    except Exception:
        return None


def move(direction: str, speed: float, duration: float) -> dict:
    """Command the robot to move in a direction.

    Args:
        direction: One of forward/back/left/right/stop.
        speed: Normalised speed 0.0–1.0.
        duration: How many seconds to move (0 = indefinite until stop).

    Returns:
        JSON-compatible result dict.
    """
    if direction not in VALID_DIRECTIONS:
        return {"error": f"Invalid direction '{direction}'. Use: {VALID_DIRECTIONS}"}
    speed = max(0.0, min(1.0, float(speed)))

    vx = vy = vz = 0.0
    if direction == "forward":
        vx = speed * 0.5
    elif direction == "back":
        vx = -speed * 0.5
    elif direction == "left":
        vy = speed * 0.5
    elif direction == "right":
        vy = -speed * 0.5

    chassis = _get_chassis()
    stub = chassis is None

    try:
        if not stub:
            chassis.set_car_motion(vx, vy, vz)
        if duration > 0:
            time.sleep(duration)
    finally:
        if not stub and direction != "stop":
            chassis.set_car_motion(0, 0, 0)

    return {
        "ok": True,
        "direction": direction,
        "speed": speed,
        "duration": duration,
        "stub": stub,
    }


def main() -> None:
    """Parse CLI args and execute move command."""
    args = sys.argv[1:]
    if not args:
        print(json.dumps({"error": "Usage: move.py <direction> [speed] [duration]"}))
        sys.exit(1)

    direction = args[0]
    speed = float(args[1]) if len(args) > 1 else 0.3
    duration = float(args[2]) if len(args) > 2 else 1.0

    try:
        result = move(direction, speed, duration)
    except Exception as exc:
        result = {"error": str(exc), "traceback": traceback.format_exc()}

    print(json.dumps(result))


if __name__ == "__main__":
    main()
