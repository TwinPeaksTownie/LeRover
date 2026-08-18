#!/usr/bin/env python3
"""PokeballApp module for Poké Ball Plus BLE teleoperation.
Implements managed BaseApp interface matching Reachy Mini application standards.
Supports dual-mode operation:
- AUX Manipulator Mode (Gantry & Pedestal control)
- ROVER Drive Mode (Overlander-4 differential drive via GPIO UART to KB2040)
Transitions between modes via 3-second Joystick Press (Button A) hold with Mario Kart audio sync.
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
    """Managed Poké Ball Plus Teleoperation Application with Dual Aux/Rover Mode."""
    metadata = AppMetadata(
        name="pokeball_teleop_app",
        title="Poké Ball Teleop",
        description="BLE Poké Ball Plus teleoperation for pedestal, gantry, and rover drive",
        version="2.0.0",
        tags=["teleop", "ble", "pokeball", "rover"],
        icon="🔴"
    )

    def __init__(self, mac_address: str = MAC_ADDRESS, api_url: str = API_URL, rover_ctrl: Optional[Any] = None) -> None:
        super().__init__()
        self.mac_address = mac_address
        self.api_url = api_url
        self.client: Optional[BleakClient] = None

        # Mode state machine: 'AUX' (Manipulator) or 'ROVER' (Drivetrain)
        self.control_mode: str = "AUX"
        self.stick_press_start_time: Optional[float] = None
        self.mode_switch_triggered: bool = False
        self.last_btn_stick_press_time: float = 0.0

        # Rover safety timing
        self.rover_start_time: float = 0.0
        self.rover_drive_active_time: float = 0.0  # Startup lockout (sound duration + 1.0s safety delay)
        self.last_rover_interaction_time: float = 0.0  # 30-second inactivity timeout tracker

        # Rover controller instance
        if rover_ctrl is not None:
            self.rover_ctrl = rover_ctrl
        elif RoverController is not None:
            self.rover_ctrl = RoverController()
        else:
            self.rover_ctrl = None

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
            "control_mode": self.control_mode,
            "hold_progress": 0.0,
            "rover_ready": False,
            "ready_countdown": 0.0,
            "inactivity_seconds": 0.0,
            "mac": self.mac_address,
            "last_seen": 0.0,
            "packet_count": 0,
            "norm_x": 0.0,
            "norm_y": 0.0,
            "button_a": False,  # Stick Click
            "button_b": False,  # Top Red Button
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

            # 12-Bit Joystick Decoding (X: steering, Y: throttle)
            raw_x_12 = data[2] | ((data[3] & 0x0F) << 8)
            raw_y_12 = (data[3] >> 4) | (data[4] << 4)

            x_offset = raw_x_12 - 2048
            y_offset = raw_y_12 - 2048

            norm_x = max(-1.0, min(1.0, x_offset / 2048.0))
            norm_y = max(-1.0, min(1.0, y_offset / 2048.0))

            # Deadzone filter
            if abs(norm_x) < 0.08:
                norm_x = 0.0
            if abs(norm_y) < 0.08:
                norm_y = 0.0

            # Direction classification for discrete step gestures
            if norm_x < -0.35:
                x_direction = "left"
            elif norm_x > 0.35:
                x_direction = "right"
            else:
                x_direction = "center"

            # Button Mapping:
            # Button A (Stick Click) = 0x02
            # Button B (Top Red Button) = 0x01
            btn_stick = bool(buttons & 0x02)  # Button A
            btn_top = bool(buttons & 0x01)    # Button B

            btn_a = btn_stick
            btn_b = btn_top

            now = time.time()

            # --- 3-SECOND JOYSTICK PRESS (BUTTON A) HOLD LOGIC ---
            hold_progress = 0.0
            # Relaxed center deadzone (55%) so firm thumb pressure during stick click doesn't cancel hold
            is_stick_centered = (abs(norm_x) < 0.55 and abs(norm_y) < 0.55)

            if btn_stick and is_stick_centered:
                self.last_btn_stick_press_time = now
                if self.stick_press_start_time is None:
                    self.stick_press_start_time = now
                
                hold_duration = now - self.stick_press_start_time
                hold_progress = min(1.0, hold_duration / 3.0)

                if hold_duration >= 3.0 and not self.mode_switch_triggered:
                    if self.control_mode == "AUX":
                        self.control_mode = "ROVER"
                        self.rover_start_time = now
                        self.rover_drive_active_time = now + 4.25  # 3.25s audio + 1.0s safety delay = 4.25s lockout
                        self.last_rover_interaction_time = now
                        if self.rover_ctrl:
                            self.rover_ctrl.start()
                            self.rover_ctrl.stop()
                        play_chime("mario_kart_start")
                        self.logger.info("🏎️ [MODE SWITCH] Switched to ROVER DRIVE MODE! Mario Kart countdown active (drive output unlocks in 4.25s).")
                    else:
                        self.control_mode = "AUX"
                        if self.rover_ctrl:
                            self.rover_ctrl.stop()
                        play_chime("disconnect")
                        self.logger.info("🦾 [MODE SWITCH] Switched to AUX MANIPULATOR MODE! Zeroed rover motors.")
                    
                    self.mode_switch_triggered = True
            elif not btn_stick:
                # 250ms release debounce buffer: prevents packet drops / glitch / interleaving from resetting hold timer
                if now - getattr(self, "last_btn_stick_press_time", 0.0) > 0.25:
                    self.stick_press_start_time = None
                    self.mode_switch_triggered = False


            # --- ROVER DRIVE MODE EXECUTION ---
            if self.control_mode == "ROVER":
                # 1. Top Red Button (Button B) Cancel: Immediately cancels Rover Mode & returns to Aux
                if btn_top and not self.last_btn_top:
                    self.control_mode = "AUX"
                    if self.rover_ctrl:
                        self.rover_ctrl.stop()
                    play_chime("disconnect")
                    self.logger.info("🛑 [MODE CANCEL] Top Red Button (Button B) pressed -> Canceled Rover Mode & returned to Aux Mode.")
                else:
                    # 2. 30-Second Inactivity Watchdog Timeout
                    is_active_input = (abs(norm_x) > 0.08 or abs(norm_y) > 0.08 or btn_stick)
                    if is_active_input:
                        self.last_rover_interaction_time = now

                    inactivity_dur = now - self.last_rover_interaction_time
                    if inactivity_dur >= 30.0:
                        self.control_mode = "AUX"
                        if self.rover_ctrl:
                            self.rover_ctrl.stop()
                        play_chime("disconnect")
                        self.logger.info("⏰ [INACTIVITY TIMEOUT] 30s elapsed with no drive input -> Auto-returned to Aux Mode.")
                    elif self.rover_ctrl:
                        # 3. 1.0s Post-Audio Safety Lockout Delay: Wheels strictly locked at 1500 during countdown + 1.0s buffer
                        if now < self.rover_drive_active_time:
                            self.rover_ctrl.stop()
                        else:
                            self.rover_ctrl.set_drive(norm_x, norm_y)


            # --- AUX MANIPULATOR MODE EXECUTION ---
            elif self.control_mode == "AUX":
                # 1. Dual-edge trigger: Top Red Button (Button B) + Stick L/R -> Step Pedestal Spinner (Motor 7)
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

                # 2. Dual-edge trigger: Stick Click (Button A) + Stick L/R -> Nudge LeSlider Gantry (Motor 8)
                # Only triggers if joystick was actively tilted left/right (canceling 3s hold mode toggle)
                stick_btn_triggered = (btn_stick and not self.last_btn_stick and x_direction in ("left", "right"))
                gantry_dir_triggered = (btn_stick and x_direction in ("left", "right") and x_direction != self.last_x_direction)

                if (stick_btn_triggered or gantry_dir_triggered) and not self.mode_switch_triggered:
                    self.stick_press_start_time = None  # Cancel mode switch hold
                    aux_calib_8 = getattr(self.backend, "aux_calibration", {}).get("8", {}) if self.backend else {}
                    gantry_min = aux_calib_8.get("min_ticks", 3)
                    gantry_max = aux_calib_8.get("max_ticks", 4800)

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

            rover_ready = (self.control_mode == "ROVER" and now >= self.rover_drive_active_time)
            ready_countdown = max(0.0, self.rover_drive_active_time - now) if (self.control_mode == "ROVER" and not rover_ready) else 0.0
            inactivity_seconds = max(0.0, now - self.last_rover_interaction_time) if self.control_mode == "ROVER" else 0.0

            self.telemetry.update({
                "running": True,
                "connected": True,
                "status": "CONNECTED",
                "control_mode": self.control_mode,
                "hold_progress": hold_progress,
                "rover_ready": rover_ready,
                "ready_countdown": ready_countdown,
                "inactivity_seconds": inactivity_seconds,
                "last_seen": time.time(),
                "packet_count": self.counter,
                "raw_hex": data.hex(' '),
                "raw_bytes": list(data),
                "data_len": len(data),
                "norm_x": norm_x,
                "norm_y": norm_y,
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
                if self.rover_ctrl:
                    self.rover_ctrl.shutdown()
                if self.connect_chime_played:
                    play_chime("disconnect")
                    self.connect_chime_played = False
                self.telemetry.update({"running": False, "connected": False, "status": "DISCONNECTED"})
                self.write_telemetry()

        asyncio.run(_async_run())
