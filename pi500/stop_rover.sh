#!/bin/bash
pkill -9 -f pokeball_rover_standalone.py 2>/dev/null
sleep 0.5
# Restore master orchestrator
SCRIPT_PATH="${HOME}/so101/pi500/start_master.sh"
if [ ! -f "$SCRIPT_PATH" ]; then
    SCRIPT_PATH="/home/user/so101/pi500/start_master.sh"
fi
bash "$SCRIPT_PATH"

