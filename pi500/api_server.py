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

from robot_backend import RobotBackend, ticks_to_degrees_s7, degrees_to_ticks_s7
from app_manager import AppManager
from teleop_control_loop import TeleopControlApp
from servo_studio_app import ServoStudioApp
from pokeball_app import PokeballApp
import threading

try:
    import network_resolver
except ImportError:
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import network_resolver


def get_mac_api_url() -> str:
    mac_ip = network_resolver.get_mac_ip(prefer_port=8086)
    return f"http://{mac_ip}:8086"


def get_pi4b_sound_url() -> str:
    pi4b_ip = network_resolver.get_pi4b_ip(prefer_port=8082)
    return f"http://{pi4b_ip}:8082/api/play_sound"

_leader_cache_lock = threading.Lock()
_cached_leader_data = {"running": False, "pid": "", "connected": False, "error": None}
_leader_poll_thread: Optional[threading.Thread] = None


def _background_leader_poller():
    """Background non-blocking worker polling Mac Mini leader arm status at 1 Hz."""
    global _cached_leader_data
    while True:
        try:
            req = urllib.request.Request(f"{get_mac_api_url()}/api/status", headers={"User-Agent": "SO101-MasterApi"})
            with urllib.request.urlopen(req, timeout=0.8) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode())
                    leader = data.get("leader", data) if isinstance(data.get("leader"), dict) else data
                    leader["connected"] = True
                    leader["error"] = None
                    with _leader_cache_lock:
                        _cached_leader_data = leader
        except Exception as e:
            with _leader_cache_lock:
                _cached_leader_data = {"running": False, "pid": "", "connected": False, "error": str(e)}
        time.sleep(1.0)


def ensure_leader_poller_started():
    global _leader_poll_thread
    if _leader_poll_thread is None or not _leader_poll_thread.is_alive():
        _leader_poll_thread = threading.Thread(target=_background_leader_poller, daemon=True, name="MacLeaderPoller")
        _leader_poll_thread.start()


def play_chime(kind: str = "incorrect") -> None:
    """Dispatches sound playback event to Pi 4B audio service asynchronously."""
    def _work():
        try:
            payload = json.dumps({"kind": kind}).encode("utf-8")
            req = urllib.request.Request(get_pi4b_sound_url(), data=payload, headers={"Content-Type": "application/json"})
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
        logging.info("MasterApiHandler.do_GET: path=%r, parsed.path=%r", self.path, parsed.path)
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
            if hasattr(self.backend, "pokeball_service") and self.backend.pokeball_service:
                pokeball_data = self.backend.pokeball_service.get_telemetry()
            elif os.path.exists("/tmp/pokeball_telemetry.json"):
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
            with _leader_cache_lock:
                leader_data = dict(_cached_leader_data)

            with self.backend.lock:
                left_b, right_b = self.backend.get_s8_bounds()
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
                    for sid_int in range(1, 7):
                        sid_str = str(sid_int)
                        mname = motor_names[sid_str]
                        s_entry = self.backend.servos.get(sid_int, {})
                        arm_data[sid_str] = {
                            "id": sid_int,
                            "name": mname,
                            "raw": s_entry.get("raw"),
                            "pos": s_entry.get("pos"),
                            "normalized": s_entry.get("normalized"),
                            "torque": s_entry.get("torque", False),
                            "connected": s_entry.get("connected", False),
                        }

                servos_map = arm_data
                s7_pos = self.backend.aux_positions.get(7)
                s7_raw = self.backend.raw_positions.get(7)
                c7 = self.backend.get_s7_center_ticks()
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

                resp = {
                    "status": "ok",
                    "hardware_connected": self.backend.hardware_active,
                    "power_state": power_state,
                    "pogo_connected": power_summary.get("pogo_connected", False),
                    "bus_voltage": power_summary.get("voltage", 0.0),
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
                bb_app = self.app_manager.active_app if (self.app_manager.current_app_name == "beat_bandit_app") else None
                if bb_app and hasattr(bb_app, "get_status"):
                    resp["beat_bandit"] = bb_app.get_status()
                else:
                    resp["beat_bandit"] = {
                        "state": "IDLE",
                        "is_running": False,
                        "track": None,
                        "progress": 0.0,
                        "tempo": 0.0,
                        "current_beat": 0,
                        "total_beats": 0,
                        "energy_level": "IDLE",
                        "current_move": "Rest Stance",
                        "vocal_power": 0.0,
                        "s7_angle_deg": 0.0,
                    }
            self._send_json(resp)
        elif parsed.path in ["/api/apps", "/api/apps/list"]:
            self._send_json({"status": "ok", "apps": self.app_manager.list_apps()})
        elif parsed.path == "/api/apps/status":
            self._send_json({"status": "ok", "app_manager": self.app_manager.get_status()})
        elif parsed.path == "/api/apps/beat_bandit/status":
            bb_app = self.app_manager.active_app if (self.app_manager.current_app_name == "beat_bandit_app") else None
            st = bb_app.get_status() if (bb_app and hasattr(bb_app, "get_status")) else {"state": "IDLE", "is_running": False}
            self._send_json({"status": "ok", "beat_bandit": st})
        elif parsed.path == "/api/apps/beat_bandit/tracks":
            bb_app = self.app_manager.active_app if (self.app_manager.current_app_name == "beat_bandit_app") else None
            if not bb_app:
                from beat_bandit_app import BeatBanditApp
                temp_app = BeatBanditApp(running_on_pi=False)
                tracks = temp_app.list_tracks()
            else:
                tracks = bb_app.list_tracks()
            self._send_json({"status": "ok", "tracks": tracks})
        elif parsed.path == "/api/apps/beat_bandit/probabilities":
            from beat_studio import get_global_studio_manager
            studio_mgr = get_global_studio_manager()
            try:
                probs = studio_mgr.get_probabilities()
                self._send_json({"status": "ok", "probabilities": probs})
            except Exception as e:
                self._send_json({"status": "error", "message": str(e)}, 500)
        elif parsed.path in ["/api/apps/beat_bandit/choreo", "/api/apps/beat_bandit/choreography"]:
            query = urllib.parse.parse_qs(parsed.query)
            track_id = query.get("track_id", [None])[0]
            from beat_studio import get_global_studio_manager
            studio_mgr = get_global_studio_manager()
            if not track_id:
                bb_app = self.app_manager.active_app if (self.app_manager.current_app_name == "beat_bandit_app") else None
                if bb_app and bb_app.active_track:
                    track_id = bb_app.active_track.get("track_id")
                else:
                    manifest = studio_mgr._load_manifest()
                    if manifest:
                        track_id = list(manifest.keys())[0]
            if not track_id:
                return self._send_json({"status": "error", "message": "No track ID available"}, 400)
            try:
                choreo = studio_mgr.get_track_choreography(track_id)
                self._send_json({"status": "ok", "choreography": choreo})
            except Exception as e:
                self._send_json({"status": "error", "message": str(e)}, 500)
        elif parsed.path == "/api/arm/presets":
            if not self.backend:
                return self._send_json({"error": "Backend uninitialized"}, 500)
            query = urllib.parse.parse_qs(parsed.query)
            mode = query.get("mode", ["normal"])[0]
            presets = self.backend.get_arm_presets(mode=mode)
            self._send_json({"status": "ok", "mode": mode, "presets": presets})
        elif parsed.path == "/api/arm/sequences":
            if not self.backend:
                return self._send_json({"error": "Backend uninitialized"}, 500)
            query = urllib.parse.parse_qs(parsed.query)
            mode = query.get("mode", [None])[0]
            sequences = self.backend.list_sequences(mode=mode)
            self._send_json({"status": "ok", "mode": mode or "all", "sequences": sequences})
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

            center_s7 = self.backend.get_s7_center_ticks()
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
            if sid == 7:
                center_s7 = self.backend.get_s7_center_ticks()
                if "angle" in body:
                    target_pos = degrees_to_ticks_s7(float(body["angle"]), center_ticks=center_s7)
                elif "target" in body:
                    target_pos = int(body["target"])
                else:
                    return self._send_json({"status": "error", "message": "Missing 'angle' or 'target' for Servo 7"}, 400)
            elif sid == 8:
                if "target" not in body:
                    return self._send_json({"status": "error", "message": "Missing 'target' for Servo 8"}, 400)
                target_pos = int(body["target"])
            else:
                return self._send_json({"status": "error", "message": f"Invalid auxiliary motor ID {sid}"}, 400)

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
            if sid == 8:
                synced_val = self.backend.sync_servo8_position(pos)
                if synced_val is None:
                    return self._send_json({"status": "error", "message": "Failed to sync Motor 8 state"}, 500)
            else:
                with self.backend.lock:
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
                    self.backend.set_arm_torque(False)
                except Exception as e:
                    logging.warning(f"Follower stop torque disarm warning: {e}")
                self.backend.follower_active = False
                self.app_manager.stop_app("teleop_app")
                self._send_json({"status": "ok", "action": action, "running": False})
            elif action == "start":
                try:
                    self.backend.set_arm_torque(True)
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
                req = urllib.request.Request(f"{get_mac_api_url()}/api/leader_toggle", data=post_data, headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=1.5) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    self._send_json(data, resp.status)
            except Exception as e:
                self._send_json({"status": "error", "message": f"Mac HTTP API error: {e}"}, 500)

        elif parsed.path == "/api/apps/start":
            app_name = body.get("name") or body.get("app")
            if not app_name:
                play_chime("incorrect")
                return self._send_json({"error": "Missing required 'name' parameter"}, 400)
            ok = self.app_manager.start_app_by_name(app_name)
            if ok:
                play_chime("connect")
            else:
                play_chime("incorrect")
            self._send_json({"status": "ok" if ok else "error", "app_name": app_name, "running": ok})

        elif parsed.path == "/api/apps/stop":
            app_name = body.get("name") or body.get("app")
            if app_name:
                self.app_manager.stop_app(app_name)
            else:
                self.app_manager.stop_all()
            play_chime("disconnect")
            self._send_json({"status": "ok", "message": f"Stopped app {app_name if app_name else 'all'}"})

        elif parsed.path == "/api/pokeball_teleop_toggle":
            action = body.get("action", "toggle")
            is_running = (self.app_manager.current_app_name == "pokeball_teleop_app")
            if action == "toggle":
                action = "stop" if is_running else "start"

            if action in ["stop", "kill"]:
                self.app_manager.stop_app("pokeball_teleop_app")
                play_chime("disconnect")
                self._send_json({"status": "ok", "action": action, "running": False})
            else:
                ok = self.app_manager.start_app_by_name("pokeball_teleop_app")
                play_chime("connect" if ok else "incorrect")
                self._send_json({"status": "ok" if ok else "error", "action": "start", "running": ok})

        elif parsed.path == "/api/servo_studio_toggle":
            action = body.get("action", "toggle")
            is_running = (self.app_manager.current_app_name == "servo_studio_app")
            if action == "toggle":
                action = "stop" if is_running else "start"

            if action in ["stop", "kill"]:
                self.app_manager.stop_app("servo_studio_app")
                play_chime("disconnect")
                self._send_json({"status": "ok", "action": action, "running": False})
            else:
                ok = self.app_manager.start_app_by_name("servo_studio_app")
                play_chime("connect" if ok else "incorrect")
                self._send_json({"status": "ok" if ok else "error", "action": "start", "running": ok})

        elif parsed.path == "/api/clack_pose_toggle":
            if "action" not in body:
                raise KeyError("Mandatory 'action' field missing from request payload")
            action = str(body["action"]).lower()
            is_running = (self.app_manager.current_app_name in ["clack_pose_app", "piranha_pose_app"])
            if action == "toggle":
                action = "stop" if is_running else "start"

            if action in ["stop", "kill"]:
                self.app_manager.stop_app("piranha_pose_app")
                self.app_manager.stop_app("clack_pose_app")
                play_chime("disconnect")
                self._send_json({"status": "ok", "action": action, "running": False})
            elif action == "start":
                ok = self.app_manager.start_app_by_name("piranha_pose_app")
                if not ok:
                    ok = self.app_manager.start_app_by_name("clack_pose_app")
                play_chime("connect" if ok else "incorrect")
                self._send_json({"status": "ok" if ok else "error", "action": "start", "running": ok})
            else:
                self._send_json({"status": "error", "message": f"Unsupported action '{action}'"}, 400)

        elif parsed.path == "/api/beat_bandit_toggle":
            action = body.get("action", "toggle")
            is_running = (self.app_manager.current_app_name == "beat_bandit_app")
            if action == "toggle":
                action = "stop" if is_running else "start"

            if action in ["stop", "kill"]:
                self.app_manager.stop_app("beat_bandit_app")
                play_chime("disconnect")
                self._send_json({"status": "ok", "action": action, "running": False})
            else:
                ok = self.app_manager.start_app_by_name("beat_bandit_app")
                play_chime("connect" if ok else "incorrect")
                self._send_json({"status": "ok" if ok else "error", "action": "start", "running": ok})

        elif parsed.path == "/api/apps/beat_bandit/start":
            if not self.backend:
                play_chime("incorrect")
                return self._send_json({"error": "Backend uninitialized"}, 500)
            url_or_id = body.get("url") or body.get("track_id")
            if not url_or_id:
                play_chime("incorrect")
                return self._send_json({"status": "error", "message": "Missing required parameter 'url' or 'track_id'"}, 400)

            start_sec = float(body.get("start_sec", 0.0))
            end_sec = float(body.get("end_sec")) if (body.get("end_sec") is not None and str(body.get("end_sec")) != "") else None
            loop = bool(body.get("loop", False))
            
            # Auto-engage beat_bandit_app session if not already active
            if self.app_manager.current_app_name != "beat_bandit_app":
                ok = self.app_manager.start_app_by_name("beat_bandit_app")
                if not ok:
                    play_chime("incorrect")
                    return self._send_json({"status": "error", "message": "Failed to activate Beat Bandit application session."}, 500)

            bb_app = self.app_manager.active_app
            if bb_app and hasattr(bb_app, "start_track_by_url_or_id"):
                res = bb_app.start_track_by_url_or_id(self.backend, url_or_id, start_sec=start_sec, end_sec=end_sec, loop=loop)
                self._send_json(res)
            else:
                play_chime("incorrect")
                self._send_json({"status": "error", "message": "Failed to activate BeatBanditApp"}, 500)

        elif parsed.path == "/api/apps/beat_bandit/stop":
            bb_app = self.app_manager.active_app if (self.app_manager.current_app_name == "beat_bandit_app") else None
            if bb_app and hasattr(bb_app, "stop_dance"):
                bb_app.stop_dance()
            self._send_json({"status": "ok", "action": "stopped"})

        elif parsed.path == "/api/apps/beat_bandit/save_choreo":
            track_id = body.get("track_id")
            choreo = body.get("choreography")
            if not track_id or not choreo:
                return self._send_json({"status": "error", "message": "Missing required fields 'track_id' and 'choreography'"}, 400)
            from beat_studio import get_global_studio_manager
            studio_mgr = get_global_studio_manager()
            try:
                res = studio_mgr.save_track_choreography(track_id, choreo)
                bb_app = self.app_manager.active_app if (self.app_manager.current_app_name == "beat_bandit_app") else None
                if bb_app and bb_app.active_track and bb_app.active_track.get("track_id") == track_id:
                    bb_app.active_track["choreography"] = choreo
                self._send_json(res)
            except Exception as e:
                self._send_json({"status": "error", "message": str(e)}, 500)

        elif parsed.path == "/api/apps/beat_bandit/probabilities":
            if "probabilities" not in body or not isinstance(body["probabilities"], dict):
                raise KeyError("Mandatory 'probabilities' dictionary object missing from request payload")
            probs = body["probabilities"]
            track_id = body.get("track_id")
            from beat_studio import get_global_studio_manager
            studio_mgr = get_global_studio_manager()
            try:
                studio_mgr.save_probabilities(probs)
                updated_choreo = None
                if track_id:
                    updated_choreo = studio_mgr.auto_generate_choreography(track_id)
                    bb_app = self.app_manager.active_app if (self.app_manager.current_app_name == "beat_bandit_app") else None
                    if bb_app and bb_app.active_track and bb_app.active_track.get("track_id") == track_id:
                        bb_app.active_track["choreography"] = updated_choreo
                self._send_json({"status": "ok", "probabilities": probs, "choreography": updated_choreo})
            except Exception as e:
                self._send_json({"status": "error", "message": str(e)}, 500)

        elif parsed.path == "/api/apps/beat_bandit/auto_generate":
            track_id = body.get("track_id")
            style = body.get("style", "balanced")
            force_clean = bool(body.get("force_clean", False))
            if not track_id:
                return self._send_json({"status": "error", "message": "Missing 'track_id'"}, 400)
            from beat_studio import get_global_studio_manager
            studio_mgr = get_global_studio_manager()
            try:
                choreo = studio_mgr.auto_generate_choreography(track_id, style=style, force_clean=force_clean)
                self._send_json({"status": "ok", "choreography": choreo})
            except Exception as e:
                self._send_json({"status": "error", "message": str(e)}, 500)

        elif parsed.path == "/api/apps/beat_bandit/preview_pose":
            pose = body.get("pose")
            if not pose:
                return self._send_json({"status": "error", "message": "Missing 'pose' dictionary"}, 400)
            from beat_studio import get_global_studio_manager
            studio_mgr = get_global_studio_manager()
            try:
                res = studio_mgr.preview_pose_on_robot(self.backend, pose)
                self._send_json(res)
            except Exception as e:
                self._send_json({"status": "error", "message": str(e)}, 500)

        elif parsed.path == "/api/apps/beat_bandit/capture_pose":
            pose_name = body.get("name", f"pose_{int(time.time())}")
            from beat_studio import get_global_studio_manager
            studio_mgr = get_global_studio_manager()
            try:
                res = studio_mgr.capture_arm_current_pose(self.backend, pose_name)
                self._send_json(res)
            except Exception as e:
                self._send_json({"status": "error", "message": str(e)}, 500)

        elif parsed.path == "/api/apps/beat_bandit/preview_movement":
            channel = body.get("channel")
            target_val = body.get("target")
            if not channel or target_val is None:
                return self._send_json({"status": "error", "message": "Missing 'channel' or 'target' parameter"}, 400)
            from beat_studio import get_global_studio_manager
            studio_mgr = get_global_studio_manager()
            try:
                res = studio_mgr.preview_movement_block(self.backend, channel, target_val)
                self._send_json(res)
            except Exception as e:
                self._send_json({"status": "error", "message": str(e)}, 500)

        elif parsed.path == "/api/apps/beat_bandit/preview_block":
            if not self.backend:
                return self._send_json({"error": "Backend uninitialized"}, 500)
            if "track_id" not in body or "channel" not in body or "block" not in body:
                return self._send_json({"status": "error", "message": "Missing 'track_id', 'channel', or 'block' in request body"}, 400)

            track_id = body["track_id"]
            channel = body["channel"]
            block = body["block"]

            # Auto-engage beat_bandit_app session if not already active
            if self.app_manager.current_app_name != "beat_bandit_app":
                ok = self.app_manager.start_app_by_name("beat_bandit_app")
                if not ok:
                    return self._send_json({"status": "error", "message": "Failed to activate Beat Bandit application session."}, 500)

            bb_app = self.app_manager.active_app
            if bb_app and hasattr(bb_app, "preview_isolated_block"):
                try:
                    res = bb_app.preview_isolated_block(self.backend, track_id, channel, block)
                    self._send_json(res)
                except Exception as e:
                    self._send_json({"status": "error", "message": str(e)}, 500)
            else:
                self._send_json({"status": "error", "message": "Failed to access BeatBanditApp"}, 500)

        elif parsed.path == "/api/arm/torque":
            if not self.backend:
                return self._send_json({"error": "Backend uninitialized"}, 500)
            enable = body.get("enable", True)
            ok = self.backend.set_arm_torque(enable)
            self._send_json({"status": "ok" if ok else "error", "torque": enable})

        elif parsed.path == "/api/arm/capture_pose":
            if not self.backend:
                return self._send_json({"error": "Backend uninitialized"}, 500)
            try:
                res = self.backend.capture_temporary_arm_pose()
                self._send_json(res)
            except Exception as e:
                self._send_json({"status": "error", "message": str(e)}, 500)

        elif parsed.path == "/api/arm/commit_preset":
            if not self.backend:
                return self._send_json({"error": "Backend uninitialized"}, 500)
            try:
                custom_name = body.get("name")
                mode = body.get("mode", "normal")
                overwrite = bool(body.get("overwrite", False))
                res = self.backend.save_official_arm_preset(custom_name=custom_name, mode=mode, overwrite=overwrite)
                self._send_json(res)
            except Exception as e:
                self._send_json({"status": "error", "message": str(e)}, 500)

        elif parsed.path == "/api/arm/overwrite_preset":
            if not self.backend:
                return self._send_json({"error": "Backend uninitialized"}, 500)
            preset_name = body.get("name")
            if not preset_name:
                return self._send_json({"status": "error", "message": "Missing required 'name' parameter"}, 400)
            mode = body.get("mode", "normal")
            try:
                res = self.backend.overwrite_arm_preset(preset_name=preset_name, mode=mode)
                self._send_json(res)
            except Exception as e:
                self._send_json({"status": "error", "message": str(e)}, 500)

        elif parsed.path == "/api/arm/delete_preset":
            if not self.backend:
                return self._send_json({"error": "Backend uninitialized"}, 500)
            preset_name = body.get("name")
            if not preset_name:
                return self._send_json({"status": "error", "message": "Missing required 'name' parameter"}, 400)
            mode = body.get("mode", "normal")
            res = self.backend.delete_arm_preset(preset_name=preset_name, mode=mode)
            self._send_json(res, 200 if res.get("status") == "ok" else 400)

        elif parsed.path == "/api/arm/resume_last_pose":
            if not self.backend:
                return self._send_json({"error": "Backend uninitialized"}, 500)
            duration = float(body.get("duration", 1.0))
            mode = body.get("mode", "normal")
            ok, msg = self.backend.resume_last_arm_pose(duration=duration, mode=mode)
            self._send_json({"status": "ok" if ok else "error", "message": msg}, 200 if ok else 400)

        elif parsed.path == "/api/arm/move_to_preset":
            if not self.backend:
                return self._send_json({"error": "Backend uninitialized"}, 500)
            preset_name = body.get("name")
            if not preset_name:
                return self._send_json({"status": "error", "message": "Missing required 'name' parameter"}, 400)
            duration = float(body.get("duration", 1.0))
            mode = body.get("mode", "normal")
            ok, msg = self.backend.move_to_specific_arm_preset(preset_name=preset_name, duration=duration, mode=mode)
            self._send_json({"status": "ok" if ok else "error", "name": preset_name, "mode": mode, "message": msg}, 200 if ok else 400)

        elif parsed.path == "/api/arm/move_norm":
            if not self.backend:
                return self._send_json({"error": "Backend uninitialized"}, 500)
            target = body.get("target") or body.get("normalized")
            if not target:
                return self._send_json({"status": "error", "message": "Missing required 'target' parameter"}, 400)
            duration = float(body.get("duration", 1.5))
            steps = int(body.get("steps", int(round(duration * 50))))
            ok, msg = self.backend.interpolate_arm_norm(target, duration=duration, steps=steps)
            self._send_json({"status": "ok" if ok else "error", "message": msg, "target": target}, 200 if ok else 400)

        elif parsed.path in ["/api/arm/execute_sequence", "/api/arm/sequence"]:
            if not self.backend:
                return self._send_json({"error": "Backend uninitialized"}, 500)
            seq_name = body.get("sequence", body.get("name", "sequence_attack"))
            mode = body.get("mode", "demo")
            threading.Thread(target=self.backend.execute_sequence, args=(seq_name, mode), daemon=True).start()
            self._send_json({"status": "ok", "action": "sequence_started", "sequence": seq_name, "mode": mode})

        elif parsed.path in ["/api/arm/attack_sequence", "/api/arm/attack"]:
            if not self.backend:
                return self._send_json({"error": "Backend uninitialized"}, 500)
            threading.Thread(target=self.backend.execute_attack_sequence, daemon=True).start()
            self._send_json({"status": "ok", "action": "attack_sequence_started"})

        elif parsed.path == "/api/arm/stop_sequence":
            if not self.backend:
                return self._send_json({"error": "Backend uninitialized"}, 500)
            self.backend.stop_sequence()
            self._send_json({"status": "ok", "action": "sequence_stopped"})

        elif parsed.path == "/api/kill_all":
            try:
                post_data = json.dumps({"action": "stop"}).encode("utf-8")
                req = urllib.request.Request(f"{get_mac_api_url()}/api/leader_toggle", data=post_data, headers={"Content-Type": "application/json"})
                urllib.request.urlopen(req, timeout=1.0)
            except Exception as e:
                logging.warning(f"Kill all Mac leader HTTP error: {e}")

            if self.backend:
                self.backend.disable_all_torque()
                self.backend.follower_active = False

            self.app_manager.stop_all()
            self._send_json({"status": "ok", "message": "All teleoperation processes killed and torque disarmed."})

        else:
            self._send_json({"error": "Endpoint not found"}, 404)


def create_master_http_server(host: str, port: int, backend: RobotBackend, app_manager: AppManager) -> ThreadedHTTPServer:
    ensure_leader_poller_started()
    MasterApiHandler.backend = backend
    MasterApiHandler.app_manager = app_manager
    return ThreadedHTTPServer((host, port), MasterApiHandler)
