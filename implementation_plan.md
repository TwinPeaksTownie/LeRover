# Implementation Plan: Resilient Drivetrain Serial Pipeline & Immediate Nudge Dispatch

## 1. Objective & Architectural Rationale
Eliminate microcontroller USB buffer stalls and eradicate the brittle serial port tear-down in `rover/rover_controller.py` without synthetic USB bus power-cycling (`usbreset`/`uhubctl`) and without altering operator-mandated safety architecture (Button A 2.0s hold, Button Y Emergency Stop, Button B AUX/Voice). Provide immediate 0 ms response on steering nudges via event-driven wakeups while reducing steady-state packet volume to 15 Hz.

---

## 2. Step 1: Single Source of Truth — Universal JSON Configuration
Before touching any Python or CircuitPython source code, update `config/rover_config.json`:

```json
{
  "pwm": {
    "neutral_pulse_us": 1500,
    "min_pulse_us": 1000,
    "max_pulse_us": 2000,
    "max_pulse_offset": 175,
    "max_speed_pct": 35
  },
  "control": {
    "command_timeout_sec": 0.30,
    "accel_time_sec": 2.0,
    "decel_time_sec": 0.5,
    "steering_trim": 0.05,
    "speed_step_pct": 5,
    "min_speed_pct": 0,
    "max_speed_pct_limit": 100,
    "loop_rate_hz": 15
  },
  "hardware_interface": {
    "assert_dtr": true,
    "assert_rts": true,
    "serial_timeout_sec": 0.01,
    "write_timeout_sec": 0.25,
    "max_consecutive_write_failures": 5
  },
  "distance_sensor": {
    "model": "goBILDA_3111_0001_0001",
    "analog_pin": "A3",
    "adc_resolution_bits": 16,
    "max_volts": 3.3,
    "max_distance_mm": 1000.0,
    "update_rate_hz": 10
  }
}
```

### JSON Modifications Summary:
1. `loop_rate_hz`: Reduced from 25 Hz to 15 Hz (66.6 ms per frame). Gives CircuitPython ample headroom for its 20–30 ms garbage collection cycles.
2. `write_timeout_sec`: Reduced from 1.0s to 0.25s to prevent blocking the thread when the bus is unresponsive.
3. `max_consecutive_write_failures`: Explicit parameter (5 attempts) before declaring the serial link dead, preventing instantaneous teardown on a single transient buffer hiccup.

---

## 3. Step 2: Pi Host Resilient Serial Driver (`rover/rover_controller.py`)
1. **Load Configuration Keys**: Direct bracket indexing `self.config["hardware_interface"]["max_consecutive_write_failures"]`.
2. **Transient Error Resilience**:
   - Track `_consecutive_write_errors: int`.
   - On `serial.SerialTimeoutException` or write failure:
     - Increment error counter.
     - Call `ser.reset_output_buffer()`.
     - Log a warning with attempt count.
     - Do NOT call `ser.close()`. Allow the loop to continue and retry on the next tick.
   - Only if `_consecutive_write_errors >= max_consecutive_write_failures` (over ~0.5s of persistent failure), log an error, cleanly close the port, and transition to reconnecting state.
   - On successful write, reset `_consecutive_write_errors = 0`.
3. **Continuous Inbound Drain**:
   - Always drain `ser.in_waiting` into `rx_buf` at the start of each iteration to prevent the KB2040's `print(stat_line)` output buffer from ever filling up on the microcontroller.
4. **Immediate Nudge Dispatch (Event-Driven Wakeup)**:
   - Add a `threading.Event()` named `self._drive_event`.
   - In `set_drive(x, y)`: if `abs(x - self._target_x) > 0.02` or `abs(y - self._target_y) > 0.02`, set `self._drive_event.set()`.
   - In `_uart_loop`: replace `time.sleep(sleep_time)` with `self._drive_event.wait(timeout=sleep_time)` and clear the event.
   - **Result**: A thumbstick nudge instantly triggers a packet within <1 ms, while cruising straight or idling runs smoothly at 15 Hz.

---

## 4. Step 3: Microcontroller Firmware Buffer Hygiene (`rover/firmware_kb2040/code.py`)
1. **Input Buffer Bound**:
   - Limit `cmd_buf` to 128 bytes (`cmd_buf = cmd_buf[-64:]` if length exceeds 128) to prevent memory ballooning if malformed packets are received.
2. **Non-Blocking Telemetry Write**:
   - In `print(stat_line, end="")`, verify `usb_cdc.console.connected` before writing over USB CDC, ensuring the board never stalls if the host is offline.

---

## 5. Step 4: Strict Contract & Scope Enforcement
1. **Button Architecture Remains Intact**:
   - Button A (hold 2.0s with stick centered): Arms `ROVER` teleop mode.
   - R Trigger: Throttle forward.
   - ZR Trigger: Throttle reverse.
   - Stick X: Steering left/right.
   - SR / SL: Speed step +5% / -5%.
   - Button Y: Emergency Stop (neutralizes PWM, stops teleop app, releases lock).
   - Button B: Tap switches to AUX mode (Servos 7 & 8); hold 2.0s launches voice assistant (`listener_app`).
2. **Zero False Tri-States (Rule 13 Compliance)**:
   - Drivetrain state remains strictly binary: `is_armed: True` vs `is_armed: False`.
   - Hardware connection remains binary: `Connected` vs `Disconnected`.
   - No synthetic watchdog restart cycles, no uhubctl power cycling, and no intermediate unverified states.

---

## 6. Verification State Machine
- **Gate 1 Audit**: Submit this plan to `auditor.query_plan_review()` to ensure zero Rule 13 violations, strict bracket indexing, and contract compliance.
- **State 1 (Pipeline Continuity & Target Deployment)**: Deploy updated JSON and Python files to `/home/carson/touch_ui/` on Pi 4B (`192.168.0.86`).
- **State 2 (Dynamic Variance & Motion Cycle)**: Run unit tests in `tests/test_rover_controller.py` verifying rate limiting, consecutive failure recovery, and immediate nudge dispatch.
- **State 3 (Live Telemetry & Physical Sampling)**: Test 100 serial writes across the live USB CDC connection on `/dev/ttyACM0` with zero timeouts or stalls.
- **State 4 (Log Audit & Parity)**: Verify clean `backend.service` logs with zero `Write timeout` exceptions.
- **Gate 2 Audit**: Execute `query_adversarial_review()` on final diff.
