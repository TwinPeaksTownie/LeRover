#!/usr/bin/env python3
"""PokeballApp and PokeballService module for Poké Ball Plus BLE teleoperation & voice interaction.
Supports:
- Intrinsic daemon BLE service (PokeballService) running 24/7 with auto-reconnection
- Voice State Machine:
  * 3-second hold of Button B (Top Red Button) -> starts listening + audio chime
  * Single click of Button B while listening -> stops listening + audio chime + initiates transcription & thinking
- AUX Manipulator Mode (Gantry & Pedestal control)
- ROVER Drive Mode (Overlander-4 differential drive via GPIO UART to KB2040)
"""

import asyncio
import json
import logging
import math
import os
import random
import struct
import subprocess
import sys
import threading
import time
import urllib.request
from typing import Optional, Dict, Any

# Ensure repo root and rover package are importable
current_dir = os.path.dirname(os.path.abspath(__file__))
workspace_root = os.path.abspath(os.path.join(current_dir, "..", ".."))
config_dir = os.path.join(workspace_root, "config")
for p in [workspace_root, config_dir]:
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from rover.rover_controller import RoverController
except ImportError:
    try:
        from rover_controller import RoverController
    except ImportError:
        RoverController = None

import audio_resolver

try:
    from bleak import BleakClient
    BLEAK_AVAILABLE = True
except ImportError:
    BleakClient = None
    BLEAK_AVAILABLE = False

from app_manager import BaseApp, AppMetadata
from robot_backend import RobotBackend

APP_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(APP_DIR, "config.json")

def load_pokeball_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        raise FileNotFoundError(f"Missing required Pokeball config: {CONFIG_PATH}")
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    _ = cfg["name"]
    _ = cfg["ble"]["mac_address"]
    _ = cfg["ble"]["input_uuid"]
    _ = cfg["ble"]["telemetry_file"]
    _ = cfg["gestures"]["chord_abort_sec"]
    _ = cfg["gestures"]["arm_drivetrain_sec"]
    _ = cfg["gestures"]["arm_lockout_sec"]
    _ = cfg["gestures"]["b_hold_sec"]
    _ = cfg["chimes"]["app_start"]
    _ = cfg["chimes"]["ble_connect"]
    _ = cfg["chimes"]["arm_rover"]
    _ = cfg["chimes"]["emergency_brake"]
    _ = cfg["chimes"]["chord_abort"]
    return cfg

_CONFIG = load_pokeball_config()
MAC_ADDRESS = _CONFIG["ble"]["mac_address"]
INPUT_UUID = _CONFIG["ble"]["input_uuid"]
API_URL = "http://127.0.0.1:8085"
TELEMETRY_FILE = _CONFIG["ble"]["telemetry_file"]

try:
    import network_resolver
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import network_resolver


def get_pi4b_base_url() -> str:
    pi4b_ip = network_resolver.get_pi4b_ip(prefer_port=8082)
    return f"http://{pi4b_ip}:8082"


def get_pi4b_sound_url() -> str:
    return f"{get_pi4b_base_url()}/api/play_sound"


def load_joystick_calibration() -> int:
    """Loads joystick neutral ticks dynamically from calibration_aux.json."""
    aux_path = os.path.join(workspace_root, "calibration_aux.json")
    if not os.path.exists(aux_path):
        aux_path = "/home/user/so101/calibration_aux.json"
    if os.path.exists(aux_path):
        with open(aux_path, "r", encoding="utf-8") as f:
            calib = json.load(f)
            if "pokeball_joystick" in calib:
                return int(calib["pokeball_joystick"]["center_x"])
            return int(calib["7"]["center_ticks"])
    raise FileNotFoundError(f"Missing required calibration file: {aux_path}")


def play_chime(event_name="device_connect"):
    """Dispatches requested sound event over HTTP to Pi 4B Touch UI audio server.
    Resolves event_name against config/audio_files.json.
    """
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
                    logging.warning(f"Audio request '{event_name}' ({sound_file}) returned non-200 status: {resp.status}")
        except Exception as e:
            logging.exception(f"Audio request '{event_name}' ({sound_file}) to Pi 4B failed: {e}")
    threading.Thread(target=_work, daemon=True).start()


class PokeballService:
    """Intrinsic daemon service managing persistent BLE connection and voice state machine for Poké Ball Plus."""

    def __init__(
        self,
        mac_address: str = MAC_ADDRESS,
        api_url: str = API_URL,
        backend: Optional[RobotBackend] = None,
        voice_bridge_url: Optional[str] = None
    ) -> None:
        self.mac_address = mac_address
        self.api_url = api_url
        self.backend = backend
        if voice_bridge_url is None:
            voice_bridge_url = f"http://{network_resolver.get_pc_ip()}:8058"
        self.voice_bridge_url = voice_bridge_url
        self.client: Optional[BleakClient] = None
        self.stop_event = threading.Event()
        self.thread: Optional[threading.Thread] = None
        self.logger = logging.getLogger("so101.pokeball_service")

        self.is_connected = False
        self.app_manager = None
        self.button_b_click_event = threading.Event()
        self.abort_audio_event = threading.Event()
        self.b_hold_triggered = False
        self.both_ab_press_start_time: Optional[float] = None
        self.ab_hold_triggered = False
        self.btn_b_press_start_time: Optional[float] = None
        self.last_btn_b = False
        self.connect_chime_played = False
        self.counter = 0

        # Teleoperation and Rover state
        self.teleop_enabled = False
        self.control_mode = "ROVER"
        self.is_armed = False
        self.arm_lockout_until = 0.0
        self.stick_press_start_time: Optional[float] = None
        self.last_btn_stick_press_time = 0.0
        self.last_rover_interaction_time = 0.0
        self.rover_drive_active_time = 0.0
        self.rover_ctrl = None
        self.joystick_center = load_joystick_calibration()
        self.joystick_range = float(self.joystick_center)

        self.is_busy = False
        self.busy_until = 0.0
        self.chord_suppress_until = 0.0
        self.last_btn_top = False
        self.last_btn_stick = False
        self.last_x_direction = "center"

        self.telemetry = {
            "running": True,
            "connected": False,
            "status": "SEARCHING",
            "is_listening": False,
            "control_mode": self.control_mode,
            "is_armed": self.is_armed,
            "hold_progress": 0.0,
            "mac": self.mac_address,
            "last_seen": 0.0,
            "packet_count": 0,
            "norm_x": 0.0,
            "norm_y": 0.0,
            "button_a": False,
            "button_b": False,
            "button_stick": False,
            "button_top": False,
            "last_error": None
        }
        self.write_telemetry()

    def write_telemetry(self) -> None:
        try:
            tmp_path = TELEMETRY_FILE + ".tmp"
            with open(tmp_path, "w") as f:
                json.dump(self.telemetry, f)
            os.replace(tmp_path, TELEMETRY_FILE)
        except Exception as e:
            self.logger.debug("Telemetry write error: %s", e)

    def get_telemetry(self) -> Dict[str, Any]:
        return dict(self.telemetry)

    def prompt_connect_announcement(self) -> None:
        """Plays startup blarg sound over Pi 4B audio service upon daemon startup."""
        def _prompt():
            time.sleep(1.0)
            try:
                play_chime("smw_blargg")
                self.logger.info("📢 Dispatched startup blarg sound (smw_blargg) to Pi 4B.")
            except Exception as e:
                self.logger.warning("Startup blarg sound dispatch failed: %s", e)
        threading.Thread(target=_prompt, daemon=True).start()


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
                with urllib.request.urlopen(req, timeout=3.0):
                    pass
            except Exception as e:
                self.logger.warning("Aux API HTTP Dispatch error: %s", e)
            finally:
                time.sleep(lock_duration)
                self.is_busy = False

        threading.Thread(target=_work, daemon=True).start()

    def notification_handler(self, sender: Any, data: bytearray) -> None:
        try:
            self.counter += 1
            if len(data) < 5:
                return

            buttons = data[1]

            # 12-Bit Joystick Decoding
            raw_x_12 = data[2] | ((data[3] & 0x0F) << 8)
            raw_y_12 = (data[3] >> 4) | (data[4] << 4)

            x_offset = raw_x_12 - self.joystick_center
            y_offset = raw_y_12 - self.joystick_center

            norm_x = max(-1.0, min(1.0, x_offset / self.joystick_range))
            norm_y = max(-1.0, min(1.0, y_offset / self.joystick_range))

            if abs(norm_x) < 0.08:
                norm_x = 0.0
            if abs(norm_y) < 0.08:
                norm_y = 0.0

            if norm_x < -0.35:
                x_direction = "left"
            elif norm_x > 0.35:
                x_direction = "right"
            else:
                x_direction = "center"

            btn_a = bool(buttons & 0x02)  # Button A (Stick Click)
            btn_b = bool(buttons & 0x01)  # Button B (Top Red Button)

            now = time.time()
            chord_abort_sec = _CONFIG["gestures"]["chord_abort_sec"]
            arm_drivetrain_sec = _CONFIG["gestures"]["arm_drivetrain_sec"]
            arm_lockout_sec = _CONFIG["gestures"]["arm_lockout_sec"]
            b_hold_sec = _CONFIG["gestures"]["b_hold_sec"]

            # --- 1. SIMULTANEOUS A + B CHORD (1.0s Hold) -> CANCEL AUDIO CAPTURE ---
            if btn_a and btn_b:
                if self.both_ab_press_start_time is None:
                    self.both_ab_press_start_time = now
                hold_duration_ab = now - self.both_ab_press_start_time
                if hold_duration_ab >= chord_abort_sec and not self.ab_hold_triggered:
                    self.ab_hold_triggered = True
                    self.chord_suppress_until = now + 1.0
                    self.btn_b_press_start_time = None
                    self.button_b_click_event.clear()
                    self.logger.info("🛑 [CHORD] A + B simultaneous hold detected! Triggering abort_audio_event...")
                    self.abort_audio_event.set()
            else:
                self.both_ab_press_start_time = None
                self.ab_hold_triggered = False

            # --- 2. BUTTON B (TOP RED BUTTON) HANDLING (When not in chord) ---
            if btn_b and not btn_a:
                if now < self.chord_suppress_until:
                    self.btn_b_press_start_time = None
                else:
                    if self.btn_b_press_start_time is None:
                        self.btn_b_press_start_time = now
                    hold_duration_b = now - self.btn_b_press_start_time
                    self.telemetry["hold_progress"] = min(1.0, hold_duration_b / b_hold_sec)
                    if hold_duration_b >= b_hold_sec and not self.b_hold_triggered:
                        self.b_hold_triggered = True
                        self.logger.info("🎙️ [TRIGGER] Button B hold detected! Launching OrnithVoiceApp...")
                        if self.app_manager:
                            threading.Thread(target=self.app_manager.start_app_by_name, args=("ornith_voice",), daemon=True).start()
                        else:
                            play_chime("ornith_app_start")
            else:
                if self.btn_b_press_start_time is not None:
                    duration = now - self.btn_b_press_start_time
                    if now >= self.chord_suppress_until and 0.05 <= duration < 2.0 and not self.b_hold_triggered:
                        self.logger.info("🔘 Button B single click detected.")
                        self.button_b_click_event.set()

                        # In PokeballApp: Button B tap acts as Emergency Brake when armed
                        if self.teleop_enabled and self.is_armed:
                            self.is_armed = False
                            self.arm_lockout_until = 0.0
                            if not self.rover_ctrl:
                                raise RuntimeError("Emergency brake engaged but rover_ctrl is missing")
                            self.rover_ctrl.stop()
                            self.logger.info("🛑 Emergency brake engaged via Button B! Rover disarmed.")
                            play_chime(_CONFIG["chimes"]["emergency_brake"])

                    self.btn_b_press_start_time = None
                self.b_hold_triggered = False
                if not (btn_a and btn_b):
                    self.telemetry["hold_progress"] = 0.0

            # --- 3. BUTTON A (JOYSTICK CLICK) HANDLING (When not in chord) ---
            if btn_a and not btn_b:
                if self.stick_press_start_time is None:
                    self.stick_press_start_time = now
                hold_duration_a = now - self.stick_press_start_time

                # When PokeballApp is active: hold arms rover drivetrain
                if self.teleop_enabled:
                    if hold_duration_a >= arm_drivetrain_sec and not self.is_armed:
                        self.is_armed = True
                        self.arm_lockout_until = now + arm_lockout_sec
                        self.logger.info("🏎️ Drivetrain Arming triggered! Playing Mario Kart countdown (lockout until %.1f)...", self.arm_lockout_until)
                        play_chime(_CONFIG["chimes"]["arm_rover"])
            else:
                self.stick_press_start_time = None

            # --- 4. TELEOPERATION ACTUATION (When PokeballApp is Active) ---
            if self.teleop_enabled:
                if self.rover_ctrl:
                    if self.is_armed and now >= self.arm_lockout_until:
                        self.rover_ctrl.set_drive(norm_x, norm_y)
                    else:
                        self.rover_ctrl.set_drive(0.0, 0.0)

                # Aux Manipulator (Gantry / Pedestal) gestures only when unarmed
                if not self.is_armed and btn_b and not self.last_btn_top and x_direction in ("left", "right"):
                    if not (self.is_busy or now < self.busy_until):
                        self._send_aux_request("/api/pedestal_step", {"direction": x_direction}, lock_duration=0.6)

            self.last_btn_b = btn_b
            self.last_btn_top = btn_b
            self.last_btn_stick = btn_a
            self.last_x_direction = x_direction

            self.telemetry.update({
                "packet_count": self.counter,
                "last_seen": now,
                "control_mode": self.control_mode,
                "is_armed": self.is_armed,
                "norm_x": round(norm_x, 3),
                "norm_y": round(norm_y, 3),
                "button_a": btn_a,
                "button_b": btn_b,
                "button_stick": btn_a,
                "button_top": btn_b
            })
            self.write_telemetry()
        except Exception as e:
            self.logger.error(f"Error in notification_handler: {e}")

    def _cleanup_bluez_device(self) -> None:
        try:
            subprocess.run(["bluetoothctl", "disconnect", self.mac_address], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            subprocess.run(["bluetoothctl", "remove", self.mac_address], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            time.sleep(0.5)
        except Exception as e:
            self.logger.debug(f"BlueZ cleanup warning: {e}")

    def _run_loop(self) -> None:
        if not BLEAK_AVAILABLE:
            self.logger.error("bleak package missing; Pokéball service cannot run.")
            return

        self.prompt_connect_announcement()

        async def _async_loop():
            self.logger.info(f"PokeballService background BLE loop started for {self.mac_address}...")
            while not self.stop_event.is_set():
                try:
                    self._cleanup_bluez_device()
                    self.logger.info(f"Searching for Poké Ball Plus ({self.mac_address})...")
                    self.telemetry.update({"connected": False, "status": "SEARCHING", "last_error": None})
                    self.write_telemetry()

                    async with BleakClient(self.mac_address, timeout=6.0) as client:
                        self.client = client
                        self.is_connected = True
                        self.logger.info("✅ Connected to Poké Ball Plus!")
                        if not self.connect_chime_played:
                            play_chime("device_connect")
                            self.connect_chime_played = True

                        self.telemetry.update({"connected": True, "status": "CONNECTED", "last_seen": time.time()})
                        self.write_telemetry()

                        await client.start_notify(INPUT_UUID, self.notification_handler)
                        self.logger.info("Listening for Poké Ball Plus telemetry & button gestures...")

                        while client.is_connected and not self.stop_event.is_set():
                            await asyncio.sleep(0.5)
                            self.telemetry["last_seen"] = time.time()
                            self.write_telemetry()

                except Exception as e:
                    err_msg = str(e)
                    self.is_connected = False
                    self.telemetry.update({"connected": False, "status": "SEARCHING", "last_error": err_msg})
                    self.write_telemetry()
                    if self.connect_chime_played:
                        play_chime("disconnect")
                        self.connect_chime_played = False
                    self.logger.info(f"Poké Ball BLE waiting for device... [{err_msg}]")
                    await asyncio.sleep(3.0)

            self.telemetry.update({"running": False, "connected": False, "status": "DISCONNECTED"})
            self.write_telemetry()

        asyncio.run(_async_loop())

    def start(self) -> None:
        if self.thread is None or not self.thread.is_alive():
            self.stop_event.clear()
            self.thread = threading.Thread(target=self._run_loop, daemon=True)
            self.thread.start()
            self.logger.info("PokeballService thread launched.")

    def stop(self) -> None:
        self.logger.info("Stopping PokeballService...")
        self.stop_event.set()
        if self.connect_chime_played:
            play_chime("disconnect")
            self.connect_chime_played = False


class PokeballApp(BaseApp):
    """Managed Poké Ball Plus Teleoperation Application with Dual Aux/Rover Mode."""
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

    def run(self, backend: RobotBackend, stop_event: threading.Event) -> None:
        self.backend = backend
        if not hasattr(backend, "pokeball_service") or backend.pokeball_service is None:
            raise AttributeError("RobotBackend is missing required 'pokeball_service'")
        service: PokeballService = backend.pokeball_service

        service.teleop_enabled = True
        service.is_armed = False
        service.arm_lockout_until = 0.0

        if hasattr(backend, "rover_ctrl") and backend.rover_ctrl is not None:
            service.rover_ctrl = backend.rover_ctrl
        elif service.rover_ctrl is None:
            if RoverController is None:
                raise RuntimeError("RoverController dependency is missing for pokeball_teleop_app")
            service.rover_ctrl = RoverController()
            service.rover_ctrl.start()

        self.logger.info("PokeballApp enabled teleoperation on intrinsic PokeballService (Unarmed baseline).")
        while not stop_event.is_set():
            time.sleep(0.5)
        service.teleop_enabled = False
        service.is_armed = False
        if service.rover_ctrl:
            service.rover_ctrl.stop()
        self.logger.info("PokeballApp disabled teleoperation on intrinsic PokeballService.")

    def stop(self) -> None:
        if self.backend and hasattr(self.backend, "pokeball_service") and self.backend.pokeball_service is not None:
            self.backend.pokeball_service.teleop_enabled = False
        super().stop()
