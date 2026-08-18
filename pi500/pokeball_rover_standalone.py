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
PI4B_SOUND_URL = "http://192.168.0.86:8082/api/play_sound"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("pokeball_rover_standalone")


def play_chime(kind: str = "connect") -> None:
    """Dispatches sound event to Pi 4B Touch UI audio service."""
    def _work():
        try:
            payload = json.dumps({"kind": kind}).encode("utf-8")
            req = urllib.request.Request(PI4B_SOUND_URL, data=payload, headers={"Content-Type": "application/json"})
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

        # Initialize RoverController with auto-port detection (/dev/ttyAMA0 on Pi 500)
        if RoverController is not None:
            self.rover_ctrl = RoverController(serial_port=serial_port, baudrate=115200)
        else:
            self.rover_ctrl = None

        self.telemetry: Dict[str, Any] = {
            "mode": "STANDALONE_ROVER",
            "connected": False,
            "armed": False,
            "packets": 0,
            "norm_x": 0.0,
            "norm_y": 0.0,
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

            # Top Red Button tap -> Instant Emergency Brake / Zero Wheels
            if btn_top and not self.last_btn_top:
                if self.rover_ctrl:
                    self.rover_ctrl.stop()
                self.is_braking = True
                logger.info("🛑 Emergency Brake engaged via Top Red Button!")
            elif not btn_top and self.last_btn_top:
                self.is_braking = False

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
