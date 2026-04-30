#!/usr/bin/env python3
"""Append entries to CHANGELOG.md on the robot.

Usage:
    python3 changelog.py add "v0.2" "Added" "Реализован MCP сервер"
"""

import json
import sys
import traceback
from datetime import datetime
from pathlib import Path

CHANGELOG_PATH = Path.home() / "CHANGELOG.md"


def add_entry(version: str, section: str, message: str) -> dict:
    """Append a versioned entry to the robot's CHANGELOG.md.

    Args:
        version: Semver string, e.g. "v0.1.0".
        section: One of Added / Changed / Fixed / Removed.
        message: Human-readable description of the change.

    Returns:
        Dict with ok, path, appended_text.
    """
    date = datetime.now().strftime("%Y-%m-%d")
    entry = (
        f"\n## [{date}] {version} — {message}\n"
        f"### {section}\n"
        f"- {message}\n"
    )
    CHANGELOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CHANGELOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(entry)
    return {"ok": True, "path": str(CHANGELOG_PATH), "appended": entry.strip()}


def main() -> None:
    """CLI entry point."""
    if len(sys.argv) < 5 or sys.argv[1] != "add":
        print(json.dumps({"error": "Usage: changelog.py add <version> <section> <message>"}))
        sys.exit(1)
    _, _, version, section, *rest = sys.argv
    message = " ".join(rest)
    try:
        result = add_entry(version, section, message)
    except Exception as exc:
        result = {"error": str(exc), "traceback": traceback.format_exc()}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
