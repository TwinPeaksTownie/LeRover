# Auxiliary Servo Interface (`aux_servo_interface`)

Web control dashboard, low-level serial driver, and dead-reckoning positioning architecture for Feetech STS3215 auxiliary servos (Motor 7 Pedestal & Motor 8 LeSlider Traversing Rail).

---

## 📐 System Architecture & Hardware Topology

```
+-----------------------------------------------------------------------+
|  Web Dashboard (static/gantry_ui.html)                               |
|  - Real-time HTML5 Canvas visualizer                                  |
|  - Live telemetry polling (:8085/api/status)                          |
+-----------------------------------------------------------------------+
                                   |
                                   v
+-----------------------------------------------------------------------+
|  HTTP Web Server (pc_gantry_spinner_web.py)                            |
|  - Dead-reckoning multi-turn position accumulation                    |
|  - Strict software safety bounds enforcement [3, 4800]                 |
|  - State persistence (calibration_aux.json, gantry_state.json)       |
+-----------------------------------------------------------------------+
                                   |
                                   v
+-----------------------------------------------------------------------+
|  Serial Protocol Driver (aux_servo_controller.py)                    |
|  - Direct 12-bit raw tick control (0-4095)                            |
|  - Mutex-locked serial bus access (/dev/ttyACM0 @ 1,000,000 baud)     |
|  - Feetech STS3215 Mode 3 (Multi-Turn Step Mode) configuration        |
+-----------------------------------------------------------------------+
```

---

## ⚙️ Servo Mapping & Modes

| Servo ID | Component Name | Description | Control Mode | Valid Position Range |
| :---: | :--- | :--- | :---: | :---: |
| **Motor 7** | **LeSpinner** | Slew bearing rotating pedestal | Single-Turn (Mode 0) | `0` to `4095` ticks ($-165^\circ$ to $+165^\circ$) |
| **Motor 8** | **LeSlider** | 2040 V-slot rack & pinion linear rail | Multi-Turn (Mode 3) | `3` (MAX LEFT) to `4800` (MAX RIGHT soft stop) |

> ⚠️ **Safety Hardstop Notice:** Motor 8 mechanical end contact occurs at `4900` ticks. Software limits are hard-clamped at `4800` ticks in `pc_gantry_spinner_web.py` to ensure a mandatory 100-tick safety buffer.

---

## 🚀 Quick Start

### 1. Run Web Controller Locally or on Pi
```bash
python3 pc_gantry_spinner_web.py
```
Access the dashboard at `http://localhost:8085`.

### 2. Deploy Script & Calibration to On-Board Pi
```bash
python3 upload_to_pi.py
```

---

## 📡 Web API Endpoints

- `GET /api/status`: Returns live servo positions, torque state, connected serial port, and calibration metadata.
- `POST /api/move`: Send absolute target ticks (`{"id": 8, "target": 2503}`).
- `POST /api/nudge_physical`: Move relative ticks (`{"id": 8, "direction": "right", "amount": 50}`).
- `POST /api/sync_position`: Lock in physical alignment tick (`{"id": 8, "pos": -3}`).
- `POST /api/torque`: Toggle torque holding state (`{"id": 8, "enable": true}`).
- `POST /api/calibration`: Save updated bounds to `calibration_aux.json`.

---

## 🛠️ Repository Structure

- `aux_servo_controller.py`: Low-level serial transceiver driver for Feetech STS3215 servos.
- `pc_gantry_spinner_web.py`: Multi-threaded HTTP server & hardware state manager.
- `static/gantry_ui.html`: WebUI control interface.
- `calibration_aux.json`: Servo travel limits and home position calibration file.
- `upload_to_pi.py`: Automated deployment script over SFTP/SSH.
