#!/bin/bash
pkill -9 -f pokeball_rover_standalone.py 2>/dev/null
sleep 0.5
# Restore master orchestrator on Pi 500
bash /home/user/so101/pi500/start_master.sh
