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
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))
sys.path.insert(0, str(Path(__file__).parent.resolve()))
sys.path.append(str(Path.home() / "so101"))

import network_resolver

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

from audio_resolver import dispatch_audio_event

BASE_DIR = Path.home() / "so101"
STATE_FILE = str(BASE_DIR / "gantry_state.json")
AUX_CALIB_FILE = str(BASE_DIR / "calibration_aux.json")
SERIAL_LOCK = threading.RLock()
NAME_TO_ID = {v: k for k, v in MOTOR_NAMES.items()}


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


def pct_to_ticks_s7(pct: float, aux_calib: dict) -> int:
    """Converts unipolar percentage (0.0 to 100.0%) to Motor 7 hardware ticks dynamically from aux_calib."""
    s7_min = int(aux_calib["7"]["min_ticks"])
    s7_max = int(aux_calib["7"]["max_ticks"])
    clamped = max(0.0, min(100.0, float(pct)))
    return int(round(s7_min + (clamped / 100.0) * (s7_max - s7_min)))


def ticks_to_pct_s7(ticks: int, aux_calib: dict) -> float:
    """Converts Motor 7 hardware ticks to unipolar percentage (0.0 to 100.0%) dynamically from aux_calib."""
    s7_min = int(aux_calib["7"]["min_ticks"])
    s7_max = int(aux_calib["7"]["max_ticks"])
    span = max(1, s7_max - s7_min)
    return round(max(0.0, min(100.0, ((int(ticks) - s7_min) / span) * 100.0)), 1)


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


PEDESTAL_PRESETS = [0.0, 12.5, 25.0, 37.5, 50.0, 62.5, 75.0, 87.5, 100.0]


def calc_next_s7_preset(curr_pct: float, direction: str) -> Tuple[float, bool]:
    """Calculates next clean preset percentage relative to current physical hardware position
    using nearest-slot snapping and hard bumper stops.
    Returns (target_pct, at_limit).
    """
    direction = str(direction).lower()
    curr_idx = min(range(len(PEDESTAL_PRESETS)), key=lambda i: abs(curr_pct - PEDESTAL_PRESETS[i]))
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
    with open(fpath, "r", encoding="utf-8-sig") as f:
        raw = json.load(f)
    return {motor: MotorCalibration(**vals) for motor, vals in raw.items()}


def make_bus(port: str, calibration: dict[str, MotorCalibration]) -> FeetechMotorsBus:
    norm_mode_body = MotorNormMode.RANGE_0_100
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

    def __init__(self, port: Optional[str] = None, robot_id: str = "follower") -> None:
        if port is None:
            self.port = network_resolver.get_hardware_serial_port()
        else:
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
        self.is_busy: bool = False
        self.active_port: str = port
        self.error_msg: Optional[str] = None
        self.power_mgr: Optional[BusPowerManager] = None
        self._shutdown_event = threading.Event()
        self._telemetry_thread: Optional[threading.Thread] = None
        self._last_dance_s7_ticks: Optional[int] = None
        self._interpolation_lock = threading.Lock()

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
                    k_str = str(k)
                    sid = None
                    if k_str in motor_name_map:
                        sid = motor_name_map[k_str]
                    elif isinstance(k, int):
                        sid = k
                    if sid is not None and 1 <= sid <= 6:
                        if v is not None:
                            self.servos[sid]["normalized"] = float(v)
                        else:
                            self.servos[sid]["normalized"] = None

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

        max_attempts = network_resolver.get_bus_reconnect_max_attempts()
        backoff_sec = network_resolver.get_bus_reconnect_backoff_sec()

        for attempt in range(max_attempts):
            try:
                self.bus = make_bus(self.port, self.arm_calibration)
                with SERIAL_LOCK:
                    self.bus.connect()
                    time.sleep(backoff_sec)
                    ser = None
                    if hasattr(self.bus, "port_handler"):
                        ph = self.bus.port_handler
                        if hasattr(ph, "ser"):
                            ser = ph.ser
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
                time.sleep(backoff_sec * (attempt + 1))

        if not self.hardware_active:
            logging.warning("Arm motor connection failed after %d attempts; flagging bus fault state.", max_attempts)
            self.error_msg = f"Arm motors offline after {max_attempts} connection retries"

        try:
            ser_handle = None
            if self.bus and hasattr(self.bus, "port_handler"):
                ph = self.bus.port_handler
                if hasattr(ph, "ser"):
                    ser_handle = ph.ser
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
                is_busy_callback=lambda: bool(self.is_busy or self.follower_active),
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
            if not self.hardware_active or self.bus is None or self.is_busy or self.follower_active:
                continue

            # Gating: Suppress telemetry queries when 12V bus power is lost to eliminate half-duplex collisions
            if self.power_mgr and not self.power_mgr.is_connected():
                continue

            # Safely acquire SERIAL_LOCK for a fast sync_read
            try:
                with SERIAL_LOCK:
                    if self.is_busy or self.follower_active or not self.hardware_active or self.bus is None:
                        continue
                    ser = None
                    if hasattr(self.bus, "port_handler"):
                        ph = self.bus.port_handler
                        if hasattr(ph, "ser"):
                            ser = ph.ser
                    if ser and hasattr(ser, "reset_input_buffer"):
                        ser.reset_input_buffer()

                    norm_dict = self.bus.sync_read("Present_Position")
                    raw_dict = self.bus.sync_read("Present_Position", normalize=False)

                if norm_dict:
                    with self.lock:
                        for k, v in norm_dict.items():
                            k_str = str(k)
                            sid = None
                            if k_str in motor_ids:
                                sid = motor_ids[k_str]
                            elif isinstance(k, int):
                                sid = k
                            if sid is not None and 1 <= sid <= 6:
                                self.servos[sid]["normalized"] = round(float(v), 2)
                                self.servos[sid]["connected"] = True

                if raw_dict:
                    with self.lock:
                        for k, v in raw_dict.items():
                            k_str = str(k)
                            sid = None
                            if k_str in motor_ids:
                                sid = motor_ids[k_str]
                            elif isinstance(k, int):
                                sid = k
                            if sid is not None and 1 <= sid <= 6:
                                self.servos[sid]["raw"] = int(v)
                                self.servos[sid]["pos"] = int(v)

                # Periodically refresh Servo 7 angle if idle
                loop_count += 1
                if loop_count % 3 == 0 and not self.is_busy and not self.follower_active:
                    with SERIAL_LOCK:
                        if not self.is_busy and not self.follower_active:
                            self.sync_servo7_position()

            except Exception as e:
                logging.debug("Background telemetry loop exception: %s", e)

    def _execute_hardware_resync(self) -> bool:
        """Hardware recovery sequence executed by BusPowerManager upon 12V restoration."""
        if not self.ctrl:
            return False
        try:
            with SERIAL_LOCK:
                # 1. Purge serial buffers across controller and bus handlers
                self.ctrl.flush_buffers()
                ser = None
                if self.bus and hasattr(self.bus, "port_handler"):
                    ph = self.bus.port_handler
                    if hasattr(ph, "ser"):
                        ser = ph.ser
                if ser and hasattr(ser, "reset_input_buffer"):
                    ser.reset_input_buffer()
                    ser.reset_output_buffer()

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
            except Exception as e:
                logging.debug("Error reading pos 7 during alarm clear retry: %s", e)

        if pos is not None:
            with self.lock:
                self.servos[7]["pos"] = pos
                self.servos[7]["raw"] = pos % 4096
                self.servos[7]["normalized"] = ticks_to_pct_s7(pos, self.aux_calibration)
                self.servos[7]["connected"] = True
                self.servos[7]["error"] = None
                if self.error_msg and "Servo 7" in self.error_msg:
                    self.error_msg = None
                logging.info(f"Synchronized Motor 7 baseline from hardware: {pos} ticks ({self.servos[7]['normalized']}%)")
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

    def get_s7_bounds(self) -> Tuple[int, int]:
        if not hasattr(self, "aux_calibration") or "7" not in self.aux_calibration or "min_ticks" not in self.aux_calibration["7"] or "max_ticks" not in self.aux_calibration["7"]:
            raise RuntimeError("Servo 7 calibration missing in calibration_aux.json")
        return int(self.aux_calibration["7"]["min_ticks"]), int(self.aux_calibration["7"]["max_ticks"])

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
            ser = None
            if hasattr(self.bus, "port_handler"):
                ph = self.bus.port_handler
                if hasattr(ph, "ser"):
                    ser = ph.ser
            if ser and hasattr(ser, "reset_input_buffer"):
                try:
                    ser.reset_input_buffer()
                    ser.reset_output_buffer()
                except Exception as e:
                    logging.debug("Buffer reset warning in _configure_bus: %s", e)

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
                            k_str = str(k)
                            sid = None
                            if k_str in motor_ids:
                                sid = motor_ids[k_str]
                            elif isinstance(k, int):
                                sid = k
                            if sid is not None and 1 <= sid <= 6:
                                self.servos[sid]["normalized"] = float(v)
                                self.servos[sid]["connected"] = True
                if raw_ticks:
                    with self.lock:
                        for k, v in raw_ticks.items():
                            k_str = str(k)
                            sid = None
                            if k_str in motor_ids:
                                sid = motor_ids[k_str]
                            elif isinstance(k, int):
                                sid = k
                            if sid is not None and 1 <= sid <= 6:
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
                ser = None
                if hasattr(self.bus, "port_handler"):
                    ph = self.bus.port_handler
                    if hasattr(ph, "ser"):
                        ser = ph.ser
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
                            k_str = str(k)
                            sid = None
                            if k_str in motor_ids:
                                sid = motor_ids[k_str]
                            elif isinstance(k, int):
                                sid = k
                            if sid is not None and 1 <= sid <= 6:
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

    def _recover_serial_bus(self) -> bool:
        """Recovers Feetech serial port from EIO / Port is in use states."""
        with SERIAL_LOCK:
            if not self.bus:
                return False
            try:
                if hasattr(self.bus, "port_handler") and self.bus.port_handler:
                    ph = self.bus.port_handler
                    ph.is_using = False
                    if hasattr(ph, "ser") and ph.ser:
                        try:
                            ph.ser.close()
                        except Exception as close_err:
                            logging.debug("Port close exception during recovery: %s", close_err)
                    if hasattr(ph, "openPort"):
                        ph.openPort()
                    if hasattr(ph, "ser") and ph.ser:
                        try:
                            ph.ser.reset_input_buffer()
                            ph.ser.reset_output_buffer()
                        except Exception as flush_err:
                            logging.debug("Buffer flush exception during recovery: %s", flush_err)
                logging.info("Feetech serial bus handler recovered cleanly.")
                return True
            except Exception as rec_err:
                logging.warning("Serial bus recovery failed: %s", rec_err)
                return False

    def set_arm_torque(self, enable: bool) -> bool:
        """Cleanly enables or disables torque on Arm Servos 1-6 using normalized positions."""
        with SERIAL_LOCK:
            if not self.bus:
                return False
            num_retry = network_resolver.get_serial_retry_attempts()
            if enable:
                ser = None
                if hasattr(self.bus, "port_handler"):
                    ph = self.bus.port_handler
                    if hasattr(ph, "ser"):
                        ser = ph.ser
                if ser and hasattr(ser, "reset_input_buffer"):
                    try:
                        ser.reset_input_buffer()
                    except Exception as e:
                        logging.warning("reset_input_buffer warning: %s", e)
                # Read current normalized positions to sync goals prior to torque enable
                current_norm = self.bus.sync_read("Present_Position")
                if current_norm and hasattr(self.bus, "sync_write"):
                    try:
                        self.bus.sync_write("Goal_Position", current_norm)
                    except Exception as e:
                        logging.warning("sync_write Goal_Position warning: %s", e)
                if hasattr(self.bus, "enable_torque"):
                    try:
                        self.bus.enable_torque(num_retry=num_retry)
                    except Exception as e:
                        logging.warning("enable_torque encountered error (%s); attempting port recovery...", e)
                        self._recover_serial_bus()
                        try:
                            self.bus.enable_torque(num_retry=num_retry)
                        except Exception as err2:
                            logging.error("enable_torque recovery attempt failed: %s", err2)
                with self.lock:
                    for sid in range(1, 7):
                        self.servos[sid]["torque"] = True
                    self.follower_active = True
                logging.info("Arm torque re-engaged on Servos 1-6 (holding current pose).")
            else:
                try:
                    if hasattr(self.bus, "disable_torque"):
                        self.bus.disable_torque(num_retry=num_retry)
                except Exception as e:
                    logging.warning("disable_torque encountered serial error (%s); attempting port recovery...", e)
                    self._recover_serial_bus()
                    try:
                        if hasattr(self.bus, "disable_torque"):
                            self.bus.disable_torque(num_retry=num_retry)
                    except Exception as err2:
                        logging.error("disable_torque recovery attempt failed: %s", err2)
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
            ser = None
            if self.bus and hasattr(self.bus, "port_handler"):
                ph = self.bus.port_handler
                if hasattr(ph, "ser"):
                    ser = ph.ser
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


    def interpolate_arm_norm(
        self,
        target_norm: Dict[str, float],
        duration: float = 1.0,
        steps: int = 40,
        stop_event: Optional[threading.Event] = None,
    ) -> Tuple[bool, str]:
        """Core cosine S-curve interpolation engine for Arm Motors 1-6."""
        if not self._interpolation_lock.acquire(blocking=False):
            return False, "Interpolation engine is already busy"
        self.is_busy = True
        try:
            with SERIAL_LOCK:
                if not self.bus:
                    return False, "Motor bus uninitialized"

                ser = None
                if hasattr(self.bus, "port_handler"):
                    ph = self.bus.port_handler
                    if hasattr(ph, "ser"):
                        ser = ph.ser
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
                    clamped = max(0.0, min(100.0, val))
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
                final_norm = None
                raw_ticks = None
                if self.bus:
                    final_norm = self.bus.sync_read("Present_Position")
                    raw_ticks = self.bus.sync_read("Present_Position", normalize=False)

            motor_ids = {"shoulder_pan": 1, "shoulder_lift": 2, "elbow_flex": 3, "wrist_flex": 4, "wrist_roll": 5, "gripper": 6}
            with self.lock:
                if final_norm:
                    for k, v in final_norm.items():
                        k_str = str(k)
                        sid = None
                        if k_str in motor_ids:
                            sid = motor_ids[k_str]
                        elif isinstance(k, int):
                            sid = k
                        if sid is not None and 1 <= sid <= 6:
                            self.servos[sid]["normalized"] = float(v)
                if raw_ticks:
                    for k, v in raw_ticks.items():
                        k_str = str(k)
                        sid = None
                        if k_str in motor_ids:
                            sid = motor_ids[k_str]
                        elif isinstance(k, int):
                            sid = k
                        if sid is not None and 1 <= sid <= 6:
                            self.servos[sid]["raw"] = int(v)
                            self.servos[sid]["pos"] = int(v)

            return True, "OK"
        finally:
            self.is_busy = False
            self._interpolation_lock.release()




    def move_target(
        self, sid: int, target_pos: int, step_size: int = 50, speed: int = 400, max_t: int = 1000
    ) -> Tuple[bool, str]:
        if sid == 7:
            s7_min, s7_max = self.get_s7_bounds()
            target_pos = max(s7_min, min(s7_max, int(target_pos)))
        elif sid == 8:
            gantry_min, gantry_max = self.get_s8_bounds()
            target_pos = max(gantry_min, min(gantry_max, int(target_pos)))

        with self.lock:
            if self.power_mgr and not self.power_mgr.is_connected():
                return False, f"Hardware Error: 12V bus is currently {self.power_mgr.state}."

            if sid not in [7, 8] and self.power_mgr:
                pogo_ok = True
                if hasattr(self.power_mgr, "pogo_connected"):
                    pogo_ok = self.power_mgr.pogo_connected
                if not pogo_ok:
                    return False, "Hardware Error: Pogo connector disconnected (Arm Servos 1-6 offline)."

            if not self.ctrl:
                return False, "Auxiliary Controller offline"

            is_moving = False
            if "is_moving" in self.servos[sid]:
                is_moving = self.servos[sid]["is_moving"]
            if is_moving:
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
                    s7_min, s7_max = self.get_s7_bounds()
                    target_pos = max(s7_min, min(s7_max, int(target_pos)))

                res = ctrl.write_goal_raw(sid, target_pos, speed=speed)
                if res is None:
                    logging.error(f"Rejected move for Servo {sid}: Serial write failed.")
                    return False, f"Hardware Error: Servo {sid} write failed."

                with self.lock:
                    self.servos[sid]["pos"] = target_pos
                    self.servos[sid]["raw"] = target_pos % 4096
                    if sid == 7:
                        self.servos[7]["normalized"] = ticks_to_pct_s7(target_pos, self.aux_calibration)
                    self.servos[sid]["torque"] = True
                    self.servos[sid]["connected"] = True

            self.save_state()
            return True, "OK"
        finally:
            with self.lock:
                self.servos[sid]["is_moving"] = False

    def step_pedestal_preset(self, direction: str) -> Tuple[bool, bool, str, Optional[float], Optional[int], bool]:
        """Calculates next preset percentage relative to live Servo 7 percentage and executes move.
        Returns (ok, moved, msg, target_pct, target_ticks, at_limit).
        """
        aux_calib = self.aux_calibration
        with self.lock:
            curr_pos = self.aux_positions.get(7)
            if curr_pos is None and hasattr(self, "sync_servo7_position"):
                curr_pos = self.sync_servo7_position()
            if curr_pos is None:
                return False, False, "Hardware Error: Servo 7 position is uninitialized", None, None, False
            curr_pct = ticks_to_pct_s7(curr_pos, aux_calib)
            target_pct, at_limit = calc_next_s7_preset(curr_pct, direction)
            target_ticks = pct_to_ticks_s7(target_pct, aux_calib)

        if at_limit:
            curr_idx = min(range(len(PEDESTAL_PRESETS)), key=lambda i: abs(curr_pct - PEDESTAL_PRESETS[i]))
            if PEDESTAL_PRESETS[curr_idx] == target_pct:
                return True, False, f"Pedestal limit reached ({target_pct}%)", target_pct, target_ticks, True

        ok, msg = self.move_target(7, target_ticks, step_size=50, speed=400, max_t=500)
        return ok, ok, msg, target_pct, target_ticks, at_limit


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
        arm_calib = self.arm_calibration
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
            aux_calib = self.aux_calibration
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
                last_s7 = self._last_dance_s7_ticks
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
                        if mname in goal_ticks:
                            self.servos[sid]["pos"] = goal_ticks[mname]
                            self.servos[sid]["raw"] = goal_ticks[mname] % 4096
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

    disconnect = close
