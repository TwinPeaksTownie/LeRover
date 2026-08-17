#!/usr/bin/env python3
"""Read-only hardware diagnostic utility for Feetech serial bus (Motors 1-8).
Performs non-destructive position and telemetry reads on /dev/ttyACM0.
"""

import argparse
import sys
import time
from pathlib import Path

# Add pi500 module path for AuxiliaryServoController import
pi500_path = Path(__file__).parent.parent / "pi500"
if str(pi500_path) not in sys.path:
    sys.path.insert(0, str(pi500_path))

try:
    from aux_servo_controller import AuxiliaryServoController
except ImportError:
    AuxiliaryServoController = None


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only SO-101 Serial Bus Telemetry Scanner")
    parser.add_argument("--port", default="/dev/ttyACM0", help="Serial port (default: /dev/ttyACM0)")
    args = parser.parse_args()

    print(f"Scanning serial bus on {args.port} (Read-Only)...")
    if not AuxiliaryServoController:
        print("Error: AuxiliaryServoController module not found in pi500/ directory.")
        sys.exit(1)

    ctrl = AuxiliaryServoController(port=args.port)
    if not ctrl.connect():
        print(f"Failed to open serial port {args.port}")
        sys.exit(1)

    print("\n--- Motor Telemetry Summary ---")
    try:
        for sid in range(1, 9):
            pos = ctrl.read_position(sid)
            vol = ctrl.read_voltage(sid)
            temp = ctrl.read_temperature(sid)
            status = f"POS: {pos:4d} | VOLT: {vol/10.0:4.1f}V | TEMP: {temp:2d}C" if pos is not None else "NO RESPONSE"
            print(f"Servo {sid}: {status}")
    finally:
        ctrl.close()
        print("\nScan completed.")


if __name__ == "__main__":
    main()
