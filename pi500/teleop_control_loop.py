#!/usr/bin/env python3
"""TeleopControlApp module for ZMQ-based leader-follower teleoperation.
Implements managed BaseApp interface for socket handling and high-frequency arm control.
"""

import json
import logging
import math
import time
import urllib.request
import threading
from typing import Optional, Dict, Any, Tuple
import zmq

from app_manager import BaseApp, AppMetadata
from robot_backend import RobotBackend, SERIAL_LOCK

PORT_ZMQ_CMD = 5555
PORT_ZMQ_OBS = 5556
WATCHDOG_TIMEOUT_MS = 500
MAX_LOOP_FREQ_HZ = 60
MAC_API_URL = "http://192.168.0.2:8086"

CACHED_LEADER_STATUS = {"running": False, "pid": ""}


def get_motor_norm_bounds(motor: str) -> Tuple[float, float]:
    """Returns normalized percentage bounds for SO-101 joints based on LeRobot norm mode."""
    if motor == "gripper":
        return (0.0, 100.0)
    return (-100.0, 100.0)


def validate_and_clamp_teleop_frame(action: dict, calibration: dict) -> Optional[dict]:
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

        min_bound, max_bound = get_motor_norm_bounds(motor)
        clamped_frame[motor] = max(min_bound, min(max_bound, val))

    return clamped_frame


class TeleopControlApp(BaseApp):
    """Managed ZMQ Teleoperation Application."""
    metadata = AppMetadata(
        name="teleop_app",
        title="Teleop Control Loop",
        description="ZMQ leader-follower remote teleoperation control loop",
        version="1.0.0",
        tags=["teleop", "zmq", "so101"],
        icon="🎮"
    )

    def __init__(self, no_zmq: bool = False) -> None:
        super().__init__()
        self.no_zmq = no_zmq
        self.cached_leader_status = dict(CACHED_LEADER_STATUS)

    def _poll_leader_loop(self, stop_event: threading.Event) -> None:
        consecutive_failures = 0
        while not stop_event.is_set():
            try:
                req = urllib.request.Request(
                    f"{MAC_API_URL}/api/status", headers={"User-Agent": "SO101-TeleopApp"}
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
            time.sleep(1.0)

    def run(self, backend: RobotBackend, stop_event: threading.Event) -> None:
        self.logger.info("Initializing ZMQ Teleop Application...")
        ctx = None
        cmd_sock = None
        obs_sock = None

        leader_thread = threading.Thread(
            target=self._poll_leader_loop, args=(stop_event,), daemon=True
        )
        leader_thread.start()

        if not self.no_zmq:
            ctx = zmq.Context()
            cmd_sock = ctx.socket(zmq.PULL)
            cmd_sock.setsockopt(zmq.CONFLATE, 1)
            cmd_sock.setsockopt(zmq.LINGER, 0)
            cmd_sock.bind(f"tcp://*:{PORT_ZMQ_CMD}")

            obs_sock = ctx.socket(zmq.PUSH)
            obs_sock.setsockopt(zmq.CONFLATE, 1)
            obs_sock.setsockopt(zmq.LINGER, 0)
            obs_sock.bind(f"tcp://*:{PORT_ZMQ_OBS}")

            self.logger.info(f"ZMQ listening on ports {PORT_ZMQ_CMD}/{PORT_ZMQ_OBS}")

        last_cmd_time = time.time()
        watchdog_active = False
        teleop_gate_unlocked = False

        try:
            while not stop_event.is_set():
                loop_start = time.time()

                if self.no_zmq:
                    time.sleep(max(1 / MAX_LOOP_FREQ_HZ - (time.time() - loop_start), 0))
                    continue

                try:
                    msg = cmd_sock.recv_string(zmq.NOBLOCK)
                    action = json.loads(msg)

                    goal_pos = validate_and_clamp_teleop_frame(action, backend.arm_calibration)
                    if goal_pos is None:
                        continue

                    is_power_connected = backend.power_mgr.is_connected() if backend.power_mgr else True
                    if not backend.follower_active or not is_power_connected:
                        # Teleop gate is locked until user taps START or hardware is RE-SYNCHING / DISCONNECTED
                        continue

                    if backend.bus:
                        with SERIAL_LOCK:
                            backend.bus.sync_write("Goal_Position", goal_pos)

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

                if teleop_gate_unlocked and (time.time() - last_cmd_time > WATCHDOG_TIMEOUT_MS / 1000) and not watchdog_active:
                    self.logger.warning("No commands for %dms, holding pose", WATCHDOG_TIMEOUT_MS)
                    watchdog_active = True
                    teleop_gate_unlocked = False

                try:
                    if obs_sock:
                        with backend.lock:
                            last_pos = dict(backend.last_arm_positions)
                        obs_sock.send_string(json.dumps(last_pos), flags=zmq.NOBLOCK)
                except Exception as e:
                    self.logger.debug("Observation socket send exception: %s", e)

                time.sleep(max(1 / MAX_LOOP_FREQ_HZ - (time.time() - loop_start), 0))

        finally:
            self.logger.info("Cleaning up ZMQ sockets...")
            if cmd_sock:
                cmd_sock.close(linger=0)
            if obs_sock:
                obs_sock.close(linger=0)
            if ctx:
                ctx.term()
            self.logger.info("ZMQ Teleop Application stopped.")
