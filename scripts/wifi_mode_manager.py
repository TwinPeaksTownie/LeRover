#!/usr/bin/env python3
"""3-Mode Wi-Fi and Network Orchestrator for SO-101 Robotics System.
Sequentially attempts:
1. iPhone Hotspot (Priority 1) with 2 retries (5 sec apart).
2. Maestas Mansion Home Wi-Fi (Priority 2).
3. Offline Mode over Direct Ethernet (10.0.0.1 <-> 10.0.0.2).
"""

import json
import logging
import os
import subprocess
import sys
import time

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("wifi_mode_manager")

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "network_config.json")
if not os.path.exists(CONFIG_PATH):
    CONFIG_PATH = "/home/carson/touch_ui/config/network_config.json"
if not os.path.exists(CONFIG_PATH):
    CONFIG_PATH = "/home/user/so101/config/network_config.json"


def load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error("Failed loading %s: %s", CONFIG_PATH, e)
    return {}


def is_wifi_connected(target_ssid: str = None) -> bool:
    try:
        res = subprocess.run(
            ["nmcli", "-t", "-f", "NAME,TYPE,DEVICE", "connection", "show", "--active"],
            capture_output=True, text=True, timeout=2.0
        )
        for line in res.stdout.strip().splitlines():
            parts = line.split(":")
            if len(parts) >= 3 and parts[1] == "802-11-wireless" and "wlan" in parts[2]:
                if target_ssid is None or parts[0] == target_ssid or target_ssid in parts[0]:
                    return True
    except Exception as e:
        logger.warning("Error checking wifi status: %s", e)
    return False


def try_connect_ssid(ssid: str, psk: str, max_retries: int = 2, delay_sec: int = 5) -> bool:
    logger.info("Attempting connection to SSID '%s' (max %d retries, %d sec delay)...", ssid, max_retries, delay_sec)
    
    # 1. Ensure connection profile exists in NetworkManager
    try:
        # Check if profile exists
        res = subprocess.run(["nmcli", "-t", "-f", "NAME", "connection", "show"], capture_output=True, text=True, timeout=2.0)
        existing = [line.strip() for line in res.stdout.strip().splitlines()]
        if ssid not in existing:
            logger.info("Adding NM Wi-Fi profile for '%s'...", ssid)
            subprocess.run([
                "sudo", "nmcli", "connection", "add", "type", "wifi", "ifname", "wlan0",
                "con-name", ssid, "ssid", ssid,
                "wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.psk", psk,
                "connection.autoconnect", "yes"
            ], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        logger.warning("Profile check/creation warning: %s", e)

    # 2. Try activating connection with retries
    for attempt in range(1, max_retries + 1):
        logger.info("  [Attempt %d/%d] Activating '%s'...", attempt, max_retries, ssid)
        try:
            res = subprocess.run(["nmcli", "connection", "up", ssid], capture_output=True, text=True, timeout=12.0)
            if res.returncode != 0 and "not authorized" in (res.stderr.lower() + res.stdout.lower()):
                res = subprocess.run(["sudo", "nmcli", "connection", "up", ssid], capture_output=True, text=True, timeout=12.0)
            if res.returncode == 0 or is_wifi_connected(ssid):
                logger.info(" Successfully connected to '%s'!", ssid)
                return True
            else:
                logger.warning("  Attempt %d failed: %s", attempt, res.stderr.strip() or res.stdout.strip())
        except Exception as ex:
            logger.warning("  Attempt %d error: %s", attempt, ex)

        if attempt < max_retries:
            time.sleep(delay_sec)

    return False


def run_mode_orchestration():
    logger.info("=== Starting 3-Mode Network Orchestration ===")
    cfg = load_config()
    wifi_modes = cfg.get("wifi_modes", {}).get("priority_list", [])

    # Check if already connected to Priority 1 (iPhone)
    if wifi_modes and len(wifi_modes) > 0:
        p1 = wifi_modes[0]
        if is_wifi_connected(p1.get("ssid")):
            logger.info("Already connected to Priority 1 Wi-Fi: '%s'. Mode: %s", p1.get("ssid"), p1.get("mode_name"))
            return p1.get("mode_name")

    # Sequentially attempt priority networks
    for mode in wifi_modes:
        ssid = mode.get("ssid")
        psk = mode.get("psk")
        retries = mode.get("max_retries", 2)
        delay = mode.get("retry_delay_sec", 5)
        mode_name = mode.get("mode_name")

        if try_connect_ssid(ssid, psk, max_retries=retries, delay_sec=delay):
            logger.info("=== Connected to Mode: %s (%s) ===", mode_name, ssid)
            return mode_name

    logger.warning("=== All Wi-Fi Modes Exhausted. Entering Mode 3: OFFLINE_DIRECT_ETH ===")
    logger.warning("Operating over Direct Ethernet Bus (10.0.0.1/2). Cloud apps disabled.")
    return "OFFLINE_DIRECT_ETH"


if __name__ == "__main__":
    mode = run_mode_orchestration()
    print(f"ACTIVE_MODE={mode}")
