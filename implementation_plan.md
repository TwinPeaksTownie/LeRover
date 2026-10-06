# Implementation Plan: Joy-Con Architecture Decoupling

## Phase 1: JSON Schema & Configuration Strictness
- **Target File:** `apps/joycon_app/config.json`
- **Schema Impact:** No changes to the JSON schema. All existing thresholds (`deadzone`, `a_hold_sec`, `shake_threshold_g`) remain intact.
- **Path Resolution:** Eliminate hardcoded `/home/carson/touch_ui/...` fallback paths. We will enforce strict `Path(__file__).resolve().parent.parent` mechanics to load configurations relative to the workspace root.

## Phase 2: Hardware Driver Extraction (`pi4b/joycon_driver.py`)
- **Action:** Extract the raw `/dev/hidraw` logic out of `JoyConService`.
- **Implementation:** Create a pure `JoyConDriver` class that handles the 49-byte initialization subcommands (`0x40`, `0x03`, `0x30`) and parses incoming 0x30/0x3F byte arrays into a structured, typed `JoyConState` dataclass (timestamp, buttons, stick axes, IMU).
- **Rule Enforcement:** Zero external dependencies on apps, `RoverController`, or web servers.

## Phase 3: Temporal & Gesture Engine (`pi4b/joycon_gestures.py`)
- **Action:** Abstract all button duration math and chord detection.
- **Implementation:** Create a `GestureEngine` that consumes the `JoyConState` dataclass at 60 Hz. It will track start times for holds (e.g., A/B for 2.0s), compute double-tap intervals, and run the IMU shake detection math.
- **Output:** Emits discrete semantic events (e.g., `BUTTON_A_HOLD_COMPLETE`, `CHORD_ABORT_TRIGGERED`).

## Phase 4: The Background Daemon (`pi4b/joycon_service.py`)
- **Action:** Refactor `JoyConService` to act strictly as the orchestrator and IPC provider.
- **Implementation:**
  - Instantiates `JoyConDriver` and feeds data into `GestureEngine`.
  - Handles BlueZ auto-pairing and OS-level Bluetooth management.
  - Maintains atomic writes to `/dev/shm/joycon_telemetry.json`.
  - Exposes a robust pub/sub callback system for applications to register for specific events.

## Phase 5: App Logic Consolidation (`apps/joycon_app/app.py`)
- **Action:** Strip `app.py` down to *just* the `JoyConApp` class.
- **Implementation:**
  - Removes all references to `listener_app` internal states (breaking the tight coupling).
  - Replaces raw `threading.Thread().start()` spams for audio/chimes with a controlled `concurrent.futures.ThreadPoolExecutor(max_workers=2)`.
  - Subscribes to the `JoyConService` IPC events and drives the `RoverController` directly when the app is active and armed.
