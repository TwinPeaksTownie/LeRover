#!/usr/bin/env python3
"""Native BlueZ Bluetooth Joy-Con Pairing & Device Lifecycle Management Module.

Repurposed and integrated directly into aux_servo_interface/apps/joycon_app/.
Features:
- Universal JSON configuration loaded fail-fast from config.json.
- Stale link-key removal (bluetoothctl remove <MAC>) to resolve BlueZ caching locks.
- Robust subprocess-based BlueZ execution without fragile pexpect regex prompt matching.
- Automatic device discovery for broadcasting Joy-Cons during rail Sync mode.
- Post-pairing hidraw permissions enforcement (0666).
"""

import json
import logging
import os
import re
import subprocess
import sys
import time
from typing import Tuple, Optional, Callable, Dict, Any

logger = logging.getLogger("joycon.pair")

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")


def load_pairing_config() -> Dict[str, Any]:
    """Loads pairing and hardware configuration fail-fast with direct bracket indexing."""
    if not os.path.exists(CONFIG_PATH):
        raise FileNotFoundError(f"Missing required Joy-Con config: {CONFIG_PATH}")
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    _ = str(cfg["hardware"]["mac_address"])
    _ = int(cfg["pairing"]["timeout_sec"])
    _ = int(cfg["pairing"]["scan_timeout_sec"])
    _ = bool(cfg["pairing"]["auto_remove_stale"])
    return cfg


def cleanup_stale_devices(target_mac: Optional[str] = None) -> None:
    """Removes any stale Joy-Con or target MAC device entries from BlueZ daemon."""
    try:
        res = subprocess.run(["bluetoothctl", "devices"], capture_output=True, text=True, timeout=6)
        for line in res.stdout.splitlines():
            line_upper = line.upper()
            is_joycon = "JOY-CON" in line_upper
            is_target = bool(target_mac and (target_mac.upper() in line_upper))
            if is_joycon or is_target:
                parts = line.split()
                if len(parts) >= 2 and parts[0] == "Device":
                    dev_mac = parts[1]
                    logger.info("Purging stale BlueZ device entry: %s", dev_mac)
                    subprocess.run(["bluetoothctl", "remove", dev_mac], capture_output=True, text=True, timeout=5)
    except Exception as e:
        logger.warning("Error during stale device cleanup: %s", e)


def _extract_mac_from_scan_output(output: str, target_mac: Optional[str]) -> Optional[str]:
    """Extracts broadcasting Joy-Con MAC address from scan output."""
    if target_mac:
        target_upper = target_mac.upper()
        if target_upper in output.upper():
            return target_upper

    for line in output.splitlines():
        if "Joy-Con" in line or "JOY-CON" in line.upper():
            match = re.search(r"([0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5})", line)
            if match:
                return match.group(1).upper()
    return None


def pair_joycon(
    mac: Optional[str] = None,
    timeout_sec: Optional[int] = None,
    status_cb: Optional[Callable[[str], None]] = None
) -> Tuple[bool, str]:
    """Purges stale link keys, scans, pairs, trusts, and connects Nintendo Switch Joy-Con."""
    cfg = load_pairing_config()
    target_mac = (mac or cfg["hardware"]["mac_address"]).upper()
    total_timeout = timeout_sec if timeout_sec is not None else int(cfg["pairing"]["timeout_sec"])
    scan_chunk = int(cfg["pairing"]["scan_timeout_sec"])
    auto_remove = bool(cfg["pairing"]["auto_remove_stale"])

    logger.info("=== Starting BlueZ Pairing for Joy-Con [%s] ===", target_mac)

    def _notify(msg: str):
        logger.info("[PAIR STATUS] %s", msg)
        if status_cb:
            try:
                status_cb(msg)
            except Exception as cb_err:
                logger.debug("status_cb exception: %s", cb_err)

    if auto_remove:
        _notify("Clearing stale link keys...")
        cleanup_stale_devices(target_mac)

    # 1. Ensure BlueZ controller is powered on and default agent is active
    try:
        subprocess.run(["bluetoothctl", "power", "on"], capture_output=True, text=True, timeout=5)
        subprocess.run(["bluetoothctl", "default-agent"], capture_output=True, text=True, timeout=5)
    except Exception as e:
        msg = f"Failed to initialize BlueZ controller state: {e}"
        logger.error(msg)
        return False, msg

    # 2. Scan for Joy-Con broadcasting in pairing mode
    _notify("Scanning for Joy-Con... Hold rail Sync button until LEDs cycle")
    t0 = time.time()
    found_mac: Optional[str] = None

    while (time.time() - t0) < total_timeout:
        rem_sec = int(total_timeout - (time.time() - t0))
        _notify(f"Scanning ({rem_sec}s remaining)... Hold rail Sync button")
        try:
            scan_proc = subprocess.run(
                ["bluetoothctl", "--timeout", str(scan_chunk), "scan", "on"],
                capture_output=True,
                text=True,
                timeout=scan_chunk + 5
            )
            scan_out = (scan_proc.stdout or "") + "\n" + (scan_proc.stderr or "")
            discovered = _extract_mac_from_scan_output(scan_out, target_mac)
            if discovered:
                found_mac = discovered
                logger.info("Discovered broadcasting Joy-Con at MAC: %s", found_mac)
                break
        except subprocess.TimeoutExpired:
            logger.debug("Scan sweep timeout, continuing scan loop...")
        except Exception as e:
            logger.warning("Scan exception: %s", e)

        # Also check existing devices in case scan already populated cache
        try:
            dev_proc = subprocess.run(["bluetoothctl", "devices"], capture_output=True, text=True, timeout=5)
            discovered = _extract_mac_from_scan_output(dev_proc.stdout or "", target_mac)
            if discovered:
                found_mac = discovered
                logger.info("Discovered Joy-Con in devices cache at MAC: %s", found_mac)
                break
        except Exception as dev_err:
            logger.debug("Device cache inspection exception: %s", dev_err)

    if not found_mac:
        # If specific MAC was provided, attempt direct pair as fallback before declaring failure
        found_mac = target_mac
        logger.info("Proceeding to direct pairing attempt for target MAC [%s]...", found_mac)

    # 3. Execute Pairing Handshake
    _notify(f"Pairing with Joy-Con [{found_mac}]...")
    try:
        pair_res = subprocess.run(["bluetoothctl", "pair", found_mac], capture_output=True, text=True, timeout=15)
        pair_out = (pair_res.stdout or "") + " " + (pair_res.stderr or "")
        logger.info("bluetoothctl pair output: %s", pair_out.strip())
        if pair_res.returncode != 0 and "Failed to pair" in pair_out and "AlreadyExists" not in pair_out:
            msg = f"Pairing handshake failed for Joy-Con [{found_mac}]: {pair_out.strip()}"
            logger.warning(msg)
            return False, msg
    except Exception as e:
        msg = f"Exception pairing Joy-Con [{found_mac}]: {e}"
        logger.error(msg)
        return False, msg

    # 4. Trust Device
    _notify(f"Trusting Joy-Con [{found_mac}]...")
    try:
        trust_res = subprocess.run(["bluetoothctl", "trust", found_mac], capture_output=True, text=True, timeout=6)
        logger.info("bluetoothctl trust output: %s", (trust_res.stdout or "").strip())
    except Exception as e:
        logger.warning("Warning trusting Joy-Con [%s]: %s", found_mac, e)

    # 5. Connect Device
    _notify(f"Connecting to Joy-Con [{found_mac}]...")
    try:
        conn_res = subprocess.run(["bluetoothctl", "connect", found_mac], capture_output=True, text=True, timeout=12)
        conn_out = (conn_res.stdout or "") + " " + (conn_res.stderr or "")
        logger.info("bluetoothctl connect output: %s", conn_out.strip())
    except Exception as e:
        logger.warning("Warning connecting Joy-Con [%s]: %s", found_mac, e)

    # 6. Ensure permissions on newly spawned /dev/hidraw nodes
    try:
        subprocess.run("sudo chmod 666 /dev/hidraw*", shell=True, capture_output=True, timeout=3)
    except Exception as e:
        logger.debug("chmod /dev/hidraw* result: %s", e)

    # 7. Verify device state via bluetoothctl info
    try:
        info_res = subprocess.run(["bluetoothctl", "info", found_mac], capture_output=True, text=True, timeout=6)
        info_out = info_res.stdout or ""
        paired = "Paired: yes" in info_out
        trusted = "Trusted: yes" in info_out
        connected = "Connected: yes" in info_out

        if paired and (connected or trusted):
            msg = f"Joy-Con [{found_mac}] successfully paired and configured (Connected: {connected})."
            logger.info("SUCCESS: %s", msg)
            _notify(msg)
            return True, msg
        else:
            msg = f"Pairing incomplete for [{found_mac}]. info report: Paired={paired}, Trusted={trusted}, Connected={connected}"
            logger.warning(msg)
            return False, msg
    except Exception as e:
        msg = f"Error reading Joy-Con info post-pair: {e}"
        logger.error(msg)
        return False, msg


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    target = None
    if len(sys.argv) > 1:
        target = sys.argv[1]
    ok, msg = pair_joycon(target)
    print(f"Result: {ok} -> {msg}")
    sys.exit(0 if ok else 1)
