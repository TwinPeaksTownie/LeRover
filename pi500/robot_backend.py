#!/usr/bin/env python3
"""RobotBackend module for SO-101 arm and auxiliary servos (Motors 1-8).
Manages low-level Feetech serial bus and AuxiliaryServoController hardware access.
Maintains unified, authoritative motor telemetry across all 8 servos.
"""

import json
import logging
import math
import os
import sys
import threading
import time
from pathlib import Path
from typing import Dict, Any, Tuple, Optional, List, Union

from aux_servo_controller import AuxiliaryServoController
from power_manager import BusPowerManager
from telemetry_proxies import _ServoFieldProxy, _ServoMotorStatesProxy, MOTOR_NAMES
try:
    from lerobot.motors import Motor, MotorCalibration, MotorNormMode
    from lerobot.motors.feetech import FeetechMotorsBus
    LEROBOT_AVAILABLE = True
except ImportError:
    Motor = Any
    MotorCalibration = Any
    MotorNormMode = Any
    FeetechMotorsBus = Any
    LEROBOT_AVAILABLE = False

sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))
sys.path.insert(0, str(Path(__file__).parent.resolve()))

try:
    from rover.rover_controller import RoverController
except ImportError:
    try:
        from rover_controller import RoverController
    except ImportError:
        RoverController = None

import urllib.request

BASE_DIR = Path.home() / "so101"
STATE_FILE = str(BASE_DIR / "gantry_state.json")
AUX_CALIB_FILE = str(BASE_DIR / "calibration_aux.json")
ARM_PRESETS_FILE = str(BASE_DIR / "arm_presets.json")
APPS_DIR = Path(__file__).resolve().parent.parent / "apps" / "preset_app"
APPS_PRESETS_DIR = APPS_DIR / "presets"
APPS_SEQUENCES_DIR = APPS_DIR / "sequences"
SERIAL_LOCK = threading.RLock()
NAME_TO_ID = {v: k for k, v in MOTOR_NAMES.items()}
try:
    import network_resolver
except ImportError:
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import network_resolver


import audio_resolver


def get_pi4b_sound_url() -> str:
    pi4b_ip = network_resolver.get_pi4b_ip(prefer_port=8082)
    return f"http://{pi4b_ip}:8082/api/play_sound"


def dispatch_audio_event(kind: str = "incorrect", wav_path: Optional[str] = None, stop_previous: bool = True, delay_sec: float = 0.0) -> None:
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
                "wav_path": wav_path,
                "stop_previous": stop_previous
            }).encode("utf-8")
            req = urllib.request.Request(
                get_pi4b_sound_url(),
                data=payload,
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                pass
        except Exception as e:
            logging.warning("Failed to dispatch audio event '%s' (%s) to Pi 4B: %s", event_name, sound_file, e)
    threading.Thread(target=_work, daemon=True).start()


def get_presets_fpath(mode: str = "normal") -> Path:
    """Resolves partitioned preset file for specified mode ('normal', 'demo', 'angry')."""
    clean_mode = str(mode).lower().strip() if mode else "normal"
    p_app = APPS_PRESETS_DIR / f"presets_{clean_mode}.json"
    if p_app.exists():
        return p_app
    p_base = BASE_DIR / f"arm_presets_{clean_mode}.json"
    if p_base.exists():
        return p_base
    if clean_mode == "normal" and Path(ARM_PRESETS_FILE).exists():
        return Path(ARM_PRESETS_FILE)
    APPS_PRESETS_DIR.mkdir(parents=True, exist_ok=True)
    return p_app


def get_sequence_fpath(name: str) -> Path:
    """Resolves sequence file path."""
    clean_name = str(name).lower().strip()
    if not clean_name.startswith("sequence_"):
        clean_name = f"sequence_{clean_name}"
    if not clean_name.endswith(".json"):
        clean_name = f"{clean_name}.json"
    p_app = APPS_SEQUENCES_DIR / clean_name
    if p_app.exists():
        return p_app
    p_base = BASE_DIR / clean_name
    if p_base.exists():
        return p_base
    return p_app


def load_aux_calibration() -> Dict[str, Any]:
    """Loads auxiliary motor calibration (Motors 7-8 travel bounds and center points).
    Ensures calibration_aux.json exists and returns dynamic calibration dict.
    """
    fpath = Path(AUX_CALIB_FILE)
    if not fpath.exists():
        raise FileNotFoundError(f"Mandatory auxiliary calibration file not found at {fpath}")
    with open(fpath, "r", encoding="utf-8") as f:
        data = json.load(f)
    if "7" not in data or "8" not in data:
        raise ValueError(f"Corrupt auxiliary calibration in {fpath}: Servos 7 and 8 entries required.")
    return data


def ticks_to_degrees_s7(ticks: int, center_ticks: Optional[int] = None) -> float:
    """Converts reported Motor 7 hardware ticks (0-4095) to intuitive degrees relative to calibrated center_ticks."""
    if center_ticks is None:
        center_ticks = int(load_aux_calibration()["7"]["center_ticks"])
    deg = (int(ticks) - int(center_ticks)) * 360.0 / 4096.0
    while deg > 180.0:
        deg -= 360.0
    while deg <= -180.0:
        deg += 360.0
    return round(deg, 1)


def degrees_to_ticks_s7(deg: float, center_ticks: Optional[int] = None) -> int:
    """Converts intuitive degrees to reported Motor 7 hardware ticks with a hard safety clamp of [-165.0, +165.0] degrees."""
    if center_ticks is None:
        center_ticks = int(load_aux_calibration()["7"]["center_ticks"])
    clamped_deg = max(-165.0, min(165.0, float(deg)))
    ticks = int(round(int(center_ticks) + (clamped_deg * 4096.0 / 360.0)))
    min_s7_ticks = int(round(int(center_ticks) - (165.0 * 4096.0 / 360.0)))
    max_s7_ticks = int(round(int(center_ticks) + (165.0 * 4096.0 / 360.0)))
    return max(min_s7_ticks, min(max_s7_ticks, ticks))


PEDESTAL_PRESETS = [-165.0, -135.0, -90.0, -45.0, 0.0, 45.0, 90.0, 135.0, 165.0]


def calc_next_s7_preset(curr_deg: float, direction: str) -> Tuple[float, bool]:
    """Calculates next clean preset angle relative to current physical hardware position
    using nearest-slot snapping and hard bumper stops.
    Returns (target_deg, at_limit).
    """
    direction = str(direction).lower()
    curr_idx = min(range(len(PEDESTAL_PRESETS)), key=lambda i: abs(curr_deg - PEDESTAL_PRESETS[i]))
    if direction == "right":
        if curr_idx >= len(PEDESTAL_PRESETS) - 1:
            return PEDESTAL_PRESETS[-1], True
        next_idx = curr_idx + 1
        return PEDESTAL_PRESETS[next_idx], (next_idx == len(PEDESTAL_PRESETS) - 1)
    else:
        if curr_idx <= 0:
            return PEDESTAL_PRESETS[0], True
        next_idx = curr_idx - 1
        return PEDESTAL_PRESETS[next_idx], (next_idx == 0)



def load_calibration(fpath: Path) -> dict[str, MotorCalibration]:
    if not fpath.exists():
        raise FileNotFoundError(f"Calibration file not found at {fpath}")
    with open(fpath) as f:
        raw = json.load(f)
    return {motor: MotorCalibration(**vals) for motor, vals in raw.items()}


def make_bus(port: str, calibration: dict[str, MotorCalibration]) -> FeetechMotorsBus:
    norm_mode_body = MotorNormMode.RANGE_M100_100
    return FeetechMotorsBus(
        port=port,
        motors={
            "shoulder_pan": Motor(1, "sts3215", norm_mode_body),
            "shoulder_lift": Motor(2, "sts3215", norm_mode_body),
            "elbow_flex": Motor(3, "sts3215", norm_mode_body),
            "wrist_flex": Motor(4, "sts3215", norm_mode_body),
            "wrist_roll": Motor(5, "sts3215", norm_mode_body),
            "gripper": Motor(6, "sts3215", MotorNormMode.RANGE_0_100),
        },
        calibration=calibration,
    )


class RobotBackend:
    """Authoritative hardware abstraction layer for SO-101 arm (1-6) and Aux servos (7-8)."""

    def __init__(self, port: str = "/dev/ttyACM0", robot_id: str = "follower") -> None:
        self.port = port
        self.robot_id = robot_id
        self.lock = threading.RLock()
        self.ctrl: Optional[AuxiliaryServoController] = None
        self.bus: Optional[FeetechMotorsBus] = None

        # Authoritative, unified motor telemetry structure
        self.servos: Dict[int, Dict[str, Any]] = {
            i: {
                "id": i,
                "name": MOTOR_NAMES[i],
                "pos": None,
                "raw": None,
                "normalized": None,
                "torque": False,
                "is_moving": False,
                "connected": False,
                "error": None,
            }
            for i in range(1, 9)
        }

        self.arm_calibration: Dict[str, MotorCalibration] = {}
        self.aux_calibration: Dict[str, Any] = load_aux_calibration()
        self.hardware_active: bool = False
        self.follower_active: bool = False
        self.active_port: str = port
        self.error_msg: Optional[str] = None
        self.power_mgr: Optional[BusPowerManager] = None
        self.last_saved_position: Optional[Dict[str, Any]] = None
        self.active_preset_mode: str = "normal"
        self._sequence_running: bool = False
        self._sequence_thread: Optional[threading.Thread] = None
        self._sequence_stop_event = threading.Event()
        self._shutdown_event = threading.Event()
        self._telemetry_thread: Optional[threading.Thread] = None

        # Initialize RoverController with auto-detection
        if RoverController is not None:
            try:
                self.rover_ctrl = RoverController()
                self.rover_ctrl.start()
                logging.info("RoverController initialized and started on RobotBackend.")
            except Exception as e:
                logging.warning("RoverController initialization warning: %s", e)
                self.rover_ctrl = None
        else:
            self.rover_ctrl = None

        self.load_state()

    # Dynamic backward-compatibility properties mapped directly to self.servos state
    @property
    def aux_positions(self) -> _ServoFieldProxy:
        return _ServoFieldProxy(self, "pos", target_sids=[7, 8])

    @property
    def raw_positions(self) -> _ServoFieldProxy:
        return _ServoFieldProxy(self, "raw")

    @property
    def torque_state(self) -> _ServoFieldProxy:
        return _ServoFieldProxy(self, "torque", target_sids=[7, 8])

    @property
    def is_moving(self) -> _ServoFieldProxy:
        return _ServoFieldProxy(self, "is_moving", target_sids=[7, 8])

    @property
    def motor_states(self) -> _ServoMotorStatesProxy:
        return _ServoMotorStatesProxy(self)

    @property
    def last_arm_positions(self) -> Dict[Any, Any]:
        with self.lock:
            res: Dict[Any, Any] = {}
            for sid in range(1, 7):
                name = self.servos[sid]["name"]
                val = self.servos[sid]["normalized"]
                res[name] = val
                res[sid] = val
            return res

    @last_arm_positions.setter
    def last_arm_positions(self, val: Dict[Any, Any]) -> None:
        motor_name_map = {
            "shoulder_pan": 1,
            "shoulder_lift": 2,
            "elbow_flex": 3,
            "wrist_flex": 4,
            "wrist_roll": 5,
            "gripper": 6,
        }
        with self.lock:
            if isinstance(val, dict):
                for k, v in val.items():
                    sid = motor_name_map.get(str(k), k if isinstance(k, int) else None)
                    if sid and 1 <= sid <= 6:
                        self.servos[sid]["normalized"] = float(v) if v is not None else None

    @property
    def last_arm_raw_ticks(self) -> Dict[int, int]:
        with self.lock:
            return {
                sid: self.servos[sid]["raw"]
                for sid in range(1, 7)
                if self.servos[sid]["raw"] is not None
            }

    @last_arm_raw_ticks.setter
    def last_arm_raw_ticks(self, val: Dict[int, int]) -> None:
        with self.lock:
            if isinstance(val, dict):
                for sid, raw in val.items():
                    if isinstance(sid, int) and 1 <= sid <= 6:
                        self.servos[sid]["raw"] = int(raw)
                        self.servos[sid]["pos"] = int(raw)
                        self.servos[sid]["connected"] = True

    @property
    def gantry_position(self) -> Optional[int]:
        """Gets dead-reckoning position (ticks) for Motor 8 (Gantry)."""
        with self.lock:
            return self.servos[8]["pos"]

    @gantry_position.setter
    def gantry_position(self, pos: int) -> None:
        """Sets dead-reckoning position (ticks) for Motor 8 (Gantry)."""
        with self.lock:
            int_pos = int(pos)
            self.servos[8]["pos"] = int_pos
            self.servos[8]["raw"] = int_pos % 4096
            self.servos[8]["connected"] = True

    def load_state(self) -> None:
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, "r") as f:
                    data = json.load(f)
                    if "8" in data:
                        self.gantry_position = int(data["8"])
                logging.info(f"Loaded persistent Gantry Motor 8 state from {STATE_FILE}: {data}")
            except Exception as e:
                logging.error(f"Failed to load state file: {e}")

    def save_state(self) -> None:
        try:
            os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
            pos8 = self.gantry_position
            if pos8 is not None:
                with open(STATE_FILE, "w") as f:
                    json.dump({"8": pos8}, f, indent=2)
        except Exception as e:
            logging.error(f"Failed to save state: {e}")

    def connect(self) -> bool:
        """Connects FeetechMotorsBus and AuxiliaryServoController with active bus recovery."""
        calib_fpath = (
            Path.home()
            / ".cache/huggingface/lerobot/calibration/robots/so_follower"
            / f"{self.robot_id}.json"
        )
        self.arm_calibration = load_calibration(calib_fpath)

        for attempt in range(5):
            try:
                self.bus = make_bus(self.port, self.arm_calibration)
                with SERIAL_LOCK:
                    self.bus.connect()
                    time.sleep(0.2)
                    ser = getattr(self.bus.port_handler, "ser", None)
                    if ser and hasattr(ser, "reset_input_buffer"):
                        ser.reset_input_buffer()
                        ser.reset_output_buffer()
                self._configure_bus()
                logging.info("SO-101 follower arm connected cleanly on %s", self.port)
                self.hardware_active = True
                self.error_msg = None
                break
            except Exception as e:
                logging.warning("Arm connection attempt %d warning: %s", attempt + 1, e)
                time.sleep(0.3 * (attempt + 1))

        if not self.hardware_active:
            logging.warning("Arm motor connection failed after 5 attempts; flagging bus fault state.")
            self.error_msg = "Arm motors offline after 5 connection retries"

        try:
            ser_handle = (
                getattr(self.bus.port_handler, "ser", None)
                if self.bus and hasattr(self.bus, "port_handler")
                else None
            )
            self.ctrl = AuxiliaryServoController(
                port=self.port, ser=ser_handle, bus_lock=SERIAL_LOCK
            )

            time.sleep(0.05)
            if hasattr(self.ctrl, "flush_buffers"):
                self.ctrl.flush_buffers()
            # Explicitly send Torque Disable to hardware so motors are physically limp
            self.ctrl.set_torque(7, False)
            self.ctrl.set_torque(8, False)
            self.sync_servo7_position()
            self.sync_servo8_position()
            self.active_port = self.port

            # Initialize dedicated single-responsibility BusPowerManager with busy callback
            self.power_mgr = BusPowerManager(
                self.ctrl,
                on_resync_callback=self._execute_hardware_resync,
                is_busy_callback=lambda: bool(self._sequence_running or self.follower_active),
            )
            self.power_mgr.start()
        except Exception as e:
            logging.error("Failed to connect Auxiliary Controller: %s", e)
            self.ctrl = None
            err = f"Aux Controller Error: {e}"
            self.error_msg = f"{self.error_msg} | {err}" if self.error_msg else err

        if self.hardware_active and (self._telemetry_thread is None or not self._telemetry_thread.is_alive()):
            self._telemetry_thread = threading.Thread(target=self._telemetry_loop, daemon=True, name="ArmTelemetryLoop")
            self._telemetry_thread.start()
            logging.info("Started 3 Hz idle-gated hardware telemetry thread.")

        return self.hardware_active

    def _telemetry_loop(self) -> None:
        """Background poller querying live joint encoder positions at 3 Hz when arm is idle/limp."""
        motor_ids = {
            "shoulder_pan": 1,
            "shoulder_lift": 2,
            "elbow_flex": 3,
            "wrist_flex": 4,
            "wrist_roll": 5,
            "gripper": 6,
        }
        loop_count = 0
        while not self._shutdown_event.is_set():
            time.sleep(0.33)  # 3 Hz refresh rate
            if not self.hardware_active or self.bus is None or self._sequence_running or self.follower_active:
                continue

            # Safely acquire SERIAL_LOCK for a fast sync_read
            try:
                with SERIAL_LOCK:
                    if self._sequence_running or self.follower_active or not self.hardware_active or self.bus is None:
                        continue
                    ser = getattr(self.bus.port_handler, "ser", None)
                    if ser and hasattr(ser, "reset_input_buffer"):
                        ser.reset_input_buffer()

                    norm_dict = self.bus.sync_read("Present_Position")
                    raw_dict = self.bus.sync_read("Present_Position", normalize=False)

                if norm_dict:
                    with self.lock:
                        for k, v in norm_dict.items():
                            sid = motor_ids.get(str(k), k if isinstance(k, int) else None)
                            if sid and 1 <= sid <= 6:
                                self.servos[sid]["normalized"] = round(float(v), 2)
                                self.servos[sid]["connected"] = True

                if raw_dict:
                    with self.lock:
                        for k, v in raw_dict.items():
                            sid = motor_ids.get(str(k), k if isinstance(k, int) else None)
                            if sid and 1 <= sid <= 6:
                                self.servos[sid]["raw"] = int(v)
                                self.servos[sid]["pos"] = int(v)

                # Periodically refresh Servo 7 angle if idle
                loop_count += 1
                if loop_count % 3 == 0 and not self._sequence_running and not self.follower_active:
                    with SERIAL_LOCK:
                        if not self._sequence_running and not self.follower_active:
                            self.sync_servo7_position()

            except Exception as e:
                logging.debug("Background telemetry loop exception: %s", e)

    def _execute_hardware_resync(self) -> bool:
        """Hardware recovery sequence executed by BusPowerManager upon 12V restoration."""
        if not self.ctrl:
            return False
        try:
            # 1. Purge serial buffers
            self.ctrl.flush_buffers()

            # 2. Explicitly ensure motors remain limp in hardware
            self.ctrl.set_torque(7, False)
            self.ctrl.set_torque(8, False)

            # 3. Re-sync encoder position baselines
            self.sync_servo7_position()
            self.sync_servo8_position()
            self.read_raw_arm_ticks()

            with self.lock:
                self.hardware_active = True
                self.error_msg = None
            logging.info("Hardware auto-recovery callback executed successfully (motors remain unpowered).")
            return True
        except Exception as ex:
            logging.error("Re-synch recovery sequence exception: %s", ex)
            return False

    def sync_servo7_position(self) -> Optional[int]:
        """Ensures Motor 7 baseline state matches live hardware encoder read on startup with active retries."""
        if not self.ctrl:
            with self.lock:
                self.servos[7]["connected"] = False
                self.servos[7]["error"] = "AuxiliaryServoController uninitialized"
            return None

        pos = None
        for attempt in range(5):
            self.ctrl.flush_buffers()
            pos = self.ctrl.read_pos(7)
            if pos is not None:
                break
            time.sleep(0.01)

        if pos is None:
            try:
                self.ctrl.clear_alarms(7)
                pos = self.ctrl.read_pos(7)
            except Exception:
                pass

        if pos is not None:
            with self.lock:
                self.servos[7]["pos"] = pos
                self.servos[7]["raw"] = pos % 4096
                self.servos[7]["connected"] = True
                self.servos[7]["error"] = None
                if self.error_msg and "Servo 7" in self.error_msg:
                    self.error_msg = None
                logging.info(f"Synchronized Motor 7 baseline from hardware: {pos} ticks")
                return pos

        with self.lock:
            self.servos[7]["connected"] = False
            self.servos[7]["error"] = "Hardware read timeout after 5 retries"
        logging.error("Failed to read Servo 7 position from hardware after retries.")
        return None

    def get_s7_center_ticks(self) -> int:
        if not hasattr(self, "aux_calibration") or "7" not in self.aux_calibration or "center_ticks" not in self.aux_calibration["7"]:
            raise RuntimeError("Servo 7 calibration missing in calibration_aux.json")
        return int(self.aux_calibration["7"]["center_ticks"])

    def get_s8_bounds(self) -> Tuple[int, int]:
        if not hasattr(self, "aux_calibration") or "8" not in self.aux_calibration or "min_ticks" not in self.aux_calibration["8"] or "max_ticks" not in self.aux_calibration["8"]:
            raise RuntimeError("Servo 8 gantry calibration missing in calibration_aux.json")
        return int(self.aux_calibration["8"]["min_ticks"]), int(self.aux_calibration["8"]["max_ticks"])

    def sync_motor8_dead_reckoning(self, pos: Optional[int] = None) -> Optional[int]:
        """Synchronizes Motor 8's absolute position baseline with dead reckoning state."""
        return self.sync_servo8_position(pos)

    def sync_servo8_position(self, pos: Optional[int] = None) -> Optional[int]:
        """Synchronizes Motor 8 dead reckoning state and saves to persistent storage."""
        with self.lock:
            if not self.ctrl:
                self.servos[8]["connected"] = False
                self.servos[8]["error"] = "AuxiliaryServoController uninitialized"
                return None

            curr = pos if pos is not None else self.servos[8]["pos"]
            if curr is None:
                self.servos[8]["connected"] = False
                self.servos[8]["error"] = "Dead reckoning state uninitialized"
                logging.error("Cannot sync Motor 8: dead reckoning position state is uninitialized.")
                return None

            gantry_min, gantry_max = self.get_s8_bounds()
            real_pos = max(gantry_min, min(gantry_max, int(curr)))

            self.servos[8]["pos"] = real_pos
            self.servos[8]["raw"] = real_pos % 4096
            self.servos[8]["connected"] = True
            self.servos[8]["error"] = None
            self.aux_positions[8] = real_pos
            logging.info(f"Synchronized Motor 8 dead reckoning baseline: {real_pos} ticks")
            self.save_state()
            return real_pos

    def _configure_bus(self) -> None:
        RETRY = 3
        if not self.bus:
            return
        with SERIAL_LOCK:
            ser = getattr(self.bus.port_handler, "ser", None)
            if ser and hasattr(ser, "reset_input_buffer"):
                try:
                    ser.reset_input_buffer()
                    ser.reset_output_buffer()
                except Exception:
                    pass

            try:
                self.bus.disable_torque(num_retry=RETRY)
            except Exception as e:
                logging.warning("disable_torque warning: %s", e)

            for attempt in range(3):
                try:
                    if ser and hasattr(ser, "reset_input_buffer"):
                        ser.reset_input_buffer()
                        ser.reset_output_buffer()
                    self.bus.configure_motors()
                    break
                except Exception as e:
                    logging.warning("configure_motors attempt %d failed: %s", attempt + 1, e)
                    time.sleep(0.1)

            current_arm_positions = {}
            try:
                if ser and hasattr(ser, "reset_input_buffer"):
                    ser.reset_input_buffer()
                    ser.reset_output_buffer()
                current_arm_positions = self.bus.sync_read("Present_Position")
                raw_ticks = self.bus.sync_read("Present_Position", normalize=False)
                motor_ids = {
                    "shoulder_pan": 1,
                    "shoulder_lift": 2,
                    "elbow_flex": 3,
                    "wrist_flex": 4,
                    "wrist_roll": 5,
                    "gripper": 6,
                }
                if current_arm_positions:
                    with self.lock:
                        for k, v in current_arm_positions.items():
                            sid = motor_ids.get(str(k), k if isinstance(k, int) else None)
                            if sid and 1 <= sid <= 6:
                                self.servos[sid]["normalized"] = float(v)
                                self.servos[sid]["connected"] = True
                if raw_ticks:
                    with self.lock:
                        for k, v in raw_ticks.items():
                            sid = motor_ids.get(str(k), k if isinstance(k, int) else None)
                            if sid and 1 <= sid <= 6:
                                self.servos[sid]["raw"] = int(v)
                                self.servos[sid]["pos"] = int(v)
                                self.servos[sid]["connected"] = True
            except Exception as e:
                logging.warning("Failed to read present arm positions prior to torque enable: %s", e)

            for motor in self.bus.motors:
                try:
                    if motor in current_arm_positions:
                        self.bus.write("Goal_Position", motor, current_arm_positions[motor], num_retry=RETRY)
                    self.bus.write("Torque_Enable", motor, 0, num_retry=RETRY)
                except Exception as e:
                    logging.warning("Failed to configure motor %s: %s", motor, e)

            try:
                self.bus.disable_torque(num_retry=RETRY)
            except Exception as e:
                logging.warning("disable_torque warning: %s", e)

    def read_raw_arm_ticks(self) -> Dict[int, int]:
        if not self.bus:
            with self.lock:
                return {sid: self.servos[sid]["raw"] for sid in range(1, 7) if self.servos[sid]["raw"] is not None}
        with SERIAL_LOCK:
            try:
                ser = getattr(self.bus.port_handler, "ser", None)
                if ser and hasattr(ser, "reset_input_buffer"):
                    ser.reset_input_buffer()
                raw_dict = self.bus.sync_read("Present_Position", normalize=False)
                if raw_dict:
                    motor_ids = {
                        "shoulder_pan": 1,
                        "shoulder_lift": 2,
                        "elbow_flex": 3,
                        "wrist_flex": 4,
                        "wrist_roll": 5,
                        "gripper": 6,
                    }
                    parsed = {}
                    with self.lock:
                        for k, val in raw_dict.items():
                            sid = motor_ids.get(str(k), k if isinstance(k, int) else None)
                            if sid and 1 <= sid <= 6:
                                raw_val = int(val)
                                parsed[sid] = raw_val
                                self.servos[sid]["raw"] = raw_val
                                self.servos[sid]["pos"] = raw_val
                                self.servos[sid]["connected"] = True
                                self.servos[sid]["error"] = None
                    return parsed
            except Exception as e:
                logging.warning("read_raw_arm_ticks warning: %s", e)
        with self.lock:
            return {sid: self.servos[sid]["raw"] for sid in range(1, 7) if self.servos[sid]["raw"] is not None}

    def set_arm_torque(self, enable: bool) -> bool:
        """Cleanly enables or disables torque on Arm Servos 1-6 using normalized positions."""
        with SERIAL_LOCK:
            if not self.bus:
                return False
            if enable:
                ser = getattr(self.bus.port_handler, "ser", None)
                if ser and hasattr(ser, "reset_input_buffer"):
                    ser.reset_input_buffer()
                # Read current normalized positions to sync goals prior to torque enable
                current_norm = self.bus.sync_read("Present_Position")
                if current_norm and hasattr(self.bus, "sync_write"):
                    try:
                        self.bus.sync_write("Goal_Position", current_norm)
                    except Exception as e:
                        logging.warning("sync_write Goal_Position warning: %s", e)
                if hasattr(self.bus, "enable_torque"):
                    self.bus.enable_torque(num_retry=2)
                with self.lock:
                    for sid in range(1, 7):
                        self.servos[sid]["torque"] = True
                    self.follower_active = True
                logging.info("Arm torque re-engaged on Servos 1-6 (holding current pose).")
            else:
                if hasattr(self.bus, "disable_torque"):
                    self.bus.disable_torque(num_retry=2)
                with self.lock:
                    for sid in range(1, 7):
                        self.servos[sid]["torque"] = False
                    self.follower_active = False
                logging.info("Arm torque disarmed on Servos 1-6 (limp mode).")
            return True

    def set_aux_torque(self, servo_id: int, enable: bool) -> bool:
        """Enables or disables torque on Aux Servo 7 or 8."""
        if not self.ctrl:
            return False
        try:
            with SERIAL_LOCK:
                self.ctrl.set_torque(servo_id, enable)
            with self.lock:
                if servo_id in self.servos:
                    self.servos[servo_id]["torque"] = enable
                self.torque_state[servo_id] = enable
            logging.info("Aux Servo %d torque %s.", servo_id, "enabled" if enable else "disabled")
            return True
        except Exception as e:
            logging.warning("Error setting aux servo %d torque to %s: %s", servo_id, enable, e)
            return False

    def disable_all_torque(self) -> bool:
        """Immediately disarms torque on Arm Servos 1-6 and Aux Servos 7-8."""
        logging.info("Disarming torque across all servos (1-8)...")
        # 1. Disable Arm Servos 1-6
        try:
            self.set_arm_torque(False)
        except Exception as e:
            logging.warning("Error disabling arm torque: %s", e)

        # 2. Disable Aux Servos 7 and 8
        try:
            if self.ctrl:
                with SERIAL_LOCK:
                    self.ctrl.set_torque(7, False)
                    self.ctrl.set_torque(8, False)
                with self.lock:
                    self.servos[7]["torque"] = False
                    self.servos[8]["torque"] = False
                    self.torque_state[7] = False
                    self.torque_state[8] = False
        except Exception as e:
            logging.warning("Error disabling aux servo torque: %s", e)

        # 3. Direct broadcast packet to ensure no Feetech servo keeps driving
        try:
            ser = getattr(self.bus.port_handler, "ser", None) if self.bus else None
            if not ser and self.ctrl and hasattr(self.ctrl, "ser"):
                ser = self.ctrl.ser
            if ser and hasattr(ser, "write"):
                with SERIAL_LOCK:
                    pkt = [0xFF, 0xFF, 0xFE, 4, 3, 40, 0]
                    pkt.append((~sum(pkt[2:])) & 0xFF)
                    ser.write(bytes(pkt))
                    if hasattr(ser, "flush"):
                        ser.flush()
        except Exception as e:
            logging.warning("Broadcast torque disable warning: %s", e)

        return True

    def get_arm_presets(self, mode: str = "normal") -> Dict[str, Any]:
        """Loads and returns the presets dictionary for specified mode ('normal', 'demo', 'angry')."""
        fpath = get_presets_fpath(mode)
        if fpath.exists():
            try:
                with open(fpath, "r") as f:
                    return json.load(f)
            except Exception as e:
                logging.warning("Failed to load presets from %s: %s", fpath, e)
        return {}

    def capture_temporary_arm_pose(self) -> Dict[str, Any]:
        """Captures live empirical normalized arm positions directly from bus,
        re-engages torque holding current pose, and stores in runtime memory as self.last_saved_position."""
        with SERIAL_LOCK:
            ser = getattr(self.bus.port_handler, "ser", None) if self.bus else None
            if ser and hasattr(ser, "reset_input_buffer"):
                ser.reset_input_buffer()
                ser.reset_output_buffer()

            norm_dict = self.bus.sync_read("Present_Position")
            raw_dict = self.bus.sync_read("Present_Position", normalize=False)
            if not norm_dict or len(norm_dict) < 6:
                raise RuntimeError(f"Incomplete empirical hardware read from arm servos: {norm_dict}")

            # Re-engage torque holding current normalized positions so the arm does not sag
            if hasattr(self.bus, "sync_write"):
                try:
                    self.bus.sync_write("Goal_Position", norm_dict)
                except Exception as e:
                    logging.warning("sync_write Goal_Position during capture warning: %s", e)
            if hasattr(self.bus, "enable_torque"):
                self.bus.enable_torque(num_retry=2)

            motor_ids = {
                "shoulder_pan": 1,
                "shoulder_lift": 2,
                "elbow_flex": 3,
                "wrist_flex": 4,
                "wrist_roll": 5,
                "gripper": 6,
            }
            with self.lock:
                for k, v in norm_dict.items():
                    sid = motor_ids.get(str(k), k if isinstance(k, int) else None)
                    if sid and 1 <= sid <= 6:
                        self.servos[sid]["normalized"] = float(v)
                        self.servos[sid]["torque"] = True
                if raw_dict:
                    for k, v in raw_dict.items():
                        sid = motor_ids.get(str(k), k if isinstance(k, int) else None)
                        if sid and 1 <= sid <= 6:
                            self.servos[sid]["raw"] = int(v)
                            self.servos[sid]["pos"] = int(v)
                            self.servos[sid]["connected"] = True

            # Capture Aux positions with dynamic hardware synchronization & calibration_aux.json resolution
            s7_pos = self.servos[7]["pos"]
            if s7_pos is None:
                s7_pos = self.sync_servo7_position()
            if s7_pos is None:
                if "7" not in self.aux_calibration or "center_ticks" not in self.aux_calibration["7"]:
                    raise KeyError("Mandatory 'center_ticks' for Servo 7 missing from calibration_aux.json")
                s7_pos = int(self.aux_calibration["7"]["center_ticks"])

            s8_pos = self.servos[8]["pos"]
            if s8_pos is None:
                s8_pos = self.sync_servo8_position()
            if s8_pos is None:
                if "8" not in self.aux_calibration or "min_ticks" not in self.aux_calibration["8"]:
                    raise KeyError("Mandatory 'min_ticks' for Servo 8 missing from calibration_aux.json")
                s8_pos = int(self.aux_calibration["8"]["min_ticks"])

            # Bi-directional read-back verification from hardware
            verify_norm = self.bus.sync_read("Present_Position")
            if not verify_norm or len(verify_norm) < 6:
                raise RuntimeError("Bi-directional read-back parity verification failed for arm servos")

            new_pose = {
                "timestamp": time.time(),
                "normalized": {k: round(float(v), 2) for k, v in verify_norm.items()},
                "raw_ticks": {str(motor_ids.get(k, k)): int(v) for k, v in raw_dict.items()} if raw_dict else {},
                "aux": {
                    "7": int(s7_pos),
                    "8": int(s8_pos),
                }
            }
            self.last_saved_position = new_pose
            logging.info("[4-STATE VERIFIED: pose_capture] Live encoder telemetry: %s, aux: S7=%d, S8=%d",
                         new_pose["normalized"], s7_pos, s8_pos)
            return {
                "status": "ok",
                "action": "temporary_saved",
                "normalized": new_pose["normalized"],
                "raw_ticks": new_pose["raw_ticks"],
                "aux": new_pose["aux"],
            }

    def capture_sequential_arm_pose(self) -> Dict[str, Any]:
        """Backward-compatible alias for temporary capture."""
        return self.capture_temporary_arm_pose()

    def save_official_arm_preset(self, custom_name: Optional[str] = None, mode: str = "normal", overwrite: bool = False) -> Dict[str, Any]:
        """Permanently commits the runtime last_saved_position (or live capture) to mode-specific preset JSON."""
        if self.last_saved_position is None:
            self.capture_temporary_arm_pose()

        pose_data = dict(self.last_saved_position)
        fpath = get_presets_fpath(mode)
        presets: Dict[str, Any] = {}
        if fpath.exists():
            try:
                with open(fpath, "r") as f:
                    presets = json.load(f)
            except Exception as e:
                logging.warning("Failed to parse %s, creating new dict: %s", fpath, e)
                presets = {}

        if custom_name:
            pose_name = custom_name
        elif overwrite:
            # Overwrite the highest index or pose_1
            existing_indices = [int(k.split("_")[1]) for k in presets.keys() if k.startswith("pose_") and k.split("_")[1].isdigit()]
            max_idx = max(existing_indices, default=1)
            pose_name = f"pose_{max_idx}"
        else:
            # Determine next sequential index
            existing_indices = [int(k.split("_")[1]) for k in presets.keys() if k.startswith("pose_") and k.split("_")[1].isdigit()]
            next_idx = max(existing_indices, default=0) + 1
            pose_name = f"pose_{next_idx}"

        presets[pose_name] = pose_data
        fpath.parent.mkdir(parents=True, exist_ok=True)
        with open(fpath, "w") as f:
            json.dump(presets, f, indent=2)

        logging.info("Committed official arm preset %s to %s: %s", pose_name, fpath, pose_data["normalized"])
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

    def overwrite_arm_preset(self, preset_name: str, mode: str = "normal") -> Dict[str, Any]:
        """Directly overwrites a designated preset slot with the live held/captured pose from physical hardware."""
        if not preset_name:
            raise ValueError("Target preset_name is required for overwrite")

        # Unconditionally capture fresh empirical position from live arm hardware
        self.capture_temporary_arm_pose()

        pose_data = dict(self.last_saved_position)
        fpath = get_presets_fpath(mode)
        presets: Dict[str, Any] = {}
        if fpath.exists():
            try:
                with open(fpath, "r") as f:
                    presets = json.load(f)
            except Exception as e:
                logging.warning("Failed to parse %s: %s", fpath, e)
                presets = {}

        presets[preset_name] = pose_data
        fpath.parent.mkdir(parents=True, exist_ok=True)
        with open(fpath, "w") as f:
            json.dump(presets, f, indent=2)

        logging.info("Overwrote preset '%s' in mode '%s' on disk: %s", preset_name, mode, pose_data["normalized"])
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
            return {"status": "error", "message": f"Preset file {fpath} does not exist"}
        try:
            with open(fpath, "r") as f:
                presets = json.load(f)
            if preset_name in presets:
                del presets[preset_name]
                with open(fpath, "w") as f:
                    json.dump(presets, f, indent=2)
                return {"status": "ok", "deleted": preset_name, "total_presets": len(presets)}
            return {"status": "error", "message": f"Preset {preset_name} not found"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def resume_last_arm_pose(self, duration: float = 1.0, steps: int = 40, mode: str = "normal") -> Tuple[bool, str]:
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
                    target_norm = pose_items[-1][2].get("normalized")
                else:
                    latest_key = list(presets.keys())[-1]
                    target_name = latest_key
                    target_norm = presets[latest_key].get("normalized")

        if not target_norm:
            return False, "No target pose found in memory or presets"

        ok, msg = self.interpolate_arm_norm(target_norm, duration=duration, steps=steps)
        if ok:
            return True, f"Resumed {target_name} ({duration}s)"
        return False, msg

    def interpolate_arm_norm(
        self,
        target_norm: Dict[str, float],
        duration: float = 1.0,
        steps: int = 40,
        stop_event: Optional[threading.Event] = None,
    ) -> Tuple[bool, str]:
        """Core cosine S-curve interpolation engine for Arm Motors 1-6."""
        with SERIAL_LOCK:
            if not self.bus:
                return False, "Motor bus uninitialized"

            ser = getattr(self.bus.port_handler, "ser", None)
            if ser and hasattr(ser, "reset_input_buffer"):
                ser.reset_input_buffer()

            start_norm = self.bus.sync_read("Present_Position")
            if not start_norm:
                return False, "Failed to read current arm start positions"

            if hasattr(self.bus, "enable_torque"):
                try:
                    self.bus.enable_torque(num_retry=2)
                except Exception as e:
                    logging.warning("enable_torque warning: %s", e)

        with self.lock:
            for sid in range(1, 7):
                self.servos[sid]["torque"] = True

        arm_motor_names = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"]
        for mname in arm_motor_names:
            if mname not in start_norm or start_norm[mname] is None:
                return False, f"Incomplete motor read: '{mname}' missing from bus telemetry"
            if mname not in target_norm or target_norm[mname] is None:
                return False, f"Incomplete target pose: '{mname}' missing from target specification"

        dt = max(0.008, duration / steps)
        consecutive_write_failures = 0
        for s in range(1, steps + 1):
            if stop_event and stop_event.is_set():
                return False, "Interpolation aborted by stop signal"

            alpha = s / float(steps)
            smooth_alpha = 0.5 * (1.0 - math.cos(math.pi * alpha))
            interp_frame = {}
            for mname in arm_motor_names:
                s_val = float(start_norm[mname])
                t_val = float(target_norm[mname])
                val = s_val + (t_val - s_val) * smooth_alpha
                if mname == "gripper":
                    clamped = max(0.0, min(100.0, val))
                else:
                    clamped = max(-100.0, min(100.0, val))
                interp_frame[mname] = clamped

            with SERIAL_LOCK:
                if self.bus and hasattr(self.bus, "sync_write"):
                    try:
                        self.bus.sync_write("Goal_Position", interp_frame)
                        consecutive_write_failures = 0
                    except Exception as e:
                        consecutive_write_failures += 1
                        logging.warning("sync_write Goal_Position warning (failure %d): %s", consecutive_write_failures, e)
                        if consecutive_write_failures >= 3:
                            logging.error("Aborting move: 3 consecutive bus write failures encountered")
                            return False, "Bus write failure threshold exceeded"
            time.sleep(dt)

        with SERIAL_LOCK:
            final_norm = self.bus.sync_read("Present_Position") if self.bus else None
            raw_ticks = self.bus.sync_read("Present_Position", normalize=False) if self.bus else None

        motor_ids = {"shoulder_pan": 1, "shoulder_lift": 2, "elbow_flex": 3, "wrist_flex": 4, "wrist_roll": 5, "gripper": 6}
        with self.lock:
            if final_norm:
                for k, v in final_norm.items():
                    sid = motor_ids.get(str(k), k if isinstance(k, int) else None)
                    if sid and 1 <= sid <= 6:
                        self.servos[sid]["normalized"] = float(v)
            if raw_ticks:
                for k, v in raw_ticks.items():
                    sid = motor_ids.get(str(k), k if isinstance(k, int) else None)
                    if sid and 1 <= sid <= 6:
                        self.servos[sid]["raw"] = int(v)
                        self.servos[sid]["pos"] = int(v)

        return True, "OK"

    def move_to_specific_arm_preset(
        self, preset_name: str, duration: float = 1.0, steps: Optional[int] = None, mode: str = "normal"
    ) -> Tuple[bool, str]:
        """Moves arm to a specific preset name in mode-specific JSON with smooth cosine S-curve interpolation."""
        if steps is None:
            steps = max(10, int(duration * 40))
        presets = self.get_arm_presets(mode=mode)
        if preset_name not in presets:
            # Also try default 'normal' if not found in requested mode
            if mode != "normal":
                presets = self.get_arm_presets(mode="normal")
            if preset_name not in presets:
                return False, f"Preset '{preset_name}' not found in presets file"

        target_norm = presets[preset_name].get("normalized")
        if not target_norm:
            return False, f"Preset '{preset_name}' has no normalized coordinates"

        ok, msg = self.interpolate_arm_norm(target_norm, duration=duration, steps=steps)
        if ok:
            logging.info("Moved arm to preset %s (mode=%s) smoothly over %.2fs", preset_name, mode, duration)
            return True, f"Moved to {preset_name} ({duration}s)"
        return False, msg

    def list_sequences(self, mode: Optional[str] = None) -> List[Dict[str, Any]]:
        """Lists available sequence choreographies from apps/preset_app/sequences/."""
        seqs = []
        if APPS_SEQUENCES_DIR.exists():
            for p in APPS_SEQUENCES_DIR.glob("sequence_*.json"):
                try:
                    with open(p, "r") as f:
                        data = json.load(f)
                        if mode is None or data.get("mode") == mode or mode == "all":
                            seqs.append({
                                "name": data.get("name", p.stem),
                                "title": data.get("title", p.stem),
                                "description": data.get("description", ""),
                                "mode": data.get("mode", "demo"),
                                "steps_count": len(data.get("steps", [])),
                                "file": p.name,
                            })
                except Exception as e:
                    logging.warning("Error reading sequence %s: %s", p, e)
        return seqs

    def _drive_burst_helper(self, throttle: float = 0.85, duration_sec: float = 1.0) -> None:
        """Drives rover in a burst for duration_sec then cleanly commands stop (inverted throttle polarity)."""
        if self.rover_ctrl:
            try:
                self.rover_ctrl.set_drive(0.0, -throttle)
                time.sleep(duration_sec)
                self.rover_ctrl.set_drive(0.0, 0.0)
            except Exception as e:
                logging.warning("Rover drive burst helper error: %s", e)

    def _execute_arm_and_pedestal_sweep(
        self,
        start_s7_deg: float,
        end_s7_deg: float,
        target_arm_norm: Dict[str, float],
        duration_sec: float = 3.0,
        steps: int = 50,
        stop_event: Optional[threading.Event] = None,
    ) -> None:
        """Synchronously interpolates arm posture (Motors 1-6) and sweeps Servo 7 (pedestal) in lockstep under SERIAL_LOCK."""
        center_s7 = self.get_s7_center_ticks()
        with SERIAL_LOCK:
            if not self.bus:
                return
            ser = getattr(self.bus.port_handler, "ser", None)
            if ser and hasattr(ser, "reset_input_buffer"):
                ser.reset_input_buffer()
            start_arm = self.bus.sync_read("Present_Position") or {}

        dt = max(0.01, duration_sec / float(steps))
        motor_keys = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"]

        for s in range(1, steps + 1):
            if stop_event and stop_event.is_set():
                return
            alpha = s / float(steps)
            smooth_alpha = 0.5 * (1.0 - math.cos(math.pi * alpha))

            # Interpolate arm frame
            arm_frame = {}
            for k in motor_keys:
                s_val = float(start_arm.get(k, 0.0))
                t_val = float(target_arm_norm.get(k, s_val))
                arm_frame[k] = s_val + (t_val - s_val) * smooth_alpha

            # Interpolate Servo 7
            deg_s7 = start_s7_deg + (end_s7_deg - start_s7_deg) * smooth_alpha
            s7_tick = degrees_to_ticks_s7(deg_s7, center_ticks=center_s7)

            with SERIAL_LOCK:
                if self.bus and hasattr(self.bus, "sync_write"):
                    try:
                        self.bus.sync_write("Goal_Position", arm_frame)
                    except Exception:
                        pass
                if self.ctrl:
                    try:
                        self.ctrl.write_goal_raw(7, s7_tick, speed=500)
                    except Exception:
                        pass
                with self.lock:
                    self.servos[7]["pos"] = s7_tick
                    self.servos[7]["raw"] = s7_tick % 4096
                    self.servos[7]["torque"] = True
                    self.servos[7]["connected"] = True

            time.sleep(dt)

    def _execute_roar_pan_sweep(
        self,
        target_pan: float = 100.0,
        min_duration_sec: float = 1.5,
        home_duration_sec: float = 1.5,
        stop_event: Optional[threading.Event] = None,
    ) -> None:
        """Synchronously sweeps Motor 1 (shoulder_pan) target_pan->home across 3.0s without bus contention."""
        with SERIAL_LOCK:
            if not self.bus:
                return
            ser = getattr(self.bus.port_handler, "ser", None)
            if ser and hasattr(ser, "reset_input_buffer"):
                ser.reset_input_buffer()
            curr_norm = self.bus.sync_read("Present_Position") or {}

        start_pan = float(curr_norm.get("shoulder_pan", 0.0))
        target_peak_pan = float(target_pan)
        home_pan = 0.0
        steps_1 = 30
        steps_2 = 30
        dt_1 = max(0.01, min_duration_sec / float(steps_1))
        dt_2 = max(0.01, home_duration_sec / float(steps_2))

        # Half 1: Pan start -> target_peak_pan (+100.0)
        for s in range(1, steps_1 + 1):
            if stop_event and stop_event.is_set():
                return
            alpha = s / float(steps_1)
            smooth_alpha = 0.5 * (1.0 - math.cos(math.pi * alpha))
            pan_val = start_pan + (target_peak_pan - start_pan) * smooth_alpha

            frame = dict(curr_norm)
            frame["shoulder_pan"] = max(-100.0, min(100.0, pan_val))

            with SERIAL_LOCK:
                if self.bus and hasattr(self.bus, "sync_write"):
                    try:
                        self.bus.sync_write("Goal_Position", frame)
                    except Exception as e:
                        logging.debug("Sync write error in roar pan sweep: %s", e)

            time.sleep(dt_1)

        # Half 2: Pan target_peak_pan -> home (0.0)
        for s in range(1, steps_2 + 1):
            if stop_event and stop_event.is_set():
                return
            alpha = s / float(steps_2)
            smooth_alpha = 0.5 * (1.0 - math.cos(math.pi * alpha))
            pan_val = target_peak_pan + (home_pan - target_peak_pan) * smooth_alpha

            frame = dict(curr_norm)
            frame["shoulder_pan"] = max(-100.0, min(100.0, pan_val))

            with SERIAL_LOCK:
                if self.bus and hasattr(self.bus, "sync_write"):
                    try:
                        self.bus.sync_write("Goal_Position", frame)
                    except Exception as e:
                        logging.debug("Sync write error in roar pan sweep: %s", e)

            time.sleep(dt_2)

    def execute_sequence(self, sequence_name_or_dict: Any, mode: str = "demo") -> Tuple[bool, str]:
        """Executes a multi-step sequence timeline from JSON definition."""
        if isinstance(sequence_name_or_dict, str):
            seq_path = get_sequence_fpath(sequence_name_or_dict)
            if not seq_path.exists():
                return False, f"Sequence file {seq_path} not found"
            try:
                with open(seq_path, "r") as f:
                    seq_data = json.load(f)
            except Exception as e:
                return False, f"Failed to load sequence: {e}"
        elif isinstance(sequence_name_or_dict, dict):
            seq_data = sequence_name_or_dict
        else:
            return False, "Invalid sequence specification"

        seq_name = seq_data.get("name", "unnamed_sequence")
        if seq_name in ["sequence_attack", "attack_piranha_plant", "attack"]:
            return self.execute_attack_sequence()

        self.stop_sequence()
        self._sequence_stop_event.clear()
        self._sequence_running = True

        try:
            center_s7 = self.get_s7_center_ticks()
            steps = seq_data.get("steps", [])
            for idx, step in enumerate(steps):
                if self._sequence_stop_event.is_set():
                    return False, "Sequence aborted"

                sname = step.get("step_name", f"step_{idx+1}")
                logging.info("[SEQUENCE %s] Running %s", seq_name, sname)

                # Audio trigger
                audio = step.get("audio")
                if audio and isinstance(audio, dict):
                    kind = audio.get("kind", "connect")
                    wav_path = audio.get("wav_path")
                    delay_sec = float(audio.get("delay_sec", 0.0))
                    stop_prev = bool(audio.get("stop_previous", True))
                    dispatch_audio_event(kind=kind, wav_path=wav_path, stop_previous=stop_prev, delay_sec=delay_sec)

                # Check if this step commands both arm preset and Servo 7
                preset = step.get("preset")
                has_s7 = "servo7_deg" in step
                s7_deg = float(step["servo7_deg"]) if has_s7 else None

                if preset and (s7_deg is not None):
                    arm_dur = float(step.get("arm_duration", step.get("duration", 1.5)))
                    target_s7 = degrees_to_ticks_s7(s7_deg, center_ticks=center_s7)
                    speed_s7 = max(100, int(abs(s7_deg) / max(0.1, arm_dur) * 11.37))
                    self.move_target(7, target_s7, speed=speed_s7)
                    self.move_to_specific_arm_preset(preset, duration=arm_dur, mode=mode)
                elif preset:
                    arm_dur = float(step.get("arm_duration", step.get("duration", 1.0)))
                    self.move_to_specific_arm_preset(preset, duration=arm_dur, mode=mode)
                elif s7_deg is not None:
                    s7_dur = float(step.get("servo7_duration", step.get("duration", 0.5)))
                    s7_speed = int(step.get("servo7_speed", 500))
                    target_s7 = degrees_to_ticks_s7(s7_deg, center_ticks=center_s7)
                    self.move_target(7, target_s7, speed=s7_speed)
                    time.sleep(s7_dur)

                # Pause
                pause_sec = float(step.get("pause_sec", 0.0))
                if pause_sec > 0:
                    time.sleep(pause_sec)

            return True, f"Sequence {seq_name} executed successfully"
        finally:
            self._sequence_running = False

    def execute_attack_sequence(self) -> Tuple[bool, str]:
        """Executes the full 8-step Piranha Plant Attack choreography."""
        self.stop_sequence()
        self._sequence_stop_event.clear()
        self._sequence_running = True

        try:
            center_s7 = self.get_s7_center_ticks()

            # Load Demo presets for keyframes strictly from disk JSON
            demo_presets = self.get_arm_presets(mode="demo")
            required_keyframes = ["lunge", "ready", "roar", "pose_1"]
            for rk in required_keyframes:
                if rk not in demo_presets or not demo_presets[rk].get("normalized"):
                    dispatch_audio_event(kind="smw_pipe", stop_previous=True)
                    err_msg = f"Attack sequence aborted: Required keyframe '{rk}' is missing from presets_demo.json"
                    logging.error(err_msg)
                    return False, err_msg

            lunge_norm = demo_presets["lunge"]["normalized"]
            ready_norm = demo_presets["ready"]["normalized"]
            roar_norm = demo_presets["roar"]["normalized"]
            home_norm = demo_presets["pose_1"]["normalized"]

            # Step 1: Lunge + Rover Drive burst
            if self._sequence_stop_event.is_set():
                return False, "Aborted"
            logging.info("[ATTACK SEQ] Step 1: Lunge forward")
            dispatch_audio_event(kind="connect", stop_previous=True)
            t_drive = threading.Thread(target=self._drive_burst_helper, kwargs={"throttle": 0.85, "duration_sec": 1.0}, daemon=True)
            t_drive.start()
            self.interpolate_arm_norm(lunge_norm, duration=1.0, steps=30, stop_event=self._sequence_stop_event)

            # Step 2: Pedestal right (+90°)
            if self._sequence_stop_event.is_set():
                return False, "Aborted"
            logging.info("[ATTACK SEQ] Step 2: Quick pedestal snap to +90°")
            target_s7_r = degrees_to_ticks_s7(90.0, center_ticks=center_s7)
            self.move_target(7, target_s7_r, speed=1000)
            time.sleep(0.3)

            # Step 3: Pedestal center (0.0°) + SMW blargg audio
            if self._sequence_stop_event.is_set():
                return False, "Aborted"
            logging.info("[ATTACK SEQ] Step 3: Pedestal return to center 0.0°")
            dispatch_audio_event(kind="smw_blargg", stop_previous=True)
            target_s7_c = degrees_to_ticks_s7(0.0, center_ticks=center_s7)
            self.move_target(7, target_s7_c, speed=1000)
            time.sleep(0.4)

            # Step 4: Sweep pedestal left (-90°) while moving arm to 'ready' stance
            if self._sequence_stop_event.is_set():
                return False, "Aborted"
            logging.info("[ATTACK SEQ] Step 4: Coordinated sweep to -90° in 'ready' stance")
            self._execute_arm_and_pedestal_sweep(
                start_s7_deg=0.0,
                end_s7_deg=-90.0,
                target_arm_norm=ready_norm,
                duration_sec=2.0,
                steps=40,
                stop_event=self._sequence_stop_event
            )

            # Step 5: Transition into roar posture
            if self._sequence_stop_event.is_set():
                return False, "Aborted"
            logging.info("[ATTACK SEQ] Step 5: Transition to 'roar' posture")
            self.interpolate_arm_norm(roar_norm, duration=0.8, steps=25, stop_event=self._sequence_stop_event)

            # Step 6: T-Rex Roar audio + simultaneous pedestal return & Motor 1 pan sweep
            if self._sequence_stop_event.is_set():
                return False, "Aborted"
            logging.info("[ATTACK SEQ] Step 6: Triggering T-Rex Roar audio and coordinated pan sweep")
            dispatch_audio_event(kind="trex_roar", stop_previous=True)

            target_s7_center = degrees_to_ticks_s7(0.0, center_ticks=center_s7)
            self.move_target(7, target_s7_center, speed=250)

            self._execute_roar_pan_sweep(
                target_pan=100.0,
                min_duration_sec=1.5,
                home_duration_sec=1.5,
                stop_event=self._sequence_stop_event
            )

            # Step 7: 0.5s pause post-audio completion
            if self._sequence_stop_event.is_set():
                return False, "Aborted"
            logging.info("[ATTACK SEQ] Step 7: Settle pause (0.5s post-audio)")
            time.sleep(1.75)

            # Step 8: Return to pose_1
            if self._sequence_stop_event.is_set():
                return False, "Aborted"
            logging.info("[ATTACK SEQ] Step 8: Returning robot back to position 1")
            target_s7_home = degrees_to_ticks_s7(0.0, center_ticks=center_s7)
            self.move_target(7, target_s7_home, speed=400)
            self.interpolate_arm_norm(home_norm, duration=1.2, steps=35, stop_event=self._sequence_stop_event)

            logging.info("[ATTACK SEQ] Completed Piranha Plant Attack sequence successfully.")
            return True, "Attack sequence completed"
        finally:
            self._sequence_running = False

    def stop_sequence(self) -> None:
        """Signals abort to any actively running sequence."""
        self._sequence_stop_event.set()
        self._sequence_running = False


    def move_target(
        self, sid: int, target_pos: int, step_size: int = 50, speed: int = 400, max_t: int = 1000
    ) -> Tuple[bool, str]:
        if sid == 8:
            gantry_min, gantry_max = self.get_s8_bounds()
            target_pos = max(gantry_min, min(gantry_max, int(target_pos)))

        with self.lock:
            if self.power_mgr and not self.power_mgr.is_connected():
                return False, f"Hardware Error: 12V bus is currently {self.power_mgr.state}."

            if sid not in [7, 8] and self.power_mgr and not getattr(self.power_mgr, "pogo_connected", True):
                return False, "Hardware Error: Pogo connector disconnected (Arm Servos 1-6 offline)."

            if not self.ctrl:
                return False, "Auxiliary Controller offline"

            if self.servos[sid].get("is_moving", False):
                logging.warning(f"Rejected move for Servo {sid}: Motor is currently executing a move.")
                return False, "Motor is currently executing a move. Request ignored."

            self.servos[sid]["torque"] = True
            self.servos[sid]["is_moving"] = True

        try:
            ctrl = self.ctrl
            if not ctrl:
                return False, "Hardware offline"

            ctrl.set_torque(sid, True, max_torque_enable=max_t)

            if sid == 8:
                gantry_min, gantry_max = self.get_s8_bounds()
                target_pos = max(gantry_min, min(gantry_max, int(target_pos)))

                with self.lock:
                    curr_pos = self.servos[8]["pos"]
                if curr_pos is None:
                    logging.error("Rejected move for Servo 8: Dead reckoning position state is uninitialized.")
                    return False, "Hardware Error: Motor 8 position uninitialized."

                delta = target_pos - curr_pos
                if delta != 0:
                    res = ctrl.set_position_multiturn(8, delta, speed=speed)
                    if res is None:
                        logging.error("Rejected move for Servo 8: Hardware write failed (12V Power OFF or Bus Error).")
                        return False, "Hardware write failed: No response from Motor 8 (Verify 12V Power Supply is ON)."

                    with self.lock:
                        self.servos[8]["pos"] = target_pos
                        self.servos[8]["raw"] = target_pos % 4096
                        self.servos[8]["torque"] = True
                        self.servos[8]["connected"] = True
                        self.aux_positions[8] = target_pos
                    self.save_state()
            else:
                if sid == 7:
                    center_t = self.get_s7_center_ticks()
                    deg = ticks_to_degrees_s7(target_pos, center_ticks=center_t)
                    clamped_deg = max(-165.0, min(165.0, deg))
                    target_pos = degrees_to_ticks_s7(clamped_deg, center_ticks=center_t)

                res = ctrl.write_goal_raw(sid, target_pos, speed=speed)
                if res is None:
                    logging.error(f"Rejected move for Servo {sid}: Serial write failed.")
                    return False, f"Hardware Error: Servo {sid} write failed."

                with self.lock:
                    self.servos[sid]["pos"] = target_pos
                    self.servos[sid]["raw"] = target_pos % 4096
                    self.servos[sid]["torque"] = True
                    self.servos[sid]["connected"] = True

            self.save_state()
            return True, "OK"
        finally:
            with self.lock:
                self.servos[sid]["is_moving"] = False

    def step_pedestal_preset(self, direction: str) -> Tuple[bool, bool, str, Optional[float], Optional[int], bool]:
        """Calculates next preset angle relative to live Servo 7 angle and executes move.
        Returns (ok, moved, msg, target_deg, target_ticks, at_limit).
        """
        center_s7 = self.get_s7_center_ticks()
        with self.lock:
            curr_pos = self.aux_positions.get(7)
            if curr_pos is None and hasattr(self, "sync_servo7_position"):
                curr_pos = self.sync_servo7_position()
            if curr_pos is None:
                return False, False, "Hardware Error: Servo 7 position is uninitialized", None, None, False
            curr_deg = ticks_to_degrees_s7(curr_pos, center_ticks=center_s7)
            target_deg, at_limit = calc_next_s7_preset(curr_deg, direction)
            target_ticks = degrees_to_ticks_s7(target_deg, center_ticks=center_s7)

        if at_limit:
            curr_idx = min(range(len(PEDESTAL_PRESETS)), key=lambda i: abs(curr_deg - PEDESTAL_PRESETS[i]))
            if PEDESTAL_PRESETS[curr_idx] == target_deg:
                return True, False, f"Pedestal limit reached ({target_deg}°)", target_deg, target_ticks, True

        ok, msg = self.move_target(7, target_ticks, step_size=50, speed=400, max_t=500)
        return ok, ok, msg, target_deg, target_ticks, at_limit


    def dispatch_dance_frame(
        self,
        rom_posture: Dict[str, float],
        s7_rom: Optional[float] = None,
        s8_goal: Optional[Union[float, int]] = None,
        s8_is_rom: bool = True,
        s8_speed: int = 500,
    ) -> Dict[str, Any]:
        """Dispatches an atomic multi-servo 0-100% ROM frame to Motors 1-8.
        Encapsulates SERIAL_LOCK, tick conversions, and bus writes internally.
        """
        arm_calib = getattr(self, "arm_calibration", {})
        goal_ticks = {}
        for mname in ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"]:
            if mname in rom_posture:
                if mname not in arm_calib:
                    raise KeyError(f"Fail-Fast Error: Calibration missing for arm motor '{mname}'")
                m_obj = arm_calib[mname]
                if isinstance(m_obj, dict):
                    if "range_min" not in m_obj or "range_max" not in m_obj:
                        raise KeyError(f"Fail-Fast Error: 'range_min' or 'range_max' missing in calibration for '{mname}'")
                    r_min = int(m_obj["range_min"])
                    r_max = int(m_obj["range_max"])
                else:
                    if not hasattr(m_obj, "range_min") or not hasattr(m_obj, "range_max"):
                        raise KeyError(f"Fail-Fast Error: 'range_min' or 'range_max' attribute missing on calibration object for '{mname}'")
                    r_min = int(m_obj.range_min)
                    r_max = int(m_obj.range_max)
                clamped_rom = max(0.0, min(100.0, float(rom_posture[mname])))
                ticks = int(round(r_min + (clamped_rom / 100.0) * (r_max - r_min)))
                goal_ticks[mname] = ticks

        s7_ticks = None
        if s7_rom is not None:
            aux_calib = getattr(self, "aux_calibration", {})
            if "7" not in aux_calib:
                raise KeyError("Fail-Fast Error: Auxiliary calibration missing for Servo 7")
            if "min_ticks" not in aux_calib["7"] or "max_ticks" not in aux_calib["7"]:
                raise KeyError("Fail-Fast Error: 'min_ticks' or 'max_ticks' missing for Servo 7 in aux_calibration")
            s7_min = int(aux_calib["7"]["min_ticks"])
            s7_max = int(aux_calib["7"]["max_ticks"])
            clamped_s7 = max(0.0, min(100.0, float(s7_rom)))
            s7_ticks = int(round(s7_min + (clamped_s7 / 100.0) * (s7_max - s7_min)))

        s8_ticks = None
        if s8_goal is not None:
            g_min, g_max = self.get_s8_bounds()
            if s8_is_rom:
                clamped_s8 = max(0.0, min(100.0, float(s8_goal)))
                s8_ticks = int(round(g_min + (clamped_s8 / 100.0) * (g_max - g_min)))
            else:
                s8_ticks = max(g_min, min(g_max, int(s8_goal)))

        with SERIAL_LOCK:
            if goal_ticks and self.bus and hasattr(self.bus, "sync_write"):
                try:
                    self.bus.sync_write("Goal_Position", goal_ticks, normalize=False)
                except Exception as ex:
                    logging.warning("sync_write Goal_Position error: %s", ex)

            if s7_ticks is not None and self.ctrl:
                last_s7 = getattr(self, "_last_dance_s7_ticks", None)
                if last_s7 is None or abs(s7_ticks - last_s7) >= 4:
                    try:
                        self.ctrl.write_goal_raw(7, s7_ticks, speed=800)
                        self._last_dance_s7_ticks = s7_ticks
                        self.aux_positions[7] = s7_ticks
                    except Exception as ex:
                        logging.warning("write_goal_raw S7 error: %s", ex)

            with self.lock:
                motor_name_to_id = {
                    "shoulder_pan": 1, "shoulder_lift": 2, "elbow_flex": 3,
                    "wrist_flex": 4, "wrist_roll": 5, "gripper": 6
                }
                for mname, rom_val in rom_posture.items():
                    sid = motor_name_to_id.get(mname)
                    if sid and sid in self.servos:
                        self.servos[sid]["normalized"] = round(float(rom_val), 2)
                        self.servos[sid]["torque"] = True
                if s7_rom is not None and 7 in self.servos:
                    self.servos[7]["normalized"] = round(float(s7_rom), 2)
                    if s7_ticks is not None:
                        self.servos[7]["pos"] = s7_ticks
                        self.servos[7]["raw"] = s7_ticks % 4096
                    self.servos[7]["torque"] = True

        if s8_ticks is not None:
            try:
                self.move_target(8, s8_ticks, speed=s8_speed, max_t=800)
            except Exception as ex:
                logging.warning("move_target S8 error: %s", ex)

        return {
            "status": "ok",
            "goal_ticks": goal_ticks,
            "s7_ticks": s7_ticks,
            "s8_ticks": s8_ticks,
        }

    def dispatch_teleop_frame(self, norm_pos: Dict[str, float]) -> None:
        """Dispatches an atomic multi-servo normalized (-100 to 100) teleop frame.
        Encapsulates SERIAL_LOCK internally.
        """
        with SERIAL_LOCK:
            if self.bus and hasattr(self.bus, "sync_write"):
                try:
                    self.bus.sync_write("Goal_Position", norm_pos)
                except Exception as ex:
                    import logging
                    logging.warning("teleop sync_write error: %s", ex)

    def close(self) -> None:
        self.stop_sequence()
        if self.rover_ctrl:
            try:
                self.rover_ctrl.shutdown()
            except Exception as e:
                logging.warning("Error shutting down rover controller: %s", e)
        if self.power_mgr:
            self.power_mgr.stop()

        self.disable_all_torque()

        try:
            if self.bus and hasattr(self.bus, "disconnect"):
                with SERIAL_LOCK:
                    self.bus.disconnect()
        except Exception as e:
            logging.error(f"Error disconnecting motor bus: {e}")

        self.hardware_active = False
        logging.info("RobotBackend shutdown complete.")
