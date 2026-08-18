# LeRover: Distributed Robotics & Teleoperation Stack

A distributed robotic control architecture for the **Overlander-4 Differential Drive Rover**, **SO-101 6-DOF Robotic Arm**, and auxiliary degrees of freedom (**LeSlider Linear Gantry** & **LeSpinner Base Pedestal**).

The system enables synchronized low-latency leader-follower teleoperation, web-based motor calibration, touchscreen diagnostic kiosk control, and dual-mode handheld teleoperation via a Nintendo Poké Ball Plus controller.

---

## System Architecture & Node Topology

The system is distributed across three physical compute nodes communicating over local high-speed Ethernet and WiFi via ZeroMQ (ZMQ), HTTP REST, and Bluetooth Low Energy (BLE):

```
+-----------------------------------------------------------------------------------+
|                                  NETWORK TOPOLOGY                                 |
+-----------------------------------------------------------------------------------+

   +--------------------------+                      +--------------------------+
   |   Leader Arm Host        |                      |   Touchscreen Kiosk      |
   |   (Mac Mini)             |                      |   (Raspberry Pi 4B)      |
   |   IP: 192.168.0.2        |                      |   IP: 192.168.0.86       |
   |                          |                      |                          |
   |  * so101_leader_client   |                      |  * Gantry UI (800x480)   |
   |  * Joint Normalization   |                      |  * Touch UI Server :8082 |
   |  * ZMQ Teleop Publisher  |                      |  * PulseAudio Sound Svc  |
   +------------+-------------+                      |  * Rover Launcher Svc    |
                |                                    +------------+-------------+
                | ZMQ Port 5555                                   |
                | (Normalized Joints)                             | HTTP REST :8085
                |                                                 | (Commands & Telemetry)
                v                                                 v
   +----------------------------------------------------------------------------+
   |                      Follower Arm & Motion Controller                      |
   |                      (Raspberry Pi 500 @ 192.168.0.130)                    |
   |                                                                            |
   |   [ API Server :8085 ] <---> [ AppManager ] <---> [ RobotBackend HAL ]     |
   |                                      |                     |               |
   |        +-----------------------------+                     v               |
   |        | Managed Applications:                      /dev/ttyACM0 (1M Baud) |
   |        |  * TeleopControlApp (ZMQ Leader-Follower)         |               |
   |        |  * PokeballApp (Dual Aux/Rover BLE Teleop)        v               |
   |        |  * ServoStudioApp (Web Calibration UI)     [ Feetech STS Bus ]    |
   +------------------------------------------------------------+---------------+
                                                                |
                               +--------------------------------+-------------------------------+
                               |                                                                |
                               v                                                                v
                 +---------------------------+                                    +---------------------------+
                 |  SO-101 Follower Arm      |                                    |  Auxiliary Actuators      |
                 |  Motors 1-6 (STS3215)     |                                    |  Motor 7: Pedestal (Spin) |
                 +---------------------------+                                    |  Motor 8: Gantry (Slide)  |
                                                                                  +---------------------------+
```

### 1. Motion Controller & Master Host (Raspberry Pi 500 @ `192.168.0.130`)
* **Hardware Authority:** Serves as the single source of truth for physical motor states and bus connectivity over `/dev/ttyACM0`.
* **Core Daemon (`main.py`):** Runs the master orchestration process hosting the REST API (`api_server.py`), hardware abstraction layer (`robot_backend.py`), and the application lifecycle manager (`app_manager.py`).
* **Active Managed Applications:**
  * `TeleopControlApp`: High-frequency ZMQ subscriber receiving leader joint frames and translating them to calibrated follower ticks.
  * `PokeballApp`: BLE client receiving inputs from the Poké Ball Plus controller to operate auxiliary actuators and drivetrain.
  * `ServoStudioApp`: Standalone visual dashboard for individual servo testing, torque toggling, and joint limit calibration.

### 2. Touchscreen Kiosk UI & Router (Raspberry Pi 4B @ `192.168.0.86`)
* **Touch Controller:** Hosts the 800x480 touchscreen interface (`server.py` on port `8082`), displaying real-time joint positions, auxiliary slider controls, and app switching.
* **Audio Playback Pipeline (`audio_service.py`):** Proxies sound effects and voice synthesis to the local speaker via PulseAudio (`paplay`) without ALSA device lock contention.
* **Rover Process Manager (`rover_launcher.py`):** Starts, monitors, and stops standalone rover driver tasks over authenticated background channels.

### 3. Leader Arm Client (Mac Mini @ `192.168.0.2`)
* **Spatial Input Capture (`so101_leader_client.py`):** Reads joint angles from the 6-DOF Leader Arm over USB serial.
* **Range Normalization:** Translates physical ticks into percentage-based normalized ranges (`[-100.0, 100.0]` for joints 1–5, `[0.0, 100.0]` for gripper joint 6) and broadcasts frames over ZMQ socket `5555`.

---

## Actuator & Hardware Mapping

### Feetech Smart Bus Servos (`/dev/ttyACM0` @ 1,000,000 Baud)
All servos communicate via the half-duplex Feetech STS TTL serial protocol with 12-bit magnetic encoders (4096 steps / 360°):

| Motor ID | Physical Designation | Servo Model | Operating Mode | Function |
| :--- | :--- | :--- | :--- | :--- |
| **ID 1** | Arm Shoulder Pan | STS3215 | Position Mode | Base arm rotation |
| **ID 2** | Arm Shoulder Lift | STS3215 | Position Mode | Shoulder elevation |
| **ID 3** | Arm Elbow Flex | STS3215 | Position Mode | Forearm pitch |
| **ID 4** | Arm Wrist Flex | STS3215 | Position Mode | Wrist pitch |
| **ID 5** | Arm Wrist Roll | STS3215 | Position Mode | Wrist rotation |
| **ID 6** | Arm Gripper | STS3215 | Position Mode | End-effector pinch |
| **ID 7** | **LeSpinner** Pedestal | STS3512 | Multi-Turn / Position | 360° Rotating mounting base |
| **ID 8** | **LeSlider** Gantry | STS3512 | Multi-Turn / Position | Linear carriage rack-and-pinion |

### Overlander-4 Drivetrain Controller (KB2040 UART)
* **Microcontroller:** Adafruit KB2040 (RP2040) running CircuitPython / C driver connected to Raspberry Pi 500 GPIO UART.
* **Output:** 4-channel standard 50Hz RC PWM signals (`1000µs` reverse to `2000µs` forward, `1500µs` neutral).

---

## Poké Ball Plus Teleoperation & Safety Bridge

The `pi500/pokeball_app.py` module provides handheld teleoperation with dual operating modes and a strict safety bridge:

```
                  +----------------------------------------------+
                  |           POKEBALL CONTROL MODES             |
                  +----------------------------------------------+

          +--------------------------------------------------------------+
          |                      AUX MANIPULATOR MODE                    |
          |                                                              |
          |  * Top Button (B) + Stick L/R: Step Pedestal (-165° to +165°)|
          |  * Stick Click (A) + Stick L/R: Nudge Gantry Linear Rail     |
          |  * Hard Limit Ricochet: Audio alert on mechanical limits     |
          +------------------------------+-------------------------------+
                                         |
                       HOLD JOYSTICK CLICK (BUTTON A)
                               FOR 3.0 SECONDS
                                         |
                                         v
          +--------------------------------------------------------------+
          |                   ROVER DRIVE MODE (SAFETY)                  |
          |                                                              |
          |  1. STARTUP LOCKOUT (4.25s):                                 |
          |     * Mario Kart countdown audio plays (3.25s)               |
          |     * 1.0s safety buffer: Wheels strictly held at 1500µs     |
          |  2. DIFFERENTIAL DRIVE:                                      |
          |     * 12-bit Joystick maps to Steering (X) & Throttle (Y)    |
          |  3. INSTANT E-STOP:                                          |
          |     * Top Red Button (B) cancels immediately to Aux Mode     |
          |  4. INACTIVITY WATCHDOG:                                     |
          |     * Auto-cancels to Aux Mode if no input for 30s           |
          +--------------------------------------------------------------+
```

---

## Repository Structure

```
LeRover/
├── pi500/                      # Pi 500 Motion Controller Stack
│   ├── main.py                 # Master daemon & startup entry point
│   ├── api_server.py           # HTTP REST API server (:8085)
│   ├── app_manager.py          # Managed application lifecycle coordinator
│   ├── robot_backend.py        # Low-level hardware abstraction layer
│   ├── aux_servo_controller.py # Direct Feetech serial protocol driver
│   ├── teleop_control_loop.py  # ZMQ Leader-to-Follower control loop
│   ├── pokeball_app.py         # Poké Ball Plus BLE dual-mode application
│   ├── servo_studio_app.py     # Interactive servo calibration dashboard
│   ├── telemetry_proxies.py    # Hardware state caching & proxy helpers
│   └── power_manager.py        # Voltage monitoring & power protection
├── pi4b/                       # Pi 4B Touchscreen Kiosk & Media Router
│   ├── server.py               # Touchscreen Kiosk web server (:8082)
│   ├── api_gateway.py          # API forwarder & routing layer
│   ├── audio_service.py        # PulseAudio non-blocking playback engine
│   ├── telemetry_poller.py     # Background state polling service
│   ├── rover_launcher.py       # Standalone rover process supervisor
│   └── static/                 # Touchscreen frontend HTML5/JS assets
├── rover/                      # Overlander-4 Rover Control Package
│   ├── rover_controller.py     # KB2040 UART differential drive client
│   ├── simulate_pokeball_rover.py # BLE input test harness
│   ├── web_simulator.py        # Browser-based 2D canvas drive visualizer
│   └── scan_ble.py             # BLE beacon discovery utility
├── mac-mini/                   # Mac Mini Leader Arm Stack
│   ├── so101_leader_client.py  # Leader arm reader & ZMQ telemetry streamer
│   └── mac_daemon.py           # Remote process lifecycle supervisor
├── hardware/                   # Hardware Specifications & CAD Assets
│   ├── STS3512.md              # Feetech register map & electrical specs
│   └── caddx_ratel_2.step      # Camera mount CAD model
├── tools/                      # Version-Controlled Read-Only Diagnostic Utilities
│   ├── README.md               # Tool execution safety guidelines
│   └── read_bus_telemetry.py   # Read-only serial bus health scanner
└── .gitignore                  # Git exclusion rules (scratch/, caches, local configs)
```

---

## Core Operational & Safety Rules

1. **Pi 500 Source of Truth:** The Pi 500 (`192.168.0.130`) maintains exclusive authority over physical motor states. Upstream nodes must query live telemetry rather than caching or asserting unverified positions.
2. **Zero Runtime EEPROM Writes:** Register offsets (Registers 31, 32, 55) must never be written during runtime. All spatial centering, angle bounds, and homing calculations are calculated in software memory using `follower.json` and `calibration_aux.json`.
3. **Loud Failure Modes:** Code must raise explicit errors when telemetry reads fail. Never inject dummy defaults (e.g. `or 2048`) that could corrupt persistent calibration files.
4. **PulseAudio Audio Pipeline:** On the Pi 4B, all sound playback must be dispatched through `paplay` or default ALSA sinks to avoid resource locking with the desktop audio subsystem.

---

## Quickstart & Execution

### 1. Running the Motion Controller (Pi 500)
```bash
# SSH into Pi 500
ssh user@192.168.0.130

# Start the unified master daemon
cd /home/user/so101/pi500
python3 main.py
```

### 2. Running the Touchscreen Kiosk (Pi 4B)
```bash
# SSH into Pi 4B
ssh carson@192.168.0.86

# The kiosk runs automatically via touch-ui.service, or can be started directly:
cd /home/carson/touch_ui
python3 server.py
```

### 3. Launching Leader Arm Teleoperation (Mac Mini)
```bash
# SSH into Mac Mini
ssh user@192.168.0.2

# Stream leader arm motion
cd ~/so101/mac-mini
python3 so101_leader_client.py --ip 192.168.0.130 --port 5555
```

### 4. Running the Rover Web Simulator Locally
```bash
# Launch the browser-based rover canvas simulator
python -m rover.web_simulator
# Open http://127.0.0.1:8090 in your browser
```

---

## Special Thanks & Acknowledgments

* **Tom Mulder (Pollen Robotics)**: Fellow original Reachy Mini beta tester, whose deep wealth of robotic knowledge, hardware experience, and continuous encouragement of out-of-the-box thinking has supported this project every step of the way.
* **Binh Pham ([@pham-tuan-binh](https://github.com/pham-tuan-binh))**: Creator of **LeSlider**, the open-source 1-DOF linear travel gantry for the SO-101 robot arm. His work directly inspired the conceptual design and engineering of **LeSpinner** (the 360° rotating base pedestal), completing the auxiliary multi-degree-of-freedom workspace for this system.
* **Hugging Face & The LeRobot Community**: For pioneering open-source embodied AI robotics frameworks and the SO-101 arm platform.

---

## Maintenance & Attribution
Maintained by Carson ([@TwinPeaksTownie](https://github.com/TwinPeaksTownie)). Built for distributed robotics research, SO-101 arm teleoperation, and mobile manipulator experimentation.
