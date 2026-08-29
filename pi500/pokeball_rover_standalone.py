#!/usr/bin/env python3
"""Standalone Poké Ball Plus BLE Rover Drivetrain Driver.
Executes pure differential driving on Overlander-4 chassis via Adafruit KB2040 safety bridge (/dev/serial0).
Zero dependencies on Feetech serial bus (/dev/ttyACM0) or external 12V power supply.
"""

import asyncio
import json
import logging
import os
import signal
import struct
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

MAC_ADDRESS = "58:2F:40:8D:50:71"
INPUT_UUID = "6675e16c-f36d-4567-bb55-6b51e27a23e6"
TELEMETRY_FILE = "/tmp/pokeball_rover_telemetry.json"
try:
    import network_resolver
except ImportError:
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import network_resolver


def get_pi4b_sound_url() -> str:
    pi4b_ip = network_resolver.get_pi4b_ip(prefer_port=8082)
    return f"http://{pi4b_ip}:8082/api/play_sound"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("pokeball_rover_standalone")


def play_chime(kind: str = "connect") -> None:
    """Dispatches sound event to Pi 4B Touch UI audio service."""
    def _work():
        try:
            payload = json.dumps({"kind": kind}).encode("utf-8")
            req = urllib.request.Request(get_pi4b_sound_url(), data=payload, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                pass
        except Exception as e:
            logger.debug("Audio request '%s' to Pi 4B failed: %s", kind, e)

    threading.Thread(target=_work, daemon=True).start()


class StandalonePokeballRover:
    """Standalone driver managing Poké Ball BLE stream and Overlander-4 RoverController."""

    def __init__(self, mac_address: str = MAC_ADDRESS, serial_port: Optional[str] = None) -> None:
        self.mac_address = mac_address
        self.serial_port = serial_port
        self.running = True
        self.client: Optional[BleakClient] = None
        self.counter = 0

        # Initialize RoverController with configurable speed cap and steering trim
        max_pulse_offset = 175
        self.steering_trim: float = 0.0
        self.trim_stick_latched: bool = False

        config_paths = ["/tmp/rover_config.json", "/home/user/so101/config/rover_config.json", os.path.join(workspace_root, "config", "rover_config.json")]
        for cp in config_paths:
            if os.path.exists(cp):
                try:
                    with open(cp, "r") as f:
                        cfg = json.load(f)
                        if "max_pulse_offset" in cfg:
                            max_pulse_offset = int(cfg["max_pulse_offset"])
                        elif "max_speed_pct" in cfg:
                            pct = float(cfg["max_speed_pct"])
                            max_pulse_offset = int(500 * (pct / 100.0))
                        if "steering_trim" in cfg:
                            self.steering_trim = float(cfg["steering_trim"])
                    logger.info("Loaded config from %s: max_pulse_offset=%d us, steering_trim=%+.3f", cp, max_pulse_offset, self.steering_trim)
                    break
                except Exception as e:
                    logger.warning("Could not read %s: %s", cp, e)

        if RoverController is not None:
            self.rover_ctrl = RoverController(serial_port=serial_port, baudrate=115200, max_pulse_offset=max_pulse_offset)
            self.rover_ctrl.set_steering_trim(self.steering_trim)
        else:
            self.rover_ctrl = None

        self.telemetry: Dict[str, Any] = {
            "mode": "STANDALONE_ROVER",
            "connected": False,
            "armed": False,
            "packets": 0,
            "norm_x": 0.0,
            "norm_y": 0.0,
            "steering_trim": self.steering_trim,
            "direction": "center",
            "raw_hex": "",
            "btn_a": False,
            "btn_b": False,
            "left_pulse": 1500,
            "right_pulse": 1500,
            "last_seen": 0.0,
        }

        self.last_btn_top = False
        self.last_btn_stick = False
        self.is_braking = False
        self.is_armed = False
        self.arm_lockout_until = 0.0

    def _adjust_trim(self, delta: float) -> None:
        """Adjusts the steering trim by delta, updates RoverController, persists config, and triggers coin sound."""
        self.steering_trim = round(max(-0.25, min(0.25, self.steering_trim + delta)), 3)
        if self.rover_ctrl:
            self.rover_ctrl.set_steering_trim(self.steering_trim)

        self._save_rover_config()
        play_chime("connect")  # On Pi 4B audio service, "connect" plays smw_coin.wav
        logger.info("🎯 Steering Trim calibrated (%+.2f) -> New trim: %+.3f (Left: %+.1f%%, Right: %+.1f%%). Triggered coin feedback.",
                    delta, self.steering_trim, -self.steering_trim * 100, self.steering_trim * 100)

    def _save_rover_config(self) -> None:
        """Persists current rover speed and steering trim to /tmp and persistent config."""
        cfg_dict = {
            "max_pulse_offset": self.rover_ctrl.max_pulse_offset if self.rover_ctrl else 175,
            "steering_trim": self.steering_trim
        }
        for path in ["/tmp/rover_config.json", "/home/user/so101/config/rover_config.json"]:
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w") as f:
                    json.dump(cfg_dict, f, indent=2)
            except Exception as e:
                logger.debug("Failed to write config to %s: %s", path, e)

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

            # 10% Deadzone filter with smooth linear remapping
            DEADZONE = 0.10
            if abs(norm_x) <= DEADZONE:
                norm_x = 0.0
            else:
                sign_x = 1.0 if norm_x > 0 else -1.0
                norm_x = sign_x * ((abs(norm_x) - DEADZONE) / (1.0 - DEADZONE))

            if abs(norm_y) <= DEADZONE:
                norm_y = 0.0
            else:
                sign_y = 1.0 if norm_y > 0 else -1.0
                norm_y = sign_y * ((abs(norm_y) - DEADZONE) / (1.0 - DEADZONE))

            # Direction classification
            if norm_x < -0.35:
                direction = "left"
            elif norm_x > 0.35:
                direction = "right"
            elif norm_y > 0.35:
                direction = "forward"
            elif norm_y < -0.35:
                direction = "reverse"
            else:
                direction = "center"

            # Button Mapping
            # Button A (Stick Click) = 0x02
            # Button B (Top Red Button) = 0x01
            btn_stick = bool(buttons & 0x02)
            btn_top = bool(buttons & 0x01)

            now = time.time()

            # Button A (Stick Click) -> Arm Drivetrain & Play Mario Kart Start
            if btn_stick and not self.last_btn_stick:
                if not self.is_armed:
                    self.is_armed = True
                    self.arm_lockout_until = now + 4.25
                    logger.info("🏎️ Drivetrain Arming triggered! Playing Mario Kart countdown (lockout until %.1f)...", self.arm_lockout_until)
                    play_chime("mario_kart_start")
                else:
                    logger.info("🏎️ Drivetrain already armed.")

            # Top Red Button (Button B) Tap & Hold Logic:
            # While Red Button is held down:
            # 1. Wheels are stopped (Braking active)
            # 2. Deflecting Stick Right (norm_x > 0.40) nudges trim by +0.01 (+1% right bias)
            # 3. Deflecting Stick Left (norm_x < -0.40) nudges trim by -0.01 (-1% left bias)
            # 4. Plays SMW coin sound on Pi 4B for each registered notch
            if btn_top:
                if not self.last_btn_top:
                    if self.rover_ctrl:
                        self.rover_ctrl.stop()
                    self.is_braking = True
                    logger.info("🛑 Emergency Brake / Calibration mode engaged via Top Red Button!")

                # Live trim calibration gesture while holding Red Button
                if norm_x > 0.40 and not self.trim_stick_latched:
                    self._adjust_trim(+0.01)
                    self.trim_stick_latched = True
                elif norm_x < -0.40 and not self.trim_stick_latched:
                    self._adjust_trim(-0.01)
                    self.trim_stick_latched = True
                elif abs(norm_x) < 0.20:
                    self.trim_stick_latched = False
            else:
                if self.last_btn_top:
                    self.is_braking = False
                    self.trim_stick_latched = False
                    logger.info("🛑 Brake released. Resuming active drive mode with steering_trim=%+.3f", self.steering_trim)

            # Dispatch drive command if armed and past the countdown lockout
            if self.rover_ctrl:
                if self.is_armed and not self.is_braking and now >= self.arm_lockout_until:
                    self.rover_ctrl.set_drive(norm_x, norm_y)
                else:
                    self.rover_ctrl.stop()

            self.last_btn_top = btn_top
            self.last_btn_stick = btn_stick

            # Update telemetry
            rover_telem = self.rover_ctrl.get_telemetry() if self.rover_ctrl else {}
            self.telemetry.update({
                "mode": "STANDALONE_ROVER",
                "connected": True,
                "armed": self.is_armed,
                "lockout_active": (now < self.arm_lockout_until),
                "packets": self.counter,
                "norm_x": round(norm_x, 3),
                "norm_y": round(norm_y, 3),
                "steering_trim": self.steering_trim,
                "direction": direction,
                "raw_hex": data.hex().upper(),
                "btn_a": btn_stick,
                "btn_b": btn_top,
                "left_pulse": rover_telem.get("left_pulse", 1500),
                "right_pulse": rover_telem.get("right_pulse", 1500),
                "last_seen": now,
            })

            # Periodically write telemetry file for Touch UI poller (every ~5 packets)
            if self.counter % 5 == 0:
                self._write_telemetry()

        except Exception as e:
            logger.error("Error processing Poké Ball packet: %s", e)

    def _write_telemetry(self) -> None:
        try:
            tmp_path = TELEMETRY_FILE + ".tmp"
            with open(tmp_path, "w") as f:
                json.dump(self.telemetry, f)
            os.replace(tmp_path, TELEMETRY_FILE)
        except Exception as e:
            logger.debug("Telemetry write error: %s", e)

    async def run(self) -> None:
        if not BLEAK_AVAILABLE:
            logger.error("Bleak library is not available. Please install bleak.")
            return

        # Start RoverController background 25Hz heartbeat loop
        if self.rover_ctrl:
            self.rover_ctrl.start()
            logger.info("Overlander-4 RoverController started.")

        logger.info("Connecting to Poké Ball Plus BLE @ %s...", self.mac_address)

        while self.running:
            try:
                async with BleakClient(self.mac_address, timeout=12.0) as client:
                    self.client = client
                    logger.info("✅ Connected to Poké Ball Plus! Subscribing to notifications...")
                    self.telemetry["connected"] = True
                    self.is_armed = False
                    self.arm_lockout_until = 0.0
                    self._write_telemetry()
                    # Litmus test: play coin sound on BLE handshake confirmation
                    play_chime("connect")

                    await client.start_notify(INPUT_UUID, self.notification_handler)

                    while self.running and client.is_connected:
                        await asyncio.sleep(0.5)

                    if client.is_connected:
                        await client.stop_notify(INPUT_UUID)

            except Exception as e:
                logger.warning("Poké Ball BLE connection lost/error: %s. Retrying in 2.0s...", e)
                self.telemetry["connected"] = False
                self.telemetry["norm_x"] = 0.0
                self.telemetry["norm_y"] = 0.0
                self._write_telemetry()
                if self.rover_ctrl:
                    self.rover_ctrl.stop()
                if self.running:
                    await asyncio.sleep(2.0)

        # Cleanup on exit
        logger.info("Shutting down Standalone Pokéball Rover...")
        if self.rover_ctrl:
            self.rover_ctrl.stop()
            self.rover_ctrl.shutdown()
        play_chime("disconnect")
        self.telemetry["connected"] = False
        self._write_telemetry()


def main() -> None:
    driver = StandalonePokeballRover()

    def _sig_handler(signum, frame):
        logger.info("Received termination signal %s. Exiting cleanly...", signum)
        driver.running = False

    signal.signal(signal.SIGTERM, _sig_handler)
    signal.signal(signal.SIGINT, _sig_handler)

    try:
        asyncio.run(driver.run())
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":
    main()
