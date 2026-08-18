#!/usr/bin/env python3
"""Helper module executed on Pi 4B to manage the Standalone Pokéball Rover process on Pi 500."""

import logging
import subprocess
import sys

PI500_IP = "192.168.0.130"
PI500_USER = "user"

logger = logging.getLogger("pi4b.rover_launcher")


def start_rover() -> bool:
    """Launches standalone Pokéball Rover driver on Pi 500."""
    cmd = [
        "ssh",
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=5",
        f"{PI500_USER}@{PI500_IP}",
        "bash /home/user/so101/pi500/start_rover.sh"
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
    logger.info("Launched Standalone Pokéball Rover on Pi 500 (code=%d): out='%s' err='%s'", res.returncode, res.stdout.strip(), res.stderr.strip())
    return res.returncode == 0


def stop_rover() -> bool:
    """Stops standalone Pokéball Rover driver on Pi 500."""
    cmd = [
        "ssh",
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=5",
        f"{PI500_USER}@{PI500_IP}",
        "bash /home/user/so101/pi500/stop_rover.sh"
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
    logger.info("Stopped Standalone Pokéball Rover on Pi 500: out='%s' err='%s'", res.stdout.strip(), res.stderr.strip())
    return True


def is_running() -> bool:
    """Checks whether Standalone Pokéball Rover is actively running on Pi 500."""
    cmd = [
        "ssh",
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=3",
        f"{PI500_USER}@{PI500_IP}",
        "pgrep -f pokeball_rover_standalone.py"
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
    return res.returncode == 0 and bool(res.stdout.strip())


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "stop":
        stop_rover()
    elif len(sys.argv) > 1 and sys.argv[1] == "status":
        print("RUNNING" if is_running() else "STOPPED")
    else:
        start_rover()
        import time
        time.sleep(1)
        print("STATUS AFTER START:", "RUNNING" if is_running() else "STOPPED")
