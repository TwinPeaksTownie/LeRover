#!/usr/bin/env python3
"""PokeballApp module for Poké Ball Plus BLE teleoperation.
Implements managed BaseApp interface matching Reachy Mini application standards.
"""

import asyncio
import json
import logging
import math
import os
import random
import struct
import subprocess
import threading
import time
import urllib.request
from typing import Optional, Dict, Any

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
PI4B_SOUND_URL = "http://192.168.0.86:8082/api/play_sound"
MARIO_SOUNDS_DIR = "/home/carson/mario_sounds"
PLANT_VINE_SOUNDS = [
    "smw_vine.wav"
]


def play_chime(kind="connect"):
    """Dispatches requested sound event over HTTP to Pi 4B Touch UI audio server.
    Logs explicit warnings if network or audio request fails.
    """
    def _work():
        try:
            payload = json.dumps({"kind": kind}).encode('utf-8')
            req = urllib.request.Request(PI4B_SOUND_URL, data=payload, headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                if resp.status != 200:
                    logging.warning(f"Audio request '{kind}' returned non-200 status: {resp.status}")
        except Exception as e:
            logging.warning(f"Audio request '{kind}' to Pi 4B failed: {e}")
    threading.Thread(target=_work, daemon=True).start()


class PokeballApp(BaseApp):
    """Managed Poké Ball Plus Teleoperation Application."""
    metadata = AppMetadata(
        name="pokeball_teleop_app",
        title="Poké Ball Teleop",
        description="BLE Poké Ball Plus teleoperation for pedestal and gantry movement",
        version="1.0.0",
        tags=["teleop", "ble", "pokeball"],
        icon="🔴"
    )

    def __init__(self, mac_address: str = MAC_ADDRESS, api_url: str = API_URL) -> None:
        super().__init__()
        self.mac_address = mac_address
        self.api_url = api_url
        self.client: Optional[BleakClient] = None

        self.preset_angles = [-165.0, -135.0, -90.0, -45.0, 0.0, 45.0, 90.0, 135.0, 165.0]
        self.preset_index = 4

        self.is_busy = False
        self.busy_until = 0.0
        self.last_buttons = 0
        self.last_x_direction = "center"
        self.last_btn_top = False
        self.last_btn_stick = False
        self.home_triggered = False
        self.counter = 0
        self.connect_chime_played = False
        self.backend: Optional[RobotBackend] = None

        self.telemetry = {
            "running": False,
            "connected": False,
            "status": "DISCONNECTED",
            "mac": self.mac_address,
            "last_seen": 0.0,
            "packet_count": 0,
            "norm_x": 0.0,
            "norm_y": 0.0,
            "button_a": False,
            "button_b": False,
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

    def _get_current_s7_angle(self) -> float:
        """Retrieves live current angle of Servo 7 from backend or triggers live hardware sync."""
        if hasattr(self, "backend") and self.backend:
            pos = self.backend.aux_positions.get(7)
            if pos is None and hasattr(self.backend, "sync_servo7_position"):
                pos = self.backend.sync_servo7_position()
            if pos is not None:
                from robot_backend import ticks_to_degrees_s7
                return ticks_to_degrees_s7(pos)
        return 0.0

    def _calc_next_s7_preset(self, direction: str) -> float:
        """Calculates next clean preset angle relative to current physical hardware position."""
        curr_deg = self._get_current_s7_angle()
        from robot_backend import calc_next_s7_preset
        target_deg, _ = calc_next_s7_preset(curr_deg, direction)
        return target_deg

    def _send_aux_request(self, endpoint: str, payload: dict, lock_duration: float = 0.6) -> None:
        now = time.time()
        if self.is_busy or now < self.busy_until:
            self.logger.info("⚠️ Aux Request Ignored: Motor is currently executing a move.")
            return

        self.is_busy = True
        self.busy_until = now + lock_duration

        def _work():
            try:
                url = f"{self.api_url}{endpoint}"
                data = json.dumps(payload).encode('utf-8')
                req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
                with urllib.request.urlopen(req, timeout=3.0) as resp:
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

            # Direct Empirical Byte Parsing (No STS servo math)
            x_val = data[3] & 0x0F  # Low digit of byte 3 (2-3: Left, 4-7: Center, 8-15: Right)
            y_val = data[4]         # Byte 4 analog vertical value (rest ~118, <80: UP)

            if x_val in (2, 3):
                x_direction = "left"
            elif x_val >= 8:
                x_direction = "right"
            else:
                x_direction = "center"

            btn_top = bool(buttons & 0x01)    # Top Red Button (BLE bit 0x01)
            btn_stick = bool(buttons & 0x02)  # Joystick Press In / Stick Click (BLE bit 0x02)

            btn_a = btn_top    # Button A = Top Red Button
            btn_b = btn_stick  # Button B = Stick Click

            self.telemetry.update({
                "running": True,
                "connected": True,
                "status": "CONNECTED",
                "last_seen": time.time(),
                "packet_count": self.counter,
                "raw_hex": data.hex(' '),
                "raw_bytes": list(data),
                "data_len": len(data),
                "x_val": x_val,
                "y_val": y_val,
                "x_direction": x_direction,
                "button_top": btn_top,
                "button_stick": btn_stick,
                "button_a": btn_a,
                "button_b": btn_b,
                "last_error": None
            })
            self.write_telemetry()
        except Exception as e:
            self.logger.error("Error processing Poké Ball packet in notification_handler: %s", e, exc_info=True)
            self.telemetry["last_error"] = f"Notification parse error: {e}"
            self.write_telemetry()
            return

        now = time.time()

        if buttons != self.last_buttons:
            if buttons != 0:
                self.logger.info("🔴 POKEBALL BUTTON PRESSED: buttons=0x%02x, x_val=%d, x_dir=%s", buttons, x_val, x_direction)

        # 1. Dual-edge trigger: Top Red Button + Joystick Left/Right -> Step Motor 7 (Pedestal Spinner Presets) + Vine Sound
        top_btn_triggered = (btn_top and not self.last_btn_top and x_direction in ("left", "right"))
        x_dir_triggered = (btn_top and x_direction in ("left", "right") and x_direction != self.last_x_direction)

        if top_btn_triggered or x_dir_triggered:
            if self.is_busy or now < self.busy_until:
                self.logger.info("⚠️ Top Red Button Ignored: Movement currently in progress.")
            else:
                self.logger.info("Joystick %s -> Stepping Pedestal Preset", x_direction.title())
                self._send_aux_request("/api/pedestal_step", {"direction": x_direction}, lock_duration=0.6)
        elif btn_top and not self.last_btn_top and x_direction == "center":
            self.logger.info("🔴 Standalone Top Red Button clicked (joystick centered).")

        # 2. Dual-edge trigger: Stick Click + Joystick Left/Right -> Move Motor 8 (Gantry Rail)
        stick_btn_triggered = (btn_stick and not self.last_btn_stick and x_direction in ("left", "right"))
        gantry_dir_triggered = (btn_stick and x_direction in ("left", "right") and x_direction != self.last_x_direction)

        aux_calib_8 = getattr(self.backend, "aux_calibration", {}).get("8", {}) if self.backend else {}
        gantry_min = aux_calib_8.get("min_ticks", 3)
        gantry_max = aux_calib_8.get("max_ticks", 4800)

        if stick_btn_triggered or gantry_dir_triggered:
            if not (self.is_busy or now < self.busy_until):
                curr_gantry = self.backend.gantry_position if (self.backend and hasattr(self.backend, "gantry_position")) else 2800

                if x_direction == "left":
                    if curr_gantry <= gantry_min:
                        self.logger.info("⚠️ Gantry Min Left Limit Reached (%d ticks) - Playing Shell Ricochet", curr_gantry)
                        play_chime("smw_shell_ricochet")
                    else:
                        target_pos = max(gantry_min, curr_gantry - 500)
                        self.logger.info("Joystick Left -> Stick Clicked -> Nudging Gantry LEFT -> Target: %d ticks", target_pos)
                        self._send_aux_request("/api/move", {"id": 8, "target": target_pos}, lock_duration=0.6)
                        play_chime("smw_map_move_to_spot")
                elif x_direction == "right":
                    if curr_gantry >= gantry_max:
                        self.logger.info("⚠️ Gantry Max Right Limit Reached (%d ticks) - Playing Shell Ricochet", curr_gantry)
                        play_chime("smw_shell_ricochet")
                    else:
                        target_pos = min(gantry_max, curr_gantry + 500)
                        self.logger.info("Joystick Right -> Stick Clicked -> Nudging Gantry RIGHT -> Target: %d ticks", target_pos)
                        self._send_aux_request("/api/move", {"id": 8, "target": target_pos}, lock_duration=0.6)
                        play_chime("smw_map_move_to_spot")

        self.last_x_direction = x_direction
        self.last_btn_top = btn_top
        self.last_btn_stick = btn_stick
        self.last_buttons = buttons

    def _cleanup_bluez_device(self) -> None:
        """Purges stale BlueZ D-Bus device locks."""
        try:
            subprocess.run(["bluetoothctl", "disconnect", self.mac_address], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            subprocess.run(["bluetoothctl", "remove", self.mac_address], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            time.sleep(0.5)
        except Exception as e:
            self.logger.debug("BlueZ cleanup warning: %s", e)

    def run(self, backend: RobotBackend, stop_event: threading.Event) -> None:
        self.backend = backend
        if not BLEAK_AVAILABLE:
            self.logger.error("bleak package not installed; Poké Ball App cannot run.")
            self.error = "bleak package missing"
            return

        if backend and backend.ctrl and backend.hardware_active:
            with backend.lock:
                backend.torque_state[7] = True
                backend.torque_state[8] = True
                try:
                    backend.ctrl.set_torque(7, True)
                    backend.ctrl.set_torque(8, True)
                except Exception as e:
                    self.logger.warning(f"PokeballApp startup torque enable warning: {e}")

        async def _async_run():
            self.connect_chime_played = False
            self.telemetry.update({"running": True, "connected": False, "status": "SEARCHING", "last_error": None})
            self.write_telemetry()
            try:
                while not stop_event.is_set():
                    try:
                        self._cleanup_bluez_device()
                        self.logger.info("Connecting to Poké Ball Plus at %s...", self.mac_address)
                        self.telemetry.update({"running": True, "connected": False, "status": "SEARCHING", "last_error": None})
                        self.write_telemetry()

                        async with BleakClient(self.mac_address, timeout=6.0) as client:
                            self.client = client
                            self.logger.info("✅ Connected to Poké Ball Plus!")
                            if not self.connect_chime_played:
                                play_chime("connect")
                                self.connect_chime_played = True

                            self.telemetry.update({"running": True, "connected": True, "status": "CONNECTED", "last_seen": time.time()})
                            self.write_telemetry()

                            await client.start_notify(INPUT_UUID, self.notification_handler)
                            self.logger.info("Listening for Poké Ball Plus telemetry...")

                            while client.is_connected and not stop_event.is_set():
                                await asyncio.sleep(0.5)
                                self.telemetry["last_seen"] = time.time()
                                self.write_telemetry()

                    except Exception as e:
                        err_msg = str(e)
                        self.logger.info("Poké Ball BLE waiting for device... [%s]", err_msg)
                        self.telemetry.update({
                            "running": True,
                            "connected": False,
                            "status": "SEARCHING",
                            "last_error": err_msg
                        })
                        self.write_telemetry()
                        await asyncio.sleep(3.0)
            finally:
                if self.connect_chime_played:
                    play_chime("disconnect")
                    self.connect_chime_played = False
                self.telemetry.update({"running": False, "connected": False, "status": "DISCONNECTED"})
                self.write_telemetry()

        asyncio.run(_async_run())
