#!/usr/bin/env python3
"""RoverController module for GoBilda Overlander-4 chassis.
Manages serial communication with the Adafruit KB2040 safety bridge over GPIO UART (/dev/serial0),
25 Hz heartbeat packets, differential arcade drive kinematics, and safety watchdogs.
Supports mock/simulated serial mode for local PC testing.
"""

import json
import logging
import os
import sys
import threading
import time
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
            _ = cfg["control"]["accel_ramp_rate"]
            _ = cfg["control"]["watchdog_timeout_sec"]
            _ = cfg["control"]["steering_trim"]
            _ = cfg["control"]["loop_rate_hz"]
            return cfg
    raise FileNotFoundError(f"Missing canonical rover_config.json in candidates: {candidates}")


class RoverController:
    """Thread-safe controller for Overlander-4 PWM wheel motors via Adafruit KB2040."""

    def __init__(
        self,
        serial_port: Optional[str] = None,
        baudrate: Optional[int] = None,
        config_path: Optional[str] = None,
        mock_mode: bool = False
    ) -> None:
        if serial_port is None:
            self.serial_port = network_resolver.get_rover_serial_port()
        else:
            self.serial_port = serial_port

        if baudrate is None:
            self.baudrate = network_resolver.get_rover_baudrate()
        else:
            self.baudrate = baudrate

        self.config = load_rover_config(config_path)
        self.neutral_pulse_us = int(self.config["pwm"]["neutral_pulse_us"])
        self.min_pulse_us = int(self.config["pwm"]["min_pulse_us"])
        self.max_pulse_us = int(self.config["pwm"]["max_pulse_us"])
        self.max_pulse_offset = int(self.config["pwm"]["max_pulse_offset"])
        self.accel_ramp_rate = float(self.config["control"]["accel_ramp_rate"])
        self.watchdog_timeout = float(self.config["control"]["watchdog_timeout_sec"])
        self.steering_trim = float(self.config["control"]["steering_trim"])
        self.loop_rate_hz = float(self.config["control"]["loop_rate_hz"])
        self.assert_dtr = bool(self.config["hardware_interface"]["assert_dtr"])
        self.assert_rts = bool(self.config["hardware_interface"]["assert_rts"])
        self.serial_timeout = float(self.config["hardware_interface"]["serial_timeout_sec"])
        self.write_timeout = float(self.config["hardware_interface"]["write_timeout_sec"])
        self.mock_mode = mock_mode

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
            "sbus_active": 0,
            "web_active": 0,
            "ch1": 1000,
            "ch2": 1000,
            "ch5": 1000,
            "distance": 0,
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
        """Starts the background 25 Hz UART heartbeat and control loop."""
        if self._worker_thread and self._worker_thread.is_alive():
            return
        self._stop_event.clear()
        self._worker_thread = threading.Thread(target=self._uart_loop, daemon=True, name="RoverUARTWorker")
        self._worker_thread.start()
        logger.info("Started RoverController background thread (port=%s, mock=%s).", self.serial_port, self.mock_mode)

    def stop(self) -> None:
        """Zeroes all target drive inputs and commands neutral 1500 us pulses."""
        with self._lock:
            self._target_x = 0.0
            self._target_y = 0.0
            self._current_left_val = 0.0
            self._current_right_val = 0.0
            self._last_drive_update = 0.0

    def shutdown(self) -> None:
        """Shuts down the background communication thread."""
        self.stop()
        self._stop_event.set()
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=1.5)
        logger.info("RoverController shut down.")

    def set_drive(self, x: float, y: float) -> None:
        """Sets normalized joystick drive inputs (x=steering [-1.0..1.0], y=throttle [-1.0..1.0])."""
        # Clamp inputs
        x_clamped = max(-1.0, min(1.0, float(x)))
        y_clamped = max(-1.0, min(1.0, float(y)))

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
                    ser.reset_input_buffer()
                    ser.reset_output_buffer()
                    logger.info("Opened hardware serial port %s at %d baud.", self.serial_port, self.baudrate)
                except Exception as e:
                    logger.warning("Failed to open serial port %s: %s. Retrying in 2s...", self.serial_port, e)
                    time.sleep(2.0)
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
                    except Exception:
                        pass
                    ser = None

            # 2. Kinematics & Arcade Drive Mixing
            now = time.time()
            if now - self._last_config_check > 0.5:
                self._last_config_check = now
                self._check_config_reload()

            with self._lock:
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

            # Standard arcade drive calculation:
            # y = throttle (+ forward, - reverse)
            # x = steering (+ right, - left)
            # Steering is inverted (-x) so positive x turns right
            # steering_trim is scaled by throttle (+ values bias right to compensate for left veer)
            throttle = y
            with self._lock:
                trim = self.steering_trim
            steering = -x + (trim * throttle)

            target_left = max(-1.0, min(1.0, throttle + steering))
            target_right = max(-1.0, min(1.0, throttle - steering))

            # Apply software smoothing acceleration ramp
            self._current_left_val += (target_left - self._current_left_val) * self.accel_ramp_rate
            self._current_right_val += (target_right - self._current_right_val) * self.accel_ramp_rate

            # Map to 50Hz PWM pulse widths using calibrated neutral and limits from rover_config.json
            # Left motor physically inverted (lower pulse = forward, higher pulse = reverse)
            # Right motor normal (higher pulse = forward, lower pulse = reverse)
            left_pulse = self.neutral_pulse_us - int(self._current_left_val * self.max_pulse_offset)
            right_pulse = self.neutral_pulse_us + int(self._current_right_val * self.max_pulse_offset)

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

            # Dispatch to hardware serial or mock sink
            if ser and ser.is_open:
                try:
                    ser.write(cmd_str.encode('utf-8'))
                except Exception as e:
                    logger.warning("Serial write error on %s: %s", self.serial_port, e)
                    try:
                        ser.close()
                    except Exception:
                        pass
                    ser = None
            elif self.mock_mode and self._mock_packet_sink:
                try:
                    self._mock_packet_sink(cmd_str, left_pulse, right_pulse)
                except Exception:
                    pass

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
            except Exception:
                pass

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
                        self.telemetry["distance"] = int(parts[8])
                    self.telemetry["last_seen"] = time.time()
        except Exception:
            pass
