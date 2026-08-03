#!/usr/bin/env python3
"""
Poké Ball Plus Teleoperation Driver with Real-Time State Export
Connects to Poké Ball Plus (MAC: 58:2F:40:8D:50:71) over BLE.
Controls Auxiliary Pedestal Spinner (Motor 7) & LeSlider Gantry (Motor 8) via HTTP API.
Writes live connection and input telemetry to /tmp/pokeball_telemetry.json for UI visual feedback.
"""

import asyncio
import time
import json
import logging
import urllib.request
import threading
import math
import struct
import subprocess
import os

from bleak import BleakClient

MAC_ADDRESS = "58:2F:40:8D:50:71"
INPUT_UUID = "6675e16c-f36d-4567-bb55-6b51e27a23e6"
API_URL = "http://127.0.0.1:8085"
TELEMETRY_FILE = "/tmp/pokeball_telemetry.json"

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

def play_chime(kind="connect"):
    def _work():
        try:
            sr = 22050
            buf = bytearray()
            if kind == "connect":
                tones = [(523.25, 0.08, 0.3), (659.25, 0.08, 0.3), (784.00, 0.16, 0.4)]
            else:
                tones = [(784.00, 0.10, 0.3), (523.25, 0.18, 0.3)]
            for freq, duration, vol in tones:
                n_samples = int(sr * duration)
                for i in range(n_samples):
                    t = i / sr
                    val = int(vol * 32767 * math.sin(2 * math.pi * freq * t))
                    buf.extend(struct.pack('<h', val))
            wav_path = f"/tmp/chime_{kind}.wav"
            with open(wav_path, "wb") as f:
                f.write(b"RIFF")
                f.write(struct.pack("<I", 36 + len(buf)))
                f.write(b"WAVEfmt ")
                f.write(struct.pack("<IHHIIHH", 16, 1, 1, sr, sr * 2, 2, 16))
                f.write(b"data")
                f.write(struct.pack("<I", len(buf)))
                f.write(buf)
            subprocess.run(["aplay", "-q", wav_path], check=False)
        except Exception:
            pass
    threading.Thread(target=_work, daemon=True).start()


class PokeballTeleopDriver:
    def __init__(self, mac_address=MAC_ADDRESS, api_url=API_URL):
        self.mac_address = mac_address
        self.api_url = api_url
        self.client = None

        # Pedestal Presets
        self.preset_angles = [-165.0, -135.0, -90.0, -45.0, 0.0, 45.0, 90.0, 135.0, 165.0]
        self.preset_index = 4  # Default 0.0 deg

        # Movement lock state
        self.is_busy = False
        self.busy_until = 0.0

        # Telemetry & Input state
        self.last_buttons = 0
        self.counter = 0
        self.telemetry = {
            "connected": False,
            "status": "DISCONNECTED",
            "mac": self.mac_address,
            "last_seen": 0.0,
            "packet_count": 0,
            "norm_x": 0.0,
            "norm_y": 0.0,
            "button_a": False,
            "button_b": False,
            "last_error": None
        }
        self.write_telemetry()

    def write_telemetry(self):
        try:
            tmp_path = TELEMETRY_FILE + ".tmp"
            with open(tmp_path, "w") as f:
                json.dump(self.telemetry, f)
            os.replace(tmp_path, TELEMETRY_FILE)
        except Exception as e:
            logging.debug("Telemetry write error: %s", e)

    def _send_aux_request(self, endpoint, payload, lock_duration=2.2):
        now = time.time()
        if self.is_busy or now < self.busy_until:
            logging.info("⚠️ Aux Request Ignored: Motor is currently executing a move.")
            return

        self.is_busy = True
        self.busy_until = now + lock_duration

        def _work():
            try:
                url = f"{self.api_url}{endpoint}"
                data = json.dumps(payload).encode('utf-8')
                req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
                with urllib.request.urlopen(req, timeout=3.0) as resp:
                    pass
            except Exception as e:
                logging.warning("Aux API HTTP Dispatch error: %s", e)
            finally:
                time.sleep(lock_duration)
                self.is_busy = False

        threading.Thread(target=_work, daemon=True).start()

    def notification_handler(self, sender, data):
        self.counter += 1
        if len(data) < 5:
            return

        buttons = data[1]

        # 12-Bit Packed Joystick Decoding
        raw_x_12 = data[2] | ((data[3] & 0x0F) << 8)
        raw_y_12 = (data[3] >> 4) | (data[4] << 4)
        
        x_offset = raw_x_12 - 2048
        y_offset = raw_y_12 - 2048
        
        norm_x = round(x_offset / 2048.0, 3)
        norm_y = round(y_offset / 2048.0, 3)
        
        btn_b = bool(buttons & 0x01)
        btn_a = bool(buttons & 0x02)

        # Deadzone filter
        filt_x = 0.0 if abs(norm_x) < 0.08 else norm_x
        filt_y = 0.0 if abs(norm_y) < 0.08 else norm_y
            
        # Stream drive commands over ZMQ to rover_daemon
        self.send_drive_command(filt_x, filt_y)

        # Update Live Telemetry
        self.telemetry.update({
            "connected": True,
            "status": "CONNECTED",
            "last_seen": time.time(),
            "packet_count": self.counter,
            "norm_x": norm_x,
            "norm_y": norm_y,
            "button_a": btn_a,
            "button_b": btn_b,
            "last_error": None
        })
        self.write_telemetry()
        
        now = time.time()

        # 1. Button B (Top Red Button)
        if btn_b and not (self.last_buttons & 0x01):
            if self.is_busy or now < self.busy_until:
                logging.info("⚠️ Button B Ignored: Movement currently in progress.")
            else:
                if x_offset > 200:
                    self.preset_index = min(len(self.preset_angles) - 1, self.preset_index + 1)
                    target_deg = self.preset_angles[self.preset_index]
                    logging.info("Joystick Right -> Button B -> Stepping Pedestal Preset: %.1f deg", target_deg)
                    self._send_aux_request("/api/move", {"id": 7, "angle": target_deg}, lock_duration=2.2)
                elif x_offset < -200:
                    self.preset_index = max(0, self.preset_index - 1)
                    target_deg = self.preset_angles[self.preset_index]
                    logging.info("Joystick Left -> Button B -> Stepping Pedestal Preset: %.1f deg", target_deg)
                    self._send_aux_request("/api/move", {"id": 7, "angle": target_deg}, lock_duration=2.2)

        # 2. Button A (Stick Click)
        if btn_a and not (self.last_buttons & 0x02):
            if x_offset < -200:
                if not (self.is_busy or now < self.busy_until):
                    logging.info("Joystick Left -> Button A Clicked -> Nudging Gantry LEFT")
                    self._send_aux_request("/api/nudge_physical", {"id": 8, "direction": "left", "amount": 500}, lock_duration=2.2)
            elif x_offset > 200:
                if not (self.is_busy or now < self.busy_until):
                    logging.info("Joystick Right -> Button A Clicked -> Nudging Gantry RIGHT")
                    self._send_aux_request("/api/nudge_physical", {"id": 8, "direction": "right", "amount": 500}, lock_duration=2.2)

        self.last_buttons = buttons

    async def run(self):
        while True:
            try:
                logging.info("Connecting to Poké Ball Plus at %s...", self.mac_address)
                self.telemetry.update({"connected": False, "status": "SEARCHING", "last_error": None})
                self.write_telemetry()

                async with BleakClient(self.mac_address, timeout=6.0) as client:
                    self.client = client
                    logging.info("✅ Connected to Poké Ball Plus!")
                    play_chime("connect")
                    self.telemetry.update({"connected": True, "status": "CONNECTED", "last_seen": time.time()})
                    self.write_telemetry()

                    await client.start_notify(INPUT_UUID, self.notification_handler)
                    logging.info("Listening for Poké Ball Plus telemetry...")
                    
                    while client.is_connected:
                        await asyncio.sleep(0.5)
                        # Heartbeat telemetry update
                        self.telemetry["last_seen"] = time.time()
                        self.write_telemetry()
                        
                    play_chime("disconnect")
            except Exception as e:
                err_msg = str(e)
                logging.info("Poké Ball BLE waiting for device... [%s]", err_msg)
                self.telemetry.update({
                    "connected": False,
                    "status": "SEARCHING",
                    "last_error": err_msg
                })
                self.write_telemetry()
                await asyncio.sleep(3.0)

def main():
    driver = PokeballTeleopDriver()
    try:
        asyncio.run(driver.run())
    except KeyboardInterrupt:
        logging.info("Driver stopped by user.")

if __name__ == "__main__":
    main()
