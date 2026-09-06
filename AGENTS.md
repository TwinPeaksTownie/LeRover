# Core Operating Protocols & Human Partnership

### 1. Human Partnership & Direct Communication
- **Direct, Plain Answers**: Answer the exact question asked directly and clearly. State technical facts, empirical findings, and concrete choices in natural, flowing language.
- **Adaptive Execution**: When corrected, identify the root cause and adjust execution immediately.
- **Actionable Reporting**: State what changed, why an approach failed, and the exact operational steps to take next.

### 2. Instruction-Gated Execution Protocol
- **Exploratory & Diagnostic Mode**: When asked exploratory, conceptual, or diagnostic questions, provide technical explanations in plain language.
- **Planning Mode & Gate 1 Build Plan Audit**: When designing architectural changes or non-trivial implementations, formulate `implementation_plan.md` and submit it to **Gate 1 (Build Plan Audit)**.
  - **Step 1 of Every Plan Must Be the JSON Schema**: Identify the exact JSON file on disk where new settings, modes, or thresholds belong, and document the JSON edits before writing any Python code.
  - The plan must pass Gate 1 (verifying zero false tri-states, fail-fast schema compliance, and scope containment with deployment checks disabled) before requesting operator approval.
- **Imperative Execution Mode**: Execute file writes, refactors, and deploy scripts only when given explicit commands (`fix`, `implement`, `edit`, `deploy`, `run`, `refactor`).

### 3. Single Source of Truth & Universal JSON Taxonomy
- **Universal JSON Storage**: Every runtime parameter, mode, and threshold must live in its designated JSON file on disk:
  - **Motor Limits & Offsets**: `follower.json` (servos 1–6) and `calibration_aux.json` (servos 7–8).
  - **Network & Topology Modes**: `config/network_config.json` (`topology_mode`, host IPs, ports).
  - **App Metadata & Settings**: `apps/<app_name>/config.json` and `manifest.json`.
  - **Audio & Dance Sequences**: `config/audio_files.json`, `presets_dance.json`, and sequence files.
- **Startup In-Memory Resolution**: Load required JSON files once into memory at process startup. Access all values using direct bracket indexing (`config["key"]`).
- **Dynamic In-Memory Arithmetic**: Calculate all spatial offsets, ticks, and safety clamping dynamically in memory against loaded calibration structures.

### 4. Separate Motion Synthesis from Runtime Execution
- **Compile Upfront**: Pre-calculate choreography, beat-alignment, and motion curves during the compilation pass and save them into JSON sequence files.
- **Deterministic 50 Hz Playback Engine**: Live playback executes keyframe interpolation, joint safety clamping, and serial dispatch to `/dev/ttyACM0`.

### 5. Mandatory Verification State Machine & Two-Gate Review
Every task must transition sequentially through two audit gates and four verification states:
- **Gate 1 (Build Plan Audit - Pre-Execution)**: Ornith audits `implementation_plan.md` against chronological operator directives for Rule 13 (Anti-Slop / False Tri-States), Rule 1 (Fail-Fast), and Rule 3 (Dynamic Calibration). Physical deployment checks are disabled (`check_deployments=False`).
- **State 1 (Pipeline Continuity & Target Deployment)**: Trace pipeline continuity, sync modified files to physical target directory (`/home/user/so101/pi500/` or `/home/carson/touch_ui/`), and restart host processes.
- **State 2 (Dynamic Variance & Motion Cycle)**: Execute a complete bidirectional motion/workload cycle ($Origin \rightarrow Target\,A \rightarrow Target\,B \rightarrow Origin$) under live application conditions, verifying target coordinates dynamically vary across timestamps.
- **State 3 (Live Telemetry & Physical Sampling)**: Sample live encoder telemetry and socket streams across checkpoints (e.g. 5s, 25s, 50s) to prove physical servos reached commanded coordinates without serial timeouts.
- **State 4 (Log Audit & Hardware Parity)**: Query daemon logs (`journalctl`) to verify zero unhandled exceptions, serial timeouts, or bounding errors occurred.
- **Gate 2 (Deployment Audit - Post-Execution)**: Ornith executes final adversarial review over the live git diff, remote MD5 parity (`check_deployments=True`), and daemon log cleanliness, announcing the spoken verdict aloud.

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
- **Direct Bracket Indexing Only**: Access dictionary values strictly with `dict["key"]`. If an expected key is missing, allow Python to raise an immediate `KeyError`. Never use `.get(key, default)` or `dict.get(key) or fallback`.
- **Upfront Payload Gate**: In HTTP, WebSocket, and ZeroMQ handlers, validate incoming client payloads with an explicit check at the top of the function:
  ```python
  for key in ["action", "speed"]:
      if key not in req_data:
          self.send_error(400, f"Missing required parameter: '{key}'")
          return
  ```
- **Loud Hardware Failure**: Raise immediate, descriptive exceptions (`KeyError`, `FileNotFoundError`, HTTP 500) with exact field names when hardware reads, network telemetry, or data parsing fail. Never mask an unreadable state with an inline fallback.

### 7. Musical Choreography Terminology
- Model and describe all choreography timelines strictly using concrete musical divisions: `measures`, `beats`, `4bars`, and `8bars`.

### 8. Anti-Slop, False Tri-States & Aesthetic Symmetry (Rule 13)
- Scrutinize state machines, options, and logic paths proposed in threes.
- Reject synthetic third states fabricated to satisfy LLM "rule of three" aesthetic balance. If a binary condition (`APPROVED` vs `BLOCKER`, `True` vs `False`) solves the problem, proposing a third state is forbidden.

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
