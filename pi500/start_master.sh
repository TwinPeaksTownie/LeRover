#!/bin/bash
pkill -9 -f pokeball_rover_standalone.py 2>/dev/null
pkill -9 -f main.py 2>/dev/null
fuser -k 8085/tcp 2>/dev/null
sleep 0.5
cd /home/user/so101/pi500
nohup /home/user/so101/.venv/bin/python -u main.py </dev/null >/tmp/so101_master.log 2>&1 &
