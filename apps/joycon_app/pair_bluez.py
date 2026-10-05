#!/usr/bin/env python3
"""Native BlueZ Bluetooth Joy-Con Pairing & Device Lifecycle Management Module.

Repurposed and integrated directly into aux_servo_interface/apps/joycon_app/.
Features:
- Universal JSON configuration loaded fail-fast from config.json.
- Stale link-key removal (bluetoothctl remove <MAC>) to resolve BlueZ caching locks.
- Active stdout monitoring of 'bluetoothctl scan on' to block until the target MAC
  is confirmed detected over the air before issuing pair commands.
- Explicit 'bluetoothctl pairable on' enforcement prior to scanning.
- Post-pairing hidraw permissions enforcement (0666).
"""

import json
import logging
import os
import re
import select
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
    _ = bool(cfg["pairing"]["stale_purge_on_startup"])
    _ = bool(cfg["pairing"]["auto_pair_on_search"])
    _ = float(cfg["pairing"]["search_scan_interval_sec"])
    _ = float(cfg["pairing"]["unpaired_grace_period_sec"])
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


def _check_dbus_device_exists(mac: str) -> bool:
    """Verifies whether BlueZ has instantiated the D-Bus device object in memory."""
    try:
        res = subprocess.run(["bluetoothctl", "info", mac], capture_output=True, text=True, timeout=3)
        out = res.stdout or ""
        return "Device " in out and mac.upper() in out.upper() and "not available" not in out.lower()
    except Exception:
        return False


def _scan_and_await_device(target_mac: str, timeout_sec: int, status_cb: Optional[Callable[[str], None]] = None) -> Optional[str]:
    """Streams 'bluetoothctl scan on' stdout in real time, blocking until target MAC is detected."""
    target_upper = target_mac.upper()
    scan_proc = subprocess.Popen(
        ["bluetoothctl", "scan", "on"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )

    t0 = time.time()
    found_mac: Optional[str] = None

    try:
        if sys.platform != "win32":
            # Unix active I/O polling via select
            while (time.time() - t0) < timeout_sec:
                rlist, _, _ = select.select([scan_proc.stdout], [], [], 0.5)
                if rlist and scan_proc.stdout is not None:
                    line = scan_proc.stdout.readline()
                    if not line:
                        break
                    line_upper = line.upper()
                    if target_upper in line_upper or ("JOY-CON" in line_upper and "DEVICE" in line_upper):
                        match = re.search(r"([0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5})", line)
                        detected = match.group(1).upper() if match else target_upper
                        if _check_dbus_device_exists(detected):
                            found_mac = detected
                            logger.info("Explicitly detected broadcast and verified D-Bus device object for [%s]", found_mac)
                            break

                if _check_dbus_device_exists(target_upper):
                    found_mac = target_upper
                    logger.info("D-Bus device object instantiated for [%s]", found_mac)
                    break
        else:
            # Non-blocking readline simulation for development environments
            while (time.time() - t0) < timeout_sec:
                if scan_proc.stdout is not None:
                    line = scan_proc.stdout.readline()
                    if target_upper in line.upper():
                        found_mac = target_upper
                        break
                if _check_dbus_device_exists(target_upper):
                    found_mac = target_upper
                    break
    finally:
        scan_proc.terminate()
        try:
            scan_proc.wait(timeout=2)
        except Exception:
            scan_proc.kill()

    return found_mac


def pair_joycon(
    mac: Optional[str] = None,
    timeout_sec: Optional[int] = None,
    status_cb: Optional[Callable[[str], None]] = None
) -> Tuple[bool, str]:
    """Purges stale link keys, continuously monitors discovery scan, pairs, trusts, and connects Joy-Con."""
    cfg = load_pairing_config()
    target_mac = (mac or cfg["hardware"]["mac_address"]).upper()
    total_timeout = timeout_sec if timeout_sec is not None else int(cfg["pairing"]["timeout_sec"])
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

    # 1. Enforce Bluetooth adapter state (Power ON, Pairable ON, Default Agent)
    try:
        subprocess.run(["bluetoothctl", "power", "on"], capture_output=True, text=True, timeout=5)
        subprocess.run(["bluetoothctl", "pairable", "on"], capture_output=True, text=True, timeout=5)
        subprocess.run(["bluetoothctl", "default-agent"], capture_output=True, text=True, timeout=5)
    except Exception as e:
        msg = f"Failed to initialize BlueZ controller state: {e}"
        logger.error(msg)
        return False, msg

    # 2. Actively monitor scan output until radio broadcast is confirmed over the air
    _notify("Scanning for Joy-Con broadcast... Hold rail Sync button until LEDs cycle")
    found_mac = _scan_and_await_device(target_mac, total_timeout, status_cb)

    if not found_mac:
        msg = f"Scan timed out after {total_timeout}s without detecting Joy-Con broadcast for [{target_mac}]."
        logger.warning(msg)
        return False, msg

    # 3. Confirm D-Bus device object exists before executing pairing handshake
    if not _check_dbus_device_exists(found_mac):
        msg = f"D-Bus device object for [{found_mac}] not present in BlueZ memory; aborting pair attempt."
        logger.error(msg)
        return False, msg

    # 4. Execute Pairing Handshake
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

    # 5. Trust Device
    _notify(f"Trusting Joy-Con [{found_mac}]...")
    try:
        trust_res = subprocess.run(["bluetoothctl", "trust", found_mac], capture_output=True, text=True, timeout=6)
        logger.info("bluetoothctl trust output: %s", (trust_res.stdout or "").strip())
    except Exception as e:
        logger.warning("Warning trusting Joy-Con [%s]: %s", found_mac, e)

    # 6. Connect Device
    _notify(f"Connecting to Joy-Con [{found_mac}]...")
    try:
        conn_res = subprocess.run(["bluetoothctl", "connect", found_mac], capture_output=True, text=True, timeout=12)
        conn_out = (conn_res.stdout or "") + " " + (conn_res.stderr or "")
        logger.info("bluetoothctl connect output: %s", conn_out.strip())
    except Exception as e:
        logger.warning("Warning connecting Joy-Con [%s]: %s", found_mac, e)

    # 7. Ensure permissions on newly spawned /dev/hidraw nodes
    try:
        subprocess.run("sudo chmod 666 /dev/hidraw*", shell=True, capture_output=True, timeout=3)
    except Exception as e:
        logger.debug("chmod /dev/hidraw* result: %s", e)

    # 8. Verify device state via bluetoothctl info
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
    ok, message = pair_joycon(target)
    print(f"Result: {ok} -> {message}")
    sys.exit(0 if ok else 1)
