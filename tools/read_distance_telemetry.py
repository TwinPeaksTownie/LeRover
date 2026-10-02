#!/usr/bin/env python3
"""Live Distance Sensor Telemetry Reader.
Reads real-time 100ms STAT telemetry from Adafruit KB2040 on Raspberry Pi.
Converts raw 16-bit ADC values to voltage and physical distance metrics.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, Any
import serial


def load_json_configs(base_path: Path) -> Dict[str, Any]:
    """Loads rover and network configurations with direct bracket access."""
    rover_cfg_path = base_path / "config" / "rover_config.json"
    net_cfg_path = base_path / "config" / "network_config.json"

    with open(rover_cfg_path, "r", encoding="utf-8") as f:
        rover_cfg = json.load(f)

    with open(net_cfg_path, "r", encoding="utf-8") as f:
        net_cfg = json.load(f)

    return {
        "port": net_cfg["hardware"]["rover_serial_port"],
        "baudrate": net_cfg["hardware"]["rover_baudrate"],
        "sensor": rover_cfg["distance_sensor"],
        "hardware_interface": rover_cfg["hardware_interface"],
    }


def render_bar(distance_mm: float, max_mm: float, bar_width: int = 30) -> str:
    """Renders a simple ASCII/Unicode visual bar for distance."""
    clamped = max(0.0, min(max_mm, distance_mm))
    fill_ratio = clamped / max_mm
    filled = int(fill_ratio * bar_width)
    return "█" * filled + "░" * (bar_width - filled)


def main() -> None:
    parser = argparse.ArgumentParser(description="Live 100ms Distance Sensor Telemetry Reader")
    parser.add_argument("--port", default=None, help="Explicit serial port override (e.g. /dev/ttyACM0)")
    parser.add_argument("--raw-stream", action="store_true", help="Print raw line stream instead of formatted dashboard")
    parser.add_argument("--samples", type=int, default=0, help="Exit after N samples (0 = run indefinitely)")
    args = parser.parse_args()

    # Locate base directory
    base_dir = Path(__file__).resolve().parent.parent
    config = load_json_configs(base_dir)

    sensor_cfg = config["sensor"]
    model_name = sensor_cfg["model"]
    adc_bits = sensor_cfg["adc_resolution_bits"]
    max_volts = float(sensor_cfg["max_volts"])
    max_distance_mm = float(sensor_cfg["max_distance_mm"])
    adc_max_count = (1 << adc_bits) - 1

    port = args.port or config["port"]
    # Fallback to /dev/ttyACM0 if symlink doesn't exist
    if not os.path.exists(port) and os.path.exists("/dev/ttyACM0"):
        port = "/dev/ttyACM0"

    print(f"\n=======================================================")
    print(f"  KB2040 Live Distance Telemetry Reader")
    print(f"  Port: {port} @ {config['baudrate']} baud")
    print(f"  Sensor Model: {model_name}")
    print(f"  ADC Resolution: {adc_bits}-bit (0-{adc_max_count}) | Scale: 0.0-{max_volts:.1f}V -> 0-{max_distance_mm:.0f}mm")
    print(f"=======================================================\n")

    try:
        ser = serial.Serial(port, baudrate=config["baudrate"], timeout=0.5)
        if config["hardware_interface"]["assert_dtr"]:
            ser.dtr = True
        if config["hardware_interface"]["assert_rts"]:
            ser.rts = True
    except Exception as exc:
        print(f"ERROR: Failed to open serial port {port}: {exc}", file=sys.stderr, flush=True)
        sys.exit(1)

    min_raw = adc_max_count
    max_raw = 0
    sample_count = 0
    last_time = time.time()

    is_tty = sys.stdout.isatty() and not args.raw_stream

    try:
        while True:
            line_bytes = ser.readline()
            if not line_bytes:
                continue

            line = line_bytes.decode("utf-8", errors="ignore").strip()
            if not line.startswith("STAT:"):
                continue

            now = time.time()
            dt_ms = (now - last_time) * 1000.0
            last_time = now

            parts = line[5:].split(",")
            if len(parts) < 9:
                continue

            mode = parts[0]
            raw_dist = int(parts[8])

            min_raw = min(min_raw, raw_dist)
            max_raw = max(max_raw, raw_dist)

            volts = (raw_dist / float(adc_max_count)) * max_volts
            distance_mm = (raw_dist / float(adc_max_count)) * max_distance_mm
            distance_cm = distance_mm / 10.0
            distance_in = distance_mm / 25.4

            bar = render_bar(distance_mm, max_distance_mm, bar_width=25)

            sample_count += 1

            if args.raw_stream:
                print(f"[{now:.3f}] RAW={raw_dist:5d} | {volts:.3f}V | {distance_cm:5.1f} cm ({distance_in:4.1f} in) | {line}", flush=True)
            elif is_tty:
                # ANSI cursor overwrite for clean in-place terminal updates
                sys.stdout.write(
                    f"\r\033[K"
                    f"[{dt_ms:4.0f}ms] "
                    f"Raw: {raw_dist:5d} ({volts:.3f}V) | "
                    f"Dist: {distance_cm:5.1f} cm ({distance_in:4.1f} in) | "
                    f"[{bar}] | "
                    f"Min: {min_raw:5d} Max: {max_raw:5d} (Δ {max_raw - min_raw:4d}) | "
                    f"Mode: {mode}"
                )
                sys.stdout.flush()
            else:
                print(
                    f"Sample {sample_count:04d} (+{dt_ms:3.0f}ms): "
                    f"Raw={raw_dist:5d} | {volts:5.3f}V | "
                    f"Distance: {distance_cm:5.1f} cm ({distance_in:4.1f} in) | "
                    f"Bar: [{bar}] | Min/Max: {min_raw}/{max_raw}",
                    flush=True
                )

            if args.samples > 0 and sample_count >= args.samples:
                break

    except KeyboardInterrupt:
        print("\n\nTelemetry reader stopped by user.")
    finally:
        ser.close()


if __name__ == "__main__":
    main()
