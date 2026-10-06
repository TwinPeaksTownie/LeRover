import os
import json
import time
import glob
import logging
import threading
from pathlib import Path
from typing import Dict, Any, Callable, List
from concurrent.futures import ThreadPoolExecutor

from pi4b.joycon_driver import JoyConDriver, JoyConState
from pi4b.gesture_engine import GestureEngine, JoyConEvent

class JoyConServiceDaemon:
    """Intrinsic 24/7 daemon service orchestrating Joy-Con HID driver and event dispatch."""

    def __init__(self, config: Dict[str, Any] = None, calibration: tuple = None, backend=None):
        self.logger = logging.getLogger("so101.joycon_service")
        
        if config is None:
            import json
            cfg_path = Path(__file__).resolve().parent.parent / "apps" / "joycon_app" / "config.json"
            with open(cfg_path, "r", encoding="utf-8") as f:
                config = json.load(f)
        if calibration is None:
            import json
            calib_path = Path(__file__).resolve().parent.parent / "calibration_aux.json"
            with open(calib_path, "r", encoding="utf-8") as f:
                calib = json.load(f)
            sec = calib["joycon_joystick"]
            calibration = (int(sec["center_x"]), int(sec["center_y"]), int(sec["span_x"]), int(sec["span_y"]), int(sec["min_calib_raw"]), int(sec["max_calib_raw"]))
            
        self.config = config
        self.backend = backend
        
        self.mac_address = config["hardware"]["mac_address"]
        self.telemetry_write_rate_hz = float(config["hardware"]["telemetry_write_rate_hz"])
        self.last_telemetry_write_time = 0.0

        c_x, c_y, s_x, s_y, _, _ = calibration
        deadzone = float(config["control"]["deadzone"])
        
        self.driver = JoyConDriver(center_x=c_x, center_y=c_y, span_x=s_x, span_y=s_y, deadzone=deadzone)
        self.gesture_engine = GestureEngine(config)
        
        self.is_connected = False
        self.stop_event = threading.Event()
        self.thread = None
        self.callbacks: Dict[JoyConEvent, List[Callable]] = {}
        self.state_callbacks: List[Callable[[JoyConState], None]] = []

        self.telemetry_file = "/dev/shm/joycon_telemetry.json"
        self.telemetry = {
            "running": True, "connected": False, "status": "SEARCHING",
            "mac": self.mac_address, "packet_count": 0, "last_seen": 0.0,
            "battery_level": 0, "buttons": {}, "stick": {"norm_x": 0.0, "norm_y": 0.0}
        }
        
    def register_event_callback(self, event: JoyConEvent, callback: Callable):
        if event not in self.callbacks:
            self.callbacks[event] = []
        self.callbacks[event].append(callback)
        
    def register_state_callback(self, callback: Callable[[JoyConState], None]):
        self.state_callbacks.append(callback)

    def _write_telemetry(self):
        now = time.time()
        if (now - self.last_telemetry_write_time) < (1.0 / self.telemetry_write_rate_hz):
            return
        self.last_telemetry_write_time = now
        try:
            tmp_path = self.telemetry_file + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self.telemetry, f)
            os.replace(tmp_path, self.telemetry_file)
        except OSError as e:
            self.logger.debug("Telemetry file write warning: %s", e)

    def _find_device_path(self) -> str | None:
        if os.name != "nt":
            for p in glob.glob("/sys/class/hidraw/hidraw*"):
                uevent_path = os.path.join(p, "device", "uevent")
                if os.path.exists(uevent_path):
                    try:
                        with open(uevent_path, "r", encoding="utf-8") as f:
                            txt = f.read()
                        if "0000057E" in txt and "2007" in txt:
                            return f"/dev/{os.path.basename(p)}"
                    except OSError:
                        pass
        return None

    def _run_loop(self):
        fd = None
        while not self.stop_event.is_set():
            if fd is None:
                dev_path = self._find_device_path()
                if dev_path:
                    try:
                        fd = os.open(dev_path, os.O_RDWR | os.O_NONBLOCK)
                        self.driver.init_joycon(fd, step_delay=float(self.config["hardware"]["init_step_delay_sec"]))
                        self.is_connected = True
                        self.telemetry["connected"] = True
                        self.telemetry["status"] = "CONNECTED"
                        self.logger.info("Joy-Con (R) connected on %s", dev_path)
                    except OSError as e:
                        self.logger.warning("Failed to open %s: %s", dev_path, e)
                        fd = None
                if fd is None:
                    self.is_connected = False
                    self.telemetry["connected"] = False
                    self.telemetry["status"] = "SEARCHING"
                    self._write_telemetry()
                    time.sleep(float(self.config["hardware"]["reconnect_delay_sec"]))
                    continue

            try:
                import select
                r, _, _ = select.select([fd], [], [], float(self.config["hardware"]["packet_timeout_sec"]))
                if r:
                    raw = os.read(fd, 64)
                    state = self.driver.process_report(raw)
                    if state:
                        self.telemetry["last_seen"] = state.timestamp
                        self.telemetry["battery_level"] = state.battery_level
                        self.telemetry["buttons"] = state.buttons
                        self.telemetry["stick"] = {"norm_x": state.stick_norm_x, "norm_y": state.stick_norm_y}
                        self.telemetry["packet_count"] += 1
                        
                        events = self.gesture_engine.process(state)
                        for ev in events:
                            for cb in self.callbacks.get(ev, []):
                                try:
                                    cb()
                                except Exception as e:
                                    self.logger.error("Event callback error: %s", e)
                                    
                        for cb in self.state_callbacks:
                            cb(state)
                            
                else:
                    self.logger.warning("Joy-Con packet timeout. Disconnecting...")
                    os.close(fd)
                    fd = None
            except OSError as e:
                self.logger.warning("Joy-Con read error: %s", e)
                if fd is not None:
                    os.close(fd)
                fd = None
                
            self._write_telemetry()

    def start(self):
        if self.thread is None:
            self.stop_event.clear()
            self.thread = threading.Thread(target=self._run_loop, daemon=True, name="JoyConServiceDaemon")
            self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=2.0)
            self.thread = None
