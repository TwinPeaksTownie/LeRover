#!/bin/bash
pkill -9 -f pokeball_rover_standalone.py 2>/dev/null
pkill -9 -f main.py 2>/dev/null
fuser -k 8085/tcp 2>/dev/null
fuser -k /dev/ttyACM0 2>/dev/null

