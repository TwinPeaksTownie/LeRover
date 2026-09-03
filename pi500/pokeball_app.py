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

# Ensure rover package is importable
current_dir = os.path.dirname(os.path.abspath(__file__))
workspace_root = os.path.abspath(os.path.join(current_dir, ".."))
if workspace_root not in sys.path:
    sys.path.insert(0, workspace_root)

try:
    from rover.rover_controller import RoverController
except ImportError:
    try:
        from rover_controller import RoverController
    except ImportError:
        RoverController = None

try:
    from bleak import BleakClient
    BLEAK_AVAILABLE = True
except ImportError:
    BleakClient = None
    BLEAK_AVAILABLE = False

from app_manager import BaseApp, AppMetadata
from robot_backend import RobotBackend

MAC_ADDRESS = "58:2F:40:8D:50:71"
INPUT_UUID = "6675e16c-f36d-4567-bb55-6b51e27a23e6"
API_URL = "http://127.0.0.1:8085"
TELEMETRY_FILE = "/tmp/pokeball_telemetry.json"

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


def play_chime(kind="connect"):
    """Dispatches requested sound event over HTTP to Pi 4B Touch UI audio server."""
    def _work():
        try:
            payload = json.dumps({"kind": kind}).encode('utf-8')
            req = urllib.request.Request(get_pi4b_sound_url(), data=payload, headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                if resp.status != 200:
                    logging.warning(f"Audio request '{kind}' returned non-200 status: {resp.status}")
        except Exception as e:
            logging.warning(f"Audio request '{kind}' to Pi 4B failed: {e}")
    threading.Thread(target=_work, daemon=True).start()


class PokeballService:
    """Intrinsic daemon service managing persistent BLE connection and voice state machine for Poké Ball Plus."""

    def __init__(
        self,
        mac_address: str = MAC_ADDRESS,
        api_url: str = API_URL,
        backend: Optional[RobotBackend] = None,
        voice_bridge_url: str = "http://192.168.0.194:8058"
    ) -> None:
        self.mac_address = mac_address
        self.api_url = api_url
        self.backend = backend
        self.voice_bridge_url = voice_bridge_url
        self.client: Optional[BleakClient] = None
        self.stop_event = threading.Event()
        self.thread: Optional[threading.Thread] = None
        self.logger = logging.getLogger("so101.pokeball_service")

        self.is_connected = False
        self.is_listening = False
        self.btn_b_press_start_time: Optional[float] = None
        self.last_btn_b = False
        self.connect_chime_played = False
        self.counter = 0

        # Teleoperation state
        self.teleop_enabled = False
        self.control_mode = "AUX"
        self.stick_press_start_time: Optional[float] = None
        self.mode_switch_triggered = False
        self.last_btn_stick_press_time = 0.0
        self.last_rover_interaction_time = 0.0
        self.rover_drive_active_time = 0.0
        self.rover_ctrl = None

        self.is_busy = False
        self.busy_until = 0.0
        self.last_btn_top = False
        self.last_btn_stick = False
        self.last_x_direction = "center"

        self.telemetry = {
            "running": True,
            "connected": False,
            "status": "SEARCHING",
            "is_listening": False,
            "control_mode": self.control_mode,
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
        """Prompts Carson over TTS via Voice Bridge upon daemon startup."""
        def _prompt():
            time.sleep(2.0)
            try:
                url = f"{self.voice_bridge_url}/api/voice/prompt_connect"
                req = urllib.request.Request(url, data=b"{}", headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=5.0) as resp:
                    if resp.status == 200:
                        self.logger.info("📢 Broadcast connection prompt to Carson over Laura TTS.")
            except Exception as e:
                self.logger.warning("Connection prompt broadcast to Voice Bridge failed: %s", e)
        threading.Thread(target=_prompt, daemon=True).start()

    def _notify_voice_bridge(self, event: str) -> None:
        """Sends button event to Voice Bridge on the PC."""
        def _post():
            try:
                url = f"{self.voice_bridge_url}/api/voice/button_event"
                payload = json.dumps({"button": "B", "event": event}).encode("utf-8")
                req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=3.0) as resp:
                    self.logger.info(f"Notified Voice Bridge of '{event}': status {resp.status}")
            except Exception as e:
                self.logger.warning(f"Failed to notify Voice Bridge of '{event}': {e}")
        threading.Thread(target=_post, daemon=True).start()

    def _start_robot_mic(self) -> None:
        """Triggers onboard PulseAudio microphone capture on Pi 4B."""
        def _work():
            try:
                url = f"{get_pi4b_base_url()}/api/microphone/start"
                req = urllib.request.Request(url, data=b"{}", headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=2.0) as resp:
                    self.logger.info("🎤 Robot onboard microphone capture STARTED.")
            except Exception as e:
                self.logger.warning(f"Failed to start robot microphone on Pi 4B: {e}")
        threading.Thread(target=_work, daemon=True).start()

    def _stop_robot_mic(self) -> None:
        """Stops Pi 4B microphone capture and dispatches recorded WAV to Voice Bridge."""
        def _work():
            try:
                url = f"{get_pi4b_base_url()}/api/microphone/stop"
                payload = json.dumps({"voice_bridge_url": f"{self.voice_bridge_url}/api/voice/process_audio"}).encode('utf-8')
                req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=4.0) as resp:
                    self.logger.info("🎤 Robot onboard microphone capture STOPPED & dispatched to Voice Bridge.")
            except Exception as e:
                self.logger.warning(f"Failed to stop robot microphone on Pi 4B: {e}")
        threading.Thread(target=_work, daemon=True).start()

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

            x_offset = raw_x_12 - 2048
            y_offset = raw_y_12 - 2048

            norm_x = max(-1.0, min(1.0, x_offset / 2048.0))
            norm_y = max(-1.0, min(1.0, y_offset / 2048.0))

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

            # --- VOICE INTERACTION STATE MACHINE (Top Red Button B) ---
            if not self.is_listening:
                # 1. Start listening via 3-second hold of Button B
                if btn_b:
                    if self.btn_b_press_start_time is None:
                        self.btn_b_press_start_time = now
                    hold_duration = now - self.btn_b_press_start_time
                    hold_progress = min(1.0, hold_duration / 3.0)
                    self.telemetry["hold_progress"] = hold_progress

                    if hold_duration >= 3.0:
                        self.is_listening = True
                        self.telemetry["is_listening"] = True
                        self.btn_b_press_start_time = None
                        self.telemetry["hold_progress"] = 0.0
                        self.logger.info("🎙️ [VOICE] 3-second Button B hold detected! Listening mode STARTED.")
                        play_chime("smw_save_menu")
                        self._start_robot_mic()
                else:
                    self.btn_b_press_start_time = None
                    self.telemetry["hold_progress"] = 0.0
            else:
                # 2. Stop listening via single click of Button B (rising edge)
                if btn_b and not self.last_btn_b:
                    self.is_listening = False
                    self.telemetry["is_listening"] = False
                    self.btn_b_press_start_time = None
                    self.logger.info("🛑 [VOICE] Single Button B click detected! Listening mode STOPPED.")
                    play_chime("smw_stomp_bones")
                    self._stop_robot_mic()

            # --- OPTIONAL TELEOP ACTUATION (If enabled via Kiosk / AppManager) ---
            if self.teleop_enabled:
                is_stick_centered = (abs(norm_x) < 0.55 and abs(norm_y) < 0.55)
                if btn_a and is_stick_centered:
                    self.last_btn_stick_press_time = now
                    if self.stick_press_start_time is None:
                        self.stick_press_start_time = now
                    hold_duration = now - self.stick_press_start_time
                    if hold_duration >= 3.0 and not self.mode_switch_triggered:
                        if self.control_mode == "AUX":
                            self.control_mode = "ROVER"
                            self.rover_drive_active_time = now + 4.25
                            self.last_rover_interaction_time = now
                            if self.rover_ctrl:
                                self.rover_ctrl.stop()
                            play_chime("mario_kart_start")
                            self.logger.info("🏎️ [MODE SWITCH] Switched to ROVER DRIVE MODE!")
                        else:
                            self.control_mode = "AUX"
                            if self.rover_ctrl:
                                self.rover_ctrl.stop()
                            play_chime("disconnect")
                            self.logger.info("🦾 [MODE SWITCH] Switched to AUX MANIPULATOR MODE!")
                        self.mode_switch_triggered = True
                elif not btn_a:
                    if now - self.last_btn_stick_press_time > 0.25:
                        self.stick_press_start_time = None
                        self.mode_switch_triggered = False

                if self.control_mode == "ROVER":
                    if btn_b and not self.last_btn_top:
                        self.control_mode = "AUX"
                        if self.rover_ctrl:
                            self.rover_ctrl.stop()
                        play_chime("disconnect")
                    elif self.rover_ctrl and now >= self.rover_drive_active_time:
                        self.rover_ctrl.set_drive(norm_x, norm_y)

                elif self.control_mode == "AUX":
                    top_btn_triggered = (btn_b and not self.last_btn_top and x_direction in ("left", "right"))
                    if top_btn_triggered and not (self.is_busy or now < self.busy_until):
                        self._send_aux_request("/api/pedestal_step", {"direction": x_direction}, lock_duration=0.6)

            self.last_btn_b = btn_b
            self.last_btn_top = btn_b
            self.last_btn_stick = btn_a
            self.last_x_direction = x_direction

            self.telemetry.update({
                "packet_count": self.counter,
                "last_seen": now,
                "control_mode": self.control_mode,
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
                            play_chime("connect")
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
        name="pokeball_teleop_app",
        title="Poké Ball Teleop",
        description="BLE Poké Ball Plus teleoperation for pedestal, gantry, and rover drive",
        version="2.1.0",
        tags=["teleop", "ble", "pokeball", "rover"],
        icon="🔴"
    )

    def __init__(self, mac_address: str = MAC_ADDRESS, api_url: str = API_URL, rover_ctrl: Optional[Any] = None) -> None:
        super().__init__()
        self.mac_address = mac_address
        self.api_url = api_url
        self.rover_ctrl = rover_ctrl
        self.backend: Optional[RobotBackend] = None

    def run(self, backend: RobotBackend, stop_event: threading.Event) -> None:
        self.backend = backend
        service: Optional[PokeballService] = getattr(backend, "pokeball_service", None)
        if service:
            service.teleop_enabled = True
            if backend and getattr(backend, "rover_ctrl", None) is not None:
                service.rover_ctrl = backend.rover_ctrl
            elif service.rover_ctrl is None and RoverController is not None:
                service.rover_ctrl = RoverController()
                service.rover_ctrl.start()

            self.logger.info("PokeballApp enabled teleoperation on intrinsic PokeballService.")
            while not stop_event.is_set():
                time.sleep(0.5)
            service.teleop_enabled = False
            self.logger.info("PokeballApp disabled teleoperation on intrinsic PokeballService.")
        else:
            self.logger.error("No intrinsic PokeballService found on backend.")
            while not stop_event.is_set():
                time.sleep(0.5)

    def stop(self) -> None:
        if self.backend and getattr(self.backend, "pokeball_service", None):
            self.backend.pokeball_service.teleop_enabled = False
        super().stop()
