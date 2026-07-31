#!/usr/bin/env python3
"""
Poké Ball Plus BLE Teleoperation & Gesture Driver
Connects to Poké Ball Plus (MAC: 58:2F:40:8D:50:71) over BLE.
Parses Joystick, Buttons, Accelerometer, and Gyroscope telemetry.
Drives SO-101 Arm via Inverse Kinematics (IK) and UGV Rover Drivetrain.
"""

import asyncio
import math
import time
import json
import logging
import zmq
from bleak import BleakClient
from so101_ik import SO101Kinematics

MAC_ADDRESS = "58:2F:40:8D:50:71"
INPUT_UUID = "6675e16c-f36d-4567-bb55-6b51e27a23e6"

PORT_ZMQ_CMD = 5555

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

class PokeballTeleopDriver:
    def __init__(self, mac_address=MAC_ADDRESS):
        self.mac_address = mac_address
        self.client = None
        self.ik = SO101Kinematics()
        
        # Operational Mode: 'ARM_IK' or 'ROVER_DRIVE'
        self.mode = 'ARM_IK'
        
        # Arm Cartesian Target State
        self.target_x = 0.16  # meters
        self.target_y = 0.00  # meters
        self.target_z = 0.12  # meters
        self.pitch_deg = 0.0
        self.roll_deg = 0.0
        self.gripper_open = True
        
        # Auxiliary Gantry & Pedestal Control State
        self.preset_angles = [-165.0, -135.0, -90.0, -45.0, 0.0, 45.0, 90.0, 135.0, 165.0]
        self.preset_index = 4  # Default index 4 = 0.0 deg (Forward)
        self.api_url = "http://127.0.0.1:8085"
        self.is_busy = False
        self.busy_until = 0.0

        # Motion deadzones & sensitivity
        self.y_center = 118
        self.y_deadzone = 15
        self.step_xy = 0.005  # 5mm per tick
        self.step_z = 0.005   # 5mm per tick
        
        # Gesture tracking
        self.last_shake_time = 0
        self.last_buttons = 0
        self.counter = 0
        
        # ZMQ Command Socket
        self.ctx = zmq.Context()
        self.zmq_sock = self.ctx.socket(zmq.PUSH)
        self.zmq_sock.setsockopt(zmq.CONFLATE, 1)
        self.zmq_sock.setsockopt(zmq.LINGER, 0)
        try:
            self.zmq_sock.connect(f"tcp://127.0.0.1:{PORT_ZMQ_CMD}")
            logging.info("Connected to local ZMQ follower socket on port %d", PORT_ZMQ_CMD)
        except Exception as e:
            logging.warning("ZMQ connection warning: %s", e)

    def _send_aux_request(self, endpoint, payload, lock_duration=2.2):
        """Asynchronously dispatches HTTP requests and enforces a strict movement lock to ignore rapid presses."""
        import urllib.request, threading
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

    def get_x_direction(self, nibble_val):
        """Returns X direction: -1 (Left), 0 (Center), +1 (Right)"""
        if nibble_val in [2, 3]:
            return -1
        elif nibble_val >= 8:
            return 1
        return 0

    def parse_imu_accel(self, data):
        """Extracts accelerometer magnitude if IMU data bytes are present"""
        if len(data) >= 12:
            try:
                # Raw signed 16-bit accel values from bytes 6..11
                ax = int.from_bytes(data[6:8], byteorder='little', signed=True)
                ay = int.from_bytes(data[8:10], byteorder='little', signed=True)
                az = int.from_bytes(data[10:12], byteorder='little', signed=True)
                
                # Convert to g-force magnitude
                mag = math.sqrt(ax**2 + ay**2 + az**2) / 4096.0
                return mag, ax, ay, az
            except Exception:
                pass
        return 1.0, 0, 0, 0

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
        
        # Check IMU Shake Gesture
        accel_mag, ax, ay, az = self.parse_imu_accel(data)
        now = time.time()
        
        if accel_mag > 2.2 and (now - self.last_shake_time) > 1.2:
            self.last_shake_time = now
            self.mode = 'ROVER_DRIVE' if self.mode == 'ARM_IK' else 'ARM_IK'
            logging.info("🔥 GESTURE DETECTED: QUICK SHAKE (|A|=%.2fg) -> Switched Mode to [%s]", accel_mag, self.mode)

        # Parse Inputs based on Mode
        if self.mode == 'ARM_IK':
            # 1. Analog Joystick X -> Target Y (Left / Right)
            if abs(x_offset) > 150:
                self.target_y += (x_offset / 2048.0) * self.step_xy
                self.target_y = max(-0.20, min(0.20, self.target_y))
                
            # 2. Analog Joystick Y -> Target X (Forward / Back)
            if abs(y_offset) > 150:
                self.target_x += (-y_offset / 2048.0) * self.step_xy
                self.target_x = max(0.05, min(0.28, self.target_x))
                
            # 3. Button B (Top Red Button) -> Advances to Next Pedestal Preset in Order
            if (buttons & 0x01) and not (self.last_buttons & 0x01):
                if self.is_busy or now < self.busy_until:
                    logging.info("⚠️ Button B Ignored: Movement currently in progress.")
                else:
                    if self.preset_index < len(self.preset_angles) - 1:
                        self.preset_index += 1
                    else:
                        self.preset_index = 0  # Loop back to start after reaching end
                        
                    target_deg = self.preset_angles[self.preset_index]
                    logging.info("Top Button B Pressed -> Next Pedestal Preset: %.1f deg (Index %d/%d)", target_deg, self.preset_index, len(self.preset_angles)-1)
                    self._send_aux_request("/api/move", {"id": 7, "angle": target_deg}, lock_duration=2.2)
                
            # 4. Joystick Left/Right + Thumbstick Click (Button A) -> Moves Gantry 500 Ticks over 2 Seconds
            if (buttons & 0x02) and not (self.last_buttons & 0x02):
                if x_offset < -200:
                    if self.is_busy or now < self.busy_until:
                        logging.info("⚠️ Thumbstick Click A + Left Ignored: Movement currently in progress.")
                    else:
                        logging.info("Thumbstick Click A + Left -> Nudging Gantry 500 ticks LEFT")
                        self._send_aux_request("/api/nudge_physical", {"id": 8, "direction": "left", "amount": 500, "speed": 250}, lock_duration=2.2)
                elif x_offset > 200:
                    if self.is_busy or now < self.busy_until:
                        logging.info("⚠️ Thumbstick Click A + Right Ignored: Movement currently in progress.")
                    else:
                        logging.info("Thumbstick Click A + Right -> Nudging Gantry 500 ticks RIGHT")
                        self._send_aux_request("/api/nudge_physical", {"id": 8, "direction": "right", "amount": 500, "speed": 250}, lock_duration=2.2)
                
            # Solve IK
            joint_angles = self.ik.inverse_kinematics(
                self.target_x, self.target_y, self.target_z,
                pitch_deg=self.pitch_deg, roll_deg=self.roll_deg
            )
            joint_angles["gripper"] = 100.0 if self.gripper_open else 0.0
            
            # Format action dict for ZMQ follower
            action = {f"{k}.pos": v for k, v in joint_angles.items()}
            
            # Send to follower host
            try:
                self.zmq_sock.send_string(json.dumps(action), flags=zmq.NOBLOCK)
            except Exception:
                pass
                
            if self.counter % 20 == 0:
                logging.info("[ARM IK] Target: (X=%.3fm, Y=%.3fm, Z=%.3fm) -> Pan:%.1f Lift:%.1f Elbow:%.1f",
                             self.target_x, self.target_y, self.target_z,
                             joint_angles["shoulder_pan"], joint_angles["shoulder_lift"], joint_angles["elbow_flex"])

        elif self.mode == 'ROVER_DRIVE':
            # Joystick Y & X -> Drive command
            cmd = "STOP"
            if y_offset < -200:
                cmd = "FORWARD"
            elif y_offset > 200:
                cmd = "BACK"
            elif x_offset < -200:
                cmd = "LEFT"
            elif x_offset > 200:
                cmd = "RIGHT"
                
            if buttons & 0x01:  # Emergency Stop
                cmd = "STOP"
                
            if self.counter % 15 == 0:
                logging.info("[ROVER DRIVE] Command: %s (X_12bit=%d, Y_12bit=%d)", cmd, raw_x_12, raw_y_12)

        self.last_buttons = buttons

    async def run(self):
        logging.info("Connecting to Poké Ball Plus at %s...", self.mac_address)
        async with BleakClient(self.mac_address) as client:
            self.client = client
            logging.info("Connected to Poké Ball Plus!")
            await client.start_notify(INPUT_UUID, self.notification_handler)
            logging.info("Listening for Poké Ball Plus telemetry & gestures. Press Ctrl+C to exit.")
            
            while True:
                await asyncio.sleep(1.0)

if __name__ == "__main__":
    driver = PokeballTeleopDriver()
    try:
        asyncio.run(driver.run())
    except KeyboardInterrupt:
        logging.info("Poké Ball Plus teleop driver stopped.")
