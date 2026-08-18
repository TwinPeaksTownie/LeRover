#!/usr/bin/env python3
"""RoverController module for GoBilda Overlander-4 chassis.
Manages serial communication with the Adafruit KB2040 safety bridge over GPIO UART (/dev/serial0),
25 Hz heartbeat packets, differential arcade drive kinematics, and safety watchdogs.
Supports mock/simulated serial mode for local PC testing.
"""

import logging
import os
import threading
import time
from typing import Optional, Dict, Any, Tuple

logger = logging.getLogger("so101.rover_controller")


class RoverController:
    """Thread-safe controller for Overlander-4 PWM wheel motors via Adafruit KB2040."""

    def __init__(
        self,
        serial_port: Optional[str] = None,
        baudrate: int = 115200,
        max_pulse_offset: int = 125,
        accel_ramp_rate: float = 0.12,
        watchdog_timeout: float = 1.0,
        mock_mode: bool = False
    ) -> None:
        if serial_port is None or serial_port in ["/dev/serial0", "/dev/ttyAMA0"]:
            if os.path.exists("/dev/ttyAMA0"):
                self.serial_port = "/dev/ttyAMA0"
            elif os.path.exists("/dev/serial0"):
                self.serial_port = "/dev/serial0"
            else:
                self.serial_port = "/dev/ttyAMA0"
        else:
            self.serial_port = serial_port

        self.baudrate = baudrate
        self.max_pulse_offset = max_pulse_offset  # +/- 125 us -> 1375 to 1625 us (indoor driving)

        self.accel_ramp_rate = accel_ramp_rate
        self.watchdog_timeout = watchdog_timeout
        self.mock_mode = mock_mode

        # Fallback to mock mode automatically if on Windows or serial port does not exist
        if not self.mock_mode:
            if os.name == "nt" or (not os.path.exists(self.serial_port) and not self.serial_port.startswith("mock")):
                self.mock_mode = True
                logger.info("RoverController automatically running in MOCK mode (serial port '%s' not present).", self.serial_port)

        self._lock = threading.Lock()
        self._target_x: float = 0.0
        self._target_y: float = 0.0
        self._last_drive_update: float = 0.0
        self._current_left_val: float = 0.0
        self._current_right_val: float = 0.0
        self._slider_val: int = 1500
        self._lights_pulse: int = 0

        self._last_left_pulse: int = 1500
        self._last_right_pulse: int = 1500
        self._last_cmd_sent: str = "CMD:1500,1500,1500,0\n"

        self.telemetry: Dict[str, Any] = {
            "mode": "MOCK" if self.mock_mode else "DISCONNECTED",
            "left_out": 1500,
            "right_out": 1500,
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
                    ser = serial.Serial(self.serial_port, self.baudrate, timeout=0.01)
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
                                line = line_bytes.decode('utf-8', errors='ignore').strip()
                                if line.startswith("STAT:"):
                                    self._parse_stat_line(line)
                except Exception as e:
                    logger.warning("Serial read error on %s: %s", self.serial_port, e)
                    try:
                        ser.close()
                    except Exception:
                        pass
                    ser = None

            # 2. Kinematics & Arcade Drive Mixing
            now = time.time()
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
            throttle = y
            steering = -x

            target_left = max(-1.0, min(1.0, throttle + steering))
            target_right = max(-1.0, min(1.0, throttle - steering))

            # Apply software smoothing acceleration ramp
            self._current_left_val += (target_left - self._current_left_val) * self.accel_ramp_rate
            self._current_right_val += (target_right - self._current_right_val) * self.accel_ramp_rate

            # Map to 50Hz PWM pulse widths (1000 - 2000 us, neutral 1500 us)
            # Left motor physically inverted (lower pulse = forward, higher pulse = reverse)
            # Right motor normal (higher pulse = forward, lower pulse = reverse)
            left_pulse = 1500 - int(self._current_left_val * self.max_pulse_offset)
            right_pulse = 1500 + int(self._current_right_val * self.max_pulse_offset)

            left_pulse = max(1000, min(2000, left_pulse))
            right_pulse = max(1000, min(2000, right_pulse))

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

            # Target ~25 Hz loop rate (40 ms cycle)
            elapsed = time.time() - loop_start
            sleep_time = max(0.005, 0.040 - elapsed)
            time.sleep(sleep_time)

        if ser and ser.is_open:
            try:
                # Send final neutral stop command
                ser.write(b"CMD:1500,1500,1500,0\n")
                ser.close()
            except Exception:
                pass

    def _parse_stat_line(self, line: str) -> None:
        """Parses telemetry feedback string from KB2040."""
        try:
            parts = line.replace("STAT:", "").split(",")
            if len(parts) >= 8:
                with self._lock:
                    self.telemetry["mode"] = parts[0]
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
