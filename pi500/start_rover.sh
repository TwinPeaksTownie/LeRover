#!/bin/bash
# Stop master daemon to yield /dev/ttyAMA0 and BLE interface exclusively to standalone rover
pkill -9 -f main.py 2>/dev/null
pkill -9 -f pokeball_rover_standalone.py 2>/dev/null
fuser -k 8085/tcp 2>/dev/null
sleep 0.5

# Launch detached in virtual environment
cd /home/user/so101/pi500
nohup /home/user/so101/.venv/bin/python -u pokeball_rover_standalone.py </dev/null >/tmp/pokeball_rover.log 2>&1 &

