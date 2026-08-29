#!/usr/bin/env python3
"""Helper module executed on Pi 4B to manage the Standalone Pokéball Rover process on Pi 500.
Dynamically resolves Pi 500 target IP (Ethernet-first fallback).
"""

import logging
import os
import subprocess
import sys

try:
    import network_resolver
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import network_resolver

PI500_USER = "user"

logger = logging.getLogger("pi4b.rover_launcher")


def get_pi500_ip() -> str:
    return network_resolver.get_pi500_ip(prefer_port=22)


def start_rover() -> bool:
    """Launches standalone Pokéball Rover driver on Pi 500."""
    target_ip = get_pi500_ip()
    cmd = [
        "ssh",
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=4",
        f"{PI500_USER}@{target_ip}",
        "bash /home/user/so101/pi500/start_rover.sh"
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=6)
    logger.info("Launched Standalone Pokéball Rover on %s (code=%d): out='%s' err='%s'", target_ip, res.returncode, res.stdout.strip(), res.stderr.strip())
    return res.returncode == 0


def stop_rover() -> bool:
    """Stops standalone Pokéball Rover driver on Pi 500."""
    target_ip = get_pi500_ip()
    cmd = [
        "ssh",
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=4",
        f"{PI500_USER}@{target_ip}",
        "bash /home/user/so101/pi500/stop_rover.sh"
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=6)
    logger.info("Stopped Standalone Pokéball Rover on %s: out='%s' err='%s'", target_ip, res.stdout.strip(), res.stderr.strip())
    return True


def is_running() -> bool:
    """Checks whether Standalone Pokéball Rover is actively running on Pi 500."""
    target_ip = get_pi500_ip()
    cmd = [
        "ssh",
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=3",
        f"{PI500_USER}@{target_ip}",
        "pgrep -f pokeball_rover_standalone.py"
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=4)
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
