#!/usr/bin/env python3
"""JoyConApp and JoyConService module running Nintendo Switch Right Joy-Con teleoperation.
Maintains package registration 'joycon_teleop_app' on disk while executing native Joy-Con HID report 0x30 driver.
Supports:
- Intrinsic daemon HID service (JoyConService) running 24/7 on /dev/hidraw* with auto-reconnection
- Mode Switching (Rule 13 Binary Mutual Exclusion):
  * Hold Button A for 2.0s -> ROVER Drivetrain Mode (armed + 'arm_rover' chime)
  * Click Button B once -> AUX Mode (Servos 7 & 8: Pedestal & Gantry + 'mode_switch_aux' chime)
- Persistent IDLE App Launching:
  * Hold Button A for 2.0s while inactive -> launches joycon_teleop_app in ROVER mode
  * Hold Button B for 2.0s -> stops active app and launches listener_app
- Ephemeral Listener and Beat Bandit Integration:
  * Single Click Button B -> start listening turn
  * Double Click Button B -> cancel/abort current recording or song and center robot
- Overlander-4 Rover Drivetrain Control:
  * Forward on R button (+1.0), Reverse on ZR trigger (-1.0)
  * Proportional steering on Right Stick X
  * Strict throttle-gated steering (neutral steering when idle)
  * SR / SL rising edge speed stepping (+/- 5%) with audible feedback
"""

import glob
import json
import logging
import math
import os
import sys
import threading
import time
import urllib.request
from pathlib import Path
from typing import Optional, Dict, Any, Tuple

# Ensure repo root and config directory are importable
current_dir = os.path.dirname(os.path.abspath(__file__))
workspace_root = os.path.abspath(os.path.join(current_dir, "..", ".."))
for p in [workspace_root, os.path.join(workspace_root, "config")]:
    if os.path.isdir(p) and p not in sys.path:
        sys.path.append(p)

try:
    from rover.rover_controller import RoverController
except ImportError:
    try:
        from rover_controller import RoverController
    except ImportError:
        RoverController = None

import audio_resolver
import network_resolver
from app_manager import BaseApp, AppMetadata
from robot_backend import RobotBackend

APP_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(APP_DIR, "config.json")


def load_joycon_config() -> dict:
    """Loads and validates Joy-Con teleoperation configuration under joycon_app package."""
    if not os.path.exists(CONFIG_PATH):
        raise FileNotFoundError(f"Missing required Joy-Con config: {CONFIG_PATH}")
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    # Fail-Fast Schema Validation via direct bracket indexing
    _ = cfg["name"]
    _ = cfg["title"]
    _ = cfg["description"]
    _ = cfg["version"]
    _ = cfg["tags"]
    _ = cfg["icon"]

    _ = int(cfg["hardware"]["vendor_id"])
    _ = int(cfg["hardware"]["product_ids"]["joycon_r"])
    _ = cfg["hardware"]["mac_address"]
    _ = float(cfg["hardware"]["poll_rate_hz"])
    _ = float(cfg["hardware"]["packet_timeout_sec"])
    _ = float(cfg["hardware"]["reconnect_delay_sec"])
    _ = float(cfg["hardware"]["init_step_delay_sec"])

    _ = float(cfg["control"]["deadzone"])
    _ = int(cfg["control"]["speed_step_pct"])
    _ = int(cfg["control"]["auto_zero_samples"])
    _ = int(cfg["control"]["gantry_step_ticks"])
    _ = float(cfg["control"]["aux_lock_duration_sec"])

    _ = float(cfg["imu"]["accel_scale_g"])
    _ = float(cfg["imu"]["gyro_scale_dps"])
    _ = float(cfg["imu"]["gyro_deadband_dps"])
    _ = float(cfg["imu"]["stationary_motion_threshold_g"])

    _ = float(cfg["gestures"]["a_hold_sec"])
    _ = float(cfg["gestures"]["b_hold_sec"])
    _ = float(cfg["gestures"]["b_double_tap_sec"])
    _ = float(cfg["gestures"]["arm_drivetrain_sec"])
    _ = float(cfg["gestures"]["arm_lockout_sec"])
    _ = float(cfg["gestures"]["chord_abort_sec"])
    _ = float(cfg["gestures"]["chord_click_suppress_sec"])

    _ = cfg["chimes"]["app_start"]
    _ = cfg["chimes"]["device_connect"]
    _ = cfg["chimes"]["disconnect"]
    _ = cfg["chimes"]["arm_rover"]
    _ = cfg["chimes"]["mode_switch_rover"]
    _ = cfg["chimes"]["mode_switch_aux"]
    _ = cfg["chimes"]["speed_up"]
    _ = cfg["chimes"]["speed_down"]
    _ = cfg["chimes"]["chord_abort"]

    _ = int(cfg["pairing"]["timeout_sec"])
    _ = int(cfg["pairing"]["scan_timeout_sec"])
    _ = bool(cfg["pairing"]["auto_remove_stale"])

    return cfg


_CONFIG = load_joycon_config()
MAC_ADDRESS = _CONFIG["hardware"]["mac_address"]
JOYCON_R_PID = int(_CONFIG["hardware"]["product_ids"]["joycon_r"])
VENDOR_ID = int(_CONFIG["hardware"]["vendor_id"])
API_URL = "http://127.0.0.1:8085"
TELEMETRY_FILE = "/tmp/joycon_telemetry.json"
LEGACY_TELEMETRY_FILE = "/tmp/pokeball_telemetry.json"


def load_joycon_calibration() -> Tuple[int, int, int, int, int, int]:
    """Loads empirical Joy-Con stick bounds and center calibrations from calibration_aux.json."""
    aux_candidates = [
        Path(APP_DIR).resolve().parent.parent / "calibration_aux.json",
        Path.home() / "so101" / "calibration_aux.json",
        Path("/home/carson/touch_ui/calibration_aux.json"),
        Path("/home/carson/so101/calibration_aux.json"),
    ]
    for p in aux_candidates:
        if p.exists():
            with open(p, "r", encoding="utf-8") as f:
                calib = json.load(f)
            sec = calib["joycon_joystick"]
            center_x = int(sec["center_x"])
            center_y = int(sec["center_y"])
            span_x = int(sec["span_x"])
            span_y = int(sec["span_y"])
            min_calib_raw = int(sec["min_calib_raw"])
            max_calib_raw = int(sec["max_calib_raw"])
            return center_x, center_y, span_x, span_y, min_calib_raw, max_calib_raw
    raise FileNotFoundError(f"Missing required calibration file: calibration_aux.json (searched: {aux_candidates})")


def load_joystick_calibration() -> Tuple[int, int]:
    """Loads empirical joystick center calibrations for backward-compatible tests."""
    center_x, center_y, _, _, _, _ = load_joycon_calibration()
    return center_x, center_y


def load_shake_detector_config() -> Dict[str, Any]:
    """Loads fail-fast shake detector configuration from preset_app/config.json."""
    candidates = [
        Path(APP_DIR).resolve().parent / "preset_app" / "config.json",
        Path("/home/carson/touch_ui/apps/preset_app/config.json"),
        Path("/home/user/so101/apps/preset_app/config.json"),
        Path(workspace_root) / "apps" / "preset_app" / "config.json",
    ]
    for p in candidates:
        if p.exists():
            with open(p, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            _ = float(cfg["shake_detector"]["shake_threshold_g"])
            _ = float(cfg["shake_detector"]["shake_cooldown_sec"])
            _ = float(cfg["shake_detector"]["shake_window_sec"])
            _ = float(cfg["shake_detector"]["baseline_alpha"])
            return cfg["shake_detector"]
    raise FileNotFoundError(f"Missing required preset_app config.json for shake detector: {candidates}")


def get_pi4b_sound_url() -> str:
    port = int(network_resolver.get_ports()["pi4b_http"])
    return f"http://127.0.0.1:{port}/api/play_sound"


def play_chime(event_name: str) -> None:
    """Dispatches audio event over HTTP to Pi 4B audio server."""
    sound_file = audio_resolver.get_audio_filename(event_name)

    def _work():
        try:
            payload = json.dumps({
                "kind": sound_file,
                "event": event_name,
                "wav_path": "",
                "stop_previous": False,
                "delay_sec": 0.0
            }).encode('utf-8')
            req = urllib.request.Request(get_pi4b_sound_url(), data=payload, headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                if resp.status != 200:
                    logging.warning("Audio request '%s' returned status: %d", event_name, resp.status)
        except Exception as e:
            logging.warning("Audio request '%s' failed: %s", event_name, e)

    threading.Thread(target=_work, daemon=True, name=f"Chime-{event_name}").start()


class JoyConService:
    """Intrinsic 24/7 daemon service reading Right Joy-Con HID report 0x30, handling teleop and app switching."""

    def __init__(
        self,
        mac_address: str = MAC_ADDRESS,
        api_url: str = API_URL,
        backend: Optional[RobotBackend] = None,
        app_manager: Optional[Any] = None
    ) -> None:
        self.mac_address = mac_address
        self.api_url = api_url
        self.backend = backend
        self.app_manager = app_manager
        self.stop_event = threading.Event()
        self.thread: Optional[threading.Thread] = None
        self.logger = logging.getLogger("so101.joycon_service")
        self.config = _CONFIG

        self.is_connected = False
        self.button_b_click_event = threading.Event()
        self.abort_audio_event = threading.Event()

        # Calibration
        c_x, c_y, s_x, s_y, min_raw, max_raw = load_joycon_calibration()
        self.center_x = c_x
        self.center_y = c_y
        self.span_x = s_x
        self.span_y = s_y
        self.min_calib_raw = min_raw
        self.max_calib_raw = max_raw

        self.auto_zero_samples = int(self.config["control"]["auto_zero_samples"])
        self.calib_samples_x: list = []
        self.calib_samples_y: list = []
        self.zero_calibrated = False
        self.deadzone = float(self.config["control"]["deadzone"])

        # Teleop and Rover state
        self.teleop_enabled = False
        self.control_mode = "ROVER"  # Exactly two modes: 'ROVER' vs 'AUX' (Rule 13)
        self.is_armed = False
        self.rover_ctrl: Optional[Any] = None
        self.arm_lockout_until = 0.0

        # Timing and gesture state
        self.btn_a_press_start_time: Optional[float] = None
        self.a_hold_triggered = False

        self.btn_b_press_start_time: Optional[float] = None
        self.b_hold_triggered = False
        self.last_btn_b_click_time: float = 0.0
        self.b_double_tap_sec = float(self.config["gestures"]["b_double_tap_sec"])

        self.both_ab_press_start_time: Optional[float] = None
        self.ab_hold_triggered = False
        self.chord_click_suppress_sec = float(self.config["gestures"]["chord_click_suppress_sec"])
        self.chord_suppress_until = 0.0

        self.last_btn_b = False
        self.last_btn_y = False
        self.last_btn_sr = False
        self.last_btn_sl = False
        self.last_x_direction = "center"
        self.last_y_direction = "center"
        self.last_listener_nav_time: float = 0.0
        self.last_btn_a_listener: bool = False

        self.is_busy = False
        self.busy_until = 0.0
        self.gantry_step_ticks = int(self.config["control"]["gantry_step_ticks"])
        self.aux_lock_duration_sec = float(self.config["control"]["aux_lock_duration_sec"])

        # IMU Scaling & Shake Detection Engine
        self.accel_scale_g = float(self.config["imu"]["accel_scale_g"])
        self.gyro_scale_dps = float(self.config["imu"]["gyro_scale_dps"])
        self.gyro_deadband_dps = float(self.config["imu"]["gyro_deadband_dps"])
        self.stationary_motion_threshold_g = float(self.config["imu"]["stationary_motion_threshold_g"])

        shake_cfg = load_shake_detector_config()
        self.shake_threshold = float(shake_cfg["shake_threshold_g"])
        self.shake_cooldown = float(shake_cfg["shake_cooldown_sec"])
        self.shake_window_sec = float(shake_cfg["shake_window_sec"])
        self.shake_baseline_alpha = float(shake_cfg["baseline_alpha"])

        self.baseline_accel_mag = 1.0
        self.shake_detected = False
        self.shake_count = 0
        self.last_shake_time = 0.0
        self.shake_callbacks: list = []

        self.telemetry = {
            "running": True,
            "connected": False,
            "status": "SEARCHING",
            "controller_type": "Joy-Con (R)",
            "mac": self.mac_address,
            "packet_count": 0,
            "last_seen": 0.0,
            "battery_level": 0,
            "control_mode": self.control_mode,
            "is_armed": self.is_armed,
            "buttons": {
                "r": False,
                "zr": False,
                "sr": False,
                "sl": False,
                "a": False,
                "b": False,
                "x": False,
                "y": False,
                "plus": False,
                "home": False,
                "r_stick": False
            },
            "stick": {"norm_x": 0.0, "norm_y": 0.0},
            "accel": {"x": 0.0, "y": 0.0, "z": 0.0, "mag": 1.0, "baseline": 1.0},
            "gyro": {"x": 0.0, "y": 0.0, "z": 0.0},
            "shake": {
                "detected": False,
                "count": 0,
                "threshold": self.shake_threshold,
                "delta": 0.0
            },
            "drivetrain": {
                "throttle": 0.0,
                "steering": 0.0,
                "gated_idle": True
            },
            "pairing": {
                "in_progress": False,
                "status": "IDLE",
                "message": ""
            }
        }
        self.pairing_in_progress = False
        self.write_telemetry()

    @property
    def joystick_center_x(self) -> int:
        return self.center_x

    @property
    def joystick_center_y(self) -> int:
        return self.center_y

    def notification_handler(self, sender: Any, data: Any) -> None:
        """Compatibility adapter translating synthetic/BLE test packets to Joy-Con report 0x30."""
        raw = bytearray(data)
        if len(raw) == 49 and raw[0] == 0x30:
            self._process_report_30(bytes(raw))
            return

        if len(raw) >= 5:
            buttons = raw[1]
            x_raw = raw[2] | ((raw[3] & 0x0F) << 8)
            y_raw = (raw[3] >> 4) | (raw[4] << 4)

            rep = bytearray(49)
            rep[0] = 0x30
            rep[1] = 0x01
            rep[2] = 0x80
            b3 = 0
            if buttons & 0x01:  # Button B
                b3 |= 0x04
            if buttons & 0x02:  # Button A
                b3 |= 0x08
            rep[3] = b3
            rep[9] = x_raw & 0xFF
            rep[10] = ((x_raw >> 8) & 0x0F) | ((y_raw & 0x0F) << 4)
            rep[11] = (y_raw >> 4) & 0xFF
            self._process_report_30(bytes(rep))

    def write_telemetry(self) -> None:
        try:
            for path in [TELEMETRY_FILE, LEGACY_TELEMETRY_FILE]:
                tmp_path = path + ".tmp"
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(self.telemetry, f)
                os.replace(tmp_path, path)
        except OSError as e:
            self.logger.debug("Telemetry file write warning: %s", e)

    def get_telemetry(self) -> Dict[str, Any]:
        data = dict(self.telemetry)
        data["is_armed"] = self.is_armed
        data["teleop_enabled"] = self.teleop_enabled
        data["control_mode"] = self.control_mode
        if self.rover_ctrl:
            data["rover"] = self.rover_ctrl.get_telemetry()
        return data

    def _send_aux_request(self, endpoint: str, payload: dict, lock_duration: float = 0.6) -> None:
        now = time.time()
        if self.is_busy or now < self.busy_until:
            return
        self.is_busy = True
        self.busy_until = now + lock_duration

        def _work():
            try:
                url = f"{self.api_url}{endpoint}"
                data = json.dumps(payload).encode('utf-8')
                req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
                with urllib.request.urlopen(req, timeout=2.5):
                    pass
            except Exception as e:
                self.logger.warning("Aux API dispatch error (%s): %s", endpoint, e)
            finally:
                time.sleep(lock_duration)
                self.is_busy = False

        threading.Thread(target=_work, daemon=True, name=f"AuxDispatch-{endpoint}").start()

    def _find_device_path(self) -> Optional[str]:
        """Discovers /dev/hidraw node matching Joy-Con (R) on Linux."""
        if sys.platform != "win32":
            for p in glob.glob("/sys/class/hidraw/hidraw*"):
                uevent_path = os.path.join(p, "device", "uevent")
                if os.path.exists(uevent_path):
                    try:
                        with open(uevent_path, "r", encoding="utf-8") as f:
                            txt = f.read()
                        if "0000057E" in txt and "2007" in txt:
                            return f"/dev/{os.path.basename(p)}"
                    except OSError as e:
                        self.logger.error("Error reading uevent for %s: %s", p, e, exc_info=True)
        return None

    @staticmethod
    def _make_subcmd_packet(subcmd_id: int, subcmd_data: bytes, packet_num: int = 0) -> bytes:
        """Constructs an authoritative 49-byte Joy-Con Bluetooth output report (OUTPUT 0x01)."""
        buf = bytearray(49)
        buf[0] = 0x01  # OUTPUT 0x01: Subcommand with rumble
        buf[1] = packet_num & 0x0F  # Incremental packet counter
        buf[2:10] = bytes([0x00, 0x01, 0x40, 0x40, 0x00, 0x01, 0x40, 0x40])  # Neutral rumble
        buf[10] = subcmd_id
        for i, b in enumerate(subcmd_data):
            buf[11 + i] = b
        return bytes(buf)

    def _init_joycon(self, fd: int) -> None:
        """Sends initialization subcommands to Joy-Con (R): enables 6-axis IMU and sets standard 60Hz 0x30 report mode."""
        step_delay = float(self.config["hardware"]["init_step_delay_sec"])
        try:
            # Subcommand 0x40 (Arg 0x01): Enable IMU sensors (exactly 49 bytes)
            report_imu = self._make_subcmd_packet(0x40, bytes([0x01]), packet_num=0)
            os.write(fd, report_imu)
            time.sleep(step_delay)
            # Subcommand 0x03 (Arg 0x30): Set standard full input report mode (exactly 49 bytes)
            report_mode = self._make_subcmd_packet(0x03, bytes([0x30]), packet_num=1)
            os.write(fd, report_mode)
            time.sleep(step_delay)
            # Subcommand 0x30 (Arg 0x01): Set Player 1 LED solid on rail to stop cycling sync lights (exactly 49 bytes)
            report_led = self._make_subcmd_packet(0x30, bytes([0x01]), packet_num=2)
            os.write(fd, report_led)
            time.sleep(step_delay)
            self.logger.info("Initialized Joy-Con (R) with 49-byte subcommands into 60Hz 0x30 report mode.")
        except OSError as e:
            self.logger.warning("Joy-Con initialization write warning on fd %d: %s (will dynamically decode 0x3F/0x30 reports)", fd, e)

    def _process_report_30(self, raw: bytes) -> None:
        """Parses Joy-Con reports dynamically (supporting standard 49-byte Report 0x30 and 12-byte simple Report 0x3F)."""
        if len(raw) < 4:
            return

        now = time.time()
        report_id = raw[0]

        if report_id == 0x3F:
            # -----------------------------------------------------------------
            # Simple HID Mode (Report 0x3F)
            # -----------------------------------------------------------------
            # Byte 1: Right face & rail buttons (Down, Right, Left, Up, SL, SR)
            b1 = raw[1]
            btn_b = bool(b1 & 0x01)
            btn_a = bool(b1 & 0x02)
            btn_y = bool(b1 & 0x04)
            btn_x = bool(b1 & 0x08)
            btn_sl = bool(b1 & 0x10)
            btn_sr = bool(b1 & 0x20)

            # Byte 2: Trigger & system buttons (Minus, Plus, LStick, RStick, Home, Capture, R, ZR)
            b2 = raw[2]
            btn_plus = bool(b2 & 0x02)
            btn_r_stick = bool(b2 & 0x08)
            btn_home = bool(b2 & 0x10)
            btn_r = bool(b2 & 0x40)
            btn_zr = bool(b2 & 0x80)

            battery_level = 4

            # Byte 3: Stick Hat data (8 = centered)
            hat = raw[3] if len(raw) > 3 else 8
            hat_map = {
                0: (0.0, 1.0),       # Up
                1: (0.707, 0.707),   # Up-Right
                2: (1.0, 0.0),       # Right
                3: (0.707, -0.707),  # Down-Right
                4: (0.0, -1.0),      # Down
                5: (-0.707, -0.707), # Down-Left
                6: (-1.0, 0.0),      # Left
                7: (-0.707, 0.707),  # Up-Left
                8: (0.0, 0.0),       # Center
            }
            norm_x, norm_y = hat_map.get(hat, (0.0, 0.0))

            if len(raw) >= 12 and (raw[4] != 0 or raw[5] != 0 or raw[6] != 0):
                raw_r_x = raw[4] | ((raw[5] & 0x0F) << 8)
                raw_r_y = (raw[5] >> 4) | (raw[6] << 4)
                if raw_r_x != 0 or raw_r_y != 0:
                    dx = raw_r_x - self.center_x
                    dy = raw_r_y - self.center_y
                    norm_x = max(-1.0, min(1.0, dx / self.span_x))
                    norm_y = max(-1.0, min(1.0, dy / self.span_y))

        else:
            # -----------------------------------------------------------------
            # Standard Full Mode (Report 0x30 / 0x21)
            # -----------------------------------------------------------------
            if len(raw) < 12:
                return
            bat_raw = raw[2]
            battery_level = (bat_raw >> 5) & 0x07

            # Byte 3: Right buttons
            b3 = raw[3]
            btn_y = bool(b3 & 0x01)
            btn_x = bool(b3 & 0x02)
            btn_b = bool(b3 & 0x04)
            btn_a = bool(b3 & 0x08)
            btn_sr = bool(b3 & 0x10)
            btn_sl = bool(b3 & 0x20)
            btn_r = bool(b3 & 0x40)
            btn_zr = bool(b3 & 0x80)

            # Byte 4: Shared buttons
            b4 = raw[4]
            btn_plus = bool(b4 & 0x02)
            btn_r_stick = bool(b4 & 0x04)
            btn_home = bool(b4 & 0x10)

            # Bytes 9-11: Right Stick (12-bit)
            raw_r_x = raw[9] | ((raw[10] & 0x0F) << 8)
            raw_r_y = (raw[10] >> 4) | (raw[11] << 4)

            # Dynamic auto-zero calibration during resting state
            if not self.zero_calibrated:
                if not (btn_r or btn_zr or btn_a or btn_b):
                    if self.min_calib_raw <= raw_r_x <= self.max_calib_raw and self.min_calib_raw <= raw_r_y <= self.max_calib_raw:
                        self.calib_samples_x.append(raw_r_x)
                        self.calib_samples_y.append(raw_r_y)
                        if len(self.calib_samples_x) >= self.auto_zero_samples:
                            self.center_x = int(sum(self.calib_samples_x) / len(self.calib_samples_x))
                            self.center_y = int(sum(self.calib_samples_y) / len(self.calib_samples_y))
                            self.zero_calibrated = True
                            self.logger.info("🎯 Joy-Con (R) stick auto-zero calibrated: center_x=%d, center_y=%d", self.center_x, self.center_y)

            dx = raw_r_x - self.center_x
            dy = raw_r_y - self.center_y
            span_x = self.span_x
            span_y = self.span_y

            raw_norm_x = max(-1.0, min(1.0, dx / span_x))
            raw_norm_y = max(-1.0, min(1.0, dy / span_y))

            # Deadzone filter
            if abs(raw_norm_x) <= self.deadzone:
                norm_x = 0.0
            else:
                sign_x = 1.0 if raw_norm_x > 0 else -1.0
                norm_x = sign_x * ((abs(raw_norm_x) - self.deadzone) / (1.0 - self.deadzone))

            if abs(raw_norm_y) <= self.deadzone:
                norm_y = 0.0
            else:
                sign_y = 1.0 if raw_norm_y > 0 else -1.0
                norm_y = sign_y * ((abs(raw_norm_y) - self.deadzone) / (1.0 - self.deadzone))

        # Discrete stick directions for AUX mode manipulation
        if norm_x < -0.35:
            x_direction = "left"
        elif norm_x > 0.35:
            x_direction = "right"
        else:
            x_direction = "center"

        if norm_y < -0.35:
            y_direction = "down"
        elif norm_y > 0.35:
            y_direction = "up"
        else:
            y_direction = "center"

        # Check if listener_app is active and in SELECTING state
        is_listener_selecting = False
        l_app = None
        if self.app_manager and self.app_manager.current_app_name == "listener_app":
            l_app = self.app_manager.active_app
            if l_app and hasattr(l_app, "state") and l_app.state == "SELECTING":
                is_listener_selecting = True

        if is_listener_selecting and l_app is not None:
            # 1. Joystick Y tilt: step row cursor with 0.35s refractory debounce
            if (now - self.last_listener_nav_time) >= 0.35:
                if norm_y > 0.4:
                    l_app.navigate_selection(-1)
                    self.last_listener_nav_time = now
                elif norm_y < -0.4:
                    l_app.navigate_selection(1)
                    self.last_listener_nav_time = now

            # 2. Button A click: confirm selection & trigger Mac analysis
            if btn_a and not self.last_btn_a_listener:
                self.logger.info("🔘 Button A click detected in SELECTING state! Triggering Mac analysis...")
                if hasattr(l_app, "trigger_analysis"):
                    l_app.trigger_analysis(l_app.selected_index)
                elif hasattr(l_app, "select_track"):
                    l_app.select_track(l_app.selected_index)
            self.last_btn_a_listener = btn_a
        else:
            self.last_btn_a_listener = False

        # ---------------------------------------------------------------------
        # 0. BUTTON Y GESTURE: UNIVERSAL EMERGENCY STOP_APP
        # ---------------------------------------------------------------------
        if btn_y and not self.last_btn_y:
            self.logger.info("🛑 [BUTTON Y CLICK] Universal STOP_APP triggered!")
            if self.app_manager:
                curr_app = self.app_manager.current_app_name
                if curr_app:
                    self.logger.info("Stopping active app '%s' via Button Y...", curr_app)
                    try:
                        self.app_manager.stop_app(curr_app)
                    except Exception as ex:
                        self.logger.error("Error stopping app '%s' on Button Y: %s", curr_app, ex)
            self.control_mode = "ROVER"
            self.teleop_enabled = False
            self.is_armed = False
            if self.rover_ctrl:
                self.rover_ctrl.set_drive(0.0, 0.0)
            play_chime(self.config["chimes"]["app_exit_idle"])
        self.last_btn_y = btn_y

        a_hold_sec = float(self.config["gestures"]["a_hold_sec"])
        b_hold_sec = float(self.config["gestures"]["b_hold_sec"])
        arm_lockout_sec = float(self.config["gestures"]["arm_lockout_sec"])
        chord_abort_sec = float(self.config["gestures"]["chord_abort_sec"])

        # ---------------------------------------------------------------------
        # 0.5 CHORD ABORT GESTURE: SIMULTANEOUS A + B HOLD (1.0s)
        # ---------------------------------------------------------------------
        if btn_a and btn_b:
            if self.both_ab_press_start_time is None:
                self.both_ab_press_start_time = now
            hold_duration_ab = now - self.both_ab_press_start_time
            if hold_duration_ab >= chord_abort_sec and not self.ab_hold_triggered:
                self.ab_hold_triggered = True
                self.abort_audio_event.set()
                self.chord_suppress_until = now + self.chord_click_suppress_sec
                self.logger.info("🛑 [CHORD ABORT A+B 1.0s] Triggering immediate audio/action abort...")
                play_chime(self.config["chimes"]["chord_abort"])
        else:
            self.both_ab_press_start_time = None
            self.ab_hold_triggered = False

        # ---------------------------------------------------------------------
        # 1. BUTTON A GESTURES: HOLD -> ROVER MODE / APP LAUNCH
        # ---------------------------------------------------------------------
        if btn_a and not btn_b and not is_listener_selecting:
            if self.btn_a_press_start_time is None:
                self.btn_a_press_start_time = now
            hold_duration_a = now - self.btn_a_press_start_time
            if hold_duration_a >= a_hold_sec and not self.a_hold_triggered:
                self.a_hold_triggered = True
                self.logger.info("🏎️ [BUTTON A HOLD] Triggering ROVER Drive Mode...")

                is_teleop_active = (
                    self.teleop_enabled or
                    (self.app_manager is not None and self.app_manager.current_app_name in ["joycon_teleop_app", "pokeball_teleop_app"])
                )

                if not is_teleop_active:
                    # Universal IDLE launch: stop whatever app is active and start joycon_teleop_app in ROVER mode
                    self.logger.info("🚀 Launching joycon_teleop_app in ROVER mode from IDLE/Active state...")
                    self.control_mode = "ROVER"
                    self.teleop_enabled = True
                    self.is_armed = True
                    self.arm_lockout_until = now + arm_lockout_sec
                    if self.rover_ctrl:
                        self.rover_ctrl.set_drive(0.0, 0.0)

                    if self.app_manager:
                        def _launch_teleop():
                            try:
                                self.app_manager.stop_all()
                                self.app_manager.start_app_by_name("joycon_teleop_app")
                            except Exception as ex:
                                self.logger.error("Failed launching joycon_teleop_app: %s", ex, exc_info=True)
                        threading.Thread(target=_launch_teleop, daemon=True, name="TeleopLaunchWorker").start()
                    play_chime(self.config["chimes"]["arm_rover"])
                else:
                    # Teleop already active: switch back to ROVER mode and re-arm
                    self.control_mode = "ROVER"
                    self.is_armed = True
                    self.arm_lockout_until = now + arm_lockout_sec
                    if self.rover_ctrl:
                        self.rover_ctrl.set_drive(0.0, 0.0)
                    self.logger.info("🏎️ [MODE SWITCH] Switched back to ROVER Mode and armed drivetrain.")
                    play_chime(self.config["chimes"]["arm_rover"])
        else:
            self.btn_a_press_start_time = None
            self.a_hold_triggered = False

        # ---------------------------------------------------------------------
        # 2. BUTTON B GESTURES: HOLD 2.0s -> LISTENER APP; CLICK 1x -> AUX MODE
        # ---------------------------------------------------------------------
        if btn_b and not btn_a:
            if not self.last_btn_b:
                self.button_b_click_event.set()
            if self.btn_b_press_start_time is None:
                self.btn_b_press_start_time = now
            hold_duration_b = now - self.btn_b_press_start_time
            if hold_duration_b >= b_hold_sec and not self.b_hold_triggered:
                self.b_hold_triggered = True
                self.logger.info("🎙️ [BUTTON B HOLD 2.0s] Stopping active apps and launching listener_app...")
                if self.app_manager:
                    def _launch_listener():
                        try:
                            self.app_manager.stop_all()
                            self.app_manager.start_app_by_name("listener_app")
                        except Exception as ex:
                            self.logger.error("Failed launching listener_app: %s", ex, exc_info=True)
                    threading.Thread(target=_launch_listener, daemon=True, name="ListenerLaunchWorker").start()
                play_chime(self.config["chimes"]["app_start"])
        else:
            if self.btn_b_press_start_time is not None:
                duration_b = now - self.btn_b_press_start_time
                if 0.05 <= duration_b < b_hold_sec and not self.b_hold_triggered:
                    # Released without holding for 2.0s: evaluate single tap vs double tap
                    time_since_last_click = now - self.last_btn_b_click_time
                    is_double_tap = (time_since_last_click <= self.b_double_tap_sec)
                    self.last_btn_b_click_time = now

                    active_app_name = self.app_manager.current_app_name if self.app_manager else None

                    if active_app_name == "listener_app":
                        if is_double_tap:
                            self.logger.info("🛑 [DOUBLE TAP B] Aborting listener_app and canceling turn...")
                            if self.app_manager and self.app_manager.active_app:
                                l_app = self.app_manager.active_app
                                if hasattr(l_app, "abort_listen_event"):
                                    l_app.abort_listen_event.set()
                            play_chime(self.config["chimes"]["chord_abort"])
                        else:
                            self.logger.info("🎙️ [SINGLE TAP B] Starting listener_app voice capture turn...")
                            if self.app_manager and self.app_manager.active_app:
                                l_app = self.app_manager.active_app
                                if hasattr(l_app, "start_listen_event"):
                                    l_app.start_listen_event.set()
                            self.button_b_click_event.set()

                    elif active_app_name == "beat_bandit_app":
                        # Signal event for BeatBanditApp to monitor double-click stop_and_center
                        self.button_b_click_event.set()

                    else:
                        # In joycon_teleop_app: Single tap switches to AUX Mode (Servos 7 & 8)
                        is_teleop_active = (
                            self.teleop_enabled or
                            (self.app_manager is not None and self.app_manager.current_app_name == "joycon_teleop_app")
                        )
                        if is_teleop_active:
                            self.control_mode = "AUX"
                            self.is_armed = False
                            if self.rover_ctrl:
                                self.rover_ctrl.set_drive(0.0, 0.0)
                            self.logger.info("🔀 [MODE SWITCH] Button B clicked -> Switched to AUX Mode (Gantry & Pedestal).")
                            play_chime(self.config["chimes"]["mode_switch_aux"])
                        self.button_b_click_event.set()

                self.btn_b_press_start_time = None
            self.b_hold_triggered = False

        # ---------------------------------------------------------------------
        # 3. TELEOPERATION ACTUATION (When joycon_teleop_app is Active)
        # ---------------------------------------------------------------------
        if self.teleop_enabled:
            if self.control_mode == "ROVER":
                # Speed Adjustments on rising edges of SR and SL
                if btn_sr and not self.last_btn_sr:
                    if self.rover_ctrl:
                        new_pct = self.rover_ctrl.adjust_speed_pct(int(self.config["control"]["speed_step_pct"]))
                        self.logger.info("🚀 [SPEED STEP +5%%] Rover speed stepped up to %d%%", new_pct)
                        play_chime(self.config["chimes"]["speed_up"])

                if btn_sl and not self.last_btn_sl:
                    if self.rover_ctrl:
                        new_pct = self.rover_ctrl.adjust_speed_pct(-int(self.config["control"]["speed_step_pct"]))
                        self.logger.info("🐢 [SPEED STEP -5%%] Rover speed stepped down to %d%%", new_pct)
                        play_chime(self.config["chimes"]["speed_down"])

                # Strict Throttle-Gated Steering:
                steering = norm_x
                if btn_r and not btn_zr:
                    throttle = 1.0
                elif btn_zr and not btn_r:
                    throttle = -1.0
                else:
                    throttle = 0.0
                gated_idle = (throttle == 0.0 and steering == 0.0)

                if self.rover_ctrl:
                    if self.is_armed:
                        self.rover_ctrl.set_drive(steering, throttle)
                    else:
                        self.rover_ctrl.set_drive(0.0, 0.0)

            elif self.control_mode == "AUX":
                # Rover drivetrain strictly locked
                throttle = 0.0
                steering = 0.0
                gated_idle = True
                if self.rover_ctrl:
                    self.rover_ctrl.set_drive(0.0, 0.0)

                # Gantry gesture: Up/Down stick deflection in AUX mode
                # Up (norm_y > 0.35) -> moves right (+ticks); Down (norm_y < -0.35) -> moves left (-ticks)
                if y_direction in ("up", "down") and abs(norm_y) >= abs(norm_x):
                    is_gantry_trigger = (self.last_y_direction == "center")
                    if is_gantry_trigger and not (self.is_busy or now < self.busy_until):
                        gantry_dir = "right" if y_direction == "up" else "left"
                        self.logger.info("🕹️ [GANTRY] Stick %s -> Nudging Gantry %s (%d ticks)", y_direction.upper(), gantry_dir.upper(), self.gantry_step_ticks)
                        self._send_aux_request("/api/nudge_physical", {"id": 8, "direction": gantry_dir, "amount": self.gantry_step_ticks}, lock_duration=self.aux_lock_duration_sec)

                # Pedestal gesture: Left/Right stick deflection in AUX mode
                elif x_direction in ("left", "right") and abs(norm_x) > abs(norm_y):
                    is_pedestal_trigger = (self.last_x_direction == "center")
                    if is_pedestal_trigger and not (self.is_busy or now < self.busy_until):
                        self.logger.info("🔄 [PEDESTAL] Stick %s -> Stepping Pedestal Preset", x_direction.upper())
                        self._send_aux_request("/api/pedestal_step", {"direction": x_direction}, lock_duration=self.aux_lock_duration_sec)

        else:
            throttle = 0.0
            steering = 0.0
            gated_idle = True

        self.last_btn_b = btn_b
        self.last_btn_sr = btn_sr
        self.last_btn_sl = btn_sl
        self.last_x_direction = x_direction
        self.last_y_direction = y_direction

        # Decode 6-Axis IMU (Report 0x30 Bytes 13-24)
        ax, ay, az = 0.0, 0.0, 0.0
        gx, gy, gz = 0.0, 0.0, 0.0
        accel_mag = 1.0
        is_shake = False
        shake_delta = 0.0

        if len(raw) >= 25:
            def _to_s16(b0: int, b1: int) -> int:
                val = (b1 << 8) | b0
                return val if val < 32768 else val - 65536

            raw_ax = _to_s16(raw[13], raw[14])
            raw_ay = _to_s16(raw[15], raw[16])
            raw_az = _to_s16(raw[17], raw[18])

            raw_gx = _to_s16(raw[19], raw[20])
            raw_gy = _to_s16(raw[21], raw[22])
            raw_gz = _to_s16(raw[23], raw[24])

            # Right Joy-Con IMU: Y and Z axes inverted due to 180 deg enclosure mounting
            ime_coeff = -1.0
            ax = round(raw_ax / self.accel_scale_g, 3)
            ay = round((raw_ay / self.accel_scale_g) * ime_coeff, 3)
            az = round((raw_az / self.accel_scale_g) * ime_coeff, 3)
            accel_mag = round(math.sqrt(ax * ax + ay * ay + az * az), 3)

            gx = round(raw_gx / self.gyro_scale_dps, 2)
            gy = round((raw_gy / self.gyro_scale_dps) * ime_coeff, 2)
            gz = round((raw_gz / self.gyro_scale_dps) * ime_coeff, 2)
            if abs(gx) < self.gyro_deadband_dps:
                gx = 0.0
            if abs(gy) < self.gyro_deadband_dps:
                gy = 0.0
            if abs(gz) < self.gyro_deadband_dps:
                gz = 0.0

            is_shake, shake_delta = self._detect_shake(accel_mag, now)

        # Update Telemetry Snapshot
        self.telemetry["packet_count"] += 1
        self.telemetry["last_seen"] = now
        self.telemetry["battery_level"] = battery_level
        self.telemetry["control_mode"] = self.control_mode
        self.telemetry["is_armed"] = self.is_armed
        self.telemetry["buttons"] = {
            "r": btn_r,
            "zr": btn_zr,
            "sr": btn_sr,
            "sl": btn_sl,
            "a": btn_a,
            "b": btn_b,
            "x": btn_x,
            "y": btn_y,
            "plus": btn_plus,
            "home": btn_home,
            "r_stick": btn_r_stick
        }
        self.telemetry["stick"] = {"norm_x": round(norm_x, 3), "norm_y": round(norm_y, 3)}
        self.telemetry["accel"] = {
            "x": ax, "y": ay, "z": az, "mag": accel_mag, "baseline": round(self.baseline_accel_mag, 3)
        }
        self.telemetry["gyro"] = {
            "x": gx, "y": gy, "z": gz
        }
        self.telemetry["shake"] = {
            "detected": is_shake,
            "count": self.shake_count,
            "threshold": self.shake_threshold,
            "delta": shake_delta
        }
        self.telemetry["drivetrain"] = {
            "throttle": throttle,
            "steering": round(steering, 3),
            "gated_idle": gated_idle
        }
        self.write_telemetry()

    def _detect_shake(self, accel_mag: float, now: float) -> Tuple[bool, float]:
        """Detects sharp acceleration spikes beyond dynamic baseline."""
        self.baseline_accel_mag = self.baseline_accel_mag * (1.0 - self.shake_baseline_alpha) + accel_mag * self.shake_baseline_alpha
        delta = abs(accel_mag - self.baseline_accel_mag)

        if delta > self.shake_threshold and (now - self.last_shake_time) > self.shake_cooldown:
            self.shake_count += 1
            self.last_shake_time = now
            self.logger.info("👋 [JOYCON SHAKE] Detected shake #%d (mag=%.2fG, delta=%.2fG > thresh=%.2fG)",
                             self.shake_count, accel_mag, delta, self.shake_threshold)
            for cb in list(self.shake_callbacks):
                try:
                    cb(accel_mag, delta)
                except Exception as ex:
                    self.logger.error("Error executing shake callback: %s", ex, exc_info=True)
            return True, round(delta, 3)
        return False, round(delta, 3)

    def register_shake_callback(self, cb: Any) -> None:
        """Registers a callback hook invoked when a shake is detected."""
        if cb not in self.shake_callbacks:
            self.shake_callbacks.append(cb)

    def unregister_shake_callback(self, cb: Any) -> None:
        """Unregisters a previously registered shake callback hook."""
        if cb in self.shake_callbacks:
            self.shake_callbacks.remove(cb)

    def _run_loop(self) -> None:
        """Main Joy-Con connection and polling worker."""
        reconnect_delay = float(self.config["hardware"]["reconnect_delay_sec"])
        packet_timeout = float(self.config["hardware"]["packet_timeout_sec"])
        self.logger.info("JoyConService daemon loop active for Joy-Con MAC %s.", self.mac_address)

        while not self.stop_event.is_set():
            dev_path = self._find_device_path()
            if not dev_path:
                self.telemetry["connected"] = False
                self.telemetry["status"] = "SEARCHING"
                self.write_telemetry()
                time.sleep(reconnect_delay)
                continue

            was_connected = False
            self.logger.info("Connecting to Joy-Con (R) at %s...", dev_path)
            try:
                fd = os.open(dev_path, os.O_RDWR)
                self._init_joycon(fd)
                self.is_connected = True
                was_connected = True
                self.telemetry["connected"] = True
                self.telemetry["status"] = "CONNECTED"
                self.telemetry["last_seen"] = time.time()
                self.zero_calibrated = False
                self.calib_samples_x.clear()
                self.calib_samples_y.clear()
                self.write_telemetry()
                play_chime(self.config["chimes"]["device_connect"])

                import select
                while not self.stop_event.is_set():
                    r, _, _ = select.select([fd], [], [], 0.05)
                    if r:
                        raw = os.read(fd, 64)
                        if raw:
                            self._process_report_30(raw)
                    now = time.time()
                    if (now - self.telemetry["last_seen"]) > packet_timeout:
                        self.logger.warning("Packet timeout reached on %s. Reconnecting...", dev_path)
                        break

                os.close(fd)
            except Exception as e:
                self.logger.warning("Joy-Con communication exception: %s", e)

            self.is_connected = False
            self.is_armed = False
            if self.rover_ctrl:
                self.rover_ctrl.set_drive(0.0, 0.0)
            self.telemetry["connected"] = False
            self.telemetry["status"] = "DISCONNECTED"
            self.write_telemetry()
            if was_connected:
                play_chime(self.config["chimes"]["disconnect"])
            time.sleep(reconnect_delay)

    def start(self) -> None:
        if self.thread is None or not self.thread.is_alive():
            self.stop_event.clear()
            self.thread = threading.Thread(target=self._run_loop, daemon=True, name="JoyConServiceWorker")
            self.thread.start()
            self.logger.info("JoyConService thread launched.")

    def stop(self) -> None:
        self.logger.info("Stopping JoyConService...")
        self.stop_event.set()

    def trigger_repair(self, timeout_sec: Optional[int] = None) -> Tuple[bool, str]:
        """Triggers asynchronous BlueZ pairing worker."""
        if self.pairing_in_progress:
            return False, "Pairing already in progress"
        self.pairing_in_progress = True
        self.telemetry["pairing"]["in_progress"] = True
        self.telemetry["pairing"]["status"] = "Preparing pairing..."
        self.telemetry["pairing"]["message"] = ""
        self.write_telemetry()

        def _worker():
            try:
                try:
                    from .pair_bluez import pair_joycon
                except ImportError:
                    from apps.joycon_app.pair_bluez import pair_joycon

                def _prog(msg: str):
                    self.telemetry["pairing"]["status"] = msg
                    self.write_telemetry()

                ok, msg = pair_joycon(mac=self.mac_address, timeout_sec=timeout_sec, status_cb=_prog)
                self.telemetry["pairing"]["in_progress"] = False
                final_status = "Connected"
                if not ok:
                    final_status = "Failed"
                self.telemetry["pairing"]["status"] = final_status
                self.telemetry["pairing"]["message"] = msg
                self.pairing_in_progress = False
                self.write_telemetry()
            except Exception as e:
                self.logger.exception("Error during pairing worker: %s", e)
                self.telemetry["pairing"]["in_progress"] = False
                self.telemetry["pairing"]["status"] = "Error"
                self.telemetry["pairing"]["message"] = str(e)
                self.pairing_in_progress = False
                self.write_telemetry()

        threading.Thread(target=_worker, daemon=True, name="JoyConPairingWorker").start()
        return True, "Pairing worker started"


# Backward-compatible alias for existing code
PokeballService = JoyConService


class JoyConApp(BaseApp):
    """Managed Teleoperation Application with Dual Rover / Aux Mode under joycon_teleop_app name."""
    metadata = AppMetadata(
        name=_CONFIG["name"],
        title=_CONFIG["title"],
        description=_CONFIG["description"],
        version=_CONFIG["version"],
        tags=_CONFIG["tags"],
        icon=_CONFIG["icon"]
    )

    def __init__(self, mac_address: str = MAC_ADDRESS, api_url: str = API_URL, rover_ctrl: Optional[Any] = None) -> None:
        super().__init__()
        self.config = _CONFIG
        self.mac_address = mac_address
        self.api_url = api_url
        self.rover_ctrl = rover_ctrl
        self.backend: Optional[RobotBackend] = None
        self.joycon_service: Optional[JoyConService] = None

    def run(self, backend: RobotBackend, stop_event: threading.Event) -> None:
        self.backend = backend
        service = None
        if self.app_manager:
            if hasattr(self.app_manager, "joycon_service") and self.app_manager.joycon_service is not None:
                service = self.app_manager.joycon_service
            elif hasattr(self.app_manager, "pokeball_service") and self.app_manager.pokeball_service is not None:
                service = self.app_manager.pokeball_service

        if service is None:
            raise AttributeError("JoyConApp requires authoritative app_manager.joycon_service from daemon host")
        self.joycon_service = service

        service.teleop_enabled = True
        service.control_mode = "ROVER"
        # Explicitly arm drivetrain so holding R drives wheels immediately upon starting the app
        service.is_armed = True
        service.arm_lockout_until = time.time() + float(self.config["gestures"]["arm_lockout_sec"])

        if self.rover_ctrl is None:
            if RoverController is None:
                raise RuntimeError("RoverController dependency is missing for joycon_teleop_app")
            self.rover_ctrl = RoverController()
            self.rover_ctrl.start()
        service.rover_ctrl = self.rover_ctrl
        self.rover_ctrl.set_drive(0.0, 0.0)

        self.logger.info(
            "JoyConApp enabled teleoperation on intrinsic JoyConService (Armed: %s, Mode: %s).",
            service.is_armed, service.control_mode
        )
        while not stop_event.is_set():
            time.sleep(0.5)

        service.teleop_enabled = False
        service.is_armed = False
        service.control_mode = "ROVER"
        if self.rover_ctrl:
            self.rover_ctrl.stop()
            try:
                self.rover_ctrl.shutdown()
            except Exception as e:
                self.logger.exception("Error shutting down RoverController in JoyConApp: %s", e)
                raise
            self.rover_ctrl = None
        service.rover_ctrl = None
        self.logger.info("JoyConApp disabled teleoperation and released rover drivetrain.")

    def stop(self) -> None:
        if self.joycon_service is not None:
            self.joycon_service.teleop_enabled = False
            self.joycon_service.is_armed = False
            self.joycon_service.control_mode = "ROVER"
            if self.joycon_service.rover_ctrl:
                self.joycon_service.rover_ctrl.stop()
        if self.rover_ctrl is not None:
            self.rover_ctrl.stop()
        super().stop()


# Backward-compatible alias for existing code
PokeballApp = JoyConApp
