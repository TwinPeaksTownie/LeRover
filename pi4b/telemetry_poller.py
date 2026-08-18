#!/usr/bin/env python3
"""Single Responsibility TelemetryPollerService module for Pi 4B.
Runs a 500ms background loop to poll ICMP ping and HTTP status endpoints from Pi 500 (:8085)
and Mac Mini (:8086), maintaining a thread-safe status cache for consumption by the API gateway.
"""

import json
import logging
import subprocess
import threading
import time
import urllib.request
from typing import Dict, Any

PI500_IP = "192.168.0.130"
MAC_IP = "192.168.0.2"


class TelemetryPollerService:
    """Dedicated background poller for Pi 500 and Mac Mini hardware telemetry."""

    def __init__(self, pi500_ip: str = PI500_IP, mac_ip: str = MAC_IP) -> None:
        self.pi500_ip = pi500_ip
        self.mac_ip = mac_ip
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        self.status_cache: Dict[str, Any] = {
            "pokeball": {"running": False, "connected": False, "status": "DISCONNECTED", "pid": ""},
            "pokeball_rover": {"running": False, "pid": ""},
            "follower": {"running": False, "pid": ""},
            "leader": {"running": False, "pid": ""},
            "pi500_online": False,
            "daemon_running": False,
            "hardware_telemetry": None,
            "last_telemetry_time": 0,
        }

    def start(self) -> None:
        """Starts the background telemetry polling thread."""
        if self._thread is None or not self._thread.is_alive():
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._poll_loop, daemon=True)
            self._thread.start()
            logging.info("Started dedicated TelemetryPollerService background loop.")

    def stop(self) -> None:
        """Stops the background polling loop."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        logging.info("Stopped TelemetryPollerService background loop.")

    def get_status(self) -> Dict[str, Any]:
        """Returns a snapshot copy of the current thread-safe status cache."""
        with self._lock:
            resp = dict(self.status_cache)
            time_since_telem = time.time() - resp.get("last_telemetry_time", 0)
            resp["closed_loop_verified"] = bool(resp.get("hardware_telemetry")) and (time_since_telem < 2.0)
            return resp

    def set_hardware_telemetry(self, data: Dict[str, Any]) -> None:
        """Directly updates cached hardware telemetry from active HTTP calls."""
        with self._lock:
            self.status_cache["hardware_telemetry"] = data
            self.status_cache["last_telemetry_time"] = time.time()

    def _poll_loop(self) -> None:
        while not self._stop_event.is_set():
            # 1. ICMP ping check for Pi 500 physical reachability
            pi500_online = False
            try:
                res = subprocess.run(["ping", "-c", "1", "-W", "1", self.pi500_ip], capture_output=True)
                pi500_online = (res.returncode == 0)
            except Exception:
                pi500_online = False

            with self._lock:
                self.status_cache["pi500_online"] = pi500_online

            # 2. Poll Pi 500 Master Daemon over HTTP 8085
            try:
                req = urllib.request.Request(f"http://{self.pi500_ip}:8085/api/status", headers={'User-Agent': 'Pi4B-TouchUI'})
                with urllib.request.urlopen(req, timeout=1.0) as response:
                    if response.status == 200:
                        data = json.loads(response.read().decode())
                        with self._lock:
                            self.status_cache["hardware_telemetry"] = data
                            self.status_cache["last_telemetry_time"] = time.time()
                            self.status_cache["daemon_running"] = bool(data.get("hardware_connected", True))
                            if isinstance(data, dict):
                                self.status_cache["follower"] = data.get("follower", {"running": False, "pid": ""})
                                self.status_cache["pokeball"] = data.get("pokeball", {"running": False, "connected": False, "status": "DISCONNECTED", "pid": ""})
                    else:
                        with self._lock:
                            self.status_cache["daemon_running"] = False
            except Exception:
                with self._lock:
                    self.status_cache["daemon_running"] = False

            # 3. Poll Mac Mini Leader API over HTTP 8086
            try:
                mac_req = urllib.request.Request(f"http://{self.mac_ip}:8086/api/status", headers={'User-Agent': 'Pi4B-TouchUI'})
                with urllib.request.urlopen(mac_req, timeout=1.0) as mac_resp:
                    if mac_resp.status == 200:
                        mac_data = json.loads(mac_resp.read().decode())
                        leader_data = mac_data.get("leader", mac_data) if isinstance(mac_data, dict) else {}
                        with self._lock:
                            self.status_cache["leader"] = {
                                "running": bool(leader_data.get("running", False)),
                                "pid": str(leader_data.get("pid", ""))
                            }
                    else:
                        with self._lock:
                            self.status_cache["leader"] = {"running": False, "pid": ""}
            except Exception:
                with self._lock:
                    self.status_cache["leader"] = {"running": False, "pid": ""}

            time.sleep(0.5)
