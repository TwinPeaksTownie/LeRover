#!/usr/bin/env python3
import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "pi500"))

from robot_backend import RobotBackend, ticks_to_degrees_s7, degrees_to_ticks_s7

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

def main():
    print("Testing software math...")
    assert ticks_to_degrees_s7(2048, center_ticks=2048) == 0.0
    assert degrees_to_ticks_s7(0.0, center_ticks=2048) == 2048
    assert ticks_to_degrees_s7(1024, center_ticks=1024) == 0.0
    assert degrees_to_ticks_s7(0.0, center_ticks=1024) == 1024
    print("Software math tests passed!")

    print("Connecting RobotBackend...")
    backend = RobotBackend()
    backend.connect()
    print(f"Backend connected: hardware_active={backend.hardware_active}")
    print(f"Aux positions: {backend.aux_positions}")
    print(f"Raw positions: {backend.raw_positions}")
    print(f"Gantry position: {backend.gantry_position}")
    if 7 in backend.aux_positions and backend.aux_positions[7] is not None:
        c7 = backend.aux_calibration.get("7", {}).get("center_ticks", 2048)
        print(f"Servo 7 angle: {ticks_to_degrees_s7(backend.aux_positions[7], center_ticks=c7)} deg (relative to center {c7})")
    backend.close()
    print("Verification completed successfully.")

if __name__ == "__main__":
    main()
