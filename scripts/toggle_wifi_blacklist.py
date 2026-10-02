#!/usr/bin/env python3
"""Wi-Fi Blacklist & Offline Isolation Test Utility for SO-101.
Allows disabling Wi-Fi across Pi 4B and Pi 500 to test direct Ethernet offline operation,
with a 10-minute safety watchdog timer that guarantees automatic restoration.
"""

import logging
import os
import subprocess
import sys
import time
import threading

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("wifi_blacklist")

PI4B_ETH_IP = "10.0.0.2"


def disable_wifi_local() -> bool:
    """Disables Wi-Fi on local machine."""
    logger.info("Disabling local Wi-Fi interface (rfkill block wifi / nmcli radio wifi off)...")
    try:
        subprocess.run(["sudo", "rfkill", "block", "wifi"], check=False)
        subprocess.run(["sudo", "nmcli", "radio", "wifi", "off"], check=False)
        return True
    except Exception as e:
        logger.error("Error disabling local wifi: %s", e)
        return False


def enable_wifi_local() -> bool:
    """Enables Wi-Fi on local machine and reconnects."""
    logger.info("Enabling local Wi-Fi interface (rfkill unblock wifi / nmcli radio wifi on)...")
    try:
        subprocess.run(["sudo", "rfkill", "unblock", "wifi"], check=False)
        subprocess.run(["sudo", "nmcli", "radio", "wifi", "on"], check=False)
        time.sleep(1.0)
        # Trigger reconnection via wifi_mode_manager if present
        mgr_script = "/home/carson/touch_ui/scripts/wifi_mode_manager.py"
        if os.path.exists(mgr_script):
            subprocess.Popen([sys.executable, mgr_script])
        return True
    except Exception as e:
        logger.error("Error enabling local wifi: %s", e)
        return False


def start_safety_watchdog(timeout_sec: int = 600):
    """Forks a detached background watchdog process that automatically unblocks Wi-Fi after timeout."""
    logger.info("Launching detached safety watchdog (%d seconds)...", timeout_sec)
    restore_cmd = f"sleep {timeout_sec} && sudo rfkill unblock wifi && sudo nmcli radio wifi on"
    subprocess.Popen(["bash", "-c", restore_cmd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def disable_all(watchdog_sec: int = 600):
    logger.info("=== DISABLING WI-FI ON PI 4B ===")
    start_safety_watchdog(watchdog_sec)
    disable_wifi_local()
    logger.info("=== Wi-Fi is now DISABLED on Pi 4B. ===")


def enable_all():
    logger.info("=== RESTORING WI-FI ON PI 4B ===")
    enable_wifi_local()
    logger.info("=== Wi-Fi has been RESTORED on Pi 4B. ===")


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "disable"
    if action == "enable" or action == "restore" or action == "on":
        enable_all()
    else:
        disable_all()
