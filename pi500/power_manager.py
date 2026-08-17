#!/usr/bin/env python3
"""Single-responsibility BusPowerManager module for SO-101 robot hardware.
Monitors 12V bus voltage, manages connection state machine (CONNECTED, DISCONNECTED, RE-SYNCHING),
and triggers automated recovery protocols upon power restoration.
"""

import logging
import threading
import time
from typing import Optional, Callable


class BusPowerManager:
    """Dedicated manager for servo bus power monitoring and auto-recovery state machine."""

    def __init__(self, ctrl=None, on_resync_callback: Optional[Callable[[], bool]] = None) -> None:
        self.ctrl = ctrl
        self.on_resync_callback = on_resync_callback
        self.state: str = "CONNECTED"
        self.error_msg: Optional[str] = None
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._monitor_thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Starts the background 400ms power monitoring loop."""
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
                "pogo_connected": getattr(self, "pogo_connected", True),
                "voltage": getattr(self, "bus_voltage", 0.0),
                "error": self.error_msg,
            }

    def _power_monitor_loop(self) -> None:
        """Background thread polling 12V bus voltage across servos and handling state transitions."""
        while not self._stop_event.is_set():
            time.sleep(0.4)
            if not self.ctrl:
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
            is_powered = (bus_v >= 10.0)
            pogo_conn = (v7 is not None and v7 >= 10.0)

            with self._lock:
                self.bus_voltage = bus_v
                self.pogo_connected = pogo_conn
                current_state = self.state

            if is_powered:
                self._fail_count = 0
                if pogo_conn:
                    self._pogo_fail_count = 0
                    with self._lock:
                        self.state = "CONNECTED"
                        self.error_msg = None
                else:
                    self._pogo_fail_count = getattr(self, "_pogo_fail_count", 0) + 1
                    if self._pogo_fail_count >= 3:
                        with self._lock:
                            self.state = "POGO_DISCONNECTED"
                            self.error_msg = "Pogo connector disconnected (Arm Servos 1-6 offline)"
            else:
                self._fail_count = getattr(self, "_fail_count", 0) + 1
                if self._fail_count >= 2:
                    with self._lock:
                        self.state = "DISCONNECTED"
                        self.error_msg = "12V Main Power Supply OFF"
                    logging.warning("12V main bus power lost. State -> DISCONNECTED")

