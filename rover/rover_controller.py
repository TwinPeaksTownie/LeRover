#!/usr/bin/env python3
"""RoverController module for GoBilda Overlander-4 chassis.
Manages serial communication with the Adafruit KB2040 safety bridge over GPIO UART (/dev/serial0),
25 Hz heartbeat packets, differential arcade drive kinematics, and safety watchdogs.
Supports mock/simulated serial mode for local PC testing.
"""

import http.server
import json
import logging
import os
import sys
import threading
import time
from socketserver import ThreadingMixIn
from typing import Optional, Dict, Any, Tuple

try:
    import network_resolver
except ImportError:
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    try:
        import network_resolver
    except ImportError:
        from pi4b import network_resolver

logger = logging.getLogger("so101.rover_controller")


def load_rover_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """Loads canonical rover drivetrain configuration fail-fast with direct bracket indexing."""
    candidates = []
    if config_path:
        candidates.append(config_path)
    if "ROVER_CONFIG_PATH" in os.environ and os.environ["ROVER_CONFIG_PATH"]:
        candidates.append(os.environ["ROVER_CONFIG_PATH"])
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidates.extend([
        os.path.join(repo_root, "config", "rover_config.json"),
        "/home/carson/touch_ui/config/rover_config.json",
        "/home/carson/aux_servo_interface/config/rover_config.json",
        "/home/user/so101/config/rover_config.json",
    ])
    for cp in candidates:
        if os.path.exists(cp):
            with open(cp, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            _ = cfg["pwm"]["neutral_pulse_us"]
            _ = cfg["pwm"]["min_pulse_us"]
            _ = cfg["pwm"]["max_pulse_us"]
            _ = cfg["pwm"]["max_pulse_offset"]
            _ = cfg["pwm"]["max_speed_pct"]
            _ = float(cfg["control"]["accel_time_sec"])
            _ = float(cfg["control"]["decel_time_sec"])
            _ = cfg["control"]["watchdog_timeout_sec"]
            _ = cfg["control"]["steering_trim"]
            _ = cfg["control"]["speed_step_pct"]
            _ = cfg["control"]["min_speed_pct"]
            _ = cfg["control"]["max_speed_pct_limit"]
            _ = cfg["control"]["loop_rate_hz"]
            _ = bool(cfg["watchdog"]["auto_recover_stalls"])
            _ = float(cfg["watchdog"]["stall_timeout_sec"])
            _ = str(cfg["watchdog"]["uhubctl_location"])
            _ = int(cfg["watchdog"]["uhubctl_port"])
            _ = str(cfg["distance_sensor"]["model"])
            _ = str(cfg["distance_sensor"]["analog_pin"])
            _ = int(cfg["distance_sensor"]["adc_resolution_bits"])
            _ = float(cfg["distance_sensor"]["max_volts"])
            _ = float(cfg["distance_sensor"]["max_distance_mm"])
            _ = float(cfg["distance_sensor"]["update_rate_hz"])
            _ = bool(cfg["collision_guard"]["enabled"])
            _ = float(cfg["collision_guard"]["danger_zone_cm"])
            _ = float(cfg["collision_guard"]["min_valid_cm"])
            _ = float(cfg["collision_guard"]["max_valid_cm"])
            _ = int(cfg["collision_guard"]["ground_exclusion_adc"])
            _ = str(cfg["collision_guard"]["recovery_button"])
            _ = float(cfg["collision_guard"]["recovery_hold_sec"])
            _ = int(cfg["collision_guard"]["speed_penalty_pct"])
            _ = int(cfg["collision_guard"]["halt_pulse_left"])
            _ = int(cfg["collision_guard"]["halt_pulse_right"])
            return cfg
    raise FileNotFoundError(f"Missing canonical rover_config.json in candidates: {candidates}")


class ThreadingHTTPServer(ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


class DistanceStatusHandler(http.server.BaseHTTPRequestHandler):
    """HTTP handler exposing distance status and safety controls."""

    def log_message(self, format, *args):
        # Suppress routine access logs to avoid log spam
        pass

    def do_GET(self):
        if self.path in ["/api/status", "/api/distance", "/api/telemetry"]:
            telem = self.server.rover_ctrl.get_telemetry()
            payload = {
                "object_detected": bool(telem["object_detected"]),
                "distance_cm": telem["distance_cm"],
                "in_danger_zone": bool(telem["in_danger_zone"]),
                "emergency_halt": bool(telem["emergency_halt"]),
                "raw_dist": int(telem["raw_dist"]),
                "max_speed_pct": int(telem["max_speed_pct"]),
                "timestamp": telem["last_seen"] or time.time()
            }
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404, "Endpoint not found")

    def do_POST(self):
        if "Content-Length" not in self.headers:
            self.send_error(400, "Missing Content-Length header")
            return
        content_length = int(self.headers["Content-Length"])
        post_data = self.rfile.read(content_length)
        try:
            req_data = json.loads(post_data.decode("utf-8"))
        except Exception:
            self.send_error(400, "Invalid JSON payload")
            return

        if self.path == "/api/halt":
            for key in ["halt"]:
                if key not in req_data:
                    self.send_error(400, f"Missing required parameter: '{key}'")
                    return
            halt_val = bool(req_data["halt"])
            self.server.rover_ctrl.set_emergency_halt(halt_val)
            resp = json.dumps({"status": "ok", "emergency_halt": halt_val}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)

        elif self.path == "/api/speed":
            for key in ["speed_pct"]:
                if key not in req_data:
                    self.send_error(400, f"Missing required parameter: '{key}'")
                    return
            new_pct = self.server.rover_ctrl.set_max_speed_pct(int(req_data["speed_pct"]))
            resp = json.dumps({"status": "ok", "max_speed_pct": new_pct}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)

        elif self.path == "/api/drive":
            for key in ["throttle", "steering"]:
                if key not in req_data:
                    self.send_error(400, f"Missing required parameter: '{key}'")
                    return
            self.server.rover_ctrl.set_drive(float(req_data["steering"]), float(req_data["throttle"]))
            resp = json.dumps({"status": "ok"}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)
        else:
            self.send_error(404, "Endpoint not found")


class RoverController:
    """Thread-safe controller for Overlander-4 PWM wheel motors via Adafruit KB2040."""

    def __init__(
        self,
        serial_port: Optional[str] = None,
        baudrate: Optional[int] = None,
        config_path: Optional[str] = None,
        mock_mode: bool = False,
        enable_http_server: bool = True
    ) -> None:
        if serial_port is None:
            self.serial_port = network_resolver.get_rover_serial_port()
        else:
            self.serial_port = serial_port

        if baudrate is None:
            self.baudrate = network_resolver.get_rover_baudrate()
        else:
            self.baudrate = baudrate

        self.enable_http_server = enable_http_server
        self._http_server: Optional[ThreadingHTTPServer] = None
        self._http_thread: Optional[threading.Thread] = None

        self.config = load_rover_config(config_path)
        self.neutral_pulse_us = int(self.config["pwm"]["neutral_pulse_us"])
        self.min_pulse_us = int(self.config["pwm"]["min_pulse_us"])
        self.max_pulse_us = int(self.config["pwm"]["max_pulse_us"])
        self.max_pulse_offset = int(self.config["pwm"]["max_pulse_offset"])
        self.max_speed_pct = int(self.config["pwm"]["max_speed_pct"])
        self.accel_time_sec = float(self.config["control"]["accel_time_sec"])
        self.decel_time_sec = float(self.config["control"]["decel_time_sec"])
        self.watchdog_timeout = float(self.config["control"]["watchdog_timeout_sec"])
        self.steering_trim = float(self.config["control"]["steering_trim"])
        self.speed_step_pct = int(self.config["control"]["speed_step_pct"])
        self.min_speed_pct = int(self.config["control"]["min_speed_pct"])
        self.max_speed_pct_limit = int(self.config["control"]["max_speed_pct_limit"])
        self.loop_rate_hz = float(self.config["control"]["loop_rate_hz"])
        self.assert_dtr = bool(self.config["hardware_interface"]["assert_dtr"])
        self.assert_rts = bool(self.config["hardware_interface"]["assert_rts"])
        self.serial_timeout = float(self.config["hardware_interface"]["serial_timeout_sec"])
        self.write_timeout = float(self.config["hardware_interface"]["write_timeout_sec"])
        self.auto_recover_stalls = bool(self.config["watchdog"]["auto_recover_stalls"])
        self.stall_timeout_sec = float(self.config["watchdog"]["stall_timeout_sec"])
        self.uhubctl_location = str(self.config["watchdog"]["uhubctl_location"])
        self.uhubctl_port = int(self.config["watchdog"]["uhubctl_port"])
        self._last_stall_recovery: float = time.time()
        self._port_opened_time: float = time.time()
        self._packets_since_open: int = 0
        self.mock_mode = mock_mode

        self.guard_cfg = self.config["collision_guard"]
        self.sensor_cfg = self.config["distance_sensor"]
        self.adc_max = (1 << int(self.sensor_cfg["adc_resolution_bits"])) - 1
        self.max_dist_cm = float(self.sensor_cfg["max_distance_mm"]) / 10.0
        self.danger_zone_cm = float(self.guard_cfg["danger_zone_cm"])
        self.min_valid_cm = float(self.guard_cfg["min_valid_cm"])
        self.max_valid_cm = float(self.guard_cfg["max_valid_cm"])
        self.ground_exclusion_adc = int(self.guard_cfg["ground_exclusion_adc"])
        self.halt_pulse_left = int(self.guard_cfg["halt_pulse_left"])
        self.halt_pulse_right = int(self.guard_cfg["halt_pulse_right"])
        self.emergency_halt: bool = False

        # Enforce strict serial port presence when mock_mode is False (No silent auto-mock fallbacks)
        if not self.mock_mode:
            if not self.serial_port.startswith("mock") and not os.path.exists(self.serial_port):
                raise FileNotFoundError(
                    f"Rover hardware serial port '{self.serial_port}' not found. "
                    f"Specify mock_mode=True explicitly to enable mock hardware simulation."
                )

        self._lock = threading.Lock()
        self._target_x: float = 0.0
        self._target_y: float = 0.0
        self._last_drive_update: float = 0.0
        self._current_left_val: float = 0.0
        self._current_right_val: float = 0.0
        self._slider_val: int = self.neutral_pulse_us
        self._lights_pulse: int = 0

        self._last_left_pulse: int = self.neutral_pulse_us
        self._last_right_pulse: int = self.neutral_pulse_us
        self._last_cmd_sent: str = f"CMD:{self.neutral_pulse_us},{self.neutral_pulse_us},{self.neutral_pulse_us},0\n"

        self.telemetry: Dict[str, Any] = {
            "mode": "MOCK" if self.mock_mode else "DISCONNECTED",
            "left_out": self.neutral_pulse_us,
            "right_out": self.neutral_pulse_us,
            "steering_trim": self.steering_trim,
            "max_speed_pct": self.max_speed_pct,
            "max_pulse_offset": self.max_pulse_offset,
            "sbus_active": 0,
            "web_active": 0,
            "ch1": 1000,
            "ch2": 1000,
            "ch5": 1000,
            "distance": 0,
            "raw_dist": 0,
            "distance_cm": None,
            "object_detected": False,
            "in_danger_zone": False,
            "emergency_halt": False,
            "last_seen": 0.0,
            "packets_sent": 0
        }

        self._stop_event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None
        self._mock_packet_sink = None  # Optional callback for simulator assertions

        self._last_config_check: float = 0.0
        self._check_config_reload()

    def set_steering_trim(self, trim: float) -> None:
        """Sets the steering trim bias factor [-0.25..0.25] in memory."""
        with self._lock:
            self.steering_trim = max(-0.25, min(0.25, float(trim)))
            self.telemetry["steering_trim"] = round(self.steering_trim, 3)
            logger.info("RoverController updated steering_trim: %+.3f", self.steering_trim)

    @property
    def accel_ramp_rate(self) -> float:
        """Backward compatibility adapter for tests inspecting or overriding ramp rate."""
        if self.accel_time_sec <= (1.0 / self.loop_rate_hz):
            return 1.0
        return 1.0 / (self.accel_time_sec * self.loop_rate_hz)

    @accel_ramp_rate.setter
    def accel_ramp_rate(self, val: float) -> None:
        """Backward compatibility setter for unit tests configuring instant or scaled response."""
        v = float(val)
        if v >= 1.0:
            self.accel_time_sec = 1.0 / self.loop_rate_hz
            self.decel_time_sec = 1.0 / self.loop_rate_hz
        else:
            self.accel_time_sec = 1.0 / (v * self.loop_rate_hz) if v > 0 else 2.0
            self.decel_time_sec = 0.5

    @staticmethod
    def _apply_asymmetric_slew(current: float, target: float, accel_step: float, decel_step: float) -> float:
        """Applies linear slew rate limiting distinguishing acceleration away from zero vs braking toward zero."""
        if current == 0.0:
            if target > 0.0:
                return min(target, accel_step)
            elif target < 0.0:
                return max(target, -accel_step)
            return 0.0

        if current > 0.0:
            if target >= current:
                # Accelerating in positive direction
                return min(target, current + accel_step)
            elif target >= 0.0:
                # Decelerating toward zero in positive territory
                return max(target, current - decel_step)
            else:
                # Reversing direction: brake to zero first
                val_after_decel = current - decel_step
                return max(0.0, val_after_decel)

        # current < 0.0
        if target <= current:
            # Accelerating in negative direction
            return max(target, current - accel_step)
        elif target <= 0.0:
            # Decelerating toward zero in negative territory
            return min(target, current + decel_step)
        else:
            # Reversing direction: brake to zero first
            val_after_decel = current + decel_step
            return min(0.0, val_after_decel)

    def _check_config_reload(self) -> None:
        """Polls /tmp/rover_config.json dynamically to allow runtime speed changes and trim adjustments without restart."""
        config_paths = ["/tmp/rover_config.json", "/home/user/so101/config/rover_config.json"]
        config_path = None
        for cp in config_paths:
            if os.path.exists(cp):
                config_path = cp
                break
        if not config_path:
            return
        try:
            with open(config_path, "r") as f:
                content = f.read().strip()
            if not content:
                return
            offset = None
            trim = None
            try:
                import json
                cfg = json.loads(content)
                if isinstance(cfg, dict):
                    if "max_pulse_offset" in cfg:
                        offset = int(cfg["max_pulse_offset"])
                    elif "max_speed_pct" in cfg:
                        offset = int(500 * (float(cfg["max_speed_pct"]) / 100.0))
                    if "steering_trim" in cfg:
                        trim = float(cfg["steering_trim"])
            except Exception:
                import re
                m_offset = re.search(r'max_pulse_offset[:\s]+(\d+)', content)
                m_pct = re.search(r'max_speed_pct[:\s]+(\d+)', content)
                m_trim = re.search(r'steering_trim[:\s]+([+-]?\d*(?:\.\d+)?)', content)
                if m_offset:
                    offset = int(m_offset.group(1))
                elif m_pct:
                    offset = int(500 * (float(m_pct.group(1)) / 100.0))
                if m_trim and m_trim.group(1):
                    trim = float(m_trim.group(1))

            if offset is not None and 50 <= offset <= 500:
                if offset != self.max_pulse_offset:
                    self.max_pulse_offset = offset
                    logger.info("RoverController updated live speed cap: max_pulse_offset=%d us", self.max_pulse_offset)

            if trim is not None and -0.25 <= trim <= 0.25:
                if trim != self.steering_trim:
                    self.steering_trim = trim
                    with self._lock:
                        self.telemetry["steering_trim"] = round(self.steering_trim, 3)
                    logger.info("RoverController updated live steering_trim: %+.3f", self.steering_trim)
        except Exception as e:
            logger.debug("Config reload check failed: %s", e)

    def start(self) -> None:
        """Starts the background 25 Hz UART heartbeat, control loop, and HTTP status server."""
        if self._worker_thread and self._worker_thread.is_alive():
            return
        self._stop_event.clear()
        self._worker_thread = threading.Thread(target=self._uart_loop, daemon=True, name="RoverUARTWorker")
        self._worker_thread.start()
        logger.info("Started RoverController background thread (port=%s, mock=%s).", self.serial_port, self.mock_mode)

        if self.enable_http_server and self._http_server is None:
            try:
                repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                net_cfg_path = os.path.join(repo_root, "config", "network_config.json")
                http_port = 8089
                http_host = "0.0.0.0"
                if os.path.exists(net_cfg_path):
                    with open(net_cfg_path, "r", encoding="utf-8") as nf:
                        ncfg = json.load(nf)
                    if "endpoints" in ncfg and "distance_telemetry" in ncfg["endpoints"]:
                        http_port = int(ncfg["endpoints"]["distance_telemetry"]["port"])
                        http_host = str(ncfg["endpoints"]["distance_telemetry"]["host"])

                server = ThreadingHTTPServer((http_host, http_port), DistanceStatusHandler)
                server.rover_ctrl = self
                self._http_server = server
                self._http_thread = threading.Thread(target=server.serve_forever, daemon=True, name="RoverHTTPServer")
                self._http_thread.start()
                logger.info("Started RoverController Distance Status HTTP server on %s:%d", http_host, http_port)
            except Exception as e:
                logger.warning("Could not bind RoverController HTTP server: %s", e)

    def stop(self) -> None:
        """Zeroes all target drive inputs and commands neutral 1500 us pulses."""
        with self._lock:
            self._target_x = 0.0
            self._target_y = 0.0
            self._current_left_val = 0.0
            self._current_right_val = 0.0
            self._last_drive_update = 0.0

    def shutdown(self) -> None:
        """Shuts down the background communication thread and HTTP status server."""
        self.stop()
        self._stop_event.set()
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=1.5)
        if self._http_server:
            try:
                self._http_server.shutdown()
                self._http_server.server_close()
            except Exception as e:
                logger.debug("Error stopping HTTP server: %s", e)
            self._http_server = None
        logger.info("RoverController shut down.")

    def set_emergency_halt(self, halt: bool) -> None:
        """Sets or clears the emergency collision halt override."""
        with self._lock:
            self.emergency_halt = bool(halt)
            self.telemetry["emergency_halt"] = self.emergency_halt
            if self.emergency_halt:
                self._target_x = 0.0
                self._target_y = 0.0
                self._current_left_val = 0.0
                self._current_right_val = 0.0
        logger.info("RoverController emergency_halt set to %s", self.emergency_halt)

    def set_max_speed_pct(self, pct: int) -> int:
        """Sets maximum speed cap directly in memory, clamping between min and max limits."""
        with self._lock:
            new_pct = max(self.min_speed_pct, min(self.max_speed_pct_limit, int(pct)))
            self.max_speed_pct = new_pct
            self.max_pulse_offset = int(500 * (new_pct / 100.0))
            self.telemetry["max_speed_pct"] = new_pct
            self.telemetry["max_pulse_offset"] = self.max_pulse_offset
            logger.info("RoverController updated speed: %d%% (pulse offset %d us)", self.max_speed_pct, self.max_pulse_offset)
            return self.max_speed_pct

    def adjust_speed_pct(self, delta_pct: int) -> int:
        """Adjusts maximum speed cap by delta_pct in memory, clamping between min and max limits."""
        with self._lock:
            new_pct = max(self.min_speed_pct, min(self.max_speed_pct_limit, self.max_speed_pct + int(delta_pct)))
            self.max_speed_pct = new_pct
            self.max_pulse_offset = int(500 * (new_pct / 100.0))
            self.telemetry["max_speed_pct"] = self.max_speed_pct
            self.telemetry["max_pulse_offset"] = self.max_pulse_offset
            logger.info("RoverController adjusted speed: %d%% (pulse offset %d us)", self.max_speed_pct, self.max_pulse_offset)
            return self.max_speed_pct

    def set_drive(self, x: float, y: float, enforce_throttle_gate: bool = False) -> None:
        """Sets normalized joystick drive inputs (x=steering [-1.0..1.0], y=throttle [-1.0..1.0]).
        If enforce_throttle_gate is True, steering is suppressed to 0.0 when throttle is idle (|y| < 0.01).
        """
        # Clamp inputs
        x_clamped = max(-1.0, min(1.0, float(x)))
        y_clamped = max(-1.0, min(1.0, float(y)))

        if enforce_throttle_gate and abs(y_clamped) < 0.01:
            x_clamped = 0.0
            y_clamped = 0.0

        with self._lock:
            self._target_x = x_clamped
            self._target_y = y_clamped
            self._last_drive_update = time.time()

    def set_mock_sink(self, sink_fn) -> None:
        """Sets a callback function to receive formatted CMD packets during simulation."""
        self._mock_packet_sink = sink_fn

    def get_telemetry(self) -> Dict[str, Any]:
        """Returns snapshot of current rover telemetry and PWM output states."""
        with self._lock:
            data = dict(self.telemetry)
            data["target_x"] = self._target_x
            data["target_y"] = self._target_y
            data["left_pulse"] = self._last_left_pulse
            data["right_pulse"] = self._last_right_pulse
            data["last_cmd"] = self._last_cmd_sent.strip()
            return data

    def _recover_stalled_port(self) -> None:
        """Executes uhubctl hardware power-cycle of the KB2040 USB port to recover from endpoint stall."""
        import subprocess
        loc = self.uhubctl_location
        port = self.uhubctl_port
        cmd = ["sudo", "uhubctl", "-l", loc, "-p", str(port), "-a", "cycle", "-d", "2"]
        logger.info("Executing hardware USB port power cycle: %s", " ".join(cmd))
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=8.0)
            if res.returncode == 0:
                logger.info("Successfully cycled USB port %d on hub %s: %s", port, loc, res.stdout.strip())
            else:
                logger.warning("uhubctl exited with code %d: %s", res.returncode, res.stderr.strip())
        except Exception as e:
            logger.error("Failed to execute uhubctl USB recovery: %s", e)
        time.sleep(1.5)

    def _uart_loop(self) -> None:
        """Main 25 Hz (40 ms) serial heartbeat loop communicating with Adafruit KB2040."""
        ser = None
        rx_buf = bytearray()

        while not self._stop_event.is_set():
            if not self.mock_mode and ser is None:
                try:
                    import serial
                    ser = serial.Serial(self.serial_port, self.baudrate, timeout=self.serial_timeout, write_timeout=self.write_timeout)
                    ser.dtr = self.assert_dtr
                    if self.assert_rts:
                        ser.rts = True
                    ser.reset_input_buffer()
                    ser.reset_output_buffer()
                    logger.info("Opened hardware serial port %s at %d baud.", self.serial_port, self.baudrate)
                    self._last_stall_recovery = time.time()
                    self._port_opened_time = time.time()
                    self._packets_since_open = 0
                except Exception as e:
                    logger.warning("Failed to open serial port %s: %s. Retrying in 2s...", self.serial_port, e)
                    time.sleep(2.0)
                    continue

            # Watchdog stall detection: auto-recover via uhubctl if no STAT: received
            if not self.mock_mode and self.auto_recover_stalls and ser and ser.is_open:
                now_check = time.time()
                last_rx = self.telemetry["last_seen"]
                is_stalled = (
                    (last_rx == 0.0 and self._packets_since_open > 100 and (now_check - self._port_opened_time) > 5.0 and (now_check - self._last_stall_recovery) > 5.0) or
                    (last_rx > 0.0 and (now_check - last_rx) > self.stall_timeout_sec and (now_check - self._last_stall_recovery) > (self.stall_timeout_sec * 2.0))
                )
                if is_stalled:
                    logger.warning(
                        "🚨 Microcontroller USB endpoint stall detected on %s! (last_seen=%.1f, packets_since_open=%d). Triggering uhubctl power cycle...",
                        self.serial_port, last_rx, self._packets_since_open
                    )
                    self._last_stall_recovery = now_check
                    self._packets_since_open = 0
                    try:
                        ser.close()
                    except Exception as e:
                        logger.debug("Stalled serial port close encountered error: %s", e)
                    ser = None
                    self._recover_stalled_port()
                    continue

            loop_start = time.time()

            # 1. Read telemetry from KB2040 (if hardware serial active)
            if ser and ser.is_open:
                try:
                    if ser.in_waiting > 0:
                        chunk = ser.read(ser.in_waiting)
                        if chunk:
                            rx_buf.extend(chunk)
                            while b'\n' in rx_buf:
                                idx = rx_buf.find(b'\n')
                                line_bytes = rx_buf[:idx]
                                rx_buf = rx_buf[idx + 1:]
                                line = line_bytes.decode('utf-8', errors='replace').strip()
                                if "STAT:" in line:
                                    self._parse_stat_line(line[line.find("STAT:"):])
                except Exception as e:
                    logger.warning("Serial read error on %s: %s", self.serial_port, e)
                    try:
                        ser.close()
                    except Exception as close_err:
                        logger.debug("Error closing serial port after read failure: %s", close_err)
                    ser = None

            # 2. Kinematics & Arcade Drive Mixing
            now = time.time()
            if now - self._last_config_check > 0.5:
                self._last_config_check = now
                self._check_config_reload()

            with self._lock:
                halt_active = self.emergency_halt
                x = self._target_x
                y = self._target_y
                update_age = now - self._last_drive_update
                slider = self._slider_val
                pulse = self._lights_pulse
                if self._lights_pulse == 1:
                    self._lights_pulse = 0

            # Watchdog timeout: if no drive updates for > watchdog_timeout, force 0
            if update_age > self.watchdog_timeout:
                x = 0.0
                y = 0.0

            if halt_active:
                left_pulse = self.halt_pulse_left
                right_pulse = self.halt_pulse_right
                self._current_left_val = 0.0
                self._current_right_val = 0.0
            else:
                # Standard arcade drive calculation:
                # y = throttle (+ forward, - reverse)
                # x = steering (+ right, - left)
                # Positive x biases target_left up and target_right down for clockwise yaw (right turn)
                # steering_trim is scaled by throttle (+ values bias right to compensate for left veer)
                throttle = y
                with self._lock:
                    trim = self.steering_trim
                steering = x + (trim * throttle)

                target_left = max(-1.0, min(1.0, throttle + steering))
                target_right = max(-1.0, min(1.0, throttle - steering))

                # Calculate per-tick slew step limits from physical timing
                accel_step = (1.0 / self.accel_time_sec) / self.loop_rate_hz if self.accel_time_sec > 0 else 1.0
                decel_step = (1.0 / self.decel_time_sec) / self.loop_rate_hz if self.decel_time_sec > 0 else 1.0

                # Apply asymmetric linear slew rate limiting
                self._current_left_val = self._apply_asymmetric_slew(
                    self._current_left_val, target_left, accel_step, decel_step
                )
                self._current_right_val = self._apply_asymmetric_slew(
                    self._current_right_val, target_right, accel_step, decel_step
                )

                # Map to 50Hz PWM pulse widths using calibrated neutral and limits from rover_config.json
                # Left motor forward: higher pulse (>1500 us)
                # Right motor forward: lower pulse (<1500 us)
                left_pulse = self.neutral_pulse_us + int(self._current_left_val * self.max_pulse_offset)
                right_pulse = self.neutral_pulse_us - int(self._current_right_val * self.max_pulse_offset)

                left_pulse = max(self.min_pulse_us, min(self.max_pulse_us, left_pulse))
                right_pulse = max(self.min_pulse_us, min(self.max_pulse_us, right_pulse))

            cmd_str = f"CMD:{left_pulse},{right_pulse},{slider},{pulse}\n"

            with self._lock:
                self._last_left_pulse = left_pulse
                self._last_right_pulse = right_pulse
                self._last_cmd_sent = cmd_str
                self.telemetry["left_out"] = left_pulse
                self.telemetry["right_out"] = right_pulse
                self.telemetry["packets_sent"] += 1
                self._packets_since_open += 1

            # Dispatch to hardware serial or mock sink
            if ser and ser.is_open:
                try:
                    ser.write(cmd_str.encode('utf-8'))
                except Exception as e:
                    logger.warning("Serial write error on %s: %s", self.serial_port, e)
                    try:
                        ser.close()
                    except Exception as close_err:
                        logger.debug("Error closing serial port after write failure: %s", close_err)
                    ser = None
            elif self.mock_mode and self._mock_packet_sink:
                try:
                    self._mock_packet_sink(cmd_str, left_pulse, right_pulse)
                except Exception as sink_err:
                    logger.debug("Mock packet sink callback error: %s", sink_err)

            # Target loop rate from configuration
            elapsed = time.time() - loop_start
            sleep_time = max(0.005, (1.0 / self.loop_rate_hz) - elapsed)
            time.sleep(sleep_time)

        if ser and ser.is_open:
            try:
                # Send final neutral stop command
                neutral_cmd = f"CMD:{self.neutral_pulse_us},{self.neutral_pulse_us},{self.neutral_pulse_us},0\n"
                ser.write(neutral_cmd.encode('utf-8'))
                ser.close()
            except Exception as close_err:
                logger.debug("Error during shutdown serial close: %s", close_err)

    def _parse_stat_line(self, line: str) -> None:
        """Parses telemetry feedback string from KB2040."""
        try:
            clean = line.strip()
            if "STAT:" in clean:
                clean = clean[clean.find("STAT:") + 5:]
            parts = clean.split(",")
            if len(parts) >= 8:
                with self._lock:
                    self.telemetry["mode"] = parts[0].strip()
                    self.telemetry["left_out"] = int(parts[1])
                    self.telemetry["right_out"] = int(parts[2])
                    self.telemetry["sbus_active"] = int(parts[3])
                    self.telemetry["web_active"] = int(parts[4])
                    self.telemetry["ch1"] = int(parts[5])
                    self.telemetry["ch2"] = int(parts[6])
                    self.telemetry["ch5"] = int(parts[7])
                    if len(parts) > 8:
                        raw_dist = int(parts[8])
                        self.telemetry["distance"] = raw_dist
                        self.telemetry["raw_dist"] = raw_dist

                        # Calibrated Distance Calculation & Ground Reflection Filtering
                        if raw_dist >= self.ground_exclusion_adc or raw_dist <= 500:
                            self.telemetry["object_detected"] = False
                            self.telemetry["distance_cm"] = None
                            self.telemetry["in_danger_zone"] = False
                        else:
                            dist_cm = (raw_dist / float(self.adc_max)) * self.max_dist_cm
                            if self.min_valid_cm <= dist_cm <= self.max_valid_cm:
                                self.telemetry["object_detected"] = True
                                self.telemetry["distance_cm"] = round(dist_cm, 1)
                                self.telemetry["in_danger_zone"] = (dist_cm <= self.danger_zone_cm)
                            else:
                                self.telemetry["object_detected"] = False
                                self.telemetry["distance_cm"] = None
                                self.telemetry["in_danger_zone"] = False

                    self.telemetry["emergency_halt"] = self.emergency_halt
                    self.telemetry["last_seen"] = time.time()
        except Exception as parse_err:
            logger.debug("STAT line parse warning: %s", parse_err)
