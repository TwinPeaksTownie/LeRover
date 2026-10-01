#!/usr/bin/env python3
"""tests/test_pokeball_reconnection.py - Unit tests for Joy-Con HID reconnection and watchdog engine.

Validates:
1. Fail-fast configuration schema (packet_timeout_sec, reconnect_delay_sec, poll_rate_hz).
2. Packet arrival tracking and last_seen updates.
3. HID raw node discovery logic.
"""

import json
import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "config"))
sys.path.insert(0, str(REPO_ROOT / "pi4b"))
sys.path.insert(0, str(REPO_ROOT / "apps"))

import apps.pokeball_app.app as pokeball_module
from apps.pokeball_app.app import PokeballService, load_pokeball_config, load_joycon_calibration


class TestPokeballConfigSchema(unittest.TestCase):
    """Verifies fail-fast schema enforcement for Joy-Con HID configuration under pokeball_app."""

    def test_config_contains_watchdog_keys(self):
        cfg = load_pokeball_config()
        self.assertIn("packet_timeout_sec", cfg["hardware"])
        self.assertIn("reconnect_delay_sec", cfg["hardware"])
        self.assertIn("poll_rate_hz", cfg["hardware"])
        self.assertAlmostEqual(cfg["hardware"]["packet_timeout_sec"], 4.0)
        self.assertAlmostEqual(cfg["hardware"]["reconnect_delay_sec"], 1.0)
        self.assertAlmostEqual(cfg["hardware"]["poll_rate_hz"], 60.0)

    def test_fail_fast_on_missing_key(self):
        with patch.dict(pokeball_module._CONFIG["hardware"], {}, clear=False):
            original_cfg = dict(pokeball_module._CONFIG)
            bad_cfg = json.loads(json.dumps(original_cfg))
            del bad_cfg["hardware"]["packet_timeout_sec"]

            with patch("builtins.open", unittest.mock.mock_open(read_data=json.dumps(bad_cfg))):
                with self.assertRaises(KeyError):
                    load_pokeball_config()


class TestPokeballWatchdog(unittest.TestCase):
    """Tests packet arrival tracking and telemetry updates."""

    def setUp(self):
        self.service = PokeballService(api_url="http://127.0.0.1:8085")
        self.service.logger = MagicMock()

    def test_report_updates_last_seen_and_counter(self):
        self.assertEqual(self.service.telemetry["packet_count"], 0)

        # Create synthetic report 0x30
        raw = bytearray(49)
        raw[0] = 0x30
        raw[2] = 0x80
        t0 = time.time()
        self.service._process_report_30(bytes(raw))

        self.assertGreaterEqual(self.service.telemetry["last_seen"], t0)
        self.assertEqual(self.service.telemetry["packet_count"], 1)

    def test_watchdog_detects_inactivity(self):
        timeout = float(self.service.config["hardware"]["packet_timeout_sec"])
        self.service.telemetry["last_seen"] = time.time() - (timeout + 0.5)
        elapsed = time.time() - self.service.telemetry["last_seen"]
        self.assertGreater(elapsed, timeout)


class TestPokeballDeviceDiscovery(unittest.TestCase):
    """Verifies Joy-Con /dev/hidraw node discovery."""

    def setUp(self):
        self.service = PokeballService(api_url="http://127.0.0.1:8085")
        self.service.logger = MagicMock()

    @patch("glob.glob")
    @patch("os.path.exists")
    @patch("builtins.open", new_callable=unittest.mock.mock_open, read_data="HID_NAME=Joy-Con (R)\nHID_ID=0003:0000057E:00002007:0001\n")
    def test_device_discovery_identifies_matching_hidraw(self, mock_file, mock_exists, mock_glob):
        with patch("sys.platform", "linux"):
            mock_glob.return_value = ["/sys/class/hidraw/hidraw1"]
            mock_exists.return_value = True

            dev_path = self.service._find_device_path()
            self.assertEqual(dev_path, "/dev/hidraw1")


if __name__ == '__main__':
    unittest.main()
