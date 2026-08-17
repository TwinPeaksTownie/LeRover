# Lessons Learned (`lessons_learned.md`)

> ⚠️ **Strict Edit Directive:** This file is a locked reference document. It can ONLY be edited when the user explicitly instructs to add or remove a lesson.

---

### Lesson 1: Pi 500 Servo Authority & Source of Truth
- **Physical Topology:** The Raspberry Pi 500 (`192.168.0.130`) controls the physical servos directly via serial bus board `/dev/ttyACM0`.
- **Source of Truth:** The Pi 500 is the ultimate source of truth for all hardware telemetry and motor states, including:
  - Auxiliary Gantry (Motor 8 LeSlider)
  - Pedestal Spinner (Motor 7 LeSpinner)
  - SO-101 Follower Arm Servos (Motors 1–6)

### Lesson 2: SSH Authentication & Privileged Command Execution (Pi 4B / Pi 500)
- **Password Authentication**: Standard system CLI `ssh` commands fail on target devices (e.g., Pi 4B `@ 192.168.0.86`) when default SSH keys are missing or unconfigured.
- **Paramiko Integration**: Always use Python `paramiko` SSH clients with explicit credentials (`carson` / `raspberry` on Pi 4B) or pass explicit password arguments.
- **Sudo Elevation**: Privileged commands (e.g., `sudo reboot`, `sudo systemctl`) hang non-interactively without TTY input. Use `echo <password> | sudo -S <command>` over authenticated Paramiko channels to execute root operations.

### Lesson 3: Custom System Services Prohibited Indefinitely
- **Service Prohibition**: Custom robot systemd services (`sewer_daemon.service`, `pokeball_teleop.service`, etc.) are explicitly prohibited indefinitely.
- **Explicit Execution**: All robot scripts, daemons, and drivers must be launched explicitly during testing or application start via direct process execution rather than background or boot-enabled systemd services.
- **Root Cause & Retries**: Multiple systemd services configured with aggressive auto-restart loops repeatedly competed for and locked `/dev/ttyACM0`, preventing clean process shutdown and testing. Consolidation into a single master process and enforcing explicit process execution eliminates service retry lock contention.

### Lesson 4: Response Structure & Actionable TLDR Design
- **Deliverable-First Communication**: Always lead with the practical outcome, fix status, and user-facing result first. Never dump raw terminal outputs, unparsed JSON payloads, or dense diagnostic logs without clear, plain-language framing.

### Lesson 5: Serial Communication & Physical Hardware Diagnostic Prohibition
- **Prohibition on Cable Disconnection Diagnosis**: NEVER diagnose a serial communication timeout (`0 bytes` / `NO_RESPONSE`) as a "disconnected cable" or "unpowered hardware" when LEDs or downstream bus devices are powered.
- **Pass-Through Topology Rule**: If any downstream motor on the serial bus (e.g., Motor 8) is responding, physical power and data lines passing through upstream motors (Motors 1–7) are physically intact.
- **Software Root Cause & Post-Power-Cycle Obligation**: Serial timeouts post-power-cycle or after EEPROM writes are caused by microcontroller mute states, `/dev/ttyACM0` port lock contention, un-flushed UART buffers, or baud mismatches. Agents must execute software buffer flushes, process lock checks, and multi-baud scans before drawing any diagnostic conclusions.


### Lesson 6: Mandatory Target Deployment & Verification Protocol
- **Local Edit Is Not Deployment**: Modifying code in local repository folders (`i:\aux_servo_interface\pi500\`) or running scratch scripts in `/tmp/` over SSH does NOT update production code on physical targets (`192.168.0.130`).
- **Forbidden False Claims**: Never claim a bug or issue is "fixed and deployed" until the modified codebase files have been explicitly SFTP'd/transferred to `/home/user/so101/pi500/` (or the corresponding target directory), master daemons/processes have been restarted, and live execution on the physical hardware has been verified.
- **Root Cause of Failed Fixes**: Modifying local files without uploading them to target hardware leaves the Raspberry Pi executing stale code from `/home/user/so101/pi500/`, causing previous fixes to silently fail while creating false claims of completion.

### Lesson 7: PulseAudio / ALSA Coexistence & Remote Workstation TTS Pipeline
- **PulseAudio Hardware Lock**: When PulseAudio is active on target devices (e.g., Pi 4B `@ 192.168.0.86`), direct hardware card access (`aplay -D plughw:4,0`) returns `Device or resource busy`. Always route audio through `paplay` or system default ALSA (`aplay -D sysdefault`) to proxy through PulseAudio safely.
- **Workstation TTS to Remote Playback**: Pocket TTS synthesized on the host PC (`http://127.0.0.1:8057/tts`) generates raw WAV binary payloads. To play speech output on remote hardware, SFTP the WAV file to `/tmp/` on the target Pi before triggering local sound playback via `paplay` or the `/api/play_sound` endpoint.

### Lesson 8: Strict Prohibition on Unprompted Code Mutations & Reactionary Editing
- **User Feedback Is Not Permission**: Never treat user commentary, opinions, or criticism (e.g. "i don't like it") as an implicit instruction or permission to edit code, rename variables, or deploy changes to target hardware.
- **Explicit Instruction Mandate**: Code edits, refactoring, and file writes must ONLY be performed when the user explicitly commands a specific code modification. If user intent is ambiguous or conversational, pause, ask for clarification, or respond directly in prose without executing file mutations.

### Lesson 9: Absolute Prohibition on Dummy Fallbacks, Fuzzy Schemas, and Calibration Bypasses
- **No Dummy Defaults**: NEVER inject dummy fallback default values (e.g., `or 3`, `or 2048`, `default_pos = ...`, `cached_pos`) into variable assignments, position sync routines, hardware API endpoints, or state updates when hardware/telemetry reads fail or state is uninitialized.
- **No Fuzzy Schema Guessing**: NEVER chain speculative dictionary key fallbacks (e.g., `req_data.get("audio_b64") or req_data.get("data_b64")...`) or swallow JSON decode errors (`try...except: req_data = {}`). Enforce a single canonical request contract and fail with HTTP 400 Bad Request if missing or malformed.
- **No Physical Calibration Bypasses**: NEVER hardcode motor range bounds (e.g., `EXPECTED_MOTOR_BOUNDS = (-100, 100)`) or search arbitrary fallback directories (e.g., HuggingFace cache paths) when calibration files are missing. All spatial normalization must consume the empirical `follower.json` calibration object loaded at runtime; if missing, raise an unrecoverable `FileNotFoundError`.
- **Enforce Loud Failure Modes**: If hardware state is uninitialized, missing, or unreadable, the system MUST fail loudly—returning explicit errors (e.g., HTTP 400/500 with descriptive message, `None` with `connected: False`, or raising exceptions) rather than masking failures with arbitrary numbers or cached states.
- **Corruption Risk**: Injecting dummy fallbacks into position calculation or state saving functions silently corrupts persistent calibration files (e.g., `gantry_state.json`), overriding calibrated physical baselines with arbitrary numbers on system restart.

### Lesson 10: `0bytes received TxRxResult: There is no status packet!` means a brief power disconnect occurred and requires the user to disconnect and reconnect the cable.









### Lesson 11: Hardware EEPROM Writes Prohibited & Mandatory JSON Calibration Loading
- **No EEPROM Writes**: NEVER call `set_position_offset()` or write to Register 31, 32, or 55 during runtime on Pi 500 (`192.168.0.130`).
- **No Hardcoded Ticks**: NEVER hardcode position ticks (e.g. `2048`) in code to set a motor's zero or center.
- **Use Calibration Files**: Motors 1–6 bounds and zeroes MUST be read from `follower.json` using exact keys (`calib_min`, `calib_max`, `homing_offset`). Motors 7–8 bounds MUST be read from `calibration_aux.json`.
- **Software Math Only**: Perform all position and tick calculations in memory using loaded JSON values.

