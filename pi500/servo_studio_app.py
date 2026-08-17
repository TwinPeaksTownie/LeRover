#!/usr/bin/env python3
"""ServoStudioApp module for SO-101 arm calibration.
Encapsulates complete pi_servo_studio web UI into a managed BaseApp interface running on port 8086.
"""

import json
import logging
import math
import os
import signal
import sys
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Dict, Any, Optional
from urllib.parse import parse_qs, urlparse

from app_manager import BaseApp, AppMetadata
from robot_backend import RobotBackend, SERIAL_LOCK

PORT_WEB = 8086
CALIB_PATH = str(Path.home() / ".cache/huggingface/lerobot/calibration/robots/so_follower/follower.json")

MOTORS = {
    1: "shoulder_pan",
    2: "shoulder_lift",
    3: "elbow_flex",
    4: "wrist_flex",
    5: "wrist_roll",
    6: "gripper",
}

MOTOR_LABELS = {
    1: "Shoulder Pan",
    2: "Shoulder Lift",
    3: "Elbow Flex",
    4: "Wrist Flex",
    5: "Wrist Roll",
    6: "Gripper",
}


class ThreadedHTTPServer(HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class StudioHandler(BaseHTTPRequestHandler):
    backend: Optional[RobotBackend] = None
    app_instance: Optional["ServoStudioApp"] = None

    def _send_json(self, data: Dict[str, Any], code: int = 200) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _handle_request(self, method: str) -> None:
        parsed = urlparse(self.path)
        if method == "GET" and parsed.path in ["/", "/index.html"]:
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            html_content = self.app_instance.get_studio_html() if self.app_instance else "<h1>Servo Studio</h1>"
            self.wfile.write(html_content.encode("utf-8"))
            return

        if not self.backend or not self.app_instance:
            return self._send_json({"error": "Uninitialized components"}, 500)

        if parsed.path in ["/api/state", "/api/status"]:
            return self._send_json(self.app_instance.get_full_state())

        qs = parse_qs(parsed.query)
        body = {}
        if method == "POST":
            content_length = int(self.headers.get("Content-Length", 0))
            body_bytes = self.rfile.read(content_length) if content_length > 0 else b"{}"
            try:
                body = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
            except Exception:
                body = {}

        sid = int(body.get("sid", qs.get("sid", [0])[0]))

        if parsed.path == "/api/set_active":
            self.app_instance.active_servo = sid if sid in range(1, 7) else None
            self._send_json({"status": "ok", "active_servo": self.app_instance.active_servo})
        elif parsed.path == "/api/capture_min":
            self._send_json(self.app_instance.capture_min(sid))
        elif parsed.path == "/api/capture_max":
            self._send_json(self.app_instance.capture_max(sid))
        elif parsed.path == "/api/capture_home":
            self._send_json(self.app_instance.capture_home(sid))
        elif parsed.path == "/api/capture_home_all":
            self._send_json(self.app_instance.capture_home_all())
        elif parsed.path == "/api/toggle_drive_mode":
            self._send_json(self.app_instance.toggle_drive_mode(sid))
        elif parsed.path == "/api/emergency_stop":
            self.app_instance.disable_torque()
            self._send_json({"status": "ok", "action": "emergency_stop"})
        elif parsed.path in ["/api/safe_home", "/api/safe_home_all"]:
            self._send_json(self.app_instance.safe_home_all())
        elif parsed.path == "/api/set_goal":
            goal = int(body.get("goal", qs.get("goal", [2048])[0]))
            self._send_json(self.app_instance.write_active_goal(sid, goal))
        else:
            self._send_json({"status": "ok", "service": "servo_studio_app"})

    def do_GET(self) -> None:
        self._handle_request("GET")

    def do_POST(self) -> None:
        self._handle_request("POST")


class ServoStudioApp(BaseApp):
    """Managed Servo Studio Calibration Application."""
    metadata = AppMetadata(
        name="servo_studio_app",
        title="Servo Studio",
        description="Web dashboard for visual joint calibration and torque management",
        version="1.0.0",
        tags=["calibration", "web", "studio"],
        icon="🛠️"
    )

    def __init__(self, port: int = PORT_WEB) -> None:
        super().__init__()
        self.port = port
        self.calib: Dict[str, Any] = {}
        self.server: Optional[ThreadedHTTPServer] = None
        self.active_servo: Optional[int] = None
        self.load_calibration()

    def load_calibration(self) -> None:
        if os.path.exists(CALIB_PATH):
            try:
                with open(CALIB_PATH, "r") as f:
                    self.calib = json.load(f)
                self.logger.info(f"Loaded studio calibration from {CALIB_PATH}")
            except Exception as e:
                self.logger.error(f"Failed to load calibration JSON: {e}")

    def save_calibration(self) -> None:
        try:
            os.makedirs(os.path.dirname(CALIB_PATH), exist_ok=True)
            with open(CALIB_PATH, "w") as f:
                json.dump(self.calib, f, indent=2)
            self.logger.info(f"Saved studio calibration to {CALIB_PATH}")
        except Exception as e:
            self.logger.error(f"Failed to save calibration JSON to {CALIB_PATH}: {e}")

    def get_home_targets(self) -> Dict[int, int]:
        home_targets = {}
        for sid, name in MOTORS.items():
            if name in self.calib:
                info = self.calib[name]
                rmin = info.get("range_min", 0)
                rmax = info.get("range_max", 4095)
                offset = info.get("homing_offset", 0)
                drive_mode = info.get("drive_mode", 0)
                raw_home = (2048 + offset) if drive_mode == 1 else (2048 - offset)
                home_targets[sid] = max(rmin, min(rmax, raw_home))
            else:
                home_targets[sid] = 2048
        return home_targets

    def get_full_state(self) -> Dict[str, Any]:
        if not self.backend:
            return {"hardware_online": False, "error": "Backend uninitialized"}

        raw_ticks = self.backend.read_raw_arm_ticks()
        home_targets = self.get_home_targets()
        
        joints = {}
        for sid, name in MOTORS.items():
            info = self.calib.get(name, {"range_min": 0, "range_max": 4095, "homing_offset": 0, "drive_mode": 0})
            f_raw = raw_ticks.get(sid, raw_ticks.get(str(sid)))
            rmin = info.get("range_min", 0)
            rmax = info.get("range_max", 4095)
            home_t = home_targets.get(sid, 2048)
            span = max(1, rmax - rmin)

            if f_raw is None:
                pct = 0.0
                dist_home = 0
                at_home = False
                f_deg = 0.0
                desc = "🔴 OFFLINE / UNPLUGGED"
                warning = "DISCONNECTED"
                home_pct = 50.0
            else:
                pct = round(max(0.0, min(100.0, ((f_raw - rmin) / span) * 100.0)), 1)
                home_pct = round(max(0.0, min(100.0, ((home_t - rmin) / span) * 100.0)), 1)
                dist_home = abs(f_raw - home_t)
                at_home = dist_home <= 25

                f_deg = (f_raw - 2048) * (360.0 / 4095.0)
                if info.get("drive_mode", 0) == 1:
                    f_deg = -f_deg
                f_deg = round(f_deg, 1)

                if sid == 1:
                    dir_t = "Centered" if abs(f_deg) < 2.0 else ("Rotated Left (CCW)" if f_deg > 0 else "Rotated Right (CW)")
                    desc = f"{dir_t} ({abs(f_deg)}°)"
                elif sid == 2:
                    dir_t = "Pitched Up/Back" if f_deg > 0 else "Pitched Forward/Down"
                    desc = f"{dir_t} ({abs(f_deg)}°)"
                elif sid == 3:
                    dir_t = "Extended Out" if f_deg > 0 else "Flexed Inward"
                    desc = f"{dir_t} ({abs(f_deg)}°)"
                elif sid == 4:
                    dir_t = "Wrist Pitched Up" if f_deg > 0 else "Wrist Pitched Down"
                    desc = f"{dir_t} ({abs(f_deg)}°)"
                elif sid == 5:
                    dir_t = "Wrist Twisted CW" if f_deg > 0 else "Wrist Twisted CCW"
                    desc = f"{dir_t} ({abs(f_deg)}°)"
                elif sid == 6:
                    desc = f"Gripper Jaws {pct}% Open"
                else:
                    desc = f"{f_deg}° Angle"

                near_min = f_raw <= (rmin + int(span * 0.05))
                near_max = f_raw >= (rmax - int(span * 0.05))
                warning = "NEAR MIN HARDSTOP" if near_min else ("NEAR MAX HARDSTOP" if near_max else None)

            joints[sid] = {
                "name": name,
                "label": MOTOR_LABELS.get(sid, name),
                "follower_raw": f_raw,
                "range_min": rmin,
                "range_max": rmax,
                "home_tick": home_t,
                "home_pct": home_pct,
                "range_pct": pct,
                "dist_home": dist_home,
                "at_home": at_home,
                "posture_desc": desc,
                "warning": warning,
                "drive_mode": info.get("drive_mode", 0),
            }

        return {
            "hardware_online": True,
            "port": "/dev/ttyACM0",
            "baud": 1000000,
            "torque_enabled": self.backend.follower_active,
            "active_servo": self.active_servo,
            "follower_raw": raw_ticks,
            "home_targets": home_targets,
            "joints": joints,
            "calibration": self.calib,
        }

    def capture_min(self, sid: int) -> Dict[str, Any]:
        name = MOTORS.get(sid)
        if not name or name not in self.calib:
            return {"error": f"Invalid motor sid {sid}"}
        if not self.backend:
            return {"error": "Backend offline"}

        raw_ticks = self.backend.read_raw_arm_ticks()
        raw = raw_ticks.get(sid, raw_ticks.get(str(sid)))
        if raw is None:
            return {"error": f"No telemetry for Motor {sid}"}

        self.calib[name]["range_min"] = int(raw)
        self.save_calibration()
        return {"status": "ok", "sid": sid, "range_min": raw}

    def capture_max(self, sid: int) -> Dict[str, Any]:
        name = MOTORS.get(sid)
        if not name or name not in self.calib:
            return {"error": f"Invalid motor sid {sid}"}
        if not self.backend:
            return {"error": "Backend offline"}

        raw_ticks = self.backend.read_raw_arm_ticks()
        raw = raw_ticks.get(sid, raw_ticks.get(str(sid)))
        if raw is None:
            return {"error": f"No telemetry for Motor {sid}"}

        self.calib[name]["range_max"] = int(raw)
        self.save_calibration()
        return {"status": "ok", "sid": sid, "range_max": raw}

    def capture_home(self, sid: int) -> Dict[str, Any]:
        name = MOTORS.get(sid)
        if not name or name not in self.calib:
            return {"error": f"Invalid motor sid {sid}"}
        if not self.backend:
            return {"error": "Backend offline"}

        raw_ticks = self.backend.read_raw_arm_ticks()
        raw = raw_ticks.get(sid, raw_ticks.get(str(sid)))
        if raw is None:
            return {"error": f"No telemetry for Motor {sid}"}

        drive_mode = self.calib[name].get("drive_mode", 0)
        new_offset = (raw - 2048) if drive_mode == 1 else (2048 - raw)
        self.calib[name]["homing_offset"] = new_offset
        self.save_calibration()
        home_targets = self.get_home_targets()
        return {"status": "ok", "sid": sid, "homing_offset": new_offset, "home_tick": home_targets.get(sid, 2048)}

    def capture_home_all(self) -> Dict[str, Any]:
        if not self.backend:
            return {"error": "Backend offline"}
        raw_ticks = self.backend.read_raw_arm_ticks()
        results = {}
        for sid, name in MOTORS.items():
            raw = raw_ticks.get(sid, raw_ticks.get(str(sid)))
            if raw is not None and name in self.calib:
                drive_mode = self.calib[name].get("drive_mode", 0)
                new_offset = (raw - 2048) if drive_mode == 1 else (2048 - raw)
                self.calib[name]["homing_offset"] = new_offset
                results[sid] = {"name": name, "homing_offset": new_offset}

        self.save_calibration()
        return {"status": "ok", "results": results}

    def toggle_drive_mode(self, sid: int) -> Dict[str, Any]:
        name = MOTORS.get(sid)
        if not name or name not in self.calib:
            return {"error": f"Invalid motor sid {sid}"}
        curr_dm = self.calib[name].get("drive_mode", 0)
        new_dm = 1 if curr_dm == 0 else 0
        self.calib[name]["drive_mode"] = new_dm
        self.save_calibration()
        return {"status": "ok", "sid": sid, "drive_mode": new_dm}

    def disable_torque(self) -> None:
        if self.backend and self.backend.bus:
            with SERIAL_LOCK:
                try:
                    self.backend.bus.disable_torque()
                except Exception as e:
                    self.logger.warning(f"Disable torque warning: {e}")

    def enable_torque(self) -> None:
        if self.backend and self.backend.bus:
            with SERIAL_LOCK:
                try:
                    self.backend.bus.enable_torque()
                except Exception as e:
                    self.logger.warning(f"Enable torque warning: {e}")

    def safe_home_all(self) -> Dict[str, Any]:
        if not self.backend or not self.backend.bus:
            return {"error": "Arm hardware offline"}

        raw_positions = self.backend.read_raw_arm_ticks()
        home_targets = self.get_home_targets()
        self.enable_torque()

        start_positions = {}
        driven = {}
        for sid, name in MOTORS.items():
            if sid in home_targets:
                curr = raw_positions.get(sid)
                start_positions[sid] = curr if curr is not None else home_targets[sid]
                driven[name] = home_targets[sid]

        def _smooth_home_worker():
            num_steps = 50
            step_delay = 0.04
            for step in range(1, num_steps + 1):
                if self.stop_event.is_set():
                    break
                alpha = step / float(num_steps)
                ease = (1.0 - math.cos(alpha * math.pi)) / 2.0
                goal_dict = {}
                for sid, name in MOTORS.items():
                    if sid in start_positions:
                        s_pos = start_positions[sid]
                        t_pos = home_targets[sid]
                        interp_pos = int(round(s_pos + (t_pos - s_pos) * ease))
                        goal_dict[name] = interp_pos
                with SERIAL_LOCK:
                    try:
                        self.backend.bus.sync_write("Goal_Position", goal_dict, normalize=False)
                    except Exception as e:
                        self.logger.error(f"Smooth home trajectory error: {e}")
                        break
                time.sleep(step_delay)

        threading.Thread(target=_smooth_home_worker, daemon=True).start()
        return {"status": "ok", "mode": "smooth_trajectory", "start_positions": start_positions, "home_targets": driven}

    def write_active_goal(self, sid: int, goal: int) -> Dict[str, Any]:
        name = MOTORS.get(sid)
        if not name or not self.backend or not self.backend.bus:
            return {"error": "Invalid motor or bus offline"}
        with SERIAL_LOCK:
            try:
                self.backend.bus.sync_write("Goal_Position", {name: goal}, normalize=False)
                return {"status": "ok", "sid": sid, "goal": goal}
            except Exception as e:
                return {"error": f"Failed to set goal: {e}"}

    def get_studio_html(self) -> str:
        from pathlib import Path
        studio_file = Path("/home/user/pi_servo_studio.py")
        if studio_file.exists():
            try:
                code = studio_file.read_text(encoding="utf-8")
                if "HTML_DASHBOARD = \"\"\"" in code:
                    start_idx = code.find("HTML_DASHBOARD = \"\"\"") + len("HTML_DASHBOARD = \"\"\"")
                    end_idx = code.find("\"\"\"", start_idx)
                    return code[start_idx:end_idx]
            except Exception:
                pass
        return "<h1>SO-101 Servo Studio</h1><p>Full web interface loading...</p>"

    def stop(self) -> None:
        super().stop()
        self.logger.info("ServoStudioApp.stop() called. Closing web server...")
        if self.server:
            try:
                self.server.server_close()
                threading.Thread(target=self.server.shutdown, daemon=True).start()
            except Exception as e:
                self.logger.warning(f"Server close error: {e}")

    def run(self, backend: RobotBackend, stop_event: threading.Event) -> None:
        self.backend = backend
        StudioHandler.backend = backend
        StudioHandler.app_instance = self

        self.disable_torque()
        self.logger.info(f"Starting Servo Studio server on port {self.port} (Default: UNTORQUED)...")
        self.server = ThreadedHTTPServer(("0.0.0.0", self.port), StudioHandler)

        server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        server_thread.start()

        try:
            while not stop_event.is_set():
                stop_event.wait(0.2)
        finally:
            self.logger.info("Stopping Servo Studio server loop...")
            if self.server:
                try:
                    self.server.server_close()
                except Exception:
                    pass
            self.logger.info("Servo Studio server loop finished.")
