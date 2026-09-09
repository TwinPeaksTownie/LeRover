#!/usr/bin/env python3
"""apps/preset_app/app.py - PiranhaPoseApp (PresetApp) for SO-101.
Owns pose capture, preset JSON persistence, sequence discovery, and attack choreography.
Dispatches movement commands to RobotBackend and sound events to Pi 4B audio service.
"""

from __future__ import annotations

import json
import logging
import math
import os
import sys
import threading
import time
import urllib.request
from pathlib import Path
from typing import Optional, Dict, Any, Tuple, List, Union

from app_manager import BaseApp, AppMetadata
from robot_backend import RobotBackend, SERIAL_LOCK, pct_to_ticks_s7, ticks_to_pct_s7, degrees_to_ticks_s7

try:
    import network_resolver
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "pi4b"))
    import network_resolver

try:
    import audio_resolver
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "pi4b"))
    import audio_resolver

try:
    from rover.rover_controller import RoverController
except ImportError:
    try:
        from rover_controller import RoverController
    except ImportError:
        RoverController = None

APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "config.json"
PRESETS_DIR = APP_DIR / "presets"
SEQUENCES_DIR = APP_DIR / "sequences"


def load_preset_config() -> dict:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Missing required Preset config: {CONFIG_PATH}")
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


_CONFIG = load_preset_config()


def get_pi4b_sound_url() -> str:
    pi4b_ip = network_resolver.get_pi4b_ip(prefer_port=8082)
    return f"http://{pi4b_ip}:8082/api/play_sound"


def dispatch_audio_event(kind: str = "connect", wav_path: Optional[str] = None, stop_previous: bool = True, delay_sec: float = 0.0) -> None:
    """Dispatches sound playback event to Pi 4B audio service asynchronously."""
    sound_file = audio_resolver.get_audio_filename(kind)
    event_name = kind

    def _work():
        try:
            if delay_sec > 0:
                time.sleep(delay_sec)
            payload = json.dumps({
                "kind": sound_file,
                "event": event_name,
                "wav_path": wav_path or "",
                "stop_previous": stop_previous,
                "delay_sec": 0.0,
            }).encode("utf-8")
            req = urllib.request.Request(
                get_pi4b_sound_url(),
                data=payload,
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                pass
        except Exception as e:
            logging.exception("Failed to dispatch audio event '%s' (%s) to Pi 4B: %s", event_name, sound_file, e)
    threading.Thread(target=_work, daemon=True).start()


def get_presets_fpath(mode: str = "normal") -> Path:
    """Resolves partitioned preset file for specified mode ('normal', 'demo', 'angry')."""
    if not mode:
        raise ValueError("Mode parameter cannot be empty")
    clean_mode = str(mode).lower().strip()
    return PRESETS_DIR / f"presets_{clean_mode}.json"


def get_sequence_fpath(sequence_name: str) -> Path:
    """Resolves sequence JSON choreography file path."""
    name = str(sequence_name).strip()
    if not name.endswith(".json"):
        name = f"{name}.json"
    if not name.startswith("sequence_"):
        name = f"sequence_{name}"
    return SEQUENCES_DIR / name


class PiranhaPoseApp(BaseApp):
    metadata = AppMetadata(
        name=_CONFIG["name"],
        title=_CONFIG["title"],
        description=_CONFIG["description"],
        version=_CONFIG["version"],
        tags=_CONFIG["tags"],
        icon=_CONFIG["icon"],
    )

    def __init__(self, running_on_pi: bool = True, config: Optional[dict] = None) -> None:
        super().__init__(running_on_pi=running_on_pi)
        self.config = config or _CONFIG
        self.logger = logging.getLogger("so101.app.piranha_pose")
        self.last_saved_position: Optional[Dict[str, Any]] = None
        self._sequence_running = False
        self._sequence_stop_event = threading.Event()
        self.rover_ctrl: Optional[Any] = None

    def setup(self, backend: RobotBackend) -> None:
        self.logger.info("PiranhaPoseApp setup initialized.")

    def run(self, backend: RobotBackend, stop_event: threading.Event) -> None:
        self.logger.info("PiranhaPoseApp active and ready for pose capture/resume requests.")
        while not stop_event.is_set():
            time.sleep(0.5)

    def teardown(self, backend: RobotBackend) -> None:
        self.logger.info("PiranhaPoseApp teardown: ensuring torque is safely maintained.")
        self.stop_sequence()
        if self.rover_ctrl:
            try:
                self.rover_ctrl.shutdown()
            except Exception as e:
                self.logger.exception("Error shutting down rover controller in PiranhaPoseApp: %s", e)
            self.rover_ctrl = None
        try:
            backend.set_arm_torque(enable=True)
        except Exception as e:
            self.logger.exception("Teardown torque enable error: %s", e)

    # -------------------------------------------------------------------------
    # Preset & Pose Management
    # -------------------------------------------------------------------------

    def get_arm_presets(self, mode: str = "normal") -> Dict[str, Any]:
        """Loads and returns the presets dictionary for specified mode ('normal', 'demo', 'angry')."""
        fpath = get_presets_fpath(mode)
        if fpath.exists():
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                self.logger.exception("Failed to load presets from %s: %s", fpath, e)
                raise
        return {}

    def capture_temporary_arm_pose(self, backend: RobotBackend) -> Dict[str, Any]:
        """Captures live empirical normalized arm positions directly from bus,
        re-engages torque holding current pose, and stores in runtime memory as self.last_saved_position."""
        with SERIAL_LOCK:
            ser = None
            if backend.bus and hasattr(backend.bus, "port_handler"):
                ph = backend.bus.port_handler
                if hasattr(ph, "ser"):
                    ser = ph.ser
            if ser and hasattr(ser, "reset_input_buffer"):
                ser.reset_input_buffer()
                ser.reset_output_buffer()

            norm_dict = backend.bus.sync_read("Present_Position")
            raw_dict = backend.bus.sync_read("Present_Position", normalize=False)
            if not norm_dict or len(norm_dict) < 6:
                raise RuntimeError(f"Incomplete empirical hardware read from arm servos: {norm_dict}")

            # Re-engage torque holding current normalized positions so the arm does not sag
            if hasattr(backend.bus, "sync_write"):
                try:
                    backend.bus.sync_write("Goal_Position", norm_dict)
                except Exception as e:
                    self.logger.exception("sync_write Goal_Position during capture failed: %s", e)
                    raise
            if hasattr(backend.bus, "enable_torque"):
                backend.bus.enable_torque(num_retry=2)

            motor_ids = {
                "shoulder_pan": 1,
                "shoulder_lift": 2,
                "elbow_flex": 3,
                "wrist_flex": 4,
                "wrist_roll": 5,
                "gripper": 6,
            }
            with backend.lock:
                for k, v in norm_dict.items():
                    k_str = str(k)
                    sid = None
                    if k_str in motor_ids:
                        sid = motor_ids[k_str]
                    elif isinstance(k, int):
                        sid = k
                    if sid is not None and 1 <= sid <= 6:
                        backend.servos[sid]["normalized"] = float(v)
                        backend.servos[sid]["torque"] = True
                if raw_dict:
                    for k, v in raw_dict.items():
                        k_str = str(k)
                        sid = None
                        if k_str in motor_ids:
                            sid = motor_ids[k_str]
                        elif isinstance(k, int):
                            sid = k
                        if sid is not None and 1 <= sid <= 6:
                            backend.servos[sid]["raw"] = int(v)
                            backend.servos[sid]["pos"] = int(v)
                            backend.servos[sid]["connected"] = True

            # Capture Aux positions with dynamic hardware synchronization
            s7_pos = backend.servos[7]["pos"]
            if s7_pos is None:
                s7_pos = backend.sync_servo7_position()
            if s7_pos is None:
                s7_pos = backend.get_s7_center_ticks()

            s8_pos = backend.servos[8]["pos"]
            if s8_pos is None:
                s8_pos = backend.sync_servo8_position()
            if s8_pos is None:
                s8_bounds = backend.get_s8_bounds()
                s8_pos = s8_bounds[0]

            verify_norm = backend.bus.sync_read("Present_Position")
            if not verify_norm or len(verify_norm) < 6:
                raise RuntimeError("Bi-directional read-back parity verification failed for arm servos")

            raw_ticks = {}
            if raw_dict:
                for k, v in raw_dict.items():
                    if k in motor_ids:
                        sid_key = str(motor_ids[k])
                    else:
                        sid_key = str(k)
                    raw_ticks[sid_key] = int(v)

            new_pose = {
                "timestamp": time.time(),
                "normalized": {k: round(float(v), 2) for k, v in verify_norm.items()},
                "raw_ticks": raw_ticks,
                "aux": {
                    "7": int(s7_pos),
                    "8": int(s8_pos),
                }
            }
            self.last_saved_position = new_pose
            self.logger.info("[4-STATE VERIFIED: pose_capture] Live encoder telemetry: %s, aux: S7=%d, S8=%d",
                             new_pose["normalized"], s7_pos, s8_pos)
            return {
                "status": "ok",
                "action": "temporary_saved",
                "normalized": new_pose["normalized"],
                "raw_ticks": new_pose["raw_ticks"],
                "aux": new_pose["aux"],
            }

    def save_official_arm_preset(self, backend: RobotBackend, custom_name: Optional[str] = None, mode: str = "normal", overwrite: bool = False) -> Dict[str, Any]:
        """Permanently commits the runtime last_saved_position (or live capture) to mode-specific preset JSON."""
        if self.last_saved_position is None:
            self.capture_temporary_arm_pose(backend)

        pose_data = dict(self.last_saved_position)
        fpath = get_presets_fpath(mode)
        presets: Dict[str, Any] = {}
        if fpath.exists():
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    presets = json.load(f)
            except Exception as e:
                self.logger.exception("Failed to parse %s: %s", fpath, e)
                raise

        if custom_name:
            pose_name = custom_name
        elif overwrite:
            existing_indices = [int(k.split("_")[1]) for k in presets.keys() if k.startswith("pose_") and k.split("_")[1].isdigit()]
            max_idx = max(existing_indices, default=1)
            pose_name = f"pose_{max_idx}"
        else:
            existing_indices = [int(k.split("_")[1]) for k in presets.keys() if k.startswith("pose_") and k.split("_")[1].isdigit()]
            next_idx = max(existing_indices, default=0) + 1
            pose_name = f"pose_{next_idx}"

        presets[pose_name] = pose_data
        fpath.parent.mkdir(parents=True, exist_ok=True)
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump(presets, f, indent=2)

        self.logger.info("Committed official arm preset %s to %s: %s", pose_name, fpath, pose_data["normalized"])
        return {
            "status": "ok",
            "action": "preset_committed",
            "name": pose_name,
            "mode": mode,
            "normalized": pose_data["normalized"],
            "raw_ticks": pose_data["raw_ticks"],
            "aux": pose_data["aux"],
            "total_presets": len(presets),
        }

    def overwrite_arm_preset(self, backend: RobotBackend, preset_name: str, mode: str = "normal") -> Dict[str, Any]:
        """Directly overwrites a designated preset slot with the live held/captured pose from physical hardware."""
        if not preset_name:
            raise ValueError("Target preset_name is required for overwrite")

        self.capture_temporary_arm_pose(backend)
        pose_data = dict(self.last_saved_position)
        fpath = get_presets_fpath(mode)
        presets: Dict[str, Any] = {}
        if fpath.exists():
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    presets = json.load(f)
            except Exception as e:
                self.logger.exception("Failed to parse %s: %s", fpath, e)
                raise

        presets[preset_name] = pose_data
        fpath.parent.mkdir(parents=True, exist_ok=True)
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump(presets, f, indent=2)

        self.logger.info("Overwrote preset '%s' in mode '%s' on disk: %s", preset_name, mode, pose_data["normalized"])
        return {
            "status": "ok",
            "action": "preset_overwritten",
            "name": preset_name,
            "mode": mode,
            "normalized": pose_data["normalized"],
            "raw_ticks": pose_data["raw_ticks"],
            "aux": pose_data["aux"],
            "total_presets": len(presets),
        }

    def delete_arm_preset(self, preset_name: str, mode: str = "normal") -> Dict[str, Any]:
        """Deletes a preset from the mode JSON file."""
        fpath = get_presets_fpath(mode)
        if not fpath.exists():
            raise FileNotFoundError(f"Preset file {fpath} does not exist")
        with open(fpath, "r", encoding="utf-8") as f:
            presets = json.load(f)
        if preset_name not in presets:
            raise KeyError(f"Preset {preset_name} not found in {fpath}")
        del presets[preset_name]
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump(presets, f, indent=2)
        return {"status": "ok", "deleted": preset_name, "total_presets": len(presets)}

    def resume_last_arm_pose(self, backend: RobotBackend, duration: float = 1.0, steps: int = 40, mode: str = "normal") -> Tuple[bool, str]:
        """Resumes last_saved_position from runtime memory (or latest from mode presets) with smooth cosine interpolation."""
        target_norm = None
        target_name = "last_saved_position"

        if self.last_saved_position and "normalized" in self.last_saved_position:
            target_norm = self.last_saved_position["normalized"]
            target_name = "runtime last_saved_position"
        else:
            presets = self.get_arm_presets(mode=mode)
            if presets:
                pose_items = []
                for k, v in presets.items():
                    if k.startswith("pose_") and k.split("_")[1].isdigit():
                        pose_items.append((int(k.split("_")[1]), k, v))
                if pose_items:
                    pose_items.sort(key=lambda x: x[0])
                    target_name = pose_items[-1][1]
                    target_norm = pose_items[-1][2]["normalized"]
                else:
                    latest_key = list(presets.keys())[-1]
                    target_name = latest_key
                    target_norm = presets[latest_key]["normalized"]

        if not target_norm:
            return False, "No target pose found in memory or presets"

        ok, msg = backend.interpolate_arm_norm(target_norm, duration=duration, steps=steps)
        if ok:
            return True, f"Resumed {target_name} ({duration}s)"
        return False, msg

    def move_to_specific_arm_preset(
        self,
        backend: RobotBackend,
        preset_name: str,
        duration: float = 1.0,
        steps: int = 40,
        mode: str = "normal"
    ) -> Tuple[bool, str]:
        """Loads named preset from specified mode partition and executes smooth cosine trajectory interpolation."""
        presets = self.get_arm_presets(mode=mode)
        if not presets:
            return False, f"No presets found for mode '{mode}'"

        if preset_name not in presets:
            return False, f"Preset '{preset_name}' not found in mode '{mode}' (available: {list(presets.keys())})"

        if "normalized" not in presets[preset_name]:
            raise KeyError(f"Preset '{preset_name}' in mode '{mode}' missing required 'normalized' coordinates")

        target_norm = presets[preset_name]["normalized"]

        ok, msg = backend.interpolate_arm_norm(target_norm, duration=duration, steps=steps)
        if ok:
            self.logger.info("Moved arm to preset %s (mode=%s) smoothly over %.2fs", preset_name, mode, duration)
            return True, f"Moved to {preset_name} ({duration}s)"
        return False, msg

    # -------------------------------------------------------------------------
    # Choreography & Sequence Playback
    # -------------------------------------------------------------------------

    def list_sequences(self, mode: Optional[str] = None) -> List[Dict[str, Any]]:
        """Lists available sequence choreographies from apps/preset_app/sequences/."""
        seqs = []
        if SEQUENCES_DIR.exists():
            for p in SEQUENCES_DIR.glob("sequence_*.json"):
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        seq_mode = "demo"
                        if "mode" in data:
                            seq_mode = str(data["mode"])
                        if mode is None or seq_mode == mode or mode == "all":
                            seq_name = p.stem
                            if "name" in data:
                                seq_name = str(data["name"])
                            seq_title = p.stem
                            if "title" in data:
                                seq_title = str(data["title"])
                            seq_desc = ""
                            if "description" in data:
                                seq_desc = str(data["description"])
                            steps_list = []
                            if "steps" in data and isinstance(data["steps"], list):
                                steps_list = data["steps"]
                            seqs.append({
                                "name": seq_name,
                                "title": seq_title,
                                "description": seq_desc,
                                "mode": seq_mode,
                                "steps_count": len(steps_list),
                                "file": p.name,
                            })
                except Exception as e:
                    self.logger.exception("Error reading sequence %s: %s", p, e)
        return seqs

    def _drive_burst_helper(self, throttle: float = 0.85, duration_sec: float = 1.0) -> None:
        """Drives rover in a burst for duration_sec then cleanly commands stop."""
        ctrl = self.rover_ctrl
        if ctrl is None and RoverController is not None:
            rover_port = network_resolver.get_rover_serial_port()
            if not os.path.exists(rover_port):
                self.logger.warning("Rover hardware serial port '%s' not present (KB2040 unpowered). Skipping drive burst.", rover_port)
                return
            try:
                ctrl = RoverController(serial_port=rover_port, baudrate=network_resolver.get_rover_baudrate())
                ctrl.start()
                self.rover_ctrl = ctrl
            except Exception as e:
                self.logger.exception("Failed to start RoverController for drive burst: %s", e)
                raise RuntimeError(f"Failed to start RoverController on {rover_port}: {e}") from e

        if ctrl:
            try:
                ctrl.set_drive(0.0, -throttle)
                time.sleep(duration_sec)
                ctrl.set_drive(0.0, 0.0)
            except Exception as e:
                self.logger.exception("Rover drive burst helper error: %s", e)
                raise RuntimeError(f"Rover drive burst command failed: {e}") from e

    def _execute_arm_and_pedestal_sweep(
        self,
        backend: RobotBackend,
        start_s7_pct: float,
        end_s7_pct: float,
        target_arm_norm: Dict[str, float],
        duration_sec: float = 3.0,
        steps: int = 50,
        stop_event: Optional[threading.Event] = None,
    ) -> None:
        """Synchronously interpolates arm posture (Motors 1-6) and sweeps Servo 7 (pedestal) in lockstep under SERIAL_LOCK."""
        aux_calib = backend.aux_calibration
        with SERIAL_LOCK:
            if not backend.bus:
                return
            ser = None
            if hasattr(backend.bus, "port_handler"):
                ph = backend.bus.port_handler
                if hasattr(ph, "ser"):
                    ser = ph.ser
            if ser and hasattr(ser, "reset_input_buffer"):
                ser.reset_input_buffer()
            start_arm = backend.bus.sync_read("Present_Position")
            if not start_arm:
                raise RuntimeError("Failed to read initial arm positions before sweep")

        dt = max(0.01, duration_sec / float(steps))
        motor_keys = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"]

        for s in range(1, steps + 1):
            if stop_event and stop_event.is_set():
                return
            alpha = s / float(steps)
            smooth_alpha = 0.5 * (1.0 - math.cos(math.pi * alpha))

            arm_frame = {}
            for k in motor_keys:
                if k not in start_arm:
                    raise KeyError(f"Missing motor '{k}' in start_arm telemetry")
                s_val = float(start_arm[k])
                if k in target_arm_norm:
                    t_val = float(target_arm_norm[k])
                else:
                    t_val = s_val
                val = s_val + (t_val - s_val) * smooth_alpha
                arm_frame[k] = max(0.0, min(100.0, val))

            pct_s7 = start_s7_pct + (end_s7_pct - start_s7_pct) * smooth_alpha
            s7_tick = pct_to_ticks_s7(pct_s7, aux_calib)

            with SERIAL_LOCK:
                if backend.bus and hasattr(backend.bus, "sync_write"):
                    try:
                        backend.bus.sync_write("Goal_Position", arm_frame)
                    except Exception as e:
                        self.logger.exception("sync_write Goal_Position during sweep error: %s", e)
                        raise
                if backend.ctrl:
                    try:
                        backend.ctrl.write_goal_raw(7, s7_tick, speed=500)
                    except Exception as e:
                        self.logger.exception("write_goal_raw during sweep error: %s", e)
                        raise
                with backend.lock:
                    backend.servos[7]["pos"] = s7_tick
                    backend.servos[7]["raw"] = s7_tick % 4096
                    backend.servos[7]["normalized"] = round(float(pct_s7), 2)
                    backend.servos[7]["torque"] = True
                    backend.servos[7]["connected"] = True

            time.sleep(dt)

    def _execute_roar_pan_sweep(
        self,
        backend: RobotBackend,
        min_duration_sec: float = 1.0,
        home_duration_sec: float = 1.0,
        stop_event: Optional[threading.Event] = None,
        **kwargs: Any,
    ) -> None:
        """Synchronously sweeps Motor 1 (shoulder_pan) center(50%) -> right(100%) -> left(0%) -> center(50%) across 3.0s without bus contention."""
        with SERIAL_LOCK:
            if not backend.bus:
                return
            ser = None
            if hasattr(backend.bus, "port_handler"):
                ph = backend.bus.port_handler
                if hasattr(ph, "ser"):
                    ser = ph.ser
            if ser and hasattr(ser, "reset_input_buffer"):
                ser.reset_input_buffer()
            curr_norm = backend.bus.sync_read("Present_Position")
            if not curr_norm:
                raise RuntimeError("Failed to read arm positions before roar pan sweep")

        if "shoulder_pan" not in curr_norm:
            raise KeyError("Missing 'shoulder_pan' in curr_norm telemetry")
        start_pan = float(curr_norm["shoulder_pan"])
        steps_per_phase = 25
        dt = max(0.01, 1.0 / float(steps_per_phase))

        # Phase 1: start_pan -> 100.0% (Right limit)
        for s in range(1, steps_per_phase + 1):
            if stop_event and stop_event.is_set():
                return
            alpha = s / float(steps_per_phase)
            smooth_alpha = 0.5 * (1.0 - math.cos(math.pi * alpha))
            pan_val = start_pan + (100.0 - start_pan) * smooth_alpha

            frame = dict(curr_norm)
            frame["shoulder_pan"] = max(0.0, min(100.0, pan_val))

            with SERIAL_LOCK:
                if backend.bus and hasattr(backend.bus, "sync_write"):
                    try:
                        backend.bus.sync_write("Goal_Position", frame)
                    except Exception as e:
                        self.logger.exception("Sync write error in roar pan sweep phase 1: %s", e)
                        raise
            with backend.lock:
                backend.servos[1]["normalized"] = round(float(frame["shoulder_pan"]), 2)
            time.sleep(dt)

        # Phase 2: 100.0% -> 0.0% (Full sweep to Left limit)
        for s in range(1, steps_per_phase + 1):
            if stop_event and stop_event.is_set():
                return
            alpha = s / float(steps_per_phase)
            smooth_alpha = 0.5 * (1.0 - math.cos(math.pi * alpha))
            pan_val = 100.0 + (0.0 - 100.0) * smooth_alpha

            frame = dict(curr_norm)
            frame["shoulder_pan"] = max(0.0, min(100.0, pan_val))

            with SERIAL_LOCK:
                if backend.bus and hasattr(backend.bus, "sync_write"):
                    try:
                        backend.bus.sync_write("Goal_Position", frame)
                    except Exception as e:
                        self.logger.exception("Sync write error in roar pan sweep phase 2: %s", e)
                        raise
            with backend.lock:
                backend.servos[1]["normalized"] = round(float(frame["shoulder_pan"]), 2)
            time.sleep(dt)

        # Phase 3: 0.0% -> 50.0% (Return to Center)
        for s in range(1, steps_per_phase + 1):
            if stop_event and stop_event.is_set():
                return
            alpha = s / float(steps_per_phase)
            smooth_alpha = 0.5 * (1.0 - math.cos(math.pi * alpha))
            pan_val = 0.0 + (50.0 - 0.0) * smooth_alpha

            frame = dict(curr_norm)
            frame["shoulder_pan"] = max(0.0, min(100.0, pan_val))

            with SERIAL_LOCK:
                if backend.bus and hasattr(backend.bus, "sync_write"):
                    try:
                        backend.bus.sync_write("Goal_Position", frame)
                    except Exception as e:
                        self.logger.exception("Sync write error in roar pan sweep phase 3: %s", e)
                        raise
            with backend.lock:
                backend.servos[1]["normalized"] = round(float(frame["shoulder_pan"]), 2)
            time.sleep(dt)

    def execute_sequence(self, backend: RobotBackend, sequence_name_or_dict: Any, mode: str = "demo") -> Tuple[bool, str]:
        """Executes a multi-step sequence timeline from JSON definition."""
        if isinstance(sequence_name_or_dict, str):
            seq_path = get_sequence_fpath(sequence_name_or_dict)
            if not seq_path.exists():
                return False, f"Sequence file {seq_path} not found"
            try:
                with open(seq_path, "r", encoding="utf-8") as f:
                    seq_data = json.load(f)
            except Exception as e:
                return False, f"Failed to load sequence: {e}"
        elif isinstance(sequence_name_or_dict, dict):
            seq_data = sequence_name_or_dict
        else:
            return False, "Invalid sequence specification"

        seq_name = "unnamed_sequence"
        if "name" in seq_data:
            seq_name = str(seq_data["name"])
        if seq_name in ["sequence_attack", "attack_piranha_plant", "attack"]:
            return self.execute_attack_sequence(backend)

        self.stop_sequence()
        self._sequence_stop_event.clear()
        self._sequence_running = True

        try:
            center_s7 = backend.get_s7_center_ticks()
            steps = []
            if "steps" in seq_data and isinstance(seq_data["steps"], list):
                steps = seq_data["steps"]
            for idx, step in enumerate(steps):
                if self._sequence_stop_event.is_set():
                    return False, "Sequence aborted"

                if "step_name" in step:
                    sname = str(step["step_name"])
                else:
                    sname = f"step_{idx+1}"
                self.logger.info("[SEQUENCE %s] Running %s", seq_name, sname)

                # Audio trigger
                if "audio" in step and isinstance(step["audio"], dict):
                    audio = step["audio"]
                    kind = "connect"
                    if "kind" in audio:
                        kind = str(audio["kind"])
                    wav_path = None
                    if "wav_path" in audio:
                        wav_path = audio["wav_path"]
                    delay_sec = 0.0
                    if "delay_sec" in audio:
                        delay_sec = float(audio["delay_sec"])
                    stop_prev = True
                    if "stop_previous" in audio:
                        stop_prev = bool(audio["stop_previous"])
                    dispatch_audio_event(kind=kind, wav_path=wav_path, stop_previous=stop_prev, delay_sec=delay_sec)

                preset = None
                if "preset" in step:
                    preset = step["preset"]
                s7_pct = None
                if "servo7_pct" in step:
                    s7_pct = float(step["servo7_pct"])
                elif "servo7_deg" in step:
                    s7_pct = float(step["servo7_deg"]) * (50.0 / 90.0) + 50.0

                if preset and (s7_pct is not None):
                    arm_dur = 1.5
                    if "arm_duration" in step:
                        arm_dur = float(step["arm_duration"])
                    elif "duration" in step:
                        arm_dur = float(step["duration"])
                    target_s7 = pct_to_ticks_s7(s7_pct, backend.aux_calibration)
                    speed_s7 = 500
                    backend.move_target(7, target_s7, speed=speed_s7)
                    self.move_to_specific_arm_preset(backend, preset, duration=arm_dur, mode=mode)
                elif preset:
                    arm_dur = 1.0
                    if "arm_duration" in step:
                        arm_dur = float(step["arm_duration"])
                    elif "duration" in step:
                        arm_dur = float(step["duration"])
                    self.move_to_specific_arm_preset(backend, preset, duration=arm_dur, mode=mode)
                elif s7_pct is not None:
                    s7_dur = 0.5
                    if "servo7_duration" in step:
                        s7_dur = float(step["servo7_duration"])
                    elif "duration" in step:
                        s7_dur = float(step["duration"])
                    s7_speed = 500
                    if "servo7_speed" in step:
                        s7_speed = int(step["servo7_speed"])
                    target_s7 = pct_to_ticks_s7(s7_pct, backend.aux_calibration)
                    backend.move_target(7, target_s7, speed=s7_speed)
                    time.sleep(s7_dur)

                pause_sec = 0.0
                if "pause_sec" in step:
                    pause_sec = float(step["pause_sec"])
                if pause_sec > 0:
                    time.sleep(pause_sec)

            return True, f"Sequence {seq_name} executed successfully"
        finally:
            self._sequence_running = False

    def execute_attack_sequence(self, backend: RobotBackend) -> Tuple[bool, str]:
        """Executes the full 8-step Piranha Plant Attack choreography."""
        self.stop_sequence()
        self._sequence_stop_event.clear()
        self._sequence_running = True

        try:
            demo_presets = self.get_arm_presets(mode="demo")
            required_keyframes = ["lunge", "ready", "roar", "pose_1"]
            for rk in required_keyframes:
                if rk not in demo_presets or "normalized" not in demo_presets[rk] or not demo_presets[rk]["normalized"]:
                    dispatch_audio_event(kind="smw_pipe", stop_previous=True)
                    err_msg = f"Attack sequence aborted: Required keyframe '{rk}' is missing from presets_demo.json"
                    self.logger.error(err_msg)
                    return False, err_msg

            lunge_norm = demo_presets["lunge"]["normalized"]
            ready_norm = demo_presets["ready"]["normalized"]
            roar_norm = demo_presets["roar"]["normalized"]
            home_norm = demo_presets["pose_1"]["normalized"]

            # Step 1: Lunge + Rover Drive burst
            if self._sequence_stop_event.is_set():
                return False, "Aborted"
            self.logger.info("[ATTACK SEQ] Step 1: Lunge forward")
            ok, msg = backend.interpolate_arm_norm(lunge_norm, duration=1.0, steps=30, stop_event=self._sequence_stop_event)
            if not ok:
                return False, f"Lunge interpolation failed: {msg}"
            dispatch_audio_event(kind="connect", stop_previous=True)
            t_drive = threading.Thread(target=self._drive_burst_helper, kwargs={"throttle": 0.85, "duration_sec": 1.0}, daemon=True)
            t_drive.start()

            # Step 2: Pedestal right (100.0%)
            if self._sequence_stop_event.is_set():
                return False, "Aborted"
            self.logger.info("[ATTACK SEQ] Step 2: Quick pedestal snap to 100.0%")
            target_s7_r = pct_to_ticks_s7(100.0, backend.aux_calibration)
            backend.move_target(7, target_s7_r, speed=1000)
            time.sleep(0.4)

            # Step 3: Pedestal center (50.0%) + SMW blargg audio
            if self._sequence_stop_event.is_set():
                return False, "Aborted"
            self.logger.info("[ATTACK SEQ] Step 3: Pedestal return to center 50.0%")
            dispatch_audio_event(kind="smw_blargg", stop_previous=True)
            target_s7_c = pct_to_ticks_s7(50.0, backend.aux_calibration)
            backend.move_target(7, target_s7_c, speed=1000)
            time.sleep(0.5)

            # Step 4: Sweep pedestal left (0.0%) while moving arm to 'ready' stance
            if self._sequence_stop_event.is_set():
                return False, "Aborted"
            self.logger.info("[ATTACK SEQ] Step 4: Coordinated sweep to 0.0% in 'ready' stance")
            self._execute_arm_and_pedestal_sweep(
                backend=backend,
                start_s7_pct=50.0,
                end_s7_pct=0.0,
                target_arm_norm=ready_norm,
                duration_sec=2.0,
                steps=40,
                stop_event=self._sequence_stop_event
            )

            # Step 5: Transition into roar posture
            if self._sequence_stop_event.is_set():
                return False, "Aborted"
            self.logger.info("[ATTACK SEQ] Step 5: Transition to 'roar' posture")
            backend.interpolate_arm_norm(roar_norm, duration=0.8, steps=25, stop_event=self._sequence_stop_event)

            # Step 6: T-Rex Roar audio + simultaneous pedestal return & Motor 1 pan sweep
            if self._sequence_stop_event.is_set():
                return False, "Aborted"
            self.logger.info("[ATTACK SEQ] Step 6: Triggering T-Rex Roar audio and coordinated pan sweep")
            dispatch_audio_event(kind="trex_roar", stop_previous=True)

            target_s7_center = pct_to_ticks_s7(50.0, backend.aux_calibration)
            backend.move_target(7, target_s7_center, speed=250)

            self._execute_roar_pan_sweep(
                backend=backend,
                min_duration_sec=1.0,
                home_duration_sec=1.0,
                stop_event=self._sequence_stop_event
            )

            # Step 7: 0.5s pause post-audio completion
            if self._sequence_stop_event.is_set():
                return False, "Aborted"
            self.logger.info("[ATTACK SEQ] Step 7: Settle pause (0.5s post-audio)")
            time.sleep(1.75)

            # Step 8: Return to pose_1
            if self._sequence_stop_event.is_set():
                return False, "Aborted"
            self.logger.info("[ATTACK SEQ] Step 8: Returning robot back to position 1")
            target_s7_home = pct_to_ticks_s7(50.0, backend.aux_calibration)
            backend.move_target(7, target_s7_home, speed=400)
            backend.interpolate_arm_norm(home_norm, duration=1.2, steps=35, stop_event=self._sequence_stop_event)

            self.logger.info("[ATTACK SEQ] Completed Piranha Plant Attack sequence successfully.")
            return True, "Attack sequence completed"
        finally:
            self._sequence_running = False

    def stop_sequence(self) -> None:
        """Signals abort to any actively running sequence."""
        self._sequence_stop_event.set()
        self._sequence_running = False


# Backward compatibility alias for main.py and clack_pose_app shim
ClackPoseApp = PiranhaPoseApp
