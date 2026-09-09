#!/usr/bin/env python3
"""apps/teleop_app/app.py - Managed ZMQ Teleoperation Application.
Implements managed BaseApp interface for socket handling and high-frequency arm control.
Loads self-contained configuration from apps/teleop_app/config.json.
"""

import json
import logging
import math
import os
import sys
import time
import urllib.request
import threading
from typing import Optional, Dict, Any, Tuple
import zmq

from app_manager import BaseApp, AppMetadata
from robot_backend import RobotBackend

try:
    import network_resolver
except ImportError:
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "pi4b"))
    import network_resolver

APP_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(APP_DIR, "config.json")

def load_teleop_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        raise FileNotFoundError(f"Missing required Teleop config file: {CONFIG_PATH}")
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    # Fail-fast validation
    _ = cfg["name"]
    _ = cfg["teleop"]["port_zmq_cmd"]
    _ = cfg["teleop"]["port_zmq_obs"]
    _ = cfg["teleop"]["watchdog_timeout_ms"]
    _ = cfg["teleop"]["max_loop_freq_hz"]
    _ = cfg["teleop"]["gripper_bounds"]
    _ = cfg["teleop"]["arm_bounds"]
    return cfg

_CONFIG = load_teleop_config()

def get_mac_api_url() -> str:
    mac_ip = network_resolver.get_mac_ip(prefer_port=8086)
    return f"http://{mac_ip}:8086"

def get_motor_norm_bounds(motor: str, cfg: dict = _CONFIG) -> Tuple[float, float]:
    """Returns normalized percentage bounds for SO-101 joints based on LeRobot norm mode."""
    if motor == "gripper":
        return tuple(cfg["teleop"]["gripper_bounds"])
    return tuple(cfg["teleop"]["arm_bounds"])

def validate_and_clamp_teleop_frame(action: dict, calibration: dict, cfg: dict = _CONFIG) -> Optional[dict]:
    """Strictly validates incoming ZMQ teleop frame against network contracts and local calibration bounds."""
    if not isinstance(action, dict) or not action:
        logging.warning("Teleop frame dropped: Invalid or empty JSON payload.")
        return None

    clamped_frame = {}
    for motor, raw_val in action.items():
        if motor not in calibration:
            logging.warning("Teleop frame dropped: Unrecognized or uncalibrated motor key '%s'", motor)
            return None

        try:
            val = float(raw_val)
        except (ValueError, TypeError):
            logging.warning("Teleop frame dropped: Non-numeric value for motor '%s': %s", motor, raw_val)
            return None

        if not math.isfinite(val):
            logging.warning("Teleop frame dropped: Non-finite float value for motor '%s': %s", motor, val)
            return None

        min_bound, max_bound = get_motor_norm_bounds(motor, cfg)
        clamped_frame[motor] = max(min_bound, min(max_bound, val))

    return clamped_frame


class TeleopControlApp(BaseApp):
    """Managed ZMQ Teleoperation Application."""
    _config = load_teleop_config()
    metadata = AppMetadata(
        name=_config["name"],
        title=_config["title"],
        description=_config["description"],
        version=_config["version"],
        tags=_config["tags"],
        icon=_config["icon"]
    )

    def __init__(self, no_zmq: bool = False, config: Optional[dict] = None) -> None:
        super().__init__()
        self.no_zmq = no_zmq
        self.config = config or load_teleop_config()
        self.cached_leader_status = {"running": False, "pid": ""}

    def _poll_leader_loop(self, stop_event: threading.Event) -> None:
        consecutive_failures = 0
        poll_interval = float(self.config["teleop"]["poll_leader_interval_sec"])
        while not stop_event.is_set():
            try:
                req = urllib.request.Request(
                    f"{get_mac_api_url()}/api/status", headers={"User-Agent": "SO101-TeleopApp"}
                )
                with urllib.request.urlopen(req, timeout=0.8) as response:
                    if response.status == 200:
                        data = json.loads(response.read().decode())
                        leader_data = (
                            data.get("leader", data)
                            if isinstance(data.get("leader"), dict)
                            else data
                        )
                        self.cached_leader_status = {
                            "running": bool(leader_data.get("running", False)),
                            "pid": str(leader_data.get("pid", "")),
                        }
                        consecutive_failures = 0
                    else:
                        consecutive_failures += 1
            except Exception:
                consecutive_failures += 1
                if consecutive_failures >= 2:
                    self.cached_leader_status = {"running": False, "pid": ""}
            time.sleep(poll_interval)

    def run(self, backend: RobotBackend, stop_event: threading.Event) -> None:
        self.logger.info("Initializing ZMQ Teleop Application...")
        ctx = None
        cmd_sock = None
        obs_sock = None

        port_cmd = self.config["teleop"]["port_zmq_cmd"]
        port_obs = self.config["teleop"]["port_zmq_obs"]
        watchdog_timeout_ms = self.config["teleop"]["watchdog_timeout_ms"]
        max_loop_freq_hz = self.config["teleop"]["max_loop_freq_hz"]

        leader_thread = threading.Thread(
            target=self._poll_leader_loop, args=(stop_event,), daemon=True
        )
        leader_thread.start()

        if not self.no_zmq:
            ctx = zmq.Context()
            cmd_sock = ctx.socket(zmq.PULL)
            cmd_sock.setsockopt(zmq.CONFLATE, 1)
            cmd_sock.setsockopt(zmq.LINGER, 0)
            cmd_sock.bind(f"tcp://*:{port_cmd}")

            obs_sock = ctx.socket(zmq.PUSH)
            obs_sock.setsockopt(zmq.CONFLATE, 1)
            obs_sock.setsockopt(zmq.LINGER, 0)
            obs_sock.bind(f"tcp://*:{port_obs}")

            self.logger.info(f"ZMQ listening on ports {port_cmd}/{port_obs}")

        last_cmd_time = time.time()
        watchdog_active = False
        teleop_gate_unlocked = False

        try:
            while not stop_event.is_set():
                loop_start = time.time()

                if self.no_zmq:
                    time.sleep(max(1 / max_loop_freq_hz - (time.time() - loop_start), 0))
                    continue

                try:
                    msg = cmd_sock.recv_string(zmq.NOBLOCK)
                    action = json.loads(msg)

                    goal_pos = validate_and_clamp_teleop_frame(action, backend.arm_calibration, self.config)
                    if goal_pos is None:
                        continue

                    is_power_connected = backend.power_mgr.is_connected() if backend.power_mgr else True
                    if not backend.follower_active or not is_power_connected:
                        continue

                    if hasattr(backend, "dispatch_teleop_frame"):
                        backend.dispatch_teleop_frame(goal_pos)

                    with backend.lock:
                        backend.last_arm_positions = goal_pos

                    last_cmd_time = time.time()
                    teleop_gate_unlocked = True
                    if watchdog_active:
                        self.logger.info("Commands resumed.")
                    watchdog_active = False

                except zmq.Again:
                    pass
                except Exception as e:
                    self.logger.error("Command handling failed: %s", e)

                if teleop_gate_unlocked and (time.time() - last_cmd_time > watchdog_timeout_ms / 1000) and not watchdog_active:
                    self.logger.warning("No commands for %dms, holding pose", watchdog_timeout_ms)
                    watchdog_active = True
                    teleop_gate_unlocked = False

                try:
                    if obs_sock:
                        with backend.lock:
                            last_pos = dict(backend.last_arm_positions)
                        obs_sock.send_string(json.dumps(last_pos), flags=zmq.NOBLOCK)
                except Exception as e:
                    self.logger.debug("Observation socket send exception: %s", e)

                time.sleep(max(1 / max_loop_freq_hz - (time.time() - loop_start), 0))

        finally:
            self.logger.info("Cleaning up ZMQ sockets...")
            if cmd_sock:
                cmd_sock.close(linger=0)
            if obs_sock:
                obs_sock.close(linger=0)
            if ctx:
                ctx.term()
            self.logger.info("ZMQ Teleop Application stopped.")
