#!/usr/bin/env python3
"""Standard library HTTP REST server (port 8085) for SO-101 robot control.
Uses built-in http.server and ThreadingMixIn to ensure 100% dependency-free operation on Pi 500.
"""

import json
import logging
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from typing import Optional, Dict, Any

from robot_backend import RobotBackend, SERIAL_LOCK, ticks_to_degrees_s7, degrees_to_ticks_s7
from app_manager import AppManager
from teleop_control_loop import TeleopControlApp
from servo_studio_app import ServoStudioApp
from pokeball_app import PokeballApp
import threading

MAC_API_URL = "http://192.168.0.2:8086"
PI4B_SOUND_URL = "http://192.168.0.86:8082/api/play_sound"


def play_chime(kind: str = "connect") -> None:
    """Dispatches sound playback event to Pi 4B audio service asynchronously."""
    def _work():
        try:
            payload = json.dumps({"kind": kind}).encode("utf-8")
            req = urllib.request.Request(PI4B_SOUND_URL, data=payload, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                pass
        except Exception as e:
            logging.warning("Failed to dispatch chime '%s' to Pi 4B: %s", kind, e)
    threading.Thread(target=_work, daemon=True).start()


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """Threaded HTTP server to prevent slow clients from blocking API requests."""
    daemon_threads = True
    allow_reuse_address = True


class MasterApiHandler(BaseHTTPRequestHandler):
    backend: Optional[RobotBackend] = None
    app_manager: Optional[AppManager] = None

    def _send_json(self, data: Dict[str, Any], code: int = 200) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/status":
            if not self.backend or not self.app_manager:
                return self._send_json({"error": "Uninitialized components"}, 500)

            pokeball_data = {
                "connected": False,
                "status": "OFFLINE",
                "mac": "58:2F:40:8D:50:71",
                "last_seen": 0,
                "packet_count": 0,
                "norm_x": 0.0,
                "norm_y": 0.0,
                "button_a": False,
                "button_b": False,
            }
            is_pokeball_app_active = (self.app_manager.current_app_name == "pokeball_teleop_app")
            if is_pokeball_app_active and os.path.exists("/tmp/pokeball_telemetry.json"):
                try:
                    with open("/tmp/pokeball_telemetry.json", "r") as pf:
                        f_data = json.load(pf)
                        last_seen = f_data.get("last_seen", 0)
                        if time.time() - last_seen <= 10.0:
                            pokeball_data = f_data
                except Exception as e:
                    logging.debug(f"Pokeball telemetry read exception: {e}")

            follower_data = {
                "running": self.backend.follower_active,
                "pid": str(os.getpid()) if self.backend.follower_active else "",
            }
            leader_data = {"running": False, "pid": "", "connected": False, "error": None}
            try:
                req = urllib.request.Request(f"{MAC_API_URL}/api/status", headers={"User-Agent": "SO101-MasterApi"})
                with urllib.request.urlopen(req, timeout=0.8) as resp:
                    if resp.status == 200:
                        data = json.loads(resp.read().decode())
                        leader_data = data.get("leader", data) if isinstance(data.get("leader"), dict) else data
                        leader_data["connected"] = True
            except Exception as e:
                logging.warning("Leader arm status poll failed (%s): %s", MAC_API_URL, e)
                leader_data["error"] = f"Leader Arm unreachable: {e}"

            with self.backend.lock:
                aux_calib_8 = getattr(self.backend, "aux_calibration", {}).get("8", {})
                left_b = aux_calib_8.get("min_ticks", 3)
                right_b = aux_calib_8.get("max_ticks", 4800)
                gantry_pos = self.backend.gantry_position

                span = max(1, abs(right_b - left_b))
                pct = round(max(0.0, min(100.0, ((gantry_pos - left_b) / span) * 100.0)), 1) if gantry_pos is not None else None

                arm_data = {}
                motor_names = {
                    "1": "shoulder_pan",
                    "2": "shoulder_lift",
                    "3": "elbow_flex",
                    "4": "wrist_flex",
                    "5": "wrist_roll",
                    "6": "gripper",
                }
                if self.backend.bus is not None:
                    arm_raw = getattr(self.backend, "last_arm_positions", {})
                    for sid, mname in motor_names.items():
                        arm_data[sid] = {
                            "name": mname,
                            "raw": arm_raw.get(mname, arm_raw.get(int(sid))),
                        }

                servos_map = arm_data
                s7_pos = self.backend.aux_positions.get(7)
                s7_raw = self.backend.raw_positions.get(7)
                c7 = self.backend.aux_calibration.get("7", {}).get("center_ticks", 2048) if hasattr(self.backend, "aux_calibration") else 2048
                servos_map["7"] = {
                    "pos": s7_pos,
                    "raw": s7_raw,
                    "angle": ticks_to_degrees_s7(s7_pos, center_ticks=c7) if s7_pos is not None else None,
                    "torque": self.backend.torque_state.get(7, True),
                    "is_moving": self.backend.is_moving.get(7, False),
                    "connected": s7_pos is not None,
                }

                s8_pos = self.backend.gantry_position
                s8_raw = self.backend.raw_positions.get(8)
                servos_map["8"] = {
                    "pos": s8_pos,
                    "raw": s8_raw,
                    "pct": pct,
                    "torque": self.backend.torque_state.get(8, True),
                    "is_moving": self.backend.is_moving.get(8, False),
                    "connected": s8_pos is not None,
                }

                power_summary = self.backend.power_mgr.get_state_summary() if self.backend.power_mgr else {"state": "UNINITIALIZED", "connected": False, "pogo_connected": False, "voltage": 0.0, "error": "BusPowerManager uninitialized"}
                power_state = power_summary["state"]
                active_error = power_summary["error"] or self.backend.error_msg
                if power_state in ["CONNECTED", "POGO_DISCONNECTED"]:
                    all_errors = [m.get("error") for m in self.backend.motor_states.values() if m.get("error")]
                    if not all_errors and power_state == "CONNECTED":
                        active_error = None
                        self.backend.error_msg = None

                resp = {
                    "status": "online" if power_summary.get("connected", True) else ("re-synching" if power_state == "RE-SYNCHING" else "offline"),
                    "hardware_connected": power_summary.get("connected", True),
                    "bus_power_state": power_state,
                    "bus_voltage": power_summary.get("voltage", 0.0),
                    "pogo_connected": power_summary.get("pogo_connected", False),
                    "current_app": self.app_manager.current_app_name,
                    "active_port": self.backend.active_port,
                    "error": active_error,
                    "apps": self.app_manager.list_apps(),
                    "app_manager_status": self.app_manager.get_status(),
                    "follower": follower_data,
                    "leader": leader_data,
                    "pokeball": pokeball_data,
                    "servos": servos_map,
                }
            self._send_json(resp)
        elif parsed.path in ["/api/apps", "/api/apps/list"]:
            self._send_json({"status": "ok", "apps": self.app_manager.list_apps()})
        elif parsed.path == "/api/apps/status":
            self._send_json({"status": "ok", "app_manager": self.app_manager.get_status()})
        elif parsed.path == "/api/pokeball_reconnect":
            self.app_manager.start_app_by_name("pokeball_teleop_app")
            self._send_json({"status": "ok", "message": "Poké Ball teleop app restart triggered"})
        else:
            self._send_json({"status": "ok", "service": "so101_master_api"})

    def do_POST(self) -> None:
        content_length = int(self.headers.get("Content-Length", 0))
        body_bytes = self.rfile.read(content_length) if content_length > 0 else b"{}"
        try:
            body = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
        except Exception:
            body = {}
        parsed = urllib.parse.urlparse(self.path)

        if not self.backend or not self.app_manager:
            return self._send_json({"error": "Uninitialized components"}, 500)

        if parsed.path.startswith("/slider") or parsed.path == "/api/slider":
            query = urllib.parse.parse_qs(parsed.query)
            val = None
            if "value" in query:
                val = int(query["value"][0])
            elif "target" in query:
                val = int(query["target"][0])
            elif "value" in body:
                val = int(body["value"])
            elif "target" in body:
                val = int(body["target"])

            if val is None:
                return self._send_json({"status": "error", "message": "Missing required 'target' or 'value' parameter"}, 400)

            val = max(3, min(4800, val))
            ok, msg = self.backend.move_target(8, val, speed=400, max_t=500)
            self._send_json({"status": "ok" if ok else "error", "message": msg, "target": val})

        elif parsed.path in ["/api/pedestal_step", "/pedestal/step"]:
            direction = str(body.get("direction", "right")).lower()
            ok, moved, msg, target_deg, target_ticks, at_limit = self.backend.step_pedestal_preset(direction)
            if not ok:
                self._send_json({"status": "error", "message": msg}, 400)
            else:
                if not moved and at_limit:
                    play_chime("smw_shell_ricochet")
                elif moved:
                    play_chime("smw_magikoopa_beam" if direction == "right" else "smw_pipe")
                self._send_json({
                    "status": "ok",
                    "id": 7,
                    "direction": direction,
                    "target_angle": target_deg,
                    "target_pos": target_ticks,
                    "moved": moved,
                    "at_limit": at_limit,
                    "message": msg
                })

        elif parsed.path.startswith("/pedestal") or parsed.path == "/api/pedestal":
            if "direction" in body or "step" in body:
                direction = str(body.get("direction", body.get("step", "right"))).lower()
                ok, moved, msg, target_deg, target_ticks, at_limit = self.backend.step_pedestal_preset(direction)
                if not ok:
                    return self._send_json({"status": "error", "message": msg}, 400)
                if not moved and at_limit:
                    play_chime("smw_shell_ricochet")
                elif moved:
                    play_chime("smw_magikoopa_beam" if direction == "right" else "smw_pipe")
                return self._send_json({
                    "status": "ok",
                    "id": 7,
                    "direction": direction,
                    "target_angle": target_deg,
                    "target_pos": target_ticks,
                    "moved": moved,
                    "at_limit": at_limit,
                    "message": msg
                })

            center_s7 = self.backend.aux_calibration.get("7", {}).get("center_ticks", 2048) if hasattr(self.backend, "aux_calibration") else 2048
            val = center_s7
            query = urllib.parse.parse_qs(parsed.query)
            if "angle" in body:
                val = degrees_to_ticks_s7(float(body["angle"]), center_ticks=center_s7)
            elif "value" in query:
                val = int(query["value"][0])
            elif "value" in body:
                val = int(body["value"])

            ok, msg = self.backend.move_target(7, val, speed=400, max_t=500)
            self._send_json({"status": "ok" if ok else "error", "message": msg, "target": val, "angle": ticks_to_degrees_s7(val, center_ticks=center_s7)})


        elif parsed.path == "/api/move":
            if "id" not in body:
                return self._send_json({"status": "error", "message": "Missing required 'id' parameter"}, 400)
            sid = int(body["id"])
            center_s7 = self.backend.aux_calibration.get("7", {}).get("center_ticks", 2048) if hasattr(self.backend, "aux_calibration") else 2048
            if "angle" in body and sid == 7:
                target_pos = degrees_to_ticks_s7(float(body["angle"]), center_ticks=center_s7)
            else:
                default_target = center_s7 if sid == 7 else 2503
                target_pos = int(body.get("target", default_target))
            ok, msg = self.backend.move_target(sid, target_pos, step_size=50, speed=400, max_t=500)
            if not ok:
                self._send_json({"status": "error", "message": msg}, 400)
            else:
                self._send_json({"status": "ok", "id": sid, "target_pos": target_pos, "angle": ticks_to_degrees_s7(target_pos, center_ticks=center_s7) if sid == 7 else None})

        elif parsed.path == "/api/nudge_physical":
            sid = int(body.get("id", 8))
            direction = str(body.get("direction", "right")).lower()
            amount = abs(int(body.get("amount", 100)))
            delta = amount if direction == "right" else -amount

            with self.backend.lock:
                curr_pos = self.backend.gantry_position if sid == 8 else self.backend.aux_positions.get(7)
                if curr_pos is None:
                    return self._send_json({"status": "error", "message": f"Hardware Error: Servo {sid} position is uninitialized"}, 400)
                target_pos = curr_pos + delta

            ok, msg = self.backend.move_target(sid, target_pos, step_size=50, speed=400, max_t=500)
            if not ok:
                self._send_json({"status": "error", "message": msg}, 400)
            else:
                current_p = self.backend.gantry_position if sid == 8 else self.backend.aux_positions.get(7)
                self._send_json({"status": "ok", "id": sid, "direction": direction, "target_pos": target_pos, "current_pos": current_p})

        elif parsed.path == "/api/torque":
            if "id" not in body:
                return self._send_json({"status": "error", "message": "Missing required 'id' parameter"}, 400)
            sid = int(body["id"])
            if sid not in [7, 8]:
                return self._send_json({"status": "error", "message": "Invalid servo 'id'. Must be 7 or 8"}, 400)

            toggle = body.get("toggle", True)
            with self.backend.lock:
                new_state = not self.backend.torque_state[sid] if toggle else bool(body.get("enable", False))
                self.backend.torque_state[sid] = new_state
                if self.backend.hardware_active and self.backend.ctrl:
                    self.backend.ctrl.set_torque(sid, new_state)
            self._send_json({"status": "ok", "id": sid, "torque": new_state})

        elif parsed.path == "/api/sync_position":
            if "id" not in body or "pos" not in body:
                return self._send_json({"status": "error", "message": "Missing required 'id' or 'pos' parameter"}, 400)
            sid = int(body["id"])
            pos = int(body["pos"])
            with self.backend.lock:
                if sid == 8:
                    self.backend.gantry_position = pos
                else:
                    self.backend.aux_positions[sid] = pos
                    self.backend.raw_positions[sid] = pos % 4096
                self.backend.save_state()
            self._send_json({"status": "ok", "id": sid, "synced_pos": pos})

        elif parsed.path == "/api/calibration":
            with self.backend.lock:
                if "calibration" in body:
                    self.backend.aux_calibration.update(body["calibration"])
            self._send_json({"status": "ok", "calibration": self.backend.aux_calibration})

        elif parsed.path == "/api/pi500_follower_toggle":
            action = body.get("action", "toggle")
            if action == "toggle":
                action = "stop" if self.backend.follower_active else "start"

            if action in ["stop", "kill"]:
                try:
                    if self.backend.bus and hasattr(self.backend.bus, "disable_torque"):
                        with SERIAL_LOCK:
                            self.backend.bus.disable_torque(num_retry=2)
                except Exception as e:
                    logging.warning(f"Follower stop torque disarm warning: {e}")
                self.backend.follower_active = False
                self.app_manager.stop_app("teleop_app")
                self._send_json({"status": "ok", "action": action, "running": False})
            elif action == "start":
                try:
                    if self.backend.bus and hasattr(self.backend.bus, "enable_torque"):
                        with SERIAL_LOCK:
                            self.backend.bus.enable_torque(num_retry=2)
                except Exception as e:
                    logging.warning(f"Follower start torque enable warning: {e}")
                self.backend.follower_active = True
                teleop_app = TeleopControlApp(no_zmq=False)
                self.app_manager.start_app(teleop_app)
                self._send_json({"status": "ok", "action": "start", "running": True})

        elif parsed.path == "/api/mac_leader_toggle":
            action = body.get("action", "toggle")
            try:
                post_data = json.dumps({"action": action}).encode("utf-8")
                req = urllib.request.Request(f"{MAC_API_URL}/api/leader_toggle", data=post_data, headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=1.5) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    self._send_json(data, resp.status)
            except Exception as e:
                self._send_json({"status": "error", "message": f"Mac HTTP API error: {e}"}, 500)

        elif parsed.path == "/api/servo_studio_toggle":
            action = body.get("action", "toggle")
            is_running = (self.app_manager.current_app_name == "servo_studio_app")
            if action == "toggle":
                action = "stop" if is_running else "start"

            if action in ["stop", "kill"]:
                self.app_manager.stop_app("servo_studio_app")
                self._send_json({"status": "ok", "action": action, "running": False})
            elif action == "start":
                self.backend.follower_active = False
                studio_app = ServoStudioApp(port=8086)
                self.app_manager.start_app(studio_app)
                self._send_json({"status": "ok", "action": "start", "running": True})

        elif parsed.path == "/api/apps/start":
            app_name = body.get("name")
            if not app_name:
                return self._send_json({"error": "Missing required 'name' parameter"}, 400)
            ok = self.app_manager.start_app_by_name(app_name)
            self._send_json({"status": "ok" if ok else "error", "app_name": app_name, "running": ok})

        elif parsed.path == "/api/apps/stop":
            app_name = body.get("name")
            if app_name:
                self.app_manager.stop_app(app_name)
            else:
                self.app_manager.stop_all()
            self._send_json({"status": "ok", "message": f"Stopped app {app_name if app_name else 'all'}"})

        elif parsed.path == "/api/pokeball_teleop_toggle":
            action = body.get("action", "toggle")
            is_running = (self.app_manager.current_app_name == "pokeball_teleop_app")
            if action == "toggle":
                action = "stop" if is_running else "start"

            if action in ["stop", "kill"]:
                self.app_manager.stop_app("pokeball_teleop_app")
                self._send_json({"status": "ok", "action": action, "running": False})
            else:
                ok = self.app_manager.start_app_by_name("pokeball_teleop_app")
                self._send_json({"status": "ok" if ok else "error", "action": "start", "running": ok})

        elif parsed.path == "/api/kill_all":
            try:
                post_data = json.dumps({"action": "stop"}).encode("utf-8")
                req = urllib.request.Request(f"{MAC_API_URL}/api/leader_toggle", data=post_data, headers={"Content-Type": "application/json"})
                urllib.request.urlopen(req, timeout=1.0)
            except Exception as e:
                logging.warning(f"Kill all Mac leader HTTP error: {e}")

            try:
                if self.backend.bus and hasattr(self.backend.bus, "disable_torque"):
                    with SERIAL_LOCK:
                        self.backend.bus.disable_torque(num_retry=2)
            except Exception as e:
                logging.warning(f"Kill all torque disarm warning: {e}")

            self.backend.follower_active = False
            self.app_manager.stop_all()
            self._send_json({"status": "ok", "message": "All teleoperation processes killed and torque disarmed."})

        else:
            self._send_json({"error": "Endpoint not found"}, 404)


def create_master_http_server(host: str, port: int, backend: RobotBackend, app_manager: AppManager) -> ThreadedHTTPServer:
    MasterApiHandler.backend = backend
    MasterApiHandler.app_manager = app_manager
    return ThreadedHTTPServer((host, port), MasterApiHandler)
