#!/usr/bin/env python3
"""
Auxiliary Servo Controller for Feetech STS3215 / SCS Servos (IDs 7 & 8).
Enforces direct raw 12-bit tick control (0-4095) with explicit bus mutexing
to prevent serial packet corruption and runaway rotation.
"""

import time
import serial
import threading
import logging

logging.basicConfig(level=logging.INFO)

class AuxiliaryServoController:
    def __init__(self, port: str = "/dev/ttyACM0", baudrate: int = 1000000, bus_lock: threading.Lock = None, ser: serial.Serial = None):
        self.port = port
        self.baudrate = baudrate
        self.ser = ser
        self.bus_lock = bus_lock if bus_lock is not None else threading.Lock()
        if self.ser is None:
            self.connect()

    def connect(self):
        with self.bus_lock:
            if self.ser is None or not self.ser.is_open:
                self.ser = serial.Serial(self.port, self.baudrate, timeout=0.1)
                self.ser.reset_input_buffer()
                self.ser.reset_output_buffer()
                logging.info(f"Auxiliary Servo Controller connected on {self.port} @ {self.baudrate} baud.")

    def disconnect(self):
        with self.bus_lock:
            if self.ser and self.ser.is_open:
                self.ser.close()
                logging.info("Auxiliary Servo Controller port closed.")

    def _send_and_read(self, pkt: list, expected_res_len: int = 6):
        target_id = pkt[2]
        checksum = (~sum(pkt[2:])) & 0xFF
        pkt.append(checksum)
        pkt_bytes = bytes(pkt)
        
        self.ser.reset_input_buffer()
        self.ser.write(pkt_bytes)
        time.sleep(0.015)
        
        raw = self.ser.read(self.ser.in_waiting or 64)
        if not raw:
            return None
        
        # Strip echo if half-duplex UART echoes sent packet
        if len(raw) >= len(pkt_bytes) and raw[:len(pkt_bytes)] == pkt_bytes:
            raw = raw[len(pkt_bytes):]
            
        for i in range(len(raw) - expected_res_len + 1):
            if raw[i] == 0xFF and raw[i+1] == 0xFF and (raw[i+2] == target_id or target_id == 0xFE):
                return raw[i:i+expected_res_len]
        return None

    def read_pos(self, servo_id: int) -> int:
        """Reads 12-bit position (0..4095) for specified servo ID in single-turn mode."""
        with self.bus_lock:
            pkt = [0xFF, 0xFF, servo_id, 4, 2, 56, 2] # Reg 56 (Present_Position), 2 bytes
            resp = self._send_and_read(pkt, expected_res_len=7)
            if resp and len(resp) >= 7 and resp[2] == servo_id:
                val_l = resp[5]
                val_h = resp[6]
                return val_l + (val_h << 8)
            return None

    def get_position_multiturn(self, servo_id: int) -> int:
        """
        Reads Reg 56-57 (Present Position).
        In Mode 3 (Multi-Turn), returns signed 16-bit position (-32767..+32767).
        Feetech uses Sign-Magnitude representation for negative numbers (Bit 15 is sign).
        """
        with self.bus_lock:
            pkt = [0xFF, 0xFF, servo_id, 4, 2, 56, 2]
            resp = self._send_and_read(pkt, expected_res_len=7)
            if resp and len(resp) >= 7 and resp[2] == servo_id:
                pos = resp[5] | (resp[6] << 8)
                if pos & 0x8000:
                    return -(pos & 0x7FFF)
                return pos
            return None

    def read_voltage(self, servo_id: int) -> float:
        """Reads Present Voltage (Reg 62) in Volts."""
        with self.bus_lock:
            pkt = [0xFF, 0xFF, servo_id, 4, 2, 62, 1]
            resp = self._send_and_read(pkt, expected_res_len=7)
            if resp and len(resp) >= 6 and resp[2] == servo_id:
                return resp[5] / 10.0
            return None

    def set_torque(self, servo_id: int, enable: bool, max_torque_enable: int = 1000):
        """Enables (True) or disables (False) torque for specified servo ID."""
        with self.bus_lock:
            max_t = max_torque_enable if enable else 0
            val_l = max_t & 0xFF
            val_h = (max_t >> 8) & 0xFF
            pkt_mt = [0xFF, 0xFF, servo_id, 5, 3, 48, val_l, val_h] # Reg 48 (RAM Torque_Limit)
            self._send_and_read(pkt_mt, expected_res_len=6)

            val = 1 if enable else 0
            pkt = [0xFF, 0xFF, servo_id, 4, 3, 40, val] # Reg 40 (Torque_Enable)
            self._send_and_read(pkt, expected_res_len=6)

    def setup_multi_turn_mode(self, servo_id: int):
        """
        Configures STS3215 for Rack & Pinion linear rail (Mode 3).
        Unlocks EEPROM, sets Mode 3 (Reg 33=3), clears angle limits (Reg 9-12=0), re-locks EEPROM.
        Must be done with torque OFF.
        """
        with self.bus_lock:
            # 1. Torque OFF
            self._send_and_read([0xFF, 0xFF, servo_id, 4, 3, 40, 0], expected_res_len=6)
            # 2. Unlock EEPROM (Reg 55 = 0)
            self._send_and_read([0xFF, 0xFF, servo_id, 4, 3, 55, 0], expected_res_len=6)
            # 3. Clear Angle Limits (Reg 9-12 = 0)
            self._send_and_read([0xFF, 0xFF, servo_id, 7, 3, 9, 0, 0, 0, 0], expected_res_len=6)
            # 4. Restore Alarm LED (Reg 35 = 7)
            self._send_and_read([0xFF, 0xFF, servo_id, 4, 3, 35, 7], expected_res_len=6)
            # 5. Mode 3 (Multi-Turn Position Control / Step Mode) (Reg 33 = 3)
            self._send_and_read([0xFF, 0xFF, servo_id, 4, 3, 33, 3], expected_res_len=6)
            # 6. Lock EEPROM (Reg 55 = 1)
            self._send_and_read([0xFF, 0xFF, servo_id, 4, 3, 55, 1], expected_res_len=6)
            logging.info(f"Servo {servo_id} successfully configured for Multi-Turn Mode (Mode 3).")

    def set_position_multiturn(self, servo_id: int, target_ticks: int, speed: int = 1500):
        """
        Writes 16-bit signed multi-turn target ticks using strict Feetech Sign-Magnitude.
        Sends Reg 42 (Goal Position), Reg 44 (Time=0), and Reg 46 (Goal Speed) in a single packet write.
        """
        target_ticks = max(-32768, min(32767, int(target_ticks)))
        
        # Feetech Sign-Magnitude: Bit 15 is the sign bit.
        if target_ticks < 0:
            raw_val = abs(target_ticks) | 0x8000
        else:
            raw_val = target_ticks
            
        pos_L = raw_val & 0xFF
        pos_H = (raw_val >> 8) & 0xFF
        spd_L = speed & 0xFF
        spd_H = (speed >> 8) & 0xFF
        
        with self.bus_lock:
            pkt = [0xFF, 0xFF, servo_id, 9, 3, 42, pos_L, pos_H, 0, 0, spd_L, spd_H]
            return self._send_and_read(pkt, expected_res_len=6)

    def set_max_torque(self, servo_id: int, max_torque: int = 1000):
        """Sets RAM Torque Limit (Reg 48, 0..1000)."""
        with self.bus_lock:
            val_l = max_torque & 0xFF
            val_h = (max_torque >> 8) & 0xFF
            pkt = [0xFF, 0xFF, servo_id, 5, 3, 48, val_l, val_h] # Reg 48 (RAM Torque_Limit)
            self._send_and_read(pkt, expected_res_len=6)

    def set_position_offset(self, servo_id: int, offset: int):
        """Sets EEPROM Position Offset (Reg 31-32, 0..4095) for specified servo ID."""
        offset = max(0, min(4095, int(offset)))
        val_l = offset & 0xFF
        val_h = (offset >> 8) & 0xFF
        with self.bus_lock:
            # Unlock EEPROM (Reg 47 = 0)
            self._send_and_read([0xFF, 0xFF, servo_id, 4, 3, 47, 0], expected_res_len=6)
            # Write Reg 31-32
            pkt = [0xFF, 0xFF, servo_id, 5, 3, 31, val_l, val_h]
            self._send_and_read(pkt, expected_res_len=6)
            # Lock EEPROM (Reg 47 = 1)
            self._send_and_read([0xFF, 0xFF, servo_id, 4, 3, 47, 1], expected_res_len=6)
            logging.info(f"Servo {servo_id}: Position offset set to {offset} ticks.")

    def write_wheel_speed(self, servo_id: int, speed: int):
        """Drives motor in Wheel Mode (Mode 1) at specified speed (-1000..1000)."""
        with self.bus_lock:
            # Set Torque Limit Reg 48 = 1000 (0x03E8)
            self._send_and_read([0xFF, 0xFF, servo_id, 5, 3, 48, 0xE8, 0x03], expected_res_len=6)
            # Enable Torque Reg 40 = 1
            self._send_and_read([0xFF, 0xFF, servo_id, 4, 3, 40, 1], expected_res_len=6)
            
            if speed >= 0:
                val = min(1000, speed)
            else:
                val = (1 << 15) | min(1000, abs(speed))
                
            vl = val & 0xFF
            vh = (val >> 8) & 0xFF
            pkt_sp = [0xFF, 0xFF, servo_id, 5, 3, 46, vl, vh] # Reg 46 (Goal_Speed)
            self._send_and_read(pkt_sp, expected_res_len=6)

    def write_goal_raw(self, servo_id: int, target_tick: int, speed: int = 0, goal_time: int = 0):
        """Writes raw goal position tick, goal time, and goal speed in a single consolidated serial packet."""
        target_tick = max(0, min(65535, int(target_tick)))
        val_l = target_tick & 0xFF
        val_h = (target_tick >> 8) & 0xFF
        gt_l = goal_time & 0xFF
        gt_h = (goal_time >> 8) & 0xFF
        sp_l = speed & 0xFF
        sp_h = (speed >> 8) & 0xFF
        
        with self.bus_lock:
            # Single multi-register packet write: Reg 42 (Position L, H), Reg 44 (Time L, H), Reg 46 (Speed L, H)
            pkt = [0xFF, 0xFF, servo_id, 9, 3, 42, val_l, val_h, gt_l, gt_h, sp_l, sp_h]
            self._send_and_read(pkt, expected_res_len=6)

    def write_goal_safe(self, servo_id: int, target_tick: int, speed: int = 0, goal_time: int = 0, max_step: int = 150):
        """Writes target tick, stepping safely across 4095/0 if needed to prevent runaway."""
        target_tick = max(0, min(4095, int(target_tick)))
        curr_pos = self.read_pos(servo_id)
        if curr_pos is None:
            self.write_goal_raw(servo_id, target_tick, speed=speed, goal_time=goal_time)
            return

        diff = (target_tick - curr_pos) % 4096
        if diff > 2048:
            diff -= 4096

        if abs(diff) <= max_step:
            self.write_goal_raw(servo_id, target_tick, speed=speed, goal_time=goal_time)
            return

        steps = int(abs(diff) / max_step) + 1
        step_delta = diff / float(steps)
        curr = float(curr_pos)

        for i in range(1, steps + 1):
            curr = (curr + step_delta) % 4096
            step_target = int(round(curr)) % 4096
            self.write_goal_raw(servo_id, step_target, speed=speed, goal_time=goal_time)
            time.sleep(0.02)


