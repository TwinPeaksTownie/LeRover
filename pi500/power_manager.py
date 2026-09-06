#!/usr/bin/env python3
"""Single-responsibility BusPowerManager module for SO-101 robot hardware.
Monitors 12V bus voltage, manages connection state machine (CONNECTED, DISCONNECTED, RE-SYNCHING),
and triggers automated recovery protocols upon power restoration.
"""

import json
import logging
from pathlib import Path
import threading
import time
from typing import Optional, Callable


def get_power_config_path() -> Path:
    p1 = Path(__file__).resolve().parent.parent / "config" / "power_config.json"
    if p1.exists():
        return p1
    p2 = Path.home() / "so101" / "config" / "power_config.json"
    if p2.exists():
        return p2
    p3 = Path("/home/carson/touch_ui/config/power_config.json")
    if p3.exists():
        return p3
    raise FileNotFoundError(f"Missing required power config: {p1}")


def load_power_config() -> dict:
    fpath = get_power_config_path()
    with open(fpath, "r", encoding="utf-8") as f:
        return json.load(f)


class BusPowerManager:
    """Dedicated manager for servo bus power monitoring and auto-recovery state machine."""

    def __init__(self, ctrl=None, on_resync_callback: Optional[Callable[[], bool]] = None, is_busy_callback: Optional[Callable[[], bool]] = None) -> None:
        self.ctrl = ctrl
        self.on_resync_callback = on_resync_callback
        self.is_busy_callback = is_busy_callback
        self.config = load_power_config()
        self.min_bus_voltage = float(self.config["min_bus_voltage"])
        self.poll_interval_sec = float(self.config["poll_interval_sec"])
        self.disconnect_fail_limit = int(self.config["disconnect_fail_limit"])
        self.pogo_fail_limit = int(self.config["pogo_fail_limit"])
        self.settle_delay_sec = float(self.config["settle_delay_sec"])

        self.state: str = "CONNECTED"
        self.error_msg: Optional[str] = None
        self.pogo_connected: bool = True
        self.bus_voltage: float = 0.0
        self._pogo_fail_count: int = 0
        self._fail_count: int = 0
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._monitor_thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Starts the background power monitoring loop."""
        if self._monitor_thread is None or not self._monitor_thread.is_alive():
            self._stop_event.clear()
            self._monitor_thread = threading.Thread(target=self._power_monitor_loop, daemon=True)
            self._monitor_thread.start()
            logging.info("Started dedicated BusPowerManager background monitor thread.")

    def stop(self) -> None:
        """Stops the background power monitoring thread."""
        self._stop_event.set()
        logging.info("Stopped BusPowerManager monitor thread.")

    def is_connected(self) -> bool:
        """Returns True if 12V main bus power is present."""
        with self._lock:
            return self.state in ["CONNECTED", "POGO_DISCONNECTED"]

    def get_state_summary(self) -> dict:
        """Returns current power state, voltage, and error string."""
        with self._lock:
            return {
                "state": self.state,
                "connected": self.state in ["CONNECTED", "POGO_DISCONNECTED"],
                "pogo_connected": self.pogo_connected,
                "voltage": self.bus_voltage,
                "error": self.error_msg,
            }

    def _power_monitor_loop(self) -> None:
        """Background thread polling 12V bus voltage across servos and handling state transitions."""
        while not self._stop_event.is_set():
            time.sleep(self.poll_interval_sec)
            if not self.ctrl:
                continue

            if self.is_busy_callback and self.is_busy_callback():
                continue

            v7 = None
            v8 = None
            try:
                v7 = self.ctrl.read_voltage(7)
            except Exception:
                v7 = None

            try:
                v8 = self.ctrl.read_voltage(8)
            except Exception:
                v8 = None

            bus_v = max([v for v in [v7, v8] if v is not None] or [0.0])
            is_powered = (bus_v >= self.min_bus_voltage)
            pogo_conn = (v7 is not None and v7 >= self.min_bus_voltage)

            with self._lock:
                self.bus_voltage = bus_v
                self.pogo_connected = pogo_conn
                previous_state = self.state

            if is_powered:
                self._fail_count = 0
                if previous_state == "DISCONNECTED":
                    logging.info(
                        "12V main bus power detected returning (%.1fV). Awaiting %.1fs MCU settling runway...",
                        bus_v,
                        self.settle_delay_sec,
                    )
                    time.sleep(self.settle_delay_sec)
                    if self.on_resync_callback:
                        try:
                            resync_ok = bool(self.on_resync_callback())
                            if not resync_ok:
                                logging.warning("Hardware resync callback reported failure during power restoration.")
                        except Exception as ex:
                            logging.error("Exception during power restoration resync callback: %s", ex)

                if pogo_conn:
                    self._pogo_fail_count = 0
                    with self._lock:
                        self.state = "CONNECTED"
                        self.error_msg = None
                else:
                    self._pogo_fail_count += 1
                    if self._pogo_fail_count >= self.pogo_fail_limit:
                        with self._lock:
                            self.state = "POGO_DISCONNECTED"
                            self.error_msg = "Pogo connector disconnected (Arm Servos 1-6 offline)"
            else:
                self._fail_count += 1
                if self._fail_count >= self.disconnect_fail_limit:
                    with self._lock:
                        self.state = "DISCONNECTED"
                        self.error_msg = "12V Main Power Supply OFF"
                    if previous_state != "DISCONNECTED":
                        logging.warning("12V main bus power lost. State -> DISCONNECTED")

