#!/bin/bash
# ==============================================================================
# SO-101 Unified Standalone Host Launcher for Raspberry Pi 4B
# Launches unified robot backend and Touch UI (pi4b/server.py on dual ports 8082 & 8085)
# ==============================================================================
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

echo "=== [SO-101] Initializing Standalone Environment on Pi 4B ==="

# 1. Clean up stale processes
pkill -9 -f "pi4b/server.py" 2>/dev/null || true
pkill -9 -f main.py 2>/dev/null || true
fuser -k 8085/tcp 2>/dev/null || true
fuser -k 8082/tcp 2>/dev/null || true
fuser -k /dev/ttyACM0 2>/dev/null || true
sleep 0.5

# 2. Resolve Python environment
PYTHON_BIN="python3"
if [ -x "${HOME}/aux_servo_interface/.venv/bin/python" ]; then
    PYTHON_BIN="${HOME}/aux_servo_interface/.venv/bin/python"
elif [ -x "${HOME}/touch_ui/.venv/bin/python" ]; then
    PYTHON_BIN="${HOME}/touch_ui/.venv/bin/python"
elif [ -x "${HOME}/so101/.venv/bin/python" ]; then
    PYTHON_BIN="${HOME}/so101/.venv/bin/python"
fi

echo "Using Python: $PYTHON_BIN"

# 3. Launch Unified Robot Backend & Touch UI Server (Ports 8082 & 8085)
echo "Starting Unified Robot Backend & Touch UI on ports 8082 and 8085..."
cd "$DIR"
exec "$PYTHON_BIN" pi4b/server.py
