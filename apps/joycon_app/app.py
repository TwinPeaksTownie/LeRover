#!/usr/bin/env python3
"""JoyConApp and JoyConService module for Nintendo Switch Right Joy-Con teleoperation.

Features:
- Bluetooth Classic HID communication via Linux /dev/hidraw or Windows hidapi.
- 60 Hz Report 0x30 decoding: Right Stick, R/ZR triggers, SL/SR buttons, A/B/X/Y, Plus, Home.
- Strict throttle-gated drivetrain control:
  * Hold R -> Drive Forward (+1.0)
  * Hold ZR -> Drive Reverse (-1.0)
  * Neither/Both -> Neutral (0.0) and complete steering suppression (stick left/right cannot drive wheels)
- Real-time speed adjustments:
  * SR click -> +5% speed increment
  * SL click -> -5% speed decrement
- Backwards-compatible events:
  * button_b_click_event for voice interaction
  * abort_audio_event for simultaneous chord abort
"""

import glob
import json
import logging
import math
import os
import struct
import subprocess
import sys
import threading
import time
import urllib.request
from typing import Optional, Dict, Any, Tuple, List

current_dir = os.path.dirname(os.path.abspath(__file__))
workspace_root = os.path.abspath(os.path.join(current_dir, "..", ".."))
for p in [workspace_root, os.path.join(workspace_root, "config"), os.path.join(workspace_root, "pi4b")]:
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
from app_manager import BaseApp, AppMetadata
from robot_backend import RobotBackend

CONFIG_PATH = os.path.join(current_dir, "config.json")


def load_joycon_config() -> Dict[str, Any]:
    """Loads canonical joycon_app configuration fail-fast with direct bracket indexing."""
    if not os.path.exists(CONFIG_PATH):
        raise FileNotFoundError(f"Missing required Joy-Con config: {CONFIG_PATH}")
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    _ = cfg["name"]
    _ = cfg["title"]
    _ = cfg["description"]
    _ = cfg["version"]
    _ = int(cfg["hardware"]["vendor_id"])
    _ = int(cfg["hardware"]["product_ids"]["joycon_r"])
    _ = str(cfg["hardware"]["mac_address"])
    _ = float(cfg["hardware"]["poll_rate_hz"])
    _ = float(cfg["hardware"]["packet_timeout_sec"])
    _ = float(cfg["hardware"]["reconnect_delay_sec"])
    _ = str(cfg["hardware"]["telemetry_file"])
    _ = float(cfg["hardware"]["init_step_delay_sec"])
    _ = cfg["network"]["sound_api_url"]
    _ = float(cfg["network"]["sound_api_timeout_sec"])
    _ = float(cfg["control"]["deadzone"])
    _ = int(cfg["control"]["speed_step_pct"])
    _ = int(cfg["control"]["auto_zero_samples"])
    _ = int(cfg["control"]["gantry_step_ticks"])
    _ = float(cfg["control"]["aux_lock_duration_sec"])
    _ = float(cfg["gestures"]["chord_abort_sec"])
    _ = float(cfg["gestures"]["b_hold_sec"])
    _ = float(cfg["gestures"]["b_double_tap_sec"])
    _ = float(cfg["gestures"]["a_hold_sec"])
    _ = cfg["chimes"]["app_start"]
    _ = cfg["chimes"]["device_connect"]
    _ = cfg["chimes"]["disconnect"]
    _ = cfg["chimes"]["arm_rover"]
    _ = cfg["chimes"]["speed_up"]
    _ = cfg["chimes"]["speed_down"]
    _ = int(cfg["pairing"]["timeout_sec"])
    _ = int(cfg["pairing"]["scan_timeout_sec"])
    _ = bool(cfg["pairing"]["auto_remove_stale"])
    return cfg


_CONFIG = load_joycon_config()
TARGET_MAC = _CONFIG["hardware"]["mac_address"].upper()
JOYCON_R_PID = int(_CONFIG["hardware"]["product_ids"]["joycon_r"])
VENDOR_ID = int(_CONFIG["hardware"]["vendor_id"])


def load_joycon_calibration() -> Dict[str, int]:
    """Loads Joy-Con analog stick calibration dynamically from calibration_aux.json."""
    aux_path = os.path.join(workspace_root, "calibration_aux.json")
    if not os.path.exists(aux_path):
        aux_path = "/home/carson/touch_ui/calibration_aux.json"
    if not os.path.exists(aux_path):
        raise FileNotFoundError(f"Missing required calibration file: {aux_path}")
    with open(aux_path, "r", encoding="utf-8") as f:
        calib = json.load(f)
    return {
        "center_x": int(calib["joycon_joystick"]["center_x"]),
        "center_y": int(calib["joycon_joystick"]["center_y"]),
        "span_x": int(calib["joycon_joystick"]["span_x"]),
        "span_y": int(calib["joycon_joystick"]["span_y"]),
        "min_calib_raw": int(calib["joycon_joystick"]["min_calib_raw"]),
        "max_calib_raw": int(calib["joycon_joystick"]["max_calib_raw"]),
    }


def play_chime(event_name: str) -> None:
    """Dispatches audio event over HTTP to Pi 4B Touch UI audio server."""
    sound_file = audio_resolver.get_audio_filename(event_name)

    def _work():
        payload = json.dumps({
            "kind": sound_file,
            "event": event_name,
            "wav_path": "",
            "stop_previous": False,
            "delay_sec": 0.0
        }).encode('utf-8')
        url = str(_CONFIG["network"]["sound_api_url"])
        timeout = float(_CONFIG["network"]["sound_api_timeout_sec"])
        req = urllib.request.Request(url, data=payload, headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status != 200:
                    logging.getLogger("so101.joycon_app").error("Audio dispatch non-200 (%s) for '%s'", resp.status, event_name)
        except urllib.error.URLError as err:
            logging.getLogger("so101.joycon_app").error("Audio dispatch network error for '%s': %s", event_name, err, exc_info=True)

    threading.Thread(target=_work, daemon=True).start()


class JoyConService:
    """Daemon service maintaining persistent connection to Nintendo Switch Right Joy-Con."""

    def __init__(
        self,
        mac_address: Optional[str] = None,
        backend: Optional[RobotBackend] = None,
        app_manager: Optional[Any] = None
    ) -> None:
        self.config = _CONFIG
        self.mac_address = (mac_address or TARGET_MAC).upper()
        self.backend = backend
        self.app_manager = app_manager
        self.logger = logging.getLogger("so101.joycon_service")

        self.stop_event = threading.Event()
        self.thread: Optional[threading.Thread] = None
        self.is_connected = False
        self.teleop_enabled = False
        self.rover_ctrl: Optional[Any] = None

        # Voice & Gesture events (Compatibility with OrnithVoice & BeatBandit)
        self.button_b_click_event = threading.Event()
        self.abort_audio_event = threading.Event()
        self.both_ab_press_start_time: Optional[float] = None
        self.ab_hold_triggered = False
        self.btn_b_press_start_time: Optional[float] = None
        self.last_btn_b_click_time: float = 0.0
        self.last_btn_b = False
        self.last_btn_sr = False
        self.last_btn_sl = False

        # Stick Calibration state
        cal = load_joycon_calibration()
        self.center_x: int = cal["center_x"]
        self.center_y: int = cal["center_y"]
        self.span_x: float = float(cal["span_x"])
        self.span_y: float = float(cal["span_y"])
        self.min_calib_raw: int = cal["min_calib_raw"]
        self.max_calib_raw: int = cal["max_calib_raw"]
        self.calib_samples_x: List[int] = []
        self.calib_samples_y: List[int] = []
        self.zero_calibrated: bool = False
        self.deadzone = float(self.config["control"]["deadzone"])
        self.auto_zero_samples = int(self.config["control"]["auto_zero_samples"])

        # Telemetry
        self.telemetry_file = self.config["hardware"]["telemetry_file"]
        self.telemetry: Dict[str, Any] = {
            "running": True,
            "connected": False,
            "status": "SEARCHING",
            "controller_type": "Joy-Con (R)",
            "mac": self.mac_address,
            "packet_count": 0,
            "last_seen": 0.0,
            "battery_level": 0,
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

    def write_telemetry(self) -> None:
        """Atomically writes structured telemetry to disk."""
        tmp = self.telemetry_file + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.telemetry, f, indent=2)
            os.replace(tmp, self.telemetry_file)
        except OSError as e:
            self.logger.error("Telemetry atomic file write failure for '%s': %s", self.telemetry_file, e, exc_info=True)
            raise

    def get_telemetry(self) -> Dict[str, Any]:
        """Returns structured snapshot of telemetry with backwards-compatible fields."""
        telem = dict(self.telemetry)
        telem["norm_x"] = self.telemetry["stick"]["norm_x"]
        telem["norm_y"] = self.telemetry["stick"]["norm_y"]
        telem["button_a"] = self.telemetry["buttons"]["a"]
        telem["button_b"] = self.telemetry["buttons"]["b"]
        telem["button_stick"] = self.telemetry["buttons"]["r_stick"]
        return telem

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
                            node = f"/dev/{os.path.basename(p)}"
                            return node
                    except OSError as e:
                        self.logger.error("Error reading uevent for %s: %s", p, e, exc_info=True)
        return None

    def _init_joycon(self, fd: int) -> None:
        """Sends initialization subcommands: enable 6-axis IMU and set standard 60Hz 0x30 report mode."""
        step_delay = float(self.config["hardware"]["init_step_delay_sec"])
        try:
            # Subcommand 0x40 (Arg 0x01): Enable IMU sensors
            report_imu = bytes([0x01, 0x00, 0x00, 0x01, 0x40, 0x40, 0x00, 0x01, 0x40, 0x40, 0x40, 0x01])
            os.write(fd, report_imu)
            time.sleep(step_delay)
            # Subcommand 0x03 (Arg 0x30): Set standard full input report mode
            report_mode = bytes([0x01, 0x01, 0x00, 0x01, 0x40, 0x40, 0x00, 0x01, 0x40, 0x40, 0x03, 0x30])
            os.write(fd, report_mode)
            time.sleep(step_delay)
            self.logger.info("Initialized Joy-Con (R) into 60Hz 0x30 report mode.")
        except OSError as e:
            self.logger.error("Joy-Con initialization write failure on fd %d: %s", fd, e, exc_info=True)
            raise

    def _process_report_30(self, raw: bytes) -> None:
        """Parses 49-byte Report 0x30 from Joy-Con (R) and drives the rover."""
        if len(raw) < 12:
            return

        now = time.time()
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

        # Auto-zero calibration during resting state
        if not self.zero_calibrated:
            if not (btn_r or btn_zr or btn_a or btn_b):
                if self.min_calib_raw <= raw_r_x <= self.max_calib_raw and self.min_calib_raw <= raw_r_y <= self.max_calib_raw:
                    self.calib_samples_x.append(raw_r_x)
                    self.calib_samples_y.append(raw_r_y)
                    if len(self.calib_samples_x) >= self.auto_zero_samples:
                        self.center_x = int(sum(self.calib_samples_x) / len(self.calib_samples_x))
                        self.center_y = int(sum(self.calib_samples_y) / len(self.calib_samples_y))
                        self.zero_calibrated = True
                        self.logger.info("🎯 Joy-Con (R) stick calibrated: center_x=%d, center_y=%d", self.center_x, self.center_y)

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

        # Speed adjustments on rising edges of SR and SL
        if btn_sr and not self.last_btn_sr:
            if self.rover_ctrl:
                new_pct = self.rover_ctrl.adjust_speed_pct(self.config["control"]["speed_step_pct"])
                self.logger.info("🚀 [SPEED STEP +5%%] Rover speed stepped up to %d%%", new_pct)
                play_chime(self.config["chimes"]["speed_up"])

        if btn_sl and not self.last_btn_sl:
            if self.rover_ctrl:
                new_pct = self.rover_ctrl.adjust_speed_pct(-self.config["control"]["speed_step_pct"])
                self.logger.info("🐢 [SPEED STEP -5%%] Rover speed stepped down to %d%%", new_pct)
                play_chime(self.config["chimes"]["speed_down"])

        self.last_btn_sr = btn_sr
        self.last_btn_sl = btn_sl

        # Strict Throttle-Gated Steering Logic:
        # Hold R  -> Forward (+1.0)
        # Hold ZR -> Reverse (-1.0)
        # Neither or Both -> Throttle = 0.0 AND Steering = 0.0
        if btn_r and not btn_zr:
            throttle = 1.0
            steering = norm_x
            gated_idle = False
        elif btn_zr and not btn_r:
            throttle = -1.0
            steering = norm_x
            gated_idle = False
        else:
            throttle = 0.0
            steering = 0.0  # Holding left/right on stick CANNOT drive wheels when throttle is zero!
            gated_idle = True

        if self.teleop_enabled and self.rover_ctrl:
            self.rover_ctrl.set_drive(steering, throttle, enforce_throttle_gate=True)

        # Button B Voice Interaction & A+B Chord Abort
        if btn_a and btn_b:
            if self.both_ab_press_start_time is None:
                self.both_ab_press_start_time = now
            if (now - self.both_ab_press_start_time) >= float(self.config["gestures"]["chord_abort_sec"]) and not self.ab_hold_triggered:
                self.ab_hold_triggered = True
                self.logger.info("🛑 [CHORD] A + B hold detected! Triggering abort_audio_event...")
                self.abort_audio_event.set()
        else:
            self.both_ab_press_start_time = None
            self.ab_hold_triggered = False

        if btn_b and not self.last_btn_b and not btn_a:
            self.logger.info("🔘 Button B single click detected.")
            self.button_b_click_event.set()

        self.last_btn_b = btn_b

        # Update Telemetry Snapshot
        self.telemetry["packet_count"] += 1
        self.telemetry["last_seen"] = now
        self.telemetry["battery_level"] = battery_level
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
        self.telemetry["drivetrain"] = {
            "throttle": throttle,
            "steering": round(steering, 3),
            "gated_idle": gated_idle
        }
        self.write_telemetry()

    def _run_loop(self) -> None:
        """Main connection and polling worker."""
        reconnect_delay = float(self.config["hardware"]["reconnect_delay_sec"])
        self.logger.info("JoyConService daemon loop started for MAC %s.", self.mac_address)

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
                self.write_telemetry()
                play_chime(self.config["chimes"]["device_connect"])

                import select
                while not self.stop_event.is_set():
                    r, _, _ = select.select([fd], [], [], 0.05)
                    if r:
                        raw = os.read(fd, 49)
                        if raw:
                            self._process_report_30(raw)
                    now = time.time()
                    if (now - self.telemetry["last_seen"]) > float(self.config["hardware"]["packet_timeout_sec"]):
                        self.logger.warning("Packet timeout reached on %s. Reconnecting...", dev_path)
                        break

                os.close(fd)
            except Exception as e:
                self.logger.warning("Joy-Con communication exception: %s", e)

            self.is_connected = False
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
        self.stop_event.set()
        if self.rover_ctrl:
            self.rover_ctrl.set_drive(0.0, 0.0)
        self.logger.info("JoyConService stopped.")

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
                    from pair_bluez import pair_joycon

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


class JoyConApp(BaseApp):
    """Managed Nintendo Switch Right Joy-Con Teleoperation Application."""
    metadata = AppMetadata(
        name=_CONFIG["name"],
        title=_CONFIG["title"],
        description=_CONFIG["description"],
        version=_CONFIG["version"],
        tags=_CONFIG["tags"],
        icon=_CONFIG["icon"]
    )

    def __init__(self, rover_ctrl: Optional[Any] = None) -> None:
        super().__init__()
        self.config = _CONFIG
        self.rover_ctrl = rover_ctrl
        self.joycon_service: Optional[JoyConService] = None

    def run(self, backend: RobotBackend, stop_event: threading.Event) -> None:
        # Retrieve authoritative joycon_service (or fallback to pokeball_service for compatibility)
        service = None
        if self.app_manager:
            if hasattr(self.app_manager, "joycon_service") and self.app_manager.joycon_service:
                service = self.app_manager.joycon_service
            elif hasattr(self.app_manager, "pokeball_service") and self.app_manager.pokeball_service:
                service = self.app_manager.pokeball_service

        if service is None:
            raise AttributeError("JoyConApp requires authoritative joycon_service from daemon host")

        self.joycon_service = service

        if self.rover_ctrl is None:
            if RoverController is None:
                raise RuntimeError("RoverController dependency is missing for joycon_teleop_app")
            self.rover_ctrl = RoverController()
            self.rover_ctrl.start()

        service.rover_ctrl = self.rover_ctrl
        service.teleop_enabled = True
        self.rover_ctrl.set_drive(0.0, 0.0)

        play_chime(self.config["chimes"]["arm_rover"])
        self.logger.info("JoyConApp enabled teleoperation on Right Joy-Con (MAC %s).", service.mac_address)

        while not stop_event.is_set():
            time.sleep(0.5)

        service.teleop_enabled = False
        if self.rover_ctrl:
            self.rover_ctrl.set_drive(0.0, 0.0)
            self.rover_ctrl.stop()
            try:
                self.rover_ctrl.shutdown()
            except Exception as e:
                self.logger.warning("Rover controller shutdown error: %s", e)
            self.rover_ctrl = None
        service.rover_ctrl = None
        self.logger.info("JoyConApp released rover drivetrain and exited.")

    def stop(self) -> None:
        if self.joycon_service:
            self.joycon_service.teleop_enabled = False
            if self.joycon_service.rover_ctrl:
                self.joycon_service.rover_ctrl.set_drive(0.0, 0.0)
        if self.rover_ctrl:
            self.rover_ctrl.set_drive(0.0, 0.0)
            self.rover_ctrl.stop()
        super().stop()
