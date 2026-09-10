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

from robot_backend import RobotBackend, ticks_to_degrees_s7, degrees_to_ticks_s7, pct_to_ticks_s7, ticks_to_pct_s7
from app_manager import AppManager
from apps.teleop_app.app import TeleopControlApp
from apps.servo_studio.app import ServoStudioApp
from apps.pokeball_app.app import PokeballApp, PokeballService
import threading

try:
    import network_resolver
except ImportError:
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import network_resolver

import audio_resolver


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
                    leader = data
                    if "leader" in data and isinstance(data["leader"], dict):
                        leader = data["leader"]
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


_CHIME_CALLBACK = None


def set_chime_callback(cb) -> None:
    global _CHIME_CALLBACK
    _CHIME_CALLBACK = cb


def play_chime(kind: str = "incorrect") -> None:
    """Dispatches sound playback event to Pi 4B audio service asynchronously."""
    global _CHIME_CALLBACK
    if _CHIME_CALLBACK is not None:
        try:
            _CHIME_CALLBACK(kind=kind)
            return
        except Exception as e:
            logging.exception("Direct chime callback failed for '%s': %s", kind, e)

    try:
        sound_file = audio_resolver.get_audio_filename(kind)
    except KeyError as e:
        logging.exception("play_chime: audio event '%s' not registered in config/audio_files.json: %s", kind, e)
        raise
    event_name = kind

    def _work():
        try:
            payload = json.dumps({
                "kind": sound_file,
                "event": event_name,
                "wav_path": "",
                "stop_previous": False,
                "delay_sec": 0.0
            }).encode("utf-8")
            req = urllib.request.Request(get_pi4b_sound_url(), data=payload, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                pass
        except Exception as e:
            logging.exception("Failed to dispatch chime '%s' (%s) to Pi 4B: %s", event_name, sound_file, e)
    threading.Thread(target=_work, daemon=True).start()


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """Threaded HTTP server to prevent slow clients from blocking API requests."""
    daemon_threads = True
    allow_reuse_address = True


class MasterApiHandler(BaseHTTPRequestHandler):
    backend: Optional[RobotBackend] = None
    app_manager: Optional[AppManager] = None
    pokeball_service: Optional[Any] = None
    _cached_preset_app: Optional[Any] = None

    @classmethod
    def get_preset_app(cls) -> Any:
        if not cls.app_manager:
            raise RuntimeError("AppManager not initialized")
        if cls.app_manager.current_app_name == "piranha_pose_app" and cls.app_manager.active_app:
            return cls.app_manager.active_app
        if "piranha_pose_app" not in cls.app_manager.registry:
            raise KeyError("Canonical 'piranha_pose_app' not registered in AppManager")
        if cls._cached_preset_app is None:
            cls._cached_preset_app = cls.app_manager.registry["piranha_pose_app"]()
        return cls._cached_preset_app

    @classmethod
    def build_status_dict(cls) -> Dict[str, Any]:
        if not cls.backend or not cls.app_manager:
            return {"error": "Uninitialized components", "status": "error"}

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
        if hasattr(cls.app_manager, "pokeball_service") and cls.app_manager.pokeball_service:
            pokeball_data = cls.app_manager.pokeball_service.get_telemetry()

        follower_pid = ""
        if cls.backend.follower_active:
            follower_pid = str(os.getpid())
        follower_data = {
            "running": cls.backend.follower_active,
            "pid": follower_pid,
        }
        with _leader_cache_lock:
            leader_data = dict(_cached_leader_data)

        with cls.backend.lock:
            left_b, right_b = cls.backend.get_s8_bounds()
            gantry_pos = cls.backend.gantry_position

            span = max(1, abs(right_b - left_b))
            pct = None
            if gantry_pos is not None:
                pct = round(max(0.0, min(100.0, ((gantry_pos - left_b) / span) * 100.0)), 1)

            arm_data = {}
            motor_names = {
                "1": "shoulder_pan",
                "2": "shoulder_lift",
                "3": "elbow_flex",
                "4": "wrist_flex",
                "5": "wrist_roll",
                "6": "gripper",
            }
            if cls.backend.bus is not None:
                for sid_int in range(1, 7):
                    sid_str = str(sid_int)
                    mname = motor_names[sid_str]
                    s_entry = cls.backend.servos[sid_int]
                    s_torque = False
                    if "torque" in s_entry:
                        s_torque = bool(s_entry["torque"])
                    s_conn = False
                    if "connected" in s_entry:
                        s_conn = bool(s_entry["connected"])
                    s_raw = None
                    if "raw" in s_entry:
                        s_raw = s_entry["raw"]
                    s_pos = None
                    if "pos" in s_entry:
                        s_pos = s_entry["pos"]
                    s_norm = None
                    if "normalized" in s_entry:
                        s_norm = s_entry["normalized"]
                    arm_data[sid_str] = {
                        "id": sid_int,
                        "name": mname,
                        "raw": s_raw,
                        "pos": s_pos,
                        "normalized": s_norm,
                        "torque": s_torque,
                        "connected": s_conn,
                    }

            servos_map = arm_data
            s7_pos = cls.backend.aux_positions.get(7)
            s7_raw = cls.backend.raw_positions.get(7)
            c7 = cls.backend.get_s7_center_ticks()
            s7_angle = None
            s7_pct = None
            if s7_pos is not None:
                s7_angle = ticks_to_degrees_s7(s7_pos, center_ticks=c7)
                s7_pct = ticks_to_pct_s7(s7_pos, cls.backend.aux_calibration)
            s7_torque = True
            if 7 in cls.backend.torque_state:
                s7_torque = cls.backend.torque_state[7]
            s7_moving = False
            if 7 in cls.backend.is_moving:
                s7_moving = cls.backend.is_moving[7]
            servos_map["7"] = {
                "pos": s7_pos,
                "raw": s7_raw,
                "angle": s7_angle,
                "pct": s7_pct,
                "normalized": s7_pct,
                "torque": s7_torque,
                "is_moving": s7_moving,
                "connected": s7_pos is not None,
            }

            s8_pos = cls.backend.gantry_position
            s8_raw = cls.backend.raw_positions.get(8)
            s8_torque = True
            if 8 in cls.backend.torque_state:
                s8_torque = cls.backend.torque_state[8]
            s8_moving = False
            if 8 in cls.backend.is_moving:
                s8_moving = cls.backend.is_moving[8]
            servos_map["8"] = {
                "pos": s8_pos,
                "raw": s8_raw,
                "pct": pct,
                "torque": s8_torque,
                "is_moving": s8_moving,
                "connected": s8_pos is not None,
            }

            if cls.backend.power_mgr:
                power_summary = cls.backend.power_mgr.get_state_summary()
            else:
                power_summary = {
                    "state": "UNINITIALIZED",
                    "connected": False,
                    "pogo_connected": False,
                    "voltage": 0.0,
                    "error": "BusPowerManager uninitialized"
                }
            power_state = power_summary["state"]
            active_error = power_summary["error"] or cls.backend.error_msg
            if power_state in ["CONNECTED", "POGO_DISCONNECTED"]:
                all_errors = [m.get("error") for m in cls.backend.motor_states.values() if m.get("error")]
                if not all_errors and power_state == "CONNECTED":
                    active_error = None

            pogo_conn = False
            if "pogo_connected" in power_summary:
                pogo_conn = bool(power_summary["pogo_connected"])
            bus_volt = 0.0
            if "voltage" in power_summary:
                bus_volt = float(power_summary["voltage"])

            resp = {
                "status": "ok",
                "hardware_connected": cls.backend.hardware_active,
                "power_state": power_state,
                "pogo_connected": pogo_conn,
                "bus_voltage": bus_volt,
                "current_app": cls.app_manager.current_app_name,
                "active_port": cls.backend.active_port,
                "error": active_error,
                "apps": cls.app_manager.list_apps(),
                "app_manager_status": cls.app_manager.get_status(),
                "follower": follower_data,
                "leader": leader_data,
                "pokeball": pokeball_data,
                "servos": servos_map,
                "aux_calibration": cls.backend.aux_calibration,
                "wlan0_ip": network_resolver.get_interface_ip("wlan0"),
            }
            bb_app = cls.app_manager.active_app if (cls.app_manager.current_app_name == "beat_bandit_app") else None
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
            l_app = cls.app_manager.active_app if (cls.app_manager.current_app_name == "listener_app") else None
            if l_app and hasattr(l_app, "get_status"):
                resp["listener"] = l_app.get_status()
            else:
                resp["listener"] = {
                    "name": "listener_app",
                    "state": "IDLE",
                    "transcript": "(none)",
                    "action_taken": "Awaiting voice command",
                    "search_query": "",
                    "search_results": [],
                    "selected_index": 0,
                    "error": "",
                }
        return resp

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
            return self._send_json(self.build_status_dict())
        elif parsed.path in ["/api/apps", "/api/apps/list"]:
            self._send_json({"status": "ok", "apps": self.app_manager.list_apps()})
        elif parsed.path == "/api/apps/status":
            self._send_json({"status": "ok", "app_manager": self.app_manager.get_status()})
        elif parsed.path == "/api/apps/listener/status":
            l_app = self.app_manager.active_app if (self.app_manager.current_app_name == "listener_app") else None
            st = {"name": "listener_app", "state": "IDLE", "search_query": "", "search_results": [], "selected_index": 0, "error": ""}
            if l_app and hasattr(l_app, "get_status"):
                st = l_app.get_status()
            self._send_json({"status": "ok", "listener": st})
        elif parsed.path == "/api/apps/beat_bandit/status":
            bb_app = None
            if self.app_manager.current_app_name == "beat_bandit_app":
                bb_app = self.app_manager.active_app
            st = {"state": "IDLE", "is_running": False}
            if bb_app and hasattr(bb_app, "get_status"):
                st = bb_app.get_status()
            self._send_json({"status": "ok", "beat_bandit": st})
        elif parsed.path == "/api/apps/beat_bandit/tracks":
            bb_app = self.app_manager.active_app if (self.app_manager.current_app_name == "beat_bandit_app") else None
            if not bb_app:
                from apps.beat_bandit.app import BeatBanditApp
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
            track_id = None
            if "track_id" in query and query["track_id"]:
                track_id = query["track_id"][0]
            from beat_studio import get_global_studio_manager
            studio_mgr = get_global_studio_manager()
            if not track_id:
                bb_app = None
                if self.app_manager.current_app_name == "beat_bandit_app":
                    bb_app = self.app_manager.active_app
                if bb_app and hasattr(bb_app, "active_track") and bb_app.active_track:
                    if "track_id" in bb_app.active_track:
                        track_id = bb_app.active_track["track_id"]
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
            preset_app = self.get_preset_app()
            query = urllib.parse.parse_qs(parsed.query)
            mode = "normal"
            if "mode" in query and query["mode"]:
                mode = query["mode"][0]
            presets = preset_app.get_arm_presets(mode=mode)
            self._send_json({"status": "ok", "mode": mode, "presets": presets})
        elif parsed.path == "/api/arm/sequences":
            preset_app = self.get_preset_app()
            query = urllib.parse.parse_qs(parsed.query)
            mode = None
            if "mode" in query and query["mode"]:
                mode = query["mode"][0]
            sequences = preset_app.list_sequences(mode=mode)
            disp_mode = "all"
            if mode:
                disp_mode = mode
            self._send_json({"status": "ok", "mode": disp_mode, "sequences": sequences})
        elif parsed.path == "/api/pokeball_reconnect":
            self.app_manager.start_app_by_name("pokeball_teleop_app")
            self._send_json({"status": "ok", "message": "Poké Ball teleop app restart triggered"})
        else:
            self._send_json({"status": "ok", "service": "so101_master_api"})

    def do_POST(self) -> None:
        content_length = 0
        if "Content-Length" in self.headers:
            try:
                content_length = int(self.headers["Content-Length"])
            except ValueError:
                content_length = 0
        body = {}
        if content_length > 0:
            body_bytes = self.rfile.read(content_length)
            try:
                body = json.loads(body_bytes.decode("utf-8"))
            except Exception as e:
                logging.exception("Failed to decode JSON payload in do_POST: %s", e)
                return self._send_json({"status": "error", "message": f"Malformed JSON payload: {e}"}, 400)
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
            if "direction" not in body:
                return self._send_json({"status": "error", "message": "Missing required 'direction' parameter"}, 400)
            direction = str(body["direction"]).lower()
            ok, moved, msg, target_deg, target_ticks, at_limit = self.backend.step_pedestal_preset(direction)
            if not ok:
                self._send_json({"status": "error", "message": msg}, 400)
            else:
                if not moved and at_limit:
                    play_chime("incorrect")
                elif moved:
                    play_chime("smw_pipe")
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
                if "direction" in body:
                    direction = str(body["direction"]).lower()
                else:
                    direction = str(body["step"]).lower()
                ok, moved, msg, target_deg, target_ticks, at_limit = self.backend.step_pedestal_preset(direction)
                if not ok:
                    return self._send_json({"status": "error", "message": msg}, 400)
                if not moved and at_limit:
                    play_chime("incorrect")
                elif moved:
                    play_chime("smw_pipe")
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
                resp_angle = None
                if sid == 7:
                    resp_angle = ticks_to_degrees_s7(target_pos, center_ticks=center_s7)
                self._send_json({"status": "ok", "id": sid, "target_pos": target_pos, "angle": resp_angle})

        elif parsed.path == "/api/nudge_physical":
            if "id" not in body:
                return self._send_json({"status": "error", "message": "Missing required 'id' parameter"}, 400)
            if "direction" not in body:
                return self._send_json({"status": "error", "message": "Missing required 'direction' parameter"}, 400)
            sid = int(body["id"])
            direction = str(body["direction"]).lower()
            amount = 100
            if "amount" in body:
                amount = abs(int(body["amount"]))
            if direction == "right":
                delta = amount
            else:
                delta = -amount

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

            toggle = True
            if "toggle" in body:
                toggle = bool(body["toggle"])
            with self.backend.lock:
                if toggle:
                    new_state = not self.backend.torque_state[sid]
                else:
                    new_state = False
                    if "enable" in body:
                        new_state = bool(body["enable"])
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

        elif parsed.path == "/api/follower_toggle":
            if "action" not in body:
                return self._send_json({"status": "error", "message": "Missing required 'action' parameter"}, 400)
            action = str(body["action"]).lower()
            if action == "toggle":
                if self.backend.follower_active:
                    action = "stop"
                else:
                    action = "start"

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
            if "action" not in body:
                return self._send_json({"status": "error", "message": "Missing required 'action' parameter"}, 400)
            action = str(body["action"]).lower()
            try:
                post_data = json.dumps({"action": action}).encode("utf-8")
                req = urllib.request.Request(f"{get_mac_api_url()}/api/leader_toggle", data=post_data, headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=1.5) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    self._send_json(data, resp.status)
            except Exception as e:
                self._send_json({"status": "error", "message": f"Mac HTTP API error: {e}"}, 500)

        elif parsed.path == "/api/apps/start":
            app_name = None
            if "name" in body:
                app_name = body["name"]
            elif "app" in body:
                app_name = body["app"]
            if not app_name:
                play_chime("incorrect")
                return self._send_json({"error": "Missing required 'name' parameter"}, 400)
            ok = self.app_manager.start_app_by_name(app_name)
            if not ok:
                play_chime("incorrect")
            self._send_json({"status": "ok" if ok else "error", "app_name": app_name, "running": ok})

        elif parsed.path == "/api/apps/stop":
            app_name = None
            if "name" in body:
                app_name = body["name"]
            elif "app" in body:
                app_name = body["app"]
            if app_name:
                self.app_manager.stop_app(app_name)
            else:
                self.app_manager.stop_all()
            self._send_json({"status": "ok", "message": f"Stopped app {app_name if app_name else 'all'}"})

        elif parsed.path == "/api/apps/listener/select":
            l_app = self.app_manager.active_app if (self.app_manager.current_app_name == "listener_app") else None
            if not l_app or not hasattr(l_app, "select_track"):
                return self._send_json({"status": "error", "message": "ListenerApp is not currently active"}, 400)
            if "index" not in body or body["index"] is None:
                return self._send_json({"status": "error", "message": "Missing required 'index' field in select payload"}, 400)
            idx = int(body["index"])
            try:
                res_track = l_app.select_track(index=idx)
                self._send_json({"status": "ok", "selected_index": idx, "track": res_track})
            except (IndexError, ValueError) as err:
                self._send_json({"status": "error", "message": str(err)}, 400)

        elif parsed.path == "/api/apps/listener/analyze":
            l_app = self.app_manager.active_app if (self.app_manager.current_app_name == "listener_app") else None
            if not l_app or not hasattr(l_app, "trigger_analysis"):
                return self._send_json({"status": "error", "message": "ListenerApp is not currently active"}, 400)
            if "index" not in body or body["index"] is None:
                return self._send_json({"status": "error", "message": "Missing required 'index' field in analyze payload"}, 400)
            idx = int(body["index"])
            try:
                res_track = l_app.trigger_analysis(index=idx)
                self._send_json({"status": "ok", "action": "analyze", "selected_index": idx, "track": res_track})
            except (IndexError, ValueError, RuntimeError) as err:
                self._send_json({"status": "error", "message": str(err)}, 400)

        elif parsed.path == "/api/apps/listener/navigate":
            l_app = self.app_manager.active_app if (self.app_manager.current_app_name == "listener_app") else None
            if not l_app or not hasattr(l_app, "navigate_selection"):
                return self._send_json({"status": "error", "message": "ListenerApp is not currently active"}, 400)
            if "delta" in body:
                delta = int(body["delta"])
            elif "direction" in body:
                direction_str = str(body["direction"]).lower()
                if direction_str == "up":
                    delta = -1
                elif direction_str == "down":
                    delta = 1
                else:
                    return self._send_json({"status": "error", "message": f"Invalid direction '{direction_str}'. Expected 'up' or 'down'"}, 400)
            else:
                return self._send_json({"status": "error", "message": "Missing required field 'delta' or 'direction' in navigate payload"}, 400)
            new_idx = l_app.navigate_selection(delta)
            self._send_json({"status": "ok", "selected_index": new_idx})

        elif parsed.path == "/api/apps/listener/command":
            l_app = self.app_manager.active_app if (self.app_manager.current_app_name == "listener_app") else None
            if not l_app:
                return self._send_json({"status": "error", "message": "ListenerApp is not currently active"}, 400)
            if "command" not in body or not body["command"]:
                return self._send_json({"status": "error", "message": "Missing required 'command' field"}, 400)
            cmd = str(body["command"])
            from apps.listener_app.intent_parser import parse_intent
            intent = parse_intent(cmd)
            intent_type = intent["intent"]
            if intent_type == "POSTURE":
                action = intent["action"]
                l_app._execute_posture(self.backend, action)
                l_app.transcript = cmd
                return self._send_json({"status": "ok", "command": cmd, "intent": intent, "action_taken": l_app.action_taken})
            return self._send_json({"status": "ok", "command": cmd, "intent": intent})

        elif parsed.path == "/api/apps/listener/trigger":
            l_app = self.app_manager.active_app if (self.app_manager.current_app_name == "listener_app") else None
            if not l_app or not hasattr(l_app, "start_listen_event"):
                return self._send_json({"status": "error", "message": "ListenerApp is not currently active"}, 400)
            l_app.start_listen_event.set()
            return self._send_json({"status": "ok", "action": "listen_triggered"})

        elif parsed.path == "/api/pokeball_teleop_toggle":
            if "action" not in body:
                return self._send_json({"status": "error", "message": "Missing required 'action' parameter"}, 400)
            action = str(body["action"]).lower()
            is_running = (self.app_manager.current_app_name == "pokeball_teleop_app")
            if action == "toggle":
                if is_running:
                    action = "stop"
                else:
                    action = "start"

            if action in ["stop", "kill"]:
                self.app_manager.stop_app("pokeball_teleop_app")
                self._send_json({"status": "ok", "action": action, "running": False})
            else:
                ok = self.app_manager.start_app_by_name("pokeball_teleop_app")
                if not ok:
                    play_chime("incorrect")
                self._send_json({"status": "ok" if ok else "error", "action": "start", "running": ok})

        elif parsed.path == "/api/servo_studio_toggle":
            if "action" not in body:
                return self._send_json({"status": "error", "message": "Missing required 'action' parameter"}, 400)
            action = str(body["action"]).lower()
            is_running = (self.app_manager.current_app_name == "servo_studio_app")
            if action == "toggle":
                if is_running:
                    action = "stop"
                else:
                    action = "start"

            if action in ["stop", "kill"]:
                self.app_manager.stop_app("servo_studio_app")
                self._send_json({"status": "ok", "action": action, "running": False})
            else:
                ok = self.app_manager.start_app_by_name("servo_studio_app")
                if not ok:
                    play_chime("incorrect")
                self._send_json({"status": "ok" if ok else "error", "action": "start", "running": ok})

        elif parsed.path == "/api/clack_pose_toggle":
            if "action" not in body:
                return self._send_json({"status": "error", "message": "Missing required 'action' parameter"}, 400)
            action = str(body["action"]).lower()
            is_running = (self.app_manager.current_app_name in ["clack_pose_app", "piranha_pose_app"])
            if action == "toggle":
                if is_running:
                    action = "stop"
                else:
                    action = "start"

            if action in ["stop", "kill"]:
                self.app_manager.stop_app("piranha_pose_app")
                self.app_manager.stop_app("clack_pose_app")
                self._send_json({"status": "ok", "action": action, "running": False})
            elif action == "start":
                ok = self.app_manager.start_app_by_name("piranha_pose_app")
                if not ok:
                    ok = self.app_manager.start_app_by_name("clack_pose_app")
                if not ok:
                    play_chime("incorrect")
                self._send_json({"status": "ok" if ok else "error", "action": "start", "running": ok})
            else:
                self._send_json({"status": "error", "message": f"Unsupported action '{action}'"}, 400)

        elif parsed.path == "/api/beat_bandit_toggle":
            if "action" not in body:
                return self._send_json({"status": "error", "message": "Missing required 'action' parameter"}, 400)
            action = str(body["action"]).lower()
            is_running = (self.app_manager.current_app_name == "beat_bandit_app")
            if action == "toggle":
                if is_running:
                    action = "stop"
                else:
                    action = "start"

            if action in ["stop", "kill"]:
                self.app_manager.stop_app("beat_bandit_app")
                self._send_json({"status": "ok", "action": action, "running": False})
            else:
                ok = self.app_manager.start_app_by_name("beat_bandit_app")
                if not ok:
                    play_chime("incorrect")
                self._send_json({"status": "ok" if ok else "error", "action": "start", "running": ok})

        elif parsed.path == "/api/apps/beat_bandit/start":
            if not self.backend:
                play_chime("incorrect")
                return self._send_json({"error": "Backend uninitialized"}, 500)
            url_or_id = None
            if "url" in body:
                url_or_id = body["url"]
            elif "track_id" in body:
                url_or_id = body["track_id"]
            if not url_or_id:
                play_chime("incorrect")
                return self._send_json({"status": "error", "message": "Missing required parameter 'url' or 'track_id'"}, 400)

            start_sec = 0.0
            if "start_sec" in body:
                start_sec = float(body["start_sec"])
            end_sec = None
            if "end_sec" in body and body["end_sec"] is not None and str(body["end_sec"]) != "":
                end_sec = float(body["end_sec"])
            loop = False
            if "loop" in body:
                loop = bool(body["loop"])
            
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
            if bb_app:
                if not hasattr(bb_app, "stop_and_center"):
                    raise AttributeError("BeatBanditApp is missing required 'stop_and_center' method")
                if not self.backend:
                    raise RuntimeError("Robot backend uninitialized for stop_and_center")
                bb_app.stop_and_center(self.backend)
            self._send_json({"status": "ok", "action": "stopped"})



        elif parsed.path == "/api/apps/beat_bandit/save_choreo":
            track_id = None
            if "track_id" in body:
                track_id = body["track_id"]
            choreo = None
            if "choreography" in body:
                choreo = body["choreography"]
            if not track_id or not choreo:
                return self._send_json({"status": "error", "message": "Missing required fields 'track_id' and 'choreography'"}, 400)
            from beat_studio import get_global_studio_manager
            studio_mgr = get_global_studio_manager()
            try:
                res = studio_mgr.save_track_choreography(track_id, choreo)
                bb_app = None
                if self.app_manager.current_app_name == "beat_bandit_app":
                    bb_app = self.app_manager.active_app
                if bb_app and hasattr(bb_app, "active_track") and bb_app.active_track:
                    if "track_id" in bb_app.active_track and bb_app.active_track["track_id"] == track_id:
                        bb_app.active_track["choreography"] = choreo
                self._send_json(res)
            except Exception as e:
                self._send_json({"status": "error", "message": str(e)}, 500)

        elif parsed.path == "/api/apps/beat_bandit/probabilities":
            if "probabilities" not in body or not isinstance(body["probabilities"], dict):
                raise KeyError("Mandatory 'probabilities' dictionary object missing from request payload")
            probs = body["probabilities"]
            track_id = None
            if "track_id" in body:
                track_id = body["track_id"]
            from beat_studio import get_global_studio_manager
            studio_mgr = get_global_studio_manager()
            try:
                studio_mgr.save_probabilities(probs)
                updated_choreo = None
                if track_id:
                    updated_choreo = studio_mgr.auto_generate_choreography(track_id)
                    bb_app = None
                    if self.app_manager.current_app_name == "beat_bandit_app":
                        bb_app = self.app_manager.active_app
                    if bb_app and hasattr(bb_app, "active_track") and bb_app.active_track:
                        if "track_id" in bb_app.active_track and bb_app.active_track["track_id"] == track_id:
                            bb_app.active_track["choreography"] = updated_choreo
                self._send_json({"status": "ok", "probabilities": probs, "choreography": updated_choreo})
            except Exception as e:
                self._send_json({"status": "error", "message": str(e)}, 500)

        elif parsed.path == "/api/apps/beat_bandit/auto_generate":
            track_id = None
            if "track_id" in body:
                track_id = body["track_id"]
            style = "balanced"
            if "style" in body:
                style = str(body["style"])
            force_clean = False
            if "force_clean" in body:
                force_clean = bool(body["force_clean"])
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
            pose = None
            if "pose" in body:
                pose = body["pose"]
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
            pose_name = f"pose_{int(time.time())}"
            if "name" in body:
                pose_name = str(body["name"])
            from beat_studio import get_global_studio_manager
            studio_mgr = get_global_studio_manager()
            try:
                res = studio_mgr.capture_arm_current_pose(self.backend, pose_name)
                self._send_json(res)
            except Exception as e:
                self._send_json({"status": "error", "message": str(e)}, 500)

        elif parsed.path == "/api/apps/beat_bandit/preview_movement":
            channel = None
            if "channel" in body:
                channel = body["channel"]
            target_val = None
            if "target" in body:
                target_val = body["target"]
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
            enable = True
            if "enable" in body:
                enable = bool(body["enable"])
            ok = self.backend.set_arm_torque(enable)
            self._send_json({"status": "ok" if ok else "error", "torque": enable})

        elif parsed.path == "/api/arm/capture_pose":
            if not self.backend:
                return self._send_json({"error": "Backend uninitialized"}, 500)
            try:
                preset_app = self.get_preset_app()
                res = preset_app.capture_temporary_arm_pose(self.backend)
                self._send_json(res)
            except Exception as e:
                self._send_json({"status": "error", "message": str(e)}, 500)

        elif parsed.path == "/api/arm/commit_preset":
            if not self.backend:
                return self._send_json({"error": "Backend uninitialized"}, 500)
            try:
                custom_name = None
                if "name" in body:
                    custom_name = body["name"]
                mode = "normal"
                if "mode" in body:
                    mode = str(body["mode"])
                overwrite = False
                if "overwrite" in body:
                    overwrite = bool(body["overwrite"])
                preset_app = self.get_preset_app()
                res = preset_app.save_official_arm_preset(self.backend, custom_name=custom_name, mode=mode, overwrite=overwrite)
                self._send_json(res)
            except Exception as e:
                self._send_json({"status": "error", "message": str(e)}, 500)

        elif parsed.path == "/api/arm/overwrite_preset":
            if not self.backend:
                return self._send_json({"error": "Backend uninitialized"}, 500)
            if "name" not in body or not body["name"]:
                return self._send_json({"status": "error", "message": "Missing required 'name' parameter"}, 400)
            preset_name = str(body["name"])
            mode = "normal"
            if "mode" in body:
                mode = str(body["mode"])
            try:
                preset_app = self.get_preset_app()
                res = preset_app.overwrite_arm_preset(self.backend, preset_name=preset_name, mode=mode)
                self._send_json(res)
            except Exception as e:
                self._send_json({"status": "error", "message": str(e)}, 500)

        elif parsed.path == "/api/arm/delete_preset":
            if "name" not in body or not body["name"]:
                return self._send_json({"status": "error", "message": "Missing required 'name' parameter"}, 400)
            preset_name = str(body["name"])
            mode = "normal"
            if "mode" in body:
                mode = str(body["mode"])
            preset_app = self.get_preset_app()
            res = preset_app.delete_arm_preset(preset_name=preset_name, mode=mode)
            status_code = 400
            if "status" in res and res["status"] == "ok":
                status_code = 200
            self._send_json(res, status_code)

        elif parsed.path == "/api/arm/resume_last_pose":
            if not self.backend:
                return self._send_json({"error": "Backend uninitialized"}, 500)
            preset_app = self.get_preset_app()
            if preset_app.config["require_active_app_for_motion"]:
                if not self.app_manager or self.app_manager.current_app_name not in ["piranha_pose_app", "clack_pose_app"]:
                    return self._send_json({
                        "status": "error",
                        "message": "Piranha Pose app is not running. Tap START PIRANHA POSE before commanding motion."
                    }, 409)
            duration = 1.0
            if "duration" in body:
                duration = float(body["duration"])
            mode = "normal"
            if "mode" in body:
                mode = str(body["mode"])
            ok, msg = preset_app.resume_last_arm_pose(self.backend, duration=duration, mode=mode)
            self._send_json({"status": "ok" if ok else "error", "message": msg}, 200 if ok else 400)

        elif parsed.path == "/api/arm/move_to_preset":
            if not self.backend:
                return self._send_json({"error": "Backend uninitialized"}, 500)
            if "name" not in body or not body["name"]:
                return self._send_json({"status": "error", "message": "Missing required 'name' parameter"}, 400)
            preset_app = self.get_preset_app()
            if preset_app.config["require_active_app_for_motion"]:
                if not self.app_manager or self.app_manager.current_app_name not in ["piranha_pose_app", "clack_pose_app"]:
                    return self._send_json({
                        "status": "error",
                        "message": "Piranha Pose app is not running. Tap START PIRANHA POSE before commanding motion."
                    }, 409)
            preset_name = str(body["name"])
            duration = 1.0
            if "duration" in body:
                duration = float(body["duration"])
            mode = "normal"
            if "mode" in body:
                mode = str(body["mode"])
            ok, msg = preset_app.move_to_specific_arm_preset(self.backend, preset_name=preset_name, duration=duration, mode=mode)
            self._send_json({"status": "ok" if ok else "error", "name": preset_name, "mode": mode, "message": msg}, 200 if ok else 400)

        elif parsed.path == "/api/arm/move_norm":
            if not self.backend:
                return self._send_json({"error": "Backend uninitialized"}, 500)
            target = None
            if "target" in body:
                target = body["target"]
            elif "normalized" in body:
                target = body["normalized"]
            if not target:
                return self._send_json({"status": "error", "message": "Missing required 'target' parameter"}, 400)
            duration = 1.5
            if "duration" in body:
                duration = float(body["duration"])
            steps = int(round(duration * 50))
            if "steps" in body:
                steps = int(body["steps"])
            ok, msg = self.backend.interpolate_arm_norm(target, duration=duration, steps=steps)
            self._send_json({"status": "ok" if ok else "error", "message": msg, "target": target}, 200 if ok else 400)

        elif parsed.path in ["/api/arm/execute_sequence", "/api/arm/sequence"]:
            if not self.backend:
                return self._send_json({"error": "Backend uninitialized"}, 500)
            preset_app = self.get_preset_app()
            if preset_app.config["require_active_app_for_motion"]:
                if not self.app_manager or self.app_manager.current_app_name not in ["piranha_pose_app", "clack_pose_app"]:
                    return self._send_json({
                        "status": "error",
                        "message": "Piranha Pose app is not running. Tap START PIRANHA POSE before commanding motion."
                    }, 409)
            seq_name = "sequence_attack"
            if "sequence" in body:
                seq_name = str(body["sequence"])
            elif "name" in body:
                seq_name = str(body["name"])
            mode = "demo"
            if "mode" in body:
                mode = str(body["mode"])
            threading.Thread(target=preset_app.execute_sequence, args=(self.backend, seq_name, mode), daemon=True).start()
            self._send_json({"status": "ok", "action": "sequence_started", "sequence": seq_name, "mode": mode})

        elif parsed.path in ["/api/arm/attack_sequence", "/api/arm/attack"]:
            if not self.backend:
                return self._send_json({"error": "Backend uninitialized"}, 500)
            preset_app = self.get_preset_app()
            if preset_app.config["require_active_app_for_motion"]:
                if not self.app_manager or self.app_manager.current_app_name not in ["piranha_pose_app", "clack_pose_app"]:
                    return self._send_json({
                        "status": "error",
                        "message": "Piranha Pose app is not running. Tap START PIRANHA POSE before commanding motion."
                    }, 409)
            threading.Thread(target=preset_app.execute_attack_sequence, args=(self.backend,), daemon=True).start()
            self._send_json({"status": "ok", "action": "attack_sequence_started"})

        elif parsed.path == "/api/arm/stop_sequence":
            preset_app = self.get_preset_app()
            preset_app.stop_sequence()
            self._send_json({"status": "ok", "action": "sequence_stopped"})

        elif parsed.path == "/api/config/rover_speed":
            if "max_speed_pct" not in body or "max_pulse_offset" not in body:
                return self._send_json({"status": "error", "message": "Missing required keys 'max_speed_pct' or 'max_pulse_offset'"}, 400)
            try:
                pct = int(body["max_speed_pct"])
                offset = int(body["max_pulse_offset"])
            except (ValueError, TypeError) as val_err:
                return self._send_json({"status": "error", "message": f"Invalid integer values: {val_err}"}, 400)

            cfg_dict = {"max_speed_pct": pct, "max_pulse_offset": offset}
            cfg_json = json.dumps(cfg_dict, indent=2)

            for target_path in ["/tmp/rover_config.json", str(Path.home() / "so101" / "config" / "rover_config.json"), "/home/user/so101/config/rover_config.json"]:
                try:
                    os.makedirs(os.path.dirname(target_path), exist_ok=True)
                    tmp_target = target_path + ".tmp"
                    with open(tmp_target, "w") as f:
                        f.write(cfg_json)
                    os.replace(tmp_target, target_path)
                except Exception as w_err:
                    logging.warning(f"Error writing {target_path}: {w_err}")

            self._send_json({"status": "ok", "config": cfg_dict})

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

            preset_app = self.get_preset_app()
            preset_app.stop_sequence()
            self.app_manager.stop_all()
            self._send_json({"status": "ok", "message": "All teleoperation processes killed and torque disarmed."})

        else:
            self._send_json({"error": "Endpoint not found"}, 404)


def create_master_http_server(host: str, port: int, backend: RobotBackend, app_manager: AppManager, pokeball_service: Optional[Any] = None) -> ThreadedHTTPServer:
    ensure_leader_poller_started()
    MasterApiHandler.backend = backend
    MasterApiHandler.app_manager = app_manager
    MasterApiHandler.pokeball_service = pokeball_service
    return ThreadedHTTPServer((host, port), MasterApiHandler)

