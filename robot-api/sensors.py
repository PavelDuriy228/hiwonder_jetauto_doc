#!/usr/bin/env python3
"""Read robot sensors: ultrasound, IMU, battery. Callable as a standalone CLI script.

Usage:
    python3 sensors.py
"""

import json
import random
import traceback


def _read_ultrasound() -> float:
    """Return distance in cm from front ultrasonic sensor."""
    try:
        from hiwonder.jetauto import Board
        board = Board()
        return board.get_distance()
    except Exception:
        return round(random.uniform(20.0, 150.0), 1)


def _read_imu() -> dict:
    """Return accelerometer and gyroscope data."""
    try:
        from hiwonder.jetauto import Board
        board = Board()
        ax, ay, az = board.get_accelerometer()
        gx, gy, gz = board.get_gyroscope()
        return {"ax": ax, "ay": ay, "az": az, "gx": gx, "gy": gy, "gz": gz}
    except Exception:
        return {
            "ax": round(random.uniform(-0.1, 0.1), 4),
            "ay": round(random.uniform(-0.1, 0.1), 4),
            "az": round(9.78 + random.uniform(-0.05, 0.05), 4),
            "gx": round(random.uniform(-1.0, 1.0), 4),
            "gy": round(random.uniform(-1.0, 1.0), 4),
            "gz": round(random.uniform(-1.0, 1.0), 4),
            "stub": True,
        }


def _read_battery() -> dict:
    """Return battery voltage and estimated percentage."""
    try:
        from hiwonder.jetauto import Board
        board = Board()
        voltage = board.get_battery_voltage()
        pct = max(0, min(100, int((voltage - 9.6) / (12.6 - 9.6) * 100)))
        return {"voltage_v": round(voltage, 2), "percent": pct}
    except Exception:
        voltage = round(random.uniform(11.0, 12.4), 2)
        pct = int((voltage - 9.6) / (12.6 - 9.6) * 100)
        return {"voltage_v": voltage, "percent": pct, "stub": True}


def read_sensors() -> dict:
    """Aggregate all sensor readings into one dict.

    Returns:
        Dict with keys: ultrasound_cm, imu, battery.
    """
    return {
        "ultrasound_cm": _read_ultrasound(),
        "imu": _read_imu(),
        "battery": _read_battery(),
    }


def main() -> None:
    """Print sensor data as JSON."""
    try:
        result = read_sensors()
    except Exception as exc:
        result = {"error": str(exc), "traceback": traceback.format_exc()}
    print(json.dumps(result))


if __name__ == "__main__":
    main()
