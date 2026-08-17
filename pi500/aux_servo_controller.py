#!/usr/bin/env python3
"""
Auxiliary Servo Controller for Feetech STS3215 / SCS Servos (IDs 7 & 8).
Pure byte codec enforcing direct raw 12-bit tick control (0-4095) with explicit
bus mutexing to prevent serial packet corruption and serial bus delays.
"""

import time
import serial
import threading
import logging

logging.basicConfig(level=logging.INFO)


class AuxiliaryServoController:
    def __init__(self, port: str = "/dev/ttyACM0", baudrate: int = 1000000, bus_lock: threading.RLock = None, ser: serial.Serial = None):
        self.port = port
        self.baudrate = baudrate
        self.ser = ser
        self.bus_lock = bus_lock if bus_lock is not None else threading.RLock()
        if self.ser is None:
            self.connect()

    def connect(self):
        with self.bus_lock:
            if self.ser is None or not self.ser.is_open:
                self.ser = serial.Serial(self.port, self.baudrate, timeout=0.03)
                self.ser.reset_input_buffer()
                self.ser.reset_output_buffer()
                logging.info(f"Auxiliary Servo Controller connected on {self.port} @ {self.baudrate} baud.")

    def disconnect(self):
        with self.bus_lock:
            if self.ser and self.ser.is_open:
                self.ser.close()
                logging.info("Auxiliary Servo Controller port closed.")

    def _send_and_read(self, pkt: list, expected_res_len: int = 6, retries: int = 2):
        target_id = pkt[2]
        checksum = (~sum(pkt[2:])) & 0xFF
        pkt_to_send = pkt + [checksum]
        pkt_bytes = bytes(pkt_to_send)

        for attempt in range(retries + 1):
            if hasattr(self.ser, "reset_input_buffer"):
                self.ser.reset_input_buffer()
                self.ser.reset_output_buffer()
            self.ser.write(pkt_bytes)
            self.ser.flush()

            raw = bytearray()
            start_time = time.monotonic()
            # Fast non-blocking polling using serial buffer without arbitrary thread sleep
            while (time.monotonic() - start_time) < 0.025:
                if self.ser.in_waiting > 0:
                    raw.extend(self.ser.read(self.ser.in_waiting))

                    # Strip exact echo if half-duplex UART echoes sent packet
                    data = bytes(raw)
                    if len(data) >= len(pkt_bytes) and data[:len(pkt_bytes)] == pkt_bytes:
                        data = data[len(pkt_bytes):]

                    for i in range(len(data) - 5):
                        if data[i] == 0xFF and data[i+1] == 0xFF and (data[i+2] == target_id or target_id == 0xFE):
                            if len(data) >= i + len(pkt_bytes) and data[i : i + len(pkt_bytes)] == pkt_bytes:
                                continue
                            pkt_len = data[i+3]
                            total_expected = 4 + pkt_len
                            if expected_res_len and total_expected != expected_res_len:
                                continue
                            if len(data) >= i + total_expected:
                                calc_chk = (~sum(data[i+2 : i+3+pkt_len])) & 0xFF
                                if calc_chk == data[i+3+pkt_len]:
                                    return data[i : i+total_expected]
                else:
                    time.sleep(0.0005)

        return None

    def read_pos(self, servo_id: int) -> int:
        """Reads 12-bit position (0..4095) for specified servo ID in single-turn mode."""
        with self.bus_lock:
            pkt = [0xFF, 0xFF, servo_id, 4, 2, 56, 2] # Reg 56 (Present_Position), 2 bytes
            resp = self._send_and_read(pkt, expected_res_len=8)
            if resp and len(resp) >= 8 and resp[2] == servo_id:
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
            resp = self._send_and_read(pkt, expected_res_len=8)
            if resp and len(resp) >= 8 and resp[2] == servo_id:
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
            if resp and len(resp) >= 7 and resp[2] == servo_id:
                return resp[5] / 10.0
            return None

    def flush_buffers(self):
        """Purges input and output serial buffers on /dev/ttyACM0."""
        with self.bus_lock:
            if self.ser and hasattr(self.ser, "reset_input_buffer"):
                try:
                    self.ser.reset_input_buffer()
                    self.ser.reset_output_buffer()
                except Exception:
                    pass

    def clear_alarms(self, servo_id: int):
        """Purges serial buffers without modifying registers or forcing torque."""
        with self.bus_lock:
            if hasattr(self.ser, "reset_input_buffer"):
                self.ser.reset_input_buffer()

    def set_torque(self, servo_id: int, enable: bool, max_torque_enable: int = 1000):
        """Enables (True) or disables (False) torque for specified servo ID using volatile RAM registers."""
        with self.bus_lock:
            max_t = max_torque_enable if enable else 0
            val_l = max_t & 0xFF
            val_h = (max_t >> 8) & 0xFF
            pkt_mt = [0xFF, 0xFF, servo_id, 5, 3, 48, val_l, val_h] # Reg 48 (RAM Torque_Limit)
            self._send_and_read(pkt_mt, expected_res_len=6)

            val = 1 if enable else 0
            pkt = [0xFF, 0xFF, servo_id, 4, 3, 40, val] # Reg 40 (Torque_Enable)
            self._send_and_read(pkt, expected_res_len=6)

    def set_position_multiturn(self, servo_id: int, target_ticks: int, speed: int = 1500):
        """
        Writes 16-bit multi-turn target ticks for Motor 8 using Feetech Sign-Magnitude encoding.
        Sends Reg 42 (Goal Position), Reg 44 (Time=0), and Reg 46 (Goal Speed) in a single packet.
        """
        target_ticks = max(-32768, min(32767, int(target_ticks)))

        # Feetech Sign-Magnitude: Bit 15 is the sign bit (0x8000)
        if target_ticks < 0:
            raw_val = abs(target_ticks) | 0x8000
        else:
            raw_val = target_ticks & 0x7FFF

        pos_L = raw_val & 0xFF
        pos_H = (raw_val >> 8) & 0xFF

        # Speed limit masking (Bit 15 forced to 0 to prevent Wheel Mode direction override)
        speed_val = max(0, min(1000, int(speed))) & 0x7FFF
        spd_L = speed_val & 0xFF
        spd_H = (speed_val >> 8) & 0xFF

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
        """Prohibited per Lesson 11: Hardware EEPROM writes (Reg 31/32/55) are strictly forbidden at runtime."""
        raise PermissionError("Hardware EEPROM writes prohibited per Lesson 11 directive. Use software calibration files.")

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
            return self._send_and_read(pkt, expected_res_len=6)
