#!/usr/bin/env python3
"""System diagnostic for JetAuto: CPU, RAM, temperature, battery.

Usage:
    python3 diagnostic.py
"""

import json
import traceback
from typing import Optional


def run_diagnostic() -> dict:
    """Collect system health metrics without requiring root.

    Returns:
        Dict with cpu_percent, ram, temperature_c, battery, uptime_s.
    """
    import psutil
    import time

    cpu = psutil.cpu_percent(interval=0.5)
    ram = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    uptime = time.time() - psutil.boot_time()

    temp_c = None
    try:
        temps = psutil.sensors_temperatures()
        for key in ("cpu_thermal", "coretemp", "cpu-thermal"):
            if key in temps and temps[key]:
                temp_c = round(temps[key][0].current, 1)
                break
    except (AttributeError, NotImplementedError):
        pass

    if temp_c is None:
        try:
            with open("/sys/class/thermal/thermal_zone0/temp") as fh:
                temp_c = round(int(fh.read().strip()) / 1000, 1)
        except OSError:
            temp_c = None

    # Battery — try real SDK, else None
    battery = None  # type: Optional[dict]
    try:
        from hiwonder.jetauto import Board
        board = Board()
        voltage = board.get_battery_voltage()
        pct = max(0, min(100, int((voltage - 9.6) / (12.6 - 9.6) * 100)))
        battery = {"voltage_v": round(voltage, 2), "percent": pct}
    except Exception:
        battery = {"voltage_v": None, "percent": None, "stub": True}

    return {
        "cpu_percent": cpu,
        "ram": {
            "total_mb": round(ram.total / 1024**2, 1),
            "used_mb": round(ram.used / 1024**2, 1),
            "percent": ram.percent,
        },
        "disk": {
            "total_gb": round(disk.total / 1024**3, 2),
            "used_gb": round(disk.used / 1024**3, 2),
            "percent": disk.percent,
        },
        "temperature_c": temp_c,
        "battery": battery,
        "uptime_s": round(uptime),
    }


def main() -> None:
    """Print diagnostic JSON to stdout."""
    try:
        result = run_diagnostic()
    except Exception as exc:
        result = {"error": str(exc), "traceback": traceback.format_exc()}
    print(json.dumps(result))


if __name__ == "__main__":
    main()
