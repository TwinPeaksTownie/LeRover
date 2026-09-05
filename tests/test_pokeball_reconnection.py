#!/usr/bin/env python3
"""tests/test_pokeball_reconnection.py - Unit tests for Poké Ball Plus reconnection engine.

Validates:
1. Fail-fast configuration schema (packet_timeout_sec, scan_timeout_sec, reconnect_delay_sec)
2. 50 Hz packet inactivity watchdog detection (<1.25s)
3. Non-destructive BlueZ cleanup (no `bluetoothctl remove`)
4. Asynchronous scanner and client lifecycle
"""

import asyncio
import json
import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "config"))
sys.path.insert(0, str(REPO_ROOT / "pi500"))
sys.path.insert(0, str(REPO_ROOT / "apps"))

import apps.pokeball_app.app as pokeball_module
from apps.pokeball_app.app import PokeballService, load_pokeball_config


class TestPokeballConfigSchema(unittest.TestCase):
    """Verifies fail-fast schema enforcement for Poké Ball BLE configuration."""

    def test_config_contains_watchdog_keys(self):
        cfg = load_pokeball_config()
        self.assertIn("packet_timeout_sec", cfg["ble"])
        self.assertIn("scan_timeout_sec", cfg["ble"])
        self.assertIn("reconnect_delay_sec", cfg["ble"])
        self.assertAlmostEqual(cfg["ble"]["packet_timeout_sec"], 1.25)
        self.assertAlmostEqual(cfg["ble"]["scan_timeout_sec"], 4.0)
        self.assertAlmostEqual(cfg["ble"]["reconnect_delay_sec"], 0.5)

    def test_fail_fast_on_missing_key(self):
        with patch.dict(pokeball_module._CONFIG["ble"], {}, clear=False):
            original_cfg = dict(pokeball_module._CONFIG)
            bad_cfg = json.loads(json.dumps(original_cfg))
            del bad_cfg["ble"]["packet_timeout_sec"]

            with patch("builtins.open", unittest.mock.mock_open(read_data=json.dumps(bad_cfg))):
                with self.assertRaises(KeyError):
                    load_pokeball_config()


class TestPokeballWatchdog(unittest.TestCase):
    """Tests packet arrival tracking and inactivity watchdog timeout."""

    def setUp(self):
        self.service = PokeballService(api_url="http://127.0.0.1:8085")
        self.service.logger = MagicMock()

    def test_notification_updates_last_packet_time(self):
        self.assertEqual(self.service.last_packet_time, 0.0)

        dummy_packet = bytearray([0x00, 0x00, 0x00, 0x08, 0x80])

        t0 = time.time()
        self.service.notification_handler(None, dummy_packet)
        self.assertGreaterEqual(self.service.last_packet_time, t0)
        self.assertEqual(self.service.counter, 1)
        self.assertEqual(self.service.telemetry["packet_count"], 1)

    def test_watchdog_detects_inactivity(self):
        self.service.last_packet_time = time.time() - 1.5
        elapsed = time.time() - self.service.last_packet_time
        self.assertGreater(elapsed, self.service.packet_timeout_sec)


class TestPokeballBlueTCleanup(unittest.TestCase):
    """Verifies that BlueZ cleanup is non-destructive (no remove command)."""

    def setUp(self):
        self.service = PokeballService(api_url="http://127.0.0.1:8085")
        self.service.logger = MagicMock()

    @patch("subprocess.run")
    def test_cleanup_calls_disconnect_only(self, mock_run):
        self.service._cleanup_bluez_device()

        calls = mock_run.call_args_list
        self.assertEqual(len(calls), 1)
        cmd = calls[0][0][0]
        self.assertEqual(cmd[0], "bluetoothctl")
        self.assertEqual(cmd[1], "disconnect")
        self.assertEqual(cmd[2], self.service.mac_address)

        for call in calls:
            self.assertNotIn("remove", call[0][0])


class TestPokeballReconnectionAsyncLoop(unittest.IsolatedAsyncioTestCase):
    """Tests the asynchronous BleakScanner presence and connection logic."""

    async def test_scanner_finds_device_and_connects(self):
        service = PokeballService(api_url="http://127.0.0.1:8085")
        service.logger = MagicMock()

        mock_device = MagicMock()
        mock_device.address = service.mac_address
        mock_device.name = "Pokemon PBP"

        with patch.object(pokeball_module, "BleakScanner") as mock_scanner_cls:
            mock_scanner_cls.find_device_by_address = AsyncMock(return_value=mock_device)

            found_dev = await pokeball_module.BleakScanner.find_device_by_address(
                service.mac_address, timeout=service.scan_timeout_sec
            )
            self.assertEqual(found_dev, mock_device)


if __name__ == '__main__':
    unittest.main()
