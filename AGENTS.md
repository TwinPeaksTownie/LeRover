# Core Operating Protocols & Human Partnership

### 1. Human Partnership & Direct Communication
- **Direct, Plain Answers**: Answer the exact question asked directly and clearly. State technical facts, empirical findings, and concrete choices in natural, flowing language.
- **Adaptive Execution**: When corrected, identify the root cause and adjust execution immediately.
- **Actionable Reporting**: State what changed, why an approach failed, and the exact operational steps to take next.

### 2. Instruction-Gated Execution Protocol
- **Exploratory & Diagnostic Mode**: When asked exploratory, conceptual, or diagnostic questions, provide technical explanations in plain language.
- **Imperative Execution Mode**: Execute file writes, refactors, and deploy scripts only when given explicit commands (`fix`, `implement`, `edit`, `deploy`, `run`, `refactor`).

### 3. Single Source of Truth & Calibration Resolution
- **Runtime JSON Calibration Resolution**: Load motor limits and neutral poses strictly into memory from disk at startup:
  - Follower Arm Servos 1–6: Read from `follower.json` (`calib_min`, `calib_max`, `homing_offset`).
  - Auxiliary Actuators Servos 7–8: Read from `calibration_aux.json`.
  - Dance Poses: Read from `presets_dance.json`.
- **Dynamic In-Memory Arithmetic**: Calculate all spatial offsets, ticks, and safety clamping dynamically in memory against loaded calibration structures.

### 4. Separate Motion Synthesis from Runtime Execution
- **Compile Upfront**: Pre-calculate choreography, beat-alignment, and motion curves during the compilation pass and save them into JSON sequence files.
- **Deterministic 50 Hz Playback Engine**: Live playback executes keyframe interpolation, joint safety clamping, and serial dispatch to `/dev/ttyACM0`.

### 5. Mandatory Verification State Machine
Every task must transition sequentially through four explicit verification states before concluding:
1. **State 1 (Pipeline Continuity)**: Trace and prove the downstream consumer explicitly reads and unmarshals the exact keys sent by the producer.
2. **State 2 (Dynamic Variance)**: Verify that target coordinates dynamically vary across timestamps (e.g. proving stances transition across distinct poses rather than locking in place).
3. **State 3 (Live Telemetry & Physical Sampling)**: Sample live hardware encoder telemetry at multiple timeline checkpoints (e.g. 5s, 25s, 50s) to prove physical servos reached commanded coordinates.
4. **State 4 (Log Audit)**: Query daemon logs (`journalctl`) to verify zero unhandled exceptions, serial timeouts, or bounding errors occurred.

---

# Operational Protocols

### 1. Telemetry & Hardware State Verification
- Inspect physical reality, active processes (`ps aux`), port locks, and serial telemetry before diagnosing hardware state.

### 2. Normalized Percentage Joint Mapping
- Calculate joint motion using `(pos - min) / (max - min)` aligned around calibrated midpoints across both arms.

### 3. Serial Bus Hygiene & Isolation
- Terminate background processes holding `/dev/ttyACM0` before running direct serial scripts.
- Flush UART software buffers and use blocking reads with explicit timeouts.
- When serial timeouts occur on `/dev/ttyACM0`, check process locks and query downstream devices to verify electrical pass-through continuity.

### 4. Target Deployment Protocol
- Sync modified files to the target devices (`/home/user/so101/pi500/` on Pi 500 or `/home/carson/touch_ui/` on Pi 4B) immediately after local edits.
- Restart target services (`backend.service`, `touchscreen.service`) and verify endpoint status before declaring a fix deployed.

### 5. Remote Process Management
- Issue explicit process termination commands (`pkill -9 -f <script>`) over SSH to prevent orphaned background jobs on remote nodes.

### 6. Strict Fail-Fast Schema & Contract Enforcement
- Parse explicitly defined keys from payloads.
- Raise immediate, descriptive exceptions (`KeyError`, `FileNotFoundError`, HTTP `400 Bad Request` / `500 Internal Error`) with exact field names when reads or payload parsing fail.

### 7. Musical Choreography Terminology
- Model and describe all choreography timelines strictly using concrete musical divisions: `measures`, `beats`, `4bars`, and `8bars`.

---

# System Topology & Entity Reference

### Entity Mapping
- **I**: The AI assistant taking actions.
- **You**: The human operator and architect.
- **Pi 500 (`192.168.0.130`)**: Follower arm driver & teleop host on `/dev/ttyACM0` (external 12V power).
- **Pi 4B (`192.168.0.86`)**: Touchscreen UI backend (`backend.service` on port `8082` at `/home/carson/touch_ui/server.py`) and physical display client (`touchscreen.service`).
- **Mac Mini (`192.168.0.149` / `mac-mini.local`)**: Leader arm telemetry API host (`8086`) and neural audio analysis server.
- **Follower Arm / Servos 1–8**: Physical 6-DOF arm and auxiliary actuators.

### Active Goal
- **Synchronized Range-Normalized Teleoperation & Choreography**: Calibrate and align leader and follower arms using normalized percentage mapping derived from empirical joint calibration bounds and midpoints.
