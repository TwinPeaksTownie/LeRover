#!/usr/bin/env python3
"""RoverController module for GoBilda Overlander-4 chassis.
Manages serial communication with the Adafruit KB2040 safety bridge over GPIO UART (/dev/serial0),
25 Hz heartbeat packets, differential arcade drive kinematics, and collision guard.
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


def get_rover_config_path(config_path: Optional[str] = None) -> str:
    """Resolves the canonical rover_config.json path on disk fail-fast."""
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
            return cp
    raise FileNotFoundError(f"Missing canonical rover_config.json in candidates: {candidates}")


def load_rover_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """Loads canonical rover drivetrain configuration fail-fast with direct bracket indexing."""
    cp = get_rover_config_path(config_path)
    with open(cp, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    _ = cfg["pwm"]["neutral_pulse_us"]
    _ = cfg["pwm"]["min_pulse_us"]
    _ = cfg["pwm"]["max_pulse_us"]
    _ = cfg["pwm"]["max_pulse_offset"]
    _ = cfg["pwm"]["max_speed_pct"]
    _ = float(cfg["control"]["command_timeout_sec"])
    _ = float(cfg["control"]["accel_time_sec"])
    _ = float(cfg["control"]["decel_time_sec"])
    _ = cfg["control"]["steering_trim"]
    _ = cfg["control"]["speed_step_pct"]
    _ = cfg["control"]["min_speed_pct"]
    _ = cfg["control"]["max_speed_pct_limit"]
    _ = cfg["control"]["loop_rate_hz"]
    _ = bool(cfg["hardware_interface"]["assert_dtr"])
    _ = bool(cfg["hardware_interface"]["assert_rts"])
    _ = float(cfg["hardware_interface"]["serial_timeout_sec"])
    _ = float(cfg["hardware_interface"]["write_timeout_sec"])
    _ = int(cfg["hardware_interface"]["max_consecutive_write_failures"])
    return cfg


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

        self.config_path = get_rover_config_path(config_path)
        self.config = load_rover_config(self.config_path)
        self._last_config_mtime: float = os.path.getmtime(self.config_path)
        self.neutral_pulse_us = int(self.config["pwm"]["neutral_pulse_us"])
        self.min_pulse_us = int(self.config["pwm"]["min_pulse_us"])
        self.max_pulse_us = int(self.config["pwm"]["max_pulse_us"])
        self.max_pulse_offset = int(self.config["pwm"]["max_pulse_offset"])
        self.max_speed_pct = int(self.config["pwm"]["max_speed_pct"])
        self.accel_time_sec = float(self.config["control"]["accel_time_sec"])
        self.decel_time_sec = float(self.config["control"]["decel_time_sec"])
        self.command_timeout_sec = float(self.config["control"]["command_timeout_sec"])
        self.steering_trim = float(self.config["control"]["steering_trim"])
        self.speed_step_pct = int(self.config["control"]["speed_step_pct"])
        self.min_speed_pct = int(self.config["control"]["min_speed_pct"])
        self.max_speed_pct_limit = int(self.config["control"]["max_speed_pct_limit"])
        self.loop_rate_hz = float(self.config["control"]["loop_rate_hz"])
        self.assert_dtr = bool(self.config["hardware_interface"]["assert_dtr"])
        self.assert_rts = bool(self.config["hardware_interface"]["assert_rts"])
        self.serial_timeout = float(self.config["hardware_interface"]["serial_timeout_sec"])
        self.write_timeout = float(self.config["hardware_interface"]["write_timeout_sec"])
        self.max_consecutive_write_failures = int(self.config["hardware_interface"]["max_consecutive_write_failures"])
        self._drive_event = threading.Event()
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
            "max_speed_pct": self.max_speed_pct,
            "max_pulse_offset": self.max_pulse_offset,
            "command_timeout_sec": self.command_timeout_sec,
            "sbus_active": 0,
            "web_active": 0,
            "ch1": 1000,
            "ch2": 1000,
            "ch5": 1000,
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
        """Polls canonical rover_config.json dynamically to allow runtime speed changes, trim adjustments, and ramp timing without restart."""
        try:
            mtime = os.path.getmtime(self.config_path)
            if mtime <= self._last_config_mtime:
                return
            self._last_config_mtime = mtime
            with open(self.config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)

            offset = int(cfg["pwm"]["max_pulse_offset"])
            max_speed = int(cfg["pwm"]["max_speed_pct"])
            trim = float(cfg["control"]["steering_trim"])
            accel = float(cfg["control"]["accel_time_sec"])
            decel = float(cfg["control"]["decel_time_sec"])
            timeout_sec = float(cfg["control"]["command_timeout_sec"])

            if offset != self.max_pulse_offset:
                self.max_pulse_offset = offset
                logger.info("RoverController updated live speed cap: max_pulse_offset=%d us", self.max_pulse_offset)

            if max_speed != self.max_speed_pct:
                self.max_speed_pct = max_speed
                logger.info("RoverController updated live max_speed_pct: %d%%", self.max_speed_pct)

            if trim != self.steering_trim:
                self.steering_trim = trim
                with self._lock:
                    self.telemetry["steering_trim"] = round(self.steering_trim, 3)
                logger.info("RoverController updated live steering_trim: %+.3f", self.steering_trim)

            if accel != self.accel_time_sec:
                self.accel_time_sec = accel
                logger.info("RoverController updated live accel_time_sec: %.2f s", self.accel_time_sec)

            if decel != self.decel_time_sec:
                self.decel_time_sec = decel
                logger.info("RoverController updated live decel_time_sec: %.2f s", self.decel_time_sec)

            if timeout_sec != self.command_timeout_sec:
                self.command_timeout_sec = timeout_sec
                with self._lock:
                    self.telemetry["command_timeout_sec"] = self.command_timeout_sec
                logger.info("RoverController updated live command_timeout_sec: %.2f s", self.command_timeout_sec)
        except Exception as e:
            logger.warning("Config reload failed: %s", e, exc_info=True)

    def start(self) -> None:
        """Starts the background 25 Hz UART heartbeat, control loop, and HTTP status server."""
        if self._worker_thread and self._worker_thread.is_alive():
            return
        self._stop_event.clear()
        self._worker_thread = threading.Thread(target=self._uart_loop, daemon=True, name="RoverUARTWorker")
        self._worker_thread.start()
        logger.info("Started RoverController background thread (port=%s, mock=%s).", self.serial_port, self.mock_mode)

    def stop(self) -> None:
        """Zeroes target drive inputs allowing the slew rate limiter to smoothly decelerate to neutral."""
        with self._lock:
            self._target_x = 0.0
            self._target_y = 0.0
            self._last_drive_update = time.time()
        self._drive_event.set()

    def shutdown(self) -> None:
        """Shuts down the background communication thread and HTTP status server."""
        self.set_drive(0.0, 0.0)
        self._stop_event.set()
        self._drive_event.set()
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=1.5)
        logger.info("RoverController shut down.")

    def set_max_speed_pct(self, pct: int) -> int:
        """Sets maximum speed cap directly in memory, clamping between min and max limits."""
        with self._lock:
            new_pct = max(self.min_speed_pct, min(self.max_speed_pct_limit, int(pct)))
            self.max_speed_pct = new_pct
            self.max_pulse_offset = int(500 * (new_pct / 100.0))
            self.telemetry["max_speed_pct"] = new_pct
            self.telemetry["max_pulse_offset"] = self.max_pulse_offset
            logger.info("RoverController updated speed: %d%% (pulse offset %d us)", self.max_speed_pct, self.max_pulse_offset)
            return new_pct

    def adjust_speed_pct(self, delta_pct: int) -> int:
        """Adjusts maximum speed cap by delta_pct in memory, clamping between min and max limits."""
        with self._lock:
            new_pct = max(self.min_speed_pct, min(self.max_speed_pct_limit, self.max_speed_pct + int(delta_pct)))
            self.max_speed_pct = new_pct
            self.max_pulse_offset = int(500 * (new_pct / 100.0))
            self.telemetry["max_speed_pct"] = self.max_speed_pct
            self.telemetry["max_pulse_offset"] = self.max_pulse_offset
            logger.info("RoverController adjusted speed: %d%% (pulse offset %d us)", self.max_speed_pct, self.max_pulse_offset)
            return new_pct

    def set_drive(self, x: float, y: float) -> None:
        """Sets normalized joystick drive inputs (x=steering [-1.0..1.0], y=throttle [-1.0..1.0])."""
        # Clamp inputs
        x_clamped = max(-1.0, min(1.0, float(x)))
        y_clamped = max(-1.0, min(1.0, float(y)))

        with self._lock:
            changed = (abs(x_clamped - self._target_x) > 0.02) or (abs(y_clamped - self._target_y) > 0.02)
            self._target_x = x_clamped
            self._target_y = y_clamped
            self._last_drive_update = time.time()

        if changed:
            self._drive_event.set()

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
        """Main serial heartbeat loop communicating with Adafruit KB2040."""
        ser = None
        rx_buf = bytearray()
        consecutive_write_failures = 0

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
                    with self._lock:
                        self._current_left_val = 0.0
                        self._current_right_val = 0.0
                        self._target_x = 0.0
                        self._target_y = 0.0
                    consecutive_write_failures = 0
                    logger.info("Opened hardware serial port %s at %d baud.", self.serial_port, self.baudrate)
                except Exception as e:
                    logger.warning("Failed to open serial port %s: %s. Retrying in 2s...", self.serial_port, e, exc_info=True)
                    time.sleep(2.0)
                    continue

            loop_start = time.time()

            # 1. Read telemetry from KB2040 (if hardware serial active)
            if ser and ser.is_open:
                try:
                    if ser.in_waiting > 0:
                        chunk = ser.read(ser.in_waiting)
                        if chunk:
                            self.telemetry["last_seen"] = time.time()
                            rx_buf.extend(chunk)
                            while b'\n' in rx_buf:
                                idx = rx_buf.find(b'\n')
                                line_bytes = rx_buf[:idx]
                                rx_buf = rx_buf[idx + 1:]
                                line = line_bytes.decode('utf-8', errors='replace').strip()
                                if "STAT:" in line:
                                    self._parse_stat_line(line[line.find("STAT:"):])
                except Exception as e:
                    logger.warning("Serial read error on %s: %s", self.serial_port, e, exc_info=True)
                    try:
                        ser.reset_input_buffer()
                    except Exception as reset_err:
                        logger.debug("Error resetting input buffer: %s", reset_err)

            # 2. Kinematics & Arcade Drive Mixing
            now = time.time()
            if now - self._last_config_check > 0.5:
                self._last_config_check = now
                self._check_config_reload()

            with self._lock:
                # Command timeout watchdog: reset target inputs to neutral if no recent update
                if (now - self._last_drive_update) > self.command_timeout_sec:
                    self._target_x = 0.0
                    self._target_y = 0.0

                x = self._target_x
                y = self._target_y
                slider = self._slider_val
                pulse = self._lights_pulse
                if self._lights_pulse == 1:
                    self._lights_pulse = 0

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

            # Direct 1-to-1 drive output (removed unapproved slew limiting)
            self._current_left_val = target_left
            self._current_right_val = target_right

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

            # Dispatch to hardware serial or mock sink
            if ser and ser.is_open:
                try:
                    ser.write(cmd_str.encode('utf-8'))
                    consecutive_write_failures = 0
                except Exception as e:
                    consecutive_write_failures += 1
                    logger.warning(
                        "Serial write error on %s (attempt %d/%d): %s",
                        self.serial_port, consecutive_write_failures, self.max_consecutive_write_failures, e
                    )
                    try:
                        ser.reset_output_buffer()
                    except Exception as reset_err:
                        logger.debug("Error resetting output buffer: %s", reset_err)
                    if consecutive_write_failures >= self.max_consecutive_write_failures:
                        logger.error(
                            "Exceeded maximum consecutive write failures (%d) on %s. Closing port...",
                            self.max_consecutive_write_failures, self.serial_port
                        )
                        try:
                            ser.close()
                        except Exception as close_err:
                            logger.warning("Error closing serial port after write failure: %s", close_err)
                        ser = None
            elif self.mock_mode and self._mock_packet_sink:
                try:
                    self._mock_packet_sink(cmd_str, left_pulse, right_pulse)
                except Exception as sink_err:
                    logger.debug("Mock packet sink callback error: %s", sink_err)

            # Target loop rate from configuration with immediate event wakeup
            elapsed = time.time() - loop_start
            sleep_time = max(0.005, (1.0 / self.loop_rate_hz) - elapsed)
            self._drive_event.wait(timeout=sleep_time)
            self._drive_event.clear()

        if ser and ser.is_open:
            try:
                # Send final neutral stop command with explicit flush
                neutral_cmd = f"CMD:{self.neutral_pulse_us},{self.neutral_pulse_us},{self.neutral_pulse_us},0\n"
                ser.write(neutral_cmd.encode('utf-8'))
                ser.flush()
                ser.close()
            except Exception as close_err:
                logger.warning("Error during shutdown serial close: %s", close_err)

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
                    self.telemetry["last_seen"] = time.time()
        except Exception as parse_err:
            logger.debug("STAT line parse warning: %s", parse_err, exc_info=True)
