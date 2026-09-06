#!/bin/bash
pkill -9 -f pokeball_rover_standalone.py 2>/dev/null
pkill -9 -f main.py 2>/dev/null
fuser -k 8085/tcp 2>/dev/null
fuser -k /dev/ttyACM0 2>/dev/null
sleep 0.5

SO101_DIR="${HOME}/aux_servo_interface/pi500"
if [ ! -d "$SO101_DIR" ]; then
    SO101_DIR="${HOME}/so101/pi500"
fi
if [ ! -d "$SO101_DIR" ]; then
    SO101_DIR="${HOME}/so101"
fi
cd "$SO101_DIR" || exit 1

PYTHON_BIN="python3"
if [ -x "${HOME}/aux_servo_interface/.venv/bin/python" ]; then
    PYTHON_BIN="${HOME}/aux_servo_interface/.venv/bin/python"
elif [ -x "${HOME}/so101/.venv/bin/python" ]; then
    PYTHON_BIN="${HOME}/so101/.venv/bin/python"
elif [ -x "${HOME}/touch_ui/.venv/bin/python" ]; then
    PYTHON_BIN="${HOME}/touch_ui/.venv/bin/python"
elif [ -x "/home/carson/touch_ui/.venv/bin/python" ]; then
    PYTHON_BIN="/home/carson/touch_ui/.venv/bin/python"
fi

nohup "$PYTHON_BIN" -u main.py </dev/null >/tmp/so101_master.log 2>&1 &

