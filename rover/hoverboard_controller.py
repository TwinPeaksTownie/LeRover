#!/usr/bin/env python3
"""HoverboardController module for Reachy Mini self-balancing base.
Manages persistent TCP socket communication with the ESP32 SimpleFOC Wireless Gateway,
streams Antun Skuric 4-state state-space LQR drive and turn targets,
monitors live IMU/odometry telemetry, and enforces client-side deadman safety.
"""

import json
import logging
import os
import socket
import sys
import threading
import time
from typing import Optional, Dict, Any, Tuple

logger = logging.getLogger("reachy.hoverboard_controller")


def load_hoverboard_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """Loads canonical hoverboard configuration fail-fast with direct bracket indexing."""
    candidates = []
    if config_path:
        candidates.append(config_path)
    if "HOVERBOARD_CONFIG_PATH" in os.environ and os.environ["HOVERBOARD_CONFIG_PATH"]:
        candidates.append(os.environ["HOVERBOARD_CONFIG_PATH"])
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidates.extend([
        os.path.join(repo_root, "config", "hoverboard_config.json"),
        "/home/carson/aux_servo_interface/config/hoverboard_config.json",
        "/home/user/aux_servo_interface/config/hoverboard_config.json",
    ])
    for cp in candidates:
        if os.path.exists(cp):
            with open(cp, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            # Direct bracket validation - fail loud if keys missing
            _ = cfg["network"]["gateway_host"]
            _ = cfg["network"]["gateway_port"]
            _ = cfg["network"]["socket_timeout_sec"]
            _ = cfg["network"]["reconnect_interval_sec"]
            _ = cfg["safety"]["deadman_interval_ms"]
            _ = cfg["safety"]["deadman_timeout_ms"]
            _ = cfg["safety"]["max_linear_velocity_rad_s"]
            _ = cfg["safety"]["max_turn_velocity_rad_s"]
            _ = cfg["balancing"]["zero_pitch_deg"]
            _ = cfg["balancing"]["cutoff_rear_deg"]
            _ = cfg["balancing"]["cutoff_front_deg"]
            _ = cfg["balancing"]["arm_min_deg"]
            _ = cfg["balancing"]["arm_max_deg"]
            _ = cfg["balancing"]["gains"]["k0_angle"]
            _ = cfg["balancing"]["gains"]["k1_gyro"]
            _ = cfg["balancing"]["gains"]["k2_velocity"]
            _ = cfg["balancing"]["gains"]["k3_position"]
            _ = cfg["slump_parking"]["target_angle_deg"]
            _ = cfg["slump_parking"]["velocity_threshold_rad_s"]
            _ = cfg["slump_parking"]["max_robot_speed_rad_s"]
            _ = cfg["teleop"]["stick_deadzone"]
            _ = cfg["teleop"]["linear_scale"]
            _ = cfg["teleop"]["turn_scale"]
            return cfg
    raise FileNotFoundError(f"Missing canonical hoverboard_config.json in candidates: {candidates}")


class HoverboardController:
    """Thread-safe client controller for ESP32 SimpleFOC hoverboard base."""

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        config_path: Optional[str] = None
    ) -> None:
        self.config = load_hoverboard_config(config_path)
        self.host = host if host is not None else self.config["network"]["gateway_host"]
        self.port = port if port is not None else int(self.config["network"]["gateway_port"])
        self.socket_timeout = float(self.config["network"]["socket_timeout_sec"])
        self.reconnect_interval = float(self.config["network"]["reconnect_interval_sec"])

        self.max_linear = float(self.config["safety"]["max_linear_velocity_rad_s"])
        self.max_turn = float(self.config["safety"]["max_turn_velocity_rad_s"])
        self.deadman_interval_s = float(self.config["safety"]["deadman_interval_ms"]) / 1000.0

        self.sock: Optional[socket.socket] = None
        self.sock_lock = threading.Lock()
        self.running = False
        self.thread: Optional[threading.Thread] = None

        self.target_linear = 0.0
        self.target_turn = 0.0
        self.last_cmd_time = 0.0
        self.is_active_drive = False

        self.telemetry: Dict[str, Any] = {
            "connected": False,
            "balancing_state": "UNKNOWN",
            "pitch_deg": 0.0,
            "zero_pitch_deg": float(self.config["balancing"]["zero_pitch_deg"]),
            "corrective_vel": 0.0,
            "robot_vel": 0.0,
            "robot_pos": 0.0,
            "slump_parking": False,
            "last_update": 0.0,
        }
        self.telemetry_lock = threading.Lock()

        self._start_connection()

    def _start_connection(self) -> None:
        self.running = True
        self.thread = threading.Thread(target=self._worker_loop, daemon=True, name="hoverboard_rx_worker")
        self.thread.start()

    def _connect_socket(self) -> bool:
        with self.sock_lock:
            if self.sock:
                try:
                    self.sock.close()
                except Exception as err:
                    logger.debug("Socket close error: %s", err)
                self.sock = None
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(self.socket_timeout)
                s.connect((self.host, self.port))
                self.sock = s
                with self.telemetry_lock:
                    self.telemetry["connected"] = True
                logger.info("Connected to ESP32 SimpleFOC Gateway at %s:%d", self.host, self.port)
                return True
            except Exception as e:
                with self.telemetry_lock:
                    self.telemetry["connected"] = False
                logger.warning("Failed to connect to gateway at %s:%d: %s", self.host, self.port, e)
                return False

    def _send_raw(self, cmd: str) -> bool:
        """Sends raw command string to gateway with newline."""
        with self.sock_lock:
            if not self.sock:
                return False
            try:
                payload = cmd.strip().encode("utf-8") + b"\n"
                self.sock.sendall(payload)
                return True
            except Exception as e:
                logger.warning("Socket send failed: %s", e)
                if self.sock:
                    try:
                        self.sock.close()
                    except Exception as err:
                        logger.debug("Socket close error: %s", err)
                    self.sock = None
                with self.telemetry_lock:
                    self.telemetry["connected"] = False
                return False

    def arm(self) -> bool:
        """Arms Antun Skuric balancing loop (engages upright)."""
        logger.info("Arming hoverboard self-balancing loop (S 0)...")
        return self._send_raw("S 0")

    def park(self) -> bool:
        """Initiates controlled kickstand slump parking routine (S 1)."""
        logger.info("Initiating controlled slump parking onto kickstand (S 1)...")
        return self._send_raw("S 1")

    def stop(self) -> bool:
        """Emergency stops all motors and disengages balancing."""
        self.target_linear = 0.0
        self.target_turn = 0.0
        self.is_active_drive = False
        return self._send_raw("STOP")

    def set_drive(self, linear: float, turn: float) -> bool:
        """Sets forward linear velocity (rad/s) and turn yaw rate (rad/s)."""
        linear = max(-self.max_linear, min(self.max_linear, linear))
        turn = max(-self.max_turn, min(self.max_turn, turn))

        self.target_linear = linear
        self.target_turn = turn
        self.last_cmd_time = time.time()
        self.is_active_drive = (abs(linear) > 0.01 or abs(turn) > 0.01)

        ok1 = self._send_raw(f"T {linear:.3f}")
        ok2 = self._send_raw(f"R {turn:.3f}")
        return ok1 and ok2

    def set_gains(self, k0: Optional[float] = None, k1: Optional[float] = None,
                  k2: Optional[float] = None, k3: Optional[float] = None) -> None:
        """Live adjusts Antun Skuric LQR state-space gains."""
        if k0 is not None: self._send_raw(f"A {k0:.3f}")
        if k1 is not None: self._send_raw(f"B {k1:.3f}")
        if k2 is not None: self._send_raw(f"C {k2:.3f}")
        if k3 is not None: self._send_raw(f"D {k3:.3f}")

    def query_status(self) -> bool:
        """Requests full status telemetry from gateway."""
        return self._send_raw("BAL:STATUS")

    def get_telemetry(self) -> Dict[str, Any]:
        with self.telemetry_lock:
            return dict(self.telemetry)

    def _worker_loop(self) -> None:
        rx_buf = ""
        last_heartbeat = time.time()

        while self.running:
            if not self.sock:
                if not self._connect_socket():
                    time.sleep(self.reconnect_interval)
                    continue

            # 1. Deadman Heartbeat (if active driving, refresh targets)
            now = time.time()
            if self.is_active_drive and (now - last_heartbeat >= self.deadman_interval_s):
                last_heartbeat = now
                self._send_raw(f"T {self.target_linear:.3f}")
                self._send_raw(f"R {self.target_turn:.3f}")

            # 2. Receive and parse telemetry stream
            try:
                data = self.sock.recv(1024)
                if not data:
                    logger.warning("Gateway closed socket connection.")
                    with self.sock_lock:
                        self.sock.close()
                        self.sock = None
                    with self.telemetry_lock:
                        self.telemetry["connected"] = False
                    continue

                rx_buf += data.decode("utf-8", errors="ignore")
                while "\n" in rx_buf:
                    line, rx_buf = rx_buf.split("\n", 1)
                    line = line.strip()
                    if line:
                        self._parse_line(line)
            except socket.timeout:
                continue
            except Exception as e:
                logger.debug("Worker recv exception: %s", e)

        with self.sock_lock:
            if self.sock:
                try:
                    self.sock.sendall(b"STOP\n")
                    self.sock.close()
                except Exception as err:
                    logger.debug("Shutdown socket error: %s", err)
                self.sock = None

    def _parse_line(self, line: str) -> None:
        """Parses gateway output lines into structured telemetry."""
        now = time.time()
        with self.telemetry_lock:
            self.telemetry["last_update"] = now

            if "[BAL]" in line:
                if "Pitch:" in line:
                    # [BAL] Pitch: -2.04 deg | Target: -2.04 | Vel: 0.00 rad/s
                    parts = line.split("|")
                    for p in parts:
                        p = p.strip()
                        if "Pitch:" in p:
                            try:
                                self.telemetry["pitch_deg"] = float(p.split(":")[1].replace("deg", "").strip())
                            except ValueError as err:
                                logger.warning("Failed parsing pitch telemetry: %s", err)
                        elif "Target:" in p:
                            try:
                                self.telemetry["zero_pitch_deg"] = float(p.split(":")[1].strip())
                            except ValueError as err:
                                logger.warning("Failed parsing zero pitch telemetry: %s", err)
                        elif "Vel:" in p:
                            try:
                                self.telemetry["corrective_vel"] = float(p.split(":")[1].replace("rad/s", "").strip())
                            except ValueError as err:
                                logger.warning("Failed parsing corrective vel telemetry: %s", err)
                elif "BALANCING ACTIVE" in line:
                    self.telemetry["balancing_state"] = "BALANCING"
                elif "ARMED" in line:
                    self.telemetry["balancing_state"] = "ARMED"
                elif "DISABLED" in line:
                    self.telemetry["balancing_state"] = "DISABLED"
                elif "FALLEN" in line:
                    self.telemetry["balancing_state"] = "FALLEN"

            elif "[IMU]" in line and "Pitch:" in line:
                # [IMU] Pitch: -3.01 | Roll: -0.14 | GyroY: 1.0 dps
                parts = line.split("|")
                for p in parts:
                    p = p.strip()
                    if "Pitch:" in p:
                        try:
                            self.telemetry["pitch_deg"] = float(p.split(":")[1].strip())
                        except ValueError as err:
                            logger.warning("Failed parsing IMU pitch telemetry: %s", err)

    def shutdown(self) -> None:
        """Shuts down controller safely."""
        logger.info("Shutting down HoverboardController...")
        self.running = False
        self.stop()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.5)
        logger.info("HoverboardController shutdown complete.")
