#!/usr/bin/env python3
import os
import sys
import json
import logging
import threading
import time
import urllib.request
from typing import Optional, Any
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

# App metadata
APP_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(APP_DIR, "config.json")

def load_joycon_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

_CONFIG = load_joycon_config()

current_dir = os.path.dirname(os.path.abspath(__file__))
workspace_root = os.path.abspath(os.path.join(current_dir, "..", ".."))
for p in [workspace_root, os.path.join(workspace_root, "config")]:
    if os.path.isdir(p) and p not in sys.path:
        sys.path.append(p)

from app_manager import BaseApp, AppMetadata
from robot_backend import RobotBackend
import audio_resolver
import network_resolver

try:
    from rover.rover_controller import RoverController
except ImportError:
    try:
        from rover_controller import RoverController
    except ImportError:
        RoverController = None

from pi4b.joycon_service import JoyConServiceDaemon
from pi4b.joycon_driver import JoyConState
from pi4b.gesture_engine import JoyConEvent

class JoyConApp(BaseApp):
    """Managed Teleoperation Application with Dual Rover / Aux Mode."""
    metadata = AppMetadata(
        name=_CONFIG["name"],
        title=_CONFIG["title"],
        description=_CONFIG["description"],
        version=_CONFIG["version"],
        tags=_CONFIG["tags"],
        icon=_CONFIG["icon"]
    )

    def __init__(self, api_url: str = "http://127.0.0.1:8085", rover_ctrl: Optional[Any] = None) -> None:
        super().__init__()
        self.config = _CONFIG
        self.api_url = api_url
        self.rover_ctrl = rover_ctrl
        self.backend: Optional[RobotBackend] = None
        self.joycon_service: Optional[JoyConServiceDaemon] = None
        
        self.thread_pool = ThreadPoolExecutor(max_workers=2)
        self.control_mode = "ROVER"
        self.is_armed = False

        self.last_speed_step_time = 0.0
        self.speed_step_cooldown = float(self.config["control"]["speed_step_cooldown_sec"])

    def _play_chime(self, event_name: str) -> None:
        sound_file = audio_resolver.get_audio_filename(event_name)
        def _work():
            try:
                port = int(network_resolver.get_ports()["pi4b_http"])
                url = f"http://127.0.0.1:{port}/api/play_sound"
                payload = json.dumps({"kind": sound_file, "event": event_name, "stop_previous": False, "delay_sec": 0.0}).encode('utf-8')
                req = urllib.request.Request(url, data=payload, headers={'Content-Type': 'application/json'})
                with urllib.request.urlopen(req, timeout=1.5):
                    pass
            except Exception as e:
                self.logger.warning("Audio request '%s' failed: %s", event_name, e)
        self.thread_pool.submit(_work)

    def _send_aux_request(self, endpoint: str, payload: dict) -> None:
        def _work():
            try:
                url = f"{self.api_url}{endpoint}"
                data = json.dumps(payload).encode('utf-8')
                req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
                with urllib.request.urlopen(req, timeout=2.5):
                    pass
            except Exception as e:
                self.logger.warning("Aux API dispatch error (%s): %s", endpoint, e)
        self.thread_pool.submit(_work)

    def on_button_a_held(self):
        self.control_mode = "ROVER"
        self.is_armed = True
        self.logger.info("🏎️ [MODE SWITCH] Switched back to ROVER Mode and armed drivetrain.")
        self._play_chime(self.config["chimes"]["arm_rover"])

    def on_button_b_click(self):
        # Aux Mode Toggle
        if self.control_mode == "ROVER":
            self.control_mode = "AUX"
            self.is_armed = False
            if self.rover_ctrl:
                self.rover_ctrl.set_drive(0.0, 0.0)
            self.logger.info("⚙️ [MODE SWITCH] Switched to AUX Mode (Pedestal/Gantry). Drivetrain disarmed.")
            self._play_chime(self.config["chimes"]["mode_switch_aux"])
        else:
            self.control_mode = "ROVER"
            self.is_armed = True
            self.logger.info("🏎️ [MODE SWITCH] Switched to ROVER Mode.")
            self._play_chime(self.config["chimes"]["mode_switch_rover"])

    def on_button_b_hold(self):
        self.logger.info("🎙️ [BUTTON B HOLD 2.0s] Stopping active apps and launching listener_app...")
        if self.app_manager:
            self._play_chime(self.config["chimes"]["app_start"])
            self.thread_pool.submit(self._launch_listener)

    def _launch_listener(self):
        try:
            self.app_manager.stop_all()
            self.app_manager.start_app_by_name("listener_app")
        except Exception as ex:
            self.logger.error("Failed launching listener_app: %s", ex, exc_info=True)

    def on_button_y_click(self):
        self.logger.info("[BUTTON Y CLICK] Closing active app and returning to IDLE...")
        if self.app_manager:
            curr_app = self.app_manager.current_app_name
            if curr_app:
                self.thread_pool.submit(self.app_manager.stop_app, curr_app)
        self._play_chime(self.config["chimes"]["app_exit_idle"])

    def on_state_update(self, state: JoyConState):
        if self.stop_event.is_set():
            return

        now = state.timestamp
        # 3. SPEED STEPPING (SR / SL)
        btn_sr = state.buttons.get("sr", False)
        btn_sl = state.buttons.get("sl", False)
        
        if (btn_sr or btn_sl) and (now - self.last_speed_step_time) > self.speed_step_cooldown:
            if self.rover_ctrl:
                delta = self.config["control"]["speed_step_pct"] if btn_sr else -self.config["control"]["speed_step_pct"]
                new_speed = self.rover_ctrl.adjust_speed_pct(delta)
                self.last_speed_step_time = now
                self._play_chime(self.config["chimes"]["speed_up"] if btn_sr else self.config["chimes"]["speed_down"])
                self.logger.info("Speed stepped to %d%%", new_speed)

        # 4. MODE ACTUATION
        if self.control_mode == "ROVER" and self.is_armed and self.rover_ctrl:
            btn_r = state.buttons.get("r", False)
            btn_zr = state.buttons.get("zr", False)
            throttle = 0.0
            if btn_r and not btn_zr:
                throttle = 1.0
            elif btn_zr and not btn_r:
                throttle = -1.0
            steering = state.stick_norm_x
            self.rover_ctrl.set_drive(steering, throttle)

        elif self.control_mode == "AUX":
            norm_x = state.stick_norm_x
            norm_y = state.stick_norm_y
            
            # Simple discrete direction for AUX
            if norm_x < -0.35: x_dir = "left"
            elif norm_x > 0.35: x_dir = "right"
            else: x_dir = "center"
            
            if norm_y < -0.35: y_dir = "down"
            elif norm_y > 0.35: y_dir = "up"
            else: y_dir = "center"

            ticks = self.config["control"]["gantry_step_ticks"]
            if x_dir == "right":
                self._send_aux_request("/api/gantry_step", {"axis": "x", "ticks": ticks})
            elif x_dir == "left":
                self._send_aux_request("/api/gantry_step", {"axis": "x", "ticks": -ticks})
            if y_dir == "up":
                self._send_aux_request("/api/pedestal_step", {"ticks": ticks})
            elif y_dir == "down":
                self._send_aux_request("/api/pedestal_step", {"ticks": -ticks})

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

        if self.rover_ctrl is None:
            self.rover_ctrl = RoverController()
            self.rover_ctrl.start()

        self.is_armed = True
        self.control_mode = "ROVER"
        self.rover_ctrl.set_drive(0.0, 0.0)

        # Register pub/sub events
        self.joycon_service.register_event_callback(JoyConEvent.BUTTON_A_HELD_2S, self.on_button_a_held)
        self.joycon_service.register_event_callback(JoyConEvent.BUTTON_B_SINGLE_CLICK, self.on_button_b_click)
        self.joycon_service.register_event_callback(JoyConEvent.BUTTON_B_HOLD_2S, self.on_button_b_hold)
        self.joycon_service.register_event_callback(JoyConEvent.BUTTON_Y_CLICK, self.on_button_y_click)
        self.joycon_service.register_state_callback(self.on_state_update)

        self.logger.info("JoyConApp enabled teleoperation on intrinsic JoyConServiceDaemon.")

        while not stop_event.is_set():
            stop_event.wait(0.1)

    def on_stop(self) -> None:
        self.is_armed = False
        if self.rover_ctrl:
            self.rover_ctrl.stop()
        self.thread_pool.shutdown(wait=False)
        self.logger.info("JoyConApp stopped.")
