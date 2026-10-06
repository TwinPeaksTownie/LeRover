import os
import time
import logging
from dataclasses import dataclass, field
from typing import Tuple, Dict

@dataclass(slots=True)
class JoyConState:
    timestamp: float
    buttons: Dict[str, bool] = field(default_factory=dict)
    stick_norm_x: float = 0.0
    stick_norm_y: float = 0.0
    accel: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    gyro: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    battery_level: int = 4
    # Raw values for testing/calibration if needed
    raw_stick_x: int = 0
    raw_stick_y: int = 0

class JoyConDriver:
    """Pure hardware abstraction for Joy-Con (R) HID."""

    def __init__(self, center_x: int, center_y: int, span_x: int, span_y: int, deadzone: float = 0.12):
        self.logger = logging.getLogger("so101.joycon_driver")
        self.center_x = center_x
        self.center_y = center_y
        self.span_x = span_x
        self.span_y = span_y
        self.deadzone = deadzone

        # For auto-zero
        self.auto_zero_samples = 30
        self.calib_samples_x = []
        self.calib_samples_y = []
        self.zero_calibrated = False
        self.min_calib_raw = center_x - 100
        self.max_calib_raw = center_x + 100

    @staticmethod
    def make_subcmd_packet(subcmd_id: int, subcmd_data: bytes, packet_num: int = 0) -> bytes:
        """Constructs an authoritative 49-byte Joy-Con Bluetooth output report (OUTPUT 0x01)."""
        buf = bytearray(49)
        buf[0] = 0x01  # OUTPUT 0x01: Subcommand with rumble
        buf[1] = packet_num & 0x0F  # Incremental packet counter
        buf[2:10] = bytes([0x00, 0x01, 0x40, 0x40, 0x00, 0x01, 0x40, 0x40])  # Neutral rumble
        buf[10] = subcmd_id
        for i, b in enumerate(subcmd_data):
            buf[11 + i] = b
        return bytes(buf)

    def init_joycon(self, fd: int, step_delay: float = 0.05) -> None:
        """Sends initialization subcommands to Joy-Con (R): enables 6-axis IMU and sets standard 60Hz 0x30 report mode."""
        try:
            # Subcommand 0x40 (Arg 0x01): Enable IMU sensors (exactly 49 bytes)
            report_imu = self.make_subcmd_packet(0x40, bytes([0x01]), packet_num=0)
            os.write(fd, report_imu)
            time.sleep(step_delay)
            # Subcommand 0x03 (Arg 0x30): Set standard full input report mode (exactly 49 bytes)
            report_mode = self.make_subcmd_packet(0x03, bytes([0x30]), packet_num=1)
            os.write(fd, report_mode)
            time.sleep(step_delay)
            # Subcommand 0x30 (Arg 0x01): Set Player 1 LED solid on rail to stop cycling sync lights (exactly 49 bytes)
            report_led = self.make_subcmd_packet(0x30, bytes([0x01]), packet_num=2)
            os.write(fd, report_led)
            time.sleep(step_delay)
            self.logger.info("Initialized Joy-Con (R) with 49-byte subcommands into 60Hz 0x30 report mode.")
        except OSError as e:
            self.logger.warning("Joy-Con initialization write warning on fd %d: %s (will dynamically decode 0x3F/0x30 reports)", fd, e)

    def process_report(self, raw: bytes) -> JoyConState | None:
        """Parses Joy-Con reports dynamically (supporting standard 49-byte Report 0x30 and 12-byte simple Report 0x3F)."""
        if len(raw) < 4:
            return None

        now = time.time()
        report_id = raw[0]
        state = JoyConState(timestamp=now)

        btn_dict = {
            "r": False, "zr": False, "sr": False, "sl": False,
            "a": False, "b": False, "x": False, "y": False,
            "plus": False, "home": False, "r_stick": False
        }

        norm_x, norm_y = 0.0, 0.0

        if report_id == 0x3F:
            # -----------------------------------------------------------------
            # Simple HID Mode (Report 0x3F)
            # -----------------------------------------------------------------
            b1 = raw[1]
            btn_dict["b"] = bool(b1 & 0x01)
            btn_dict["a"] = bool(b1 & 0x02)
            btn_dict["y"] = bool(b1 & 0x04)
            btn_dict["x"] = bool(b1 & 0x08)
            btn_dict["sl"] = bool(b1 & 0x10)
            btn_dict["sr"] = bool(b1 & 0x20)

            b2 = raw[2]
            btn_dict["plus"] = bool(b2 & 0x02)
            btn_dict["r_stick"] = bool(b2 & 0x08)
            btn_dict["home"] = bool(b2 & 0x10)
            btn_dict["r"] = bool(b2 & 0x40)
            btn_dict["zr"] = bool(b2 & 0x80)

            state.battery_level = 4

            hat = raw[3] if len(raw) > 3 else 8
            hat_map = {
                0: (0.0, 1.0), 1: (0.707, 0.707), 2: (1.0, 0.0), 3: (0.707, -0.707),
                4: (0.0, -1.0), 5: (-0.707, -0.707), 6: (-1.0, 0.0), 7: (-0.707, 0.707), 8: (0.0, 0.0),
            }
            norm_x, norm_y = hat_map.get(hat, (0.0, 0.0))

            if len(raw) >= 12 and (raw[4] != 0 or raw[5] != 0 or raw[6] != 0):
                raw_r_x = raw[4] | ((raw[5] & 0x0F) << 8)
                raw_r_y = (raw[5] >> 4) | (raw[6] << 4)
                if raw_r_x != 0 or raw_r_y != 0:
                    dx = raw_r_x - self.center_x
                    dy = raw_r_y - self.center_y
                    raw_norm_x = max(-1.0, min(1.0, dx / self.span_x))
                    raw_norm_y = max(-1.0, min(1.0, dy / self.span_y))
                    if abs(raw_norm_x) <= self.deadzone:
                        norm_x = 0.0
                    else:
                        sign_x = 1.0 if raw_norm_x > 0 else -1.0
                        norm_x = sign_x * ((abs(raw_norm_x) - self.deadzone) / (1.0 - self.deadzone))
                    if abs(raw_norm_y) <= self.deadzone:
                        norm_y = 0.0
                    else:
                        sign_y = 1.0 if raw_norm_y > 0 else -1.0
                        norm_y = sign_y * ((abs(raw_norm_y) - self.deadzone) / (1.0 - self.deadzone))

        else:
            # -----------------------------------------------------------------
            # Standard Full Mode (Report 0x30 / 0x21)
            # -----------------------------------------------------------------
            if len(raw) < 12:
                return None
            bat_raw = raw[2]
            state.battery_level = (bat_raw >> 5) & 0x07

            b3 = raw[3]
            btn_dict["y"] = bool(b3 & 0x01)
            btn_dict["x"] = bool(b3 & 0x02)
            btn_dict["b"] = bool(b3 & 0x04)
            btn_dict["a"] = bool(b3 & 0x08)
            btn_dict["sr"] = bool(b3 & 0x10)
            btn_dict["sl"] = bool(b3 & 0x20)
            btn_dict["r"] = bool(b3 & 0x40)
            btn_dict["zr"] = bool(b3 & 0x80)

            b4 = raw[4]
            btn_dict["plus"] = bool(b4 & 0x02)
            btn_dict["r_stick"] = bool(b4 & 0x04)
            btn_dict["home"] = bool(b4 & 0x10)

            raw_r_x = raw[9] | ((raw[10] & 0x0F) << 8)
            raw_r_y = (raw[10] >> 4) | (raw[11] << 4)
            state.raw_stick_x = raw_r_x
            state.raw_stick_y = raw_r_y

            if not self.zero_calibrated:
                if not (btn_dict["r"] or btn_dict["zr"] or btn_dict["a"] or btn_dict["b"]):
                    if self.min_calib_raw <= raw_r_x <= self.max_calib_raw and self.min_calib_raw <= raw_r_y <= self.max_calib_raw:
                        self.calib_samples_x.append(raw_r_x)
                        self.calib_samples_y.append(raw_r_y)
                        if len(self.calib_samples_x) >= self.auto_zero_samples:
                            self.center_x = int(sum(self.calib_samples_x) / len(self.calib_samples_x))
                            self.center_y = int(sum(self.calib_samples_y) / len(self.calib_samples_y))
                            self.zero_calibrated = True
                            self.logger.info("🎯 Joy-Con (R) stick auto-zero calibrated: center_x=%d, center_y=%d", self.center_x, self.center_y)

            dx = raw_r_x - self.center_x
            dy = raw_r_y - self.center_y

            raw_norm_x = max(-1.0, min(1.0, dx / self.span_x))
            raw_norm_y = max(-1.0, min(1.0, dy / self.span_y))

            if abs(raw_norm_x) <= self.deadzone:
                norm_x = 0.0
            else:
                sign_x = 1.0 if raw_norm_x > 0 else -1.0
                norm_x = sign_x * ((abs(raw_norm_x) - self.deadzone) / (1.0 - self.deadzone))

            if abs(raw_norm_y) <= self.deadzone:
                norm_y = 0.0
            else:
                sign_y = 1.0 if raw_norm_y > 0 else -1.0
                norm_y = sign_y * ((abs(raw_norm_y) - self.deadzone) / (1.0 - self.deadzone))

            # TODO: Extract IMU data correctly if needed
            if len(raw) >= 49:
                pass # IMU extraction would go here if not done downstream

        state.buttons = btn_dict
        state.stick_norm_x = norm_x
        state.stick_norm_y = norm_y

        return state
