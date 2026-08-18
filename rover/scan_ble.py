#!/usr/bin/env python3
"""Scans for nearby BLE devices, particularly Poké Ball Plus."""

import asyncio
import sys

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from bleak import BleakScanner

async def scan():
    print("Scanning for BLE devices (10 seconds)...")
    print("TIP: Press the Top Red Button or Stick Click on the Poké Ball Plus so the LED flashes!")
    devices = await BleakScanner.discover(timeout=10.0, return_adv=True)
    print(f"\nFound {len(devices)} BLE devices:\n")
    for d, adv in devices.values():
        name = d.name or adv.local_name or "Unknown"
        is_pokeball = "Pokemon" in name or "Poke" in name or d.address.upper() == "58:2F:40:8D:50:71"
        prefix = "--> [POKEBALL DETECTED!]" if is_pokeball else "   "
        print(f"{prefix} Address: {d.address} | Name: {name} | RSSI: {adv.rssi} dBm")

if __name__ == "__main__":
    asyncio.run(scan())
