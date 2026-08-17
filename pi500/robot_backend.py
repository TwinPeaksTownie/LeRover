#!/usr/bin/env python3
"""RobotBackend module for SO-101 arm and auxiliary servos (Motors 1-8).
Manages low-level Feetech serial bus and AuxiliaryServoController hardware access.
Maintains unified, authoritative motor telemetry across all 8 servos.
"""

import json
import logging
import math
import os
import threading
import time
from pathlib import Path
from typing import Dict, Any, Tuple, Optional

from aux_servo_controller import AuxiliaryServoController
from power_manager import BusPowerManager
from telemetry_proxies import _ServoFieldProxy, _ServoMotorStatesProxy, MOTOR_NAMES
from lerobot.motors import Motor, MotorCalibration, MotorNormMode
from lerobot.motors.feetech import FeetechMotorsBus

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
    if fpath.exists():
        try:
            with open(fpath, "r") as f:
                return json.load(f)
        except Exception as e:
            logging.warning("Failed to read calibration_aux.json: %s", e)

    default_aux = {
        "7": {"min_ticks": 0, "max_ticks": 4095, "center_ticks": 2048},
        "8": {"min_ticks": 3, "max_ticks": 4800},
    }
    try:
        fpath.parent.mkdir(parents=True, exist_ok=True)
        with open(fpath, "w") as f:
            json.dump(default_aux, f, indent=2)
    except Exception as e:
        logging.warning("Failed to write default calibration_aux.json: %s", e)
    return default_aux


def ticks_to_degrees_s7(ticks: int, center_ticks: int = 2048) -> float:
    """Converts reported Motor 7 hardware ticks (0-4095) to intuitive degrees relative to calibrated center_ticks."""
    deg = (int(ticks) - int(center_ticks)) * 360.0 / 4096.0
    while deg > 180.0:
        deg -= 360.0
    while deg <= -180.0:
        deg += 360.0
    return round(deg, 1)


def degrees_to_ticks_s7(deg: float, center_ticks: int = 2048) -> int:
    """Converts intuitive degrees to reported Motor 7 hardware ticks with a hard safety clamp of [-165.0, +165.0] degrees."""
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
                    for sid_str, pos in data.items():
                        sid = int(sid_str)
                        if sid == 8:
                            self.gantry_position = int(pos)
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

            # Initialize dedicated single-responsibility BusPowerManager
            self.power_mgr = BusPowerManager(self.ctrl, on_resync_callback=self._execute_hardware_resync)
            self.power_mgr.start()
        except Exception as e:
            logging.error("Failed to connect Auxiliary Controller: %s", e)
            self.ctrl = None
            err = f"Aux Controller Error: {e}"
            self.error_msg = f"{self.error_msg} | {err}" if self.error_msg else err

        return self.hardware_active

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

    def sync_servo8_position(self) -> Optional[int]:
        """Ensures Motor 8 dead reckoning state is clamped to calibrated rail bounds [3, 4800]."""
        with self.lock:
            if not self.ctrl:
                self.servos[8]["connected"] = False
                self.servos[8]["error"] = "AuxiliaryServoController uninitialized"
                return None

            curr = self.servos[8]["pos"]
            if curr is None:
                self.servos[8]["connected"] = False
                self.servos[8]["error"] = "Dead reckoning state uninitialized"
                logging.error("Cannot sync Motor 8: dead reckoning position state is uninitialized.")
                return None

            gantry_min = self.aux_calibration.get("8", {}).get("min_ticks", 3)
            gantry_max = self.aux_calibration.get("8", {}).get("max_ticks", 4800)
            real_pos = max(gantry_min, min(gantry_max, int(curr)))
            self.servos[8]["pos"] = real_pos
            self.servos[8]["raw"] = real_pos % 4096
            self.servos[8]["connected"] = True
            self.servos[8]["error"] = None
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

    def move_target(
        self, sid: int, target_pos: int, step_size: int = 50, speed: int = 400, max_t: int = 1000
    ) -> Tuple[bool, str]:
        if sid == 8:
            gantry_min = self.aux_calibration.get("8", {}).get("min_ticks", 3)
            gantry_max = self.aux_calibration.get("8", {}).get("max_ticks", 4800)
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
                gantry_min = self.aux_calibration.get("8", {}).get("min_ticks", 3)
                gantry_max = self.aux_calibration.get("8", {}).get("max_ticks", 4800)
                target_pos = max(gantry_min, min(gantry_max, int(target_pos)))
                with self.lock:
                    curr_pos = self.servos[8]["pos"]
                if curr_pos is None:
                    logging.error("Rejected move for Servo 8: Dead reckoning position state is uninitialized.")
                    return False, "Hardware Error: Motor 8 position uninitialized."
                delta = target_pos - curr_pos

                if delta == 0:
                    return True, "OK"

                curr_hw = ctrl.get_position_multiturn(8)
                if curr_hw is None:
                    logging.error("Failed to read Motor 8 hardware position phase for offset calculation.")
                    return False, "Hardware Error: Failed to read Motor 8 position phase."

                hw_target = curr_hw + delta
                res = ctrl.set_position_multiturn(8, hw_target, speed=speed)
                if res is None:
                    logging.error(f"Rejected move for Servo {sid}: Hardware write failed (12V Power OFF or Bus Error).")
                    return False, "Hardware write failed: No response from Motor 8 (Verify 12V Power Supply is ON)."

                with self.lock:
                    self.servos[8]["pos"] = target_pos
                    self.servos[8]["raw"] = target_pos % 4096
                    self.servos[8]["torque"] = True
                    self.servos[8]["connected"] = True
            else:
                if sid == 7:
                    center_t = self.aux_calibration.get("7", {}).get("center_ticks", 2048) if hasattr(self, "aux_calibration") else 2048
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
        center_s7 = self.aux_calibration.get("7", {}).get("center_ticks", 2048) if hasattr(self, "aux_calibration") else 2048
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


    def close(self) -> None:
        if self.power_mgr:
            self.power_mgr.stop()
        try:
            if self.bus and hasattr(self.bus, "disable_torque"):
                with SERIAL_LOCK:
                    self.bus.disable_torque(num_retry=2)
        except Exception as e:
            logging.error(f"Error disabling motor torque: {e}")

        try:
            if self.bus and hasattr(self.bus, "disconnect"):
                with SERIAL_LOCK:
                    self.bus.disconnect()
        except Exception as e:
            logging.error(f"Error disconnecting motor bus: {e}")

        self.hardware_active = False
        logging.info("RobotBackend shutdown complete.")
