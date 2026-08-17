# Repository Diagnostic Tools (`tools/`)

This directory contains version-controlled, **strictly read-only** hardware diagnostic tools for the SO-101 robot and auxiliary servo system.

## Strict Tool Guidelines
- **Zero EEPROM Writes**: Tools in this directory MUST NEVER call `set_position_offset()` or write to EEPROM Registers 31, 32, 55, or 8.
- **Read-Only Telemetry**: Tools are designed for inspecting motor positions, voltage levels, temperature, and serial bus connectivity without altering motor states or calibration data.

## Available Diagnostic Utilities
- `read_bus_telemetry.py`: Scans serial bus `/dev/ttyACM0`, pings Servos 1–8, and outputs current positions, voltages, and connection statuses.
