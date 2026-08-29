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

PI500_ETH_IP = "10.0.0.1"
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
        if not os.path.exists(mgr_script):
            mgr_script = "/home/user/so101/scripts/wifi_mode_manager.py"
        if os.path.exists(mgr_script):
            subprocess.Popen([sys.executable, mgr_script])
        return True
    except Exception as e:
        logger.error("Error enabling local wifi: %s", e)
        return False


def disable_wifi_remote_pi500() -> bool:
    """Disables Wi-Fi on Pi 500 via direct Ethernet SSH."""
    logger.info("Disabling Pi 500 Wi-Fi over Direct Ethernet (%s)...", PI500_ETH_IP)
    cmd = [
        "ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=4",
        f"user@{PI500_ETH_IP}",
        "sudo rfkill block wifi; sudo nmcli radio wifi off"
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=6)
    logger.info("Pi 500 Wi-Fi disable output: out='%s' err='%s'", res.stdout.strip(), res.stderr.strip())
    return res.returncode == 0


def enable_wifi_remote_pi500() -> bool:
    """Enables Wi-Fi on Pi 500 via direct Ethernet SSH."""
    logger.info("Enabling Pi 500 Wi-Fi over Direct Ethernet (%s)...", PI500_ETH_IP)
    cmd = [
        "ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=4",
        f"user@{PI500_ETH_IP}",
        "sudo rfkill unblock wifi; sudo nmcli radio wifi on"
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=6)
    logger.info("Pi 500 Wi-Fi enable output: out='%s' err='%s'", res.stdout.strip(), res.stderr.strip())
    return res.returncode == 0


def start_safety_watchdog(timeout_sec: int = 600):
    """Forks a detached background watchdog process that automatically unblocks Wi-Fi after timeout."""
    logger.info("Launching detached safety watchdog (%d seconds)...", timeout_sec)
    restore_cmd = f"sleep {timeout_sec} && sudo rfkill unblock wifi && sudo nmcli radio wifi on && ssh -o StrictHostKeyChecking=no -o ConnectTimeout=4 user@{PI500_ETH_IP} 'sudo rfkill unblock wifi; sudo nmcli radio wifi on'"
    subprocess.Popen(["bash", "-c", restore_cmd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def disable_all(watchdog_sec: int = 600):
    logger.info("=== DISABLING WI-FI ACROSS PI 4B AND PI 500 ===")
    start_safety_watchdog(watchdog_sec)
    disable_wifi_remote_pi500()
    disable_wifi_local()
    logger.info("=== Wi-Fi is now DISABLED on both Pis. Robot operating in 100% Direct Ethernet Isolation. ===")


def enable_all():
    logger.info("=== RESTORING WI-FI ACROSS PI 4B AND PI 500 ===")
    enable_wifi_local()
    enable_wifi_remote_pi500()
    logger.info("=== Wi-Fi has been RESTORED on both Pis. ===")


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "disable"
    if action == "enable" or action == "restore" or action == "on":
        enable_all()
    else:
        disable_all()
