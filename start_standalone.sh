#!/bin/bash
# ==============================================================================
# SO-101 Unified Standalone Host Launcher for Raspberry Pi 4B
# Launches both master hardware backend (pi500/main.py on 8085) and Touch UI (pi4b/server.py on 8082)
# ==============================================================================
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

echo "=== [SO-101] Initializing Standalone Environment on Pi 4B ==="

# 1. Clean up stale processes
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

# 3. Launch Master Hardware Backend Daemon on Port 8085
echo "Starting Master Hardware Daemon on port 8085..."
cd "$DIR/pi500"
nohup "$PYTHON_BIN" -u main.py </dev/null >/tmp/so101_master.log 2>&1 &
BACKEND_PID=$!
echo "Master Hardware Daemon running with PID $BACKEND_PID (logs: /tmp/so101_master.log)"

# 4. Wait for Master Backend HTTP 8085 to become responsive
echo "Waiting for Master Backend on port 8085..."
READY=0
for i in $(seq 1 20); do
    if curl -s http://127.0.0.1:8085/api/status >/dev/null 2>&1; then
        READY=1
        echo "Master Backend active and healthy on port 8085."
        break
    fi
    sleep 0.5
done

if [ $READY -ne 1 ]; then
    echo "WARNING: Master Backend did not respond within 10s. Inspecting /tmp/so101_master.log:"
    tail -n 20 /tmp/so101_master.log || true
fi

# 5. Launch Touch UI Web Server on Port 8082
echo "Starting Touch UI Server on port 8082..."
cd "$DIR"
exec "$PYTHON_BIN" pi4b/server.py
