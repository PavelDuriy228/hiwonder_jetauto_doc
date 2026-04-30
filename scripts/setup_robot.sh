#!/usr/bin/env bash
# Deploy robot_api to JetAuto and install dependencies.
# Run from the project root: bash scripts/setup_robot.sh

set -euo pipefail

ROBOT="jetauto@192.168.149.1"
REMOTE_DIR="~/jetauto_tesla/robot_api"
LOCAL_DIR="$(cd "$(dirname "$0")/.." && pwd)/robot_api"

GREEN="\033[32m"
RED="\033[31m"
RESET="\033[0m"

ok()   { echo -e "${GREEN}[OK]${RESET}  $*"; }
fail() { echo -e "${RED}[FAIL]${RESET} $*"; exit 1; }

echo "=== JetAuto robot_api setup ==="
echo "Remote: ${ROBOT}:${REMOTE_DIR}"
echo ""

# 1. Create remote directory
echo "Step 1: Creating remote directory..."
ssh "$ROBOT" "mkdir -p ${REMOTE_DIR}" && ok "Directory created" || fail "Cannot create remote dir"

# 2. Copy robot_api files via scp
echo "Step 2: Copying robot_api files..."
scp -r "${LOCAL_DIR}/." "${ROBOT}:${REMOTE_DIR}/" && ok "Files copied" || fail "scp failed"

# 3. Install Python dependencies on robot
echo "Step 3: Installing Python dependencies on robot..."
ssh "$ROBOT" "pip3 install --quiet psutil opencv-python-headless 2>&1 | tail -3" \
  && ok "Dependencies installed" \
  || fail "pip3 install failed"

# 4. Verify by running diagnostic
echo "Step 4: Running diagnostic on robot..."
OUTPUT=$(ssh "$ROBOT" "python3 ${REMOTE_DIR}/diagnostic.py" 2>&1)
if echo "$OUTPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print('CPU:', d['cpu_percent'], '% | RAM:', d['ram']['percent'], '%')" 2>/dev/null; then
  ok "Diagnostic passed"
else
  fail "Diagnostic failed. Raw output:\n${OUTPUT}"
fi

echo ""
echo "=== Setup complete ==="
echo "Register MCP server with:"
echo "  claude mcp add jetauto -- python3 .claude/mcp_server.py"
