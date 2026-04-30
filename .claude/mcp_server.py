"""MCP server for JetAuto robot control."""

import asyncio
import json
import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp.server import Server
from mcp.server.stdio import stdio_server
import mcp.types as types

from config import (
    ROBOT, ROBOT_API_DIR, SSH_TIMEOUT, EMERGENCY_TIMEOUT,
    LOG_FILE, LOCAL_CHANGELOG, REMOTE_CHANGELOG,
)

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("jetauto-mcp")

server = Server("jetauto")


def _ssh(cmd: list[str], timeout: int = SSH_TIMEOUT) -> dict:
    """Run a command on the robot via SSH and return parsed JSON output.

    Args:
        cmd: Command parts to append after the SSH call.
        timeout: Seconds before the call is killed.

    Returns:
        Parsed JSON dict from robot stdout, or {"error": "..."} on failure.
    """
    full_cmd = ["ssh", ROBOT] + cmd
    log.info("SSH call: %s", " ".join(full_cmd))
    try:
        result = subprocess.run(
            full_cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        stdout = result.stdout.strip()
        log.info("SSH stdout: %s", stdout[:500])
        if result.returncode != 0 and not stdout:
            return {"error": result.stderr.strip() or "non-zero exit", "returncode": result.returncode}
        return json.loads(stdout) if stdout else {"ok": True}
    except subprocess.TimeoutExpired:
        log.error("SSH timeout after %ds", timeout)
        return {"error": f"SSH timeout after {timeout}s"}
    except json.JSONDecodeError as exc:
        log.error("JSON parse error: %s | raw: %s", exc, stdout[:200])
        return {"error": "invalid JSON from robot", "raw": stdout[:200]}
    except Exception as exc:
        log.error("SSH error: %s", exc)
        return {"error": str(exc)}


def _scp(local_path: str, remote_path: str) -> dict:
    """Copy a local file to the robot via scp.

    Args:
        local_path: Absolute or relative path on this machine.
        remote_path: Destination path on the robot (~ supported).

    Returns:
        {"ok": True} on success or {"error": "..."} on failure.
    """
    cmd = ["scp", local_path, f"{ROBOT}:{remote_path}"]
    log.info("SCP: %s", " ".join(cmd))
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=SSH_TIMEOUT)
        if result.returncode != 0:
            return {"error": result.stderr.strip()}
        return {"ok": True, "local": local_path, "remote": remote_path}
    except subprocess.TimeoutExpired:
        return {"error": f"SCP timeout after {SSH_TIMEOUT}s"}
    except Exception as exc:
        return {"error": str(exc)}


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    """Enumerate all available robot tools."""
    return [
        types.Tool(
            name="robot_move",
            description="Move the robot in a direction for a given duration.",
            inputSchema={
                "type": "object",
                "properties": {
                    "direction": {"type": "string", "enum": ["forward", "back", "left", "right", "stop"]},
                    "speed": {"type": "number", "minimum": 0.0, "maximum": 1.0, "default": 0.3},
                    "duration": {"type": "number", "minimum": 0.0, "default": 1.0},
                },
                "required": ["direction"],
            },
        ),
        types.Tool(
            name="read_sensors",
            description="Read ultrasound, IMU and battery data from the robot.",
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="get_camera_snapshot",
            description="Capture a JPEG frame from the robot camera (base64-encoded).",
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="run_diagnostic",
            description="Return CPU, RAM, temperature and battery status.",
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="emergency_stop",
            description="Immediately halt all motors. Always works even under load.",
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="update_changelog",
            description="Append an entry to CHANGELOG.md on the robot and locally.",
            inputSchema={
                "type": "object",
                "properties": {
                    "version": {"type": "string"},
                    "section": {"type": "string", "enum": ["Added", "Changed", "Fixed", "Removed"]},
                    "message": {"type": "string"},
                },
                "required": ["version", "section", "message"],
            },
        ),
        types.Tool(
            name="deploy_file",
            description="Upload a local file to the robot via scp.",
            inputSchema={
                "type": "object",
                "properties": {
                    "local_path": {"type": "string"},
                    "remote_path": {"type": "string"},
                },
                "required": ["local_path", "remote_path"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    """Dispatch tool calls to the robot.

    Args:
        name: Tool name from list_tools.
        arguments: Tool input arguments.

    Returns:
        List with one TextContent containing a JSON result string.
    """
    log.info("Tool call: %s | args: %s", name, arguments)

    if name == "robot_move":
        direction = arguments.get("direction", "stop")
        speed = float(arguments.get("speed", 0.3))
        duration = float(arguments.get("duration", 1.0))
        result = _ssh(
            [f"python3 {ROBOT_API_DIR}/move.py", direction, str(speed), str(duration)]
        )

    elif name == "read_sensors":
        result = _ssh([f"python3 {ROBOT_API_DIR}/sensors.py"])

    elif name == "get_camera_snapshot":
        result = _ssh([f"python3 {ROBOT_API_DIR}/camera.py", "snapshot"])

    elif name == "run_diagnostic":
        result = _ssh([f"python3 {ROBOT_API_DIR}/diagnostic.py"])

    elif name == "emergency_stop":
        result = _ssh(
            [f"python3 {ROBOT_API_DIR}/move.py", "stop", "0", "0"],
            timeout=EMERGENCY_TIMEOUT,
        )

    elif name == "update_changelog":
        version = arguments["version"]
        section = arguments["section"]
        message = arguments["message"]
        date = datetime.now().strftime("%Y-%m-%d")
        entry = f"## [{date}] {version} — {message}"

        # Write to local CHANGELOG
        try:
            with open(LOCAL_CHANGELOG, "a", encoding="utf-8") as fh:
                fh.write(f"\n{entry}\n### {section}\n- {message}\n")
            local_ok = True
        except OSError as exc:
            local_ok = str(exc)

        # Write to robot CHANGELOG
        result = _ssh([
            f"python3 {ROBOT_API_DIR}/changelog.py",
            "add", version, section, message,
        ])
        result["local_write"] = local_ok

    elif name == "deploy_file":
        local_path = arguments["local_path"]
        remote_path = arguments["remote_path"]
        result = _scp(local_path, remote_path)

    else:
        result = {"error": f"Unknown tool: {name}"}

    log.info("Result: %s", json.dumps(result)[:300])
    return [types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]


async def main() -> None:
    """Entry point — run the MCP server over stdio."""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())
