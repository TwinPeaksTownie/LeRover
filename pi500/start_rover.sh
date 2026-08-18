#!/bin/bash
# Clean up any stale standalone rover processes
pkill -9 -f pokeball_rover_standalone.py 2>/dev/null
sleep 0.3

# Launch detached in virtual environment
cd /home/user/so101/pi500
nohup /home/user/so101/.venv/bin/python pokeball_rover_standalone.py </dev/null >/tmp/pokeball_rover.log 2>&1 &
