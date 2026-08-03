# 🚨 HANDOFF DOCUMENT: POKÉBALL PLUS BLE CONNECTION

> [!CAUTION]
> ### 🛑 STRICT BOUNDARY WARNING FOR THE NEXT AGENT
> **DO NOT TOUCH, MODIFY, OR REFACTOR THE GANTRY, SPINNER, OR `aux_daemon.py`!**
> * The Gantry (Motor 8) and Pedestal (Motor 7) hardware interface, REST API endpoints (`/api/status`, `/api/nudge_physical`, `/api/move`, `/api/sync_position`), relative step delta calculations (`delta = target_acc - curr`), and dynamic trajectory duration locks (`moving_until`) are **100% WORKING, TESTED, AND VERIFIED**.
> * Motor 8 software position state is calibrated and synced at **`4800` (Max Right)**.
> * **THIS TASK IS ENTIRELY A POKÉBALL PLUS BLE CONNECTION ISSUE.** Do not make changes to any motor control logic or daemon code outside of Poké Ball BLE connectivity.

---

## 1. System Context & Hardware Overview

| Component | Target IP / Device | Details |
| :--- | :--- | :--- |
| **Auxiliary Daemon (`aux_daemon.py`)** | `192.168.0.130:8085` (Pi 500) | Servo motor control daemon over `/dev/ttyACM0` (Motor 7 & Motor 8). **DO NOT MODIFY.** |
| **Poké Ball Driver (`pokeball_teleop_driver.py`)** | `192.168.0.130` (Pi 500) | BLE client script for Poké Ball Plus controller. |
| **Poké Ball Controller MAC** | `58:2F:40:8D:50:71` | Bluetooth Low Energy (BLE) peripheral MAC address. |
| **Touch UI Server (`touch_ui_server.py`)** | `192.168.0.86:8082` (Pi 4B) | Touchscreen control panel. Serves UI and controls Poké Ball process lifecycle. |

---

## 2. Work Completed & Recent Fixes

1. **PyZMQ Socket Thread Lock Fix**:
   - Fixed a C++ libzmq assertion crash (`Assertion failed: pfd.revents & POLLIN`) in `pokeball_teleop_driver.py` by adding `self.zmq_lock = threading.Lock()` around ZMQ REQ socket operations.
   - Deployed updated driver to `/home/user/pokeball_teleop_driver.py` on Pi 500 (`192.168.0.130`).

2. **Daemon & Hardware Stability**:
   - `aux_daemon.py` on Pi 500 is running cleanly and serving `/api/status`.
   - Web UI on Port 8085 (`http://192.168.0.130:8085/`) serves `static/gantry_ui.html`.

---

## 3. Current Issue & Diagnostic State

* **Problem**: The Poké Ball Plus controller (`58:2F:40:8D:50:71`) is failing to pair / connect over BLE with Pi 500.
* **Current Log Output (`/home/user/pokeball.log` on Pi 500)**:
  ```text
  2026-08-03 11:00:46,309 [INFO] Connecting to Poké Ball Plus at 58:2F:40:8D:50:71...
  2026-08-03 11:00:52,311 [INFO] Poké Ball BLE waiting for device (press button to wake up)... [Device with address 58:2F:40:8D:50:71 was not found.]
  ```

---

## 4. Next Agent Action Items (Poké Ball BLE Focus Only)

1. **Check Bluetooth Adapter & BlueZ Stack on Pi 500**:
   - Run `bluetoothctl show` and `bluetoothctl devices` via SSH to verify `hci0` radio status.
   - Check if `58:2F:40:8D:50:71` is paired or cached in bluetoothctl:
     ```bash
     bluetoothctl info 58:2F:40:8D:50:71
     ```
2. **Trigger BLE Scanning**:
   - Run `bluetoothctl scan on` or `hcitool lescan` on Pi 500 while pressing the top red button (Button B) or white stick (Button A) on the Poké Ball controller to check if advertising packets are seen.
3. **Re-Pairing / Trusting Device**:
   - If needed, remove and re-pair/trust the device in `bluetoothctl`:
     ```bash
     bluetoothctl remove 58:2F:40:8D:50:71
     bluetoothctl scan on
     # (press Poké Ball button)
     bluetoothctl trust 58:2F:40:8D:50:71
     bluetoothctl connect 58:2F:40:8D:50:71
     ```

---

## 5. Strict Behavioral Rules for Future Sessions
* **Rule 1**: Do NOT report on Motor 7 telemetry or status unless specifically requested by the user.
* **Rule 2**: NEVER execute motor movement commands without explicit user permission.
* **Rule 3**: Do NOT modify `aux_daemon.py`, `aux_servo_controller.py`, or `gantry_state.json`.
