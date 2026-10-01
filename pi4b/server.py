#!/usr/bin/env python3
"""Pi 4B Touchscreen Kiosk UI & Unified Robot Backend Server.
Target Deployment: /home/carson/touch_ui/server.py on Pi 4B (192.168.0.86)
Executed by: backend.service (Binds dual ports: 8082 for Touch UI, 8085 for Robot REST API)
"""

import http.server
import json
import logging
import os
import signal
import socket
import socketserver
import subprocess
import sys
import threading
import time
import traceback
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional, Dict, Any, List

# Ensure virtualenv site-packages are available even if started via system Python
venv_site_candidates = [
    "/home/carson/aux_servo_interface/.venv/lib/python3.11/site-packages",
    "/home/carson/touch_ui/.venv/lib/python3.11/site-packages",
    "/home/user/so101/.venv/lib/python3.11/site-packages",
]
for p in venv_site_candidates:
    if os.path.isdir(p) and p not in sys.path:
        sys.path.insert(0, p)

DIRECTORY = os.path.dirname(os.path.abspath(__file__))
if DIRECTORY not in sys.path:
    sys.path.insert(0, DIRECTORY)

# Ensure pi4b subfolder is available if server.py is at repository root
pi4b_dir = os.path.join(DIRECTORY, "pi4b")
if os.path.isdir(pi4b_dir) and pi4b_dir not in sys.path:
    sys.path.insert(0, pi4b_dir)

# If server.py is executing from inside the pi4b subfolder, include repo root
if os.path.basename(DIRECTORY) == "pi4b":
    repo_root = os.path.dirname(DIRECTORY)
    if repo_root not in sys.path and os.path.abspath(repo_root) != os.path.abspath(os.path.expanduser("~")):
        sys.path.insert(0, repo_root)

import network_resolver
import audio_resolver
from robot_backend import RobotBackend
from app_manager import AppManager
from apps.pokeball_app.app import PokeballService
try:
    from apps.joycon_app.app import JoyConService
except ImportError:
    JoyConService = None
from api_server import MasterApiHandler, set_chime_callback, ensure_leader_poller_started

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

PORT_TOUCH_UI = 8082
PORT_MASTER_API = 8085

GLOBAL_BACKEND: Optional[RobotBackend] = None
GLOBAL_APP_MANAGER: Optional[AppManager] = None
GLOBAL_POKEBALL: Optional[PokeballService] = None

STATUS_CACHE: Dict[str, Any] = {
    "pokeball": {"running": False, "connected": False, "status": "DISCONNECTED", "pid": ""},
    "follower": {"running": False, "pid": ""},
    "leader": {"running": False, "pid": ""},
    "clack_pose": {"running": False},
    "ornith_state": "IDLE",
    "topology_mode": "STANDALONE_PI4B",
    "backend_online": False,
    "vosk_ready": False,
    "hardware_telemetry": None,
    "last_telemetry_time": 0,
    "connection_mode": {"mode": "OFFLINE_DIRECT_ETH", "is_offline": True, "is_cloud_enabled": False},
    "pi4b_wlan_ip": None,
}

TAP_DETECTOR = None
TAP_DETECTOR_LOCK = threading.RLock()

def start_tap_detector() -> bool:
    """Safely instantiates and starts AudioTapDetector with active app validation callback."""
    global TAP_DETECTOR
    with TAP_DETECTOR_LOCK:
        if TAP_DETECTOR is None or not TAP_DETECTOR.is_alive():
            try:
                from audio_tap_detector import AudioTapDetector
                TAP_DETECTOR = AudioTapDetector(
                    peak_threshold=int(UI_CONFIG["clack_threshold"]),
                    play_sound_cb=play_sound_helper,
                    is_active_cb=lambda: bool(GLOBAL_APP_MANAGER and GLOBAL_APP_MANAGER.current_app_name in ["piranha_pose_app", "clack_pose_app"])
                )
                TAP_DETECTOR.start()
                STATUS_CACHE["clack_pose"] = {"running": True}
                logging.info("[ClackPose] AudioTapDetector successfully started.")
                return True
            except Exception as e:
                logging.error(f"[ClackPose] Failed to start AudioTapDetector: {e}")
                return False
        return True

def stop_tap_detector() -> None:
    """Safely terminates AudioTapDetector, kills child parecord process, and updates status."""
    global TAP_DETECTOR
    with TAP_DETECTOR_LOCK:
        if TAP_DETECTOR is not None:
            try:
                TAP_DETECTOR.stop()
            except Exception as st_err:
                logging.warning(f"[ClackPose] TAP_DETECTOR stop warning: {st_err}")
            TAP_DETECTOR = None
    STATUS_CACHE["clack_pose"] = {"running": False}

ROBOT_MIC_PROC = None
ROBOT_MIC_LOCK = threading.Lock()

MARIO_SOUNDS_DIR = "/home/carson/mario_sounds"
PLANT_VINE_SOUNDS = [
    "nsmbwiiGiantPiranhaPlant.wav",
    "nsmbwiiPiranhaPlant1.wav",
    "nsmbwiiPiranhaPlant2.wav",
    "piranhaPlant.wav",
    "smw_vine.wav"
]

PULSE_ENV = dict(os.environ)
PULSE_ENV["XDG_RUNTIME_DIR"] = "/run/user/1000"
PULSE_ENV["PULSE_SERVER"] = "unix:/run/user/1000/pulse/native"

CONFIG_FILE = os.path.join(DIRECTORY, "ui_config.json")

def load_ui_config() -> Dict[str, Any]:
    if not os.path.exists(CONFIG_FILE):
        raise FileNotFoundError(f"Missing required UI configuration file: {CONFIG_FILE}")
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    # Fail-fast validation with direct bracket access
    _ = cfg["clack_threshold"]
    _ = cfg["volume_pct"]
    _ = cfg["rover_max_speed_pct"]
    _ = cfg["arm_speed_sec"]
    _ = cfg["default_tab"]
    _ = cfg["drawer_default_open"]
    _ = cfg["top_bar_height_px"]
    _ = cfg["launcher_mode"]
    _ = cfg["carousel_app_index"]
    _ = cfg["config_step_pct"]
    _ = cfg["selected_config_var"]
    return cfg

def save_ui_config(cfg: Dict[str, Any]) -> None:
    _ = cfg["clack_threshold"]
    _ = cfg["volume_pct"]
    _ = cfg["rover_max_speed_pct"]
    _ = cfg["arm_speed_sec"]
    _ = cfg["default_tab"]
    _ = cfg["drawer_default_open"]
    _ = cfg["top_bar_height_px"]
    _ = cfg["launcher_mode"]
    _ = cfg["carousel_app_index"]
    _ = cfg["config_step_pct"]
    _ = cfg["selected_config_var"]
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)

def load_config_limits() -> Dict[str, Any]:
    calib_aux_path = os.path.join(DIRECTORY, "calibration_aux.json")
    if not os.path.exists(calib_aux_path):
        calib_aux_path = os.path.join(os.path.dirname(DIRECTORY), "calibration_aux.json")
    if not os.path.exists(calib_aux_path):
        raise FileNotFoundError(f"Missing required calibration file: {calib_aux_path}")

    with open(calib_aux_path, "r", encoding="utf-8") as f:
        calib_aux = json.load(f)

    follower_path = os.path.join(DIRECTORY, "follower.json")
    if not os.path.exists(follower_path):
        follower_path = os.path.join(os.path.dirname(DIRECTORY), "follower.json")
    if not os.path.exists(follower_path):
        raise FileNotFoundError(f"Missing required follower calibration: {follower_path}")

    with open(follower_path, "r", encoding="utf-8") as f:
        follower = json.load(f)

    # Dynamic arm move speed limits derived from maximum follower joint span and calibrated velocity limits
    max_joint_span = max(
        follower[joint]["range_max"] - follower[joint]["range_min"]
        for joint in ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"]
    )
    vel_max = float(follower["velocity_limits"]["ticks_per_sec_max"])
    vel_min = float(follower["velocity_limits"]["ticks_per_sec_min"])
    arm_min_sec = round(max_joint_span / vel_max, 2)
    arm_max_sec = round(max_joint_span / vel_min, 2)

    return {
        "volume_pct": {
            "min": int(calib_aux["system_audio"]["min_volume_pct"]),
            "max": int(calib_aux["system_audio"]["max_volume_pct"]),
            "is_percentage": True,
            "span": int(calib_aux["system_audio"]["max_volume_pct"]) - int(calib_aux["system_audio"]["min_volume_pct"])
        },
        "rover_max_speed_pct": {
            "min": int(calib_aux["rover_drive"]["min_speed_pct"]),
            "max": int(calib_aux["rover_drive"]["max_speed_pct"]),
            "is_percentage": True,
            "span": int(calib_aux["rover_drive"]["max_speed_pct"]) - int(calib_aux["rover_drive"]["min_speed_pct"])
        },
        "arm_speed_sec": {
            "min": arm_min_sec,
            "max": arm_max_sec,
            "is_percentage": False,
            "span": round(arm_max_sec - arm_min_sec, 2)
        },
        "clack_threshold": {
            "min": int(calib_aux["clack_detector"]["min_threshold"]),
            "max": int(calib_aux["clack_detector"]["max_threshold"]),
            "is_percentage": False,
            "span": int(calib_aux["clack_detector"]["max_threshold"]) - int(calib_aux["clack_detector"]["min_threshold"])
        }
    }

CONFIG_LIMITS = load_config_limits()
STATUS_CACHE["config_limits"] = CONFIG_LIMITS
UI_CONFIG = load_ui_config()
STATUS_CACHE["config"] = UI_CONFIG

def set_system_volume(pct: int):
    try:
        val = max(CONFIG_LIMITS["volume_pct"]["min"], min(CONFIG_LIMITS["volume_pct"]["max"], int(pct)))
        subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{val}%"], env=PULSE_ENV, check=False)
        subprocess.run(["amixer", "set", "Master", f"{val}%"], env=PULSE_ENV, check=False)
        UI_CONFIG["volume_pct"] = val
        STATUS_CACHE["config"] = UI_CONFIG
        save_ui_config(UI_CONFIG)
    except Exception as e:
        logging.exception(f"Failed setting system volume to {pct}%: {e}")
        raise RuntimeError(f"Failed setting system volume to {pct}%: {e}") from e

def sync_rover_speed_config(pct: int):
    try:
        val = max(CONFIG_LIMITS["rover_max_speed_pct"]["min"], min(CONFIG_LIMITS["rover_max_speed_pct"]["max"], int(pct)))
        max_offset = int(500 * (val / 100.0))
        UI_CONFIG["rover_max_speed_pct"] = val
        STATUS_CACHE["config"] = UI_CONFIG
        save_ui_config(UI_CONFIG)
        cfg_dict = {"max_speed_pct": val, "max_pulse_offset": max_offset}
        with open("/tmp/rover_config.json", "w") as f:
            json.dump(cfg_dict, f, indent=2)
    except Exception as e:
        logging.exception(f"Failed syncing rover speed to {pct}%: {e}")
        raise RuntimeError(f"Failed syncing rover speed to {pct}%: {e}") from e

CURRENT_PAPLAY_PROC: Optional[subprocess.Popen] = None

def play_sound_helper(event: str = "", wav_path: str = "", stop_previous: bool = False, delay_sec: float = 0.0, kind: str = "") -> float:
    """Dispatches audio playback on Pi 4B PulseAudio daemon with fail-fast validation and full traceback logging."""
    active_event = event if event else kind
    if active_event == "stop_audio":
        duration_sec = 0.0
    else:
        duration_sec = audio_resolver.get_audio_duration_sec(wav_path if wav_path else active_event)

    def _work(total_duration: float = duration_sec):
        global CURRENT_PAPLAY_PROC
        try:
            active_event = event if event else kind

            if stop_previous or active_event == "stop_audio" or active_event in ("trex_roar", "trex_roar_isolated"):
                if CURRENT_PAPLAY_PROC is not None and CURRENT_PAPLAY_PROC.poll() is None:
                    try:
                        CURRENT_PAPLAY_PROC.terminate()
                        CURRENT_PAPLAY_PROC.wait(timeout=0.05)
                    except Exception:
                        try:
                            CURRENT_PAPLAY_PROC.kill()
                        except Exception as kill_err:
                            logging.debug("Error killing previous paplay process: %s", kill_err)
                    CURRENT_PAPLAY_PROC = None
                if active_event == "stop_audio":
                    return

            if delay_sec > 0:
                time.sleep(delay_sec)

            global TAP_DETECTOR
            if TAP_DETECTOR and hasattr(TAP_DETECTOR, "mute"):
                if total_duration > 0.0:
                    mute_dur = total_duration + 0.5
                else:
                    mute_dur = 2.0
                TAP_DETECTOR.mute(mute_dur)

            if wav_path:
                if not os.path.exists(wav_path):
                    raise FileNotFoundError(f"Provided wav_path does not exist on disk: {wav_path}")
                target_wav = wav_path
            else:
                if not active_event:
                    raise ValueError("play_sound_helper requires either a non-empty 'event' identifier or 'wav_path'")
                resolved_filename = audio_resolver.get_audio_filename(active_event)
                cand = os.path.join(MARIO_SOUNDS_DIR, resolved_filename)
                if not os.path.exists(cand):
                    raise FileNotFoundError(f"Resolved audio asset '{cand}' does not exist on disk.")
                target_wav = cand

            proc = subprocess.Popen(
                ["paplay", "--latency-msec=20", target_wav],
                env=PULSE_ENV,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE
            )
            CURRENT_PAPLAY_PROC = proc
            _, stderr_data = proc.communicate()
            rc = proc.returncode
            if rc != 0:
                if rc in (-9, -15, 137, 143):
                    logging.info("Audio playback for %s cancelled by subsequent audio request (signal %d).", target_wav, rc)
                    return
                err_txt = ""
                if stderr_data:
                    err_txt = stderr_data.decode('utf-8', errors='replace')
                raise RuntimeError(f"PulseAudio paplay failed for {target_wav} (code {rc}): {err_txt}")
        except Exception as e:
            traceback.print_exc()
            logging.exception("Sound playback failure for event='%s', wav_path='%s': %s", event, wav_path, e)
            raise
    threading.Thread(target=_work, daemon=True).start()
    return duration_sec

def manage_local_backend(action: str) -> Optional[int]:
    """Manages the in-memory master hardware backend.
    Accepts explicit lifecycle actions: 'start', 'stop', 'restart'.
    """
    global GLOBAL_BACKEND
    if action in ["stop", "restart"]:
        logging.info("[BackendLifecycle] Stopping/disconnecting robot backend...")
        try:
            if GLOBAL_BACKEND is not None:
                GLOBAL_BACKEND.disable_all_torque()
                GLOBAL_BACKEND.follower_active = False
                GLOBAL_BACKEND.disconnect()
        except Exception as ex:
            logging.warning(f"[BackendLifecycle] Backend disconnect warning: {ex}")

        STATUS_CACHE["backend_online"] = False
        STATUS_CACHE["follower"] = {"running": False, "pid": ""}
        STATUS_CACHE["hardware_telemetry"] = None

        if action == "stop":
            return None

    if action in ["start", "restart"]:
        logging.info("[BackendLifecycle] Starting/reconnecting robot backend...")
        try:
            if GLOBAL_BACKEND is not None:
                GLOBAL_BACKEND.connect()
                STATUS_CACHE["backend_online"] = GLOBAL_BACKEND.hardware_active
        except Exception as ex:
            logging.error(f"[BackendLifecycle] Backend connect error: {ex}")
        return os.getpid()
    return None


VOSK_CONFIG_PATH_CANDIDATES = [
    Path("/home/carson/vosk_server/vosk_config.json"),
    Path("/home/carson/touch_ui/config/vosk_config.json"),
    Path(__file__).resolve().parent.parent / "config" / "vosk_config.json",
    Path(__file__).resolve().parent / "config" / "vosk_config.json",
    Path("config/vosk_config.json"),
]


def load_vosk_config() -> Dict[str, Any]:
    target_path: Optional[Path] = None
    for p in VOSK_CONFIG_PATH_CANDIDATES:
        if p.exists():
            target_path = p
            break
    if target_path is None:
        raise FileNotFoundError(f"Missing canonical Vosk configuration. Checked: {VOSK_CONFIG_PATH_CANDIDATES}")

    with open(target_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    # Fail-fast schema validation
    _ = str(cfg["host"])
    _ = int(cfg["port"])
    _ = str(cfg["service_name"])
    _ = bool(cfg["start_on_ui_ready"])
    return cfg


VOSK_LAUNCH_LOCK = threading.Lock()
VOSK_LAUNCH_TRIGGERED = False


def launch_vosk_service() -> bool:
    """Launches resident Vosk standby server in background thread upon UI readiness."""
    global VOSK_LAUNCH_TRIGGERED
    with VOSK_LAUNCH_LOCK:
        if VOSK_LAUNCH_TRIGGERED:
            return False
        VOSK_LAUNCH_TRIGGERED = True

    def _launcher() -> None:
        service_name = "vosk-server.service"
        try:
            cfg = load_vosk_config()
            service_name = str(cfg["service_name"])
            logging.info(f"[VoskLifecycle] Touch UI load confirmed. Initiating background start for {service_name}...")
            res = subprocess.run(
                ["sudo", "-n", "systemctl", "start", service_name],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=15,
                text=True
            )
            if res.returncode == 0:
                logging.info(f"[VoskLifecycle] Successfully signaled systemd to start {service_name}.")
            else:
                logging.warning(f"[VoskLifecycle] systemctl start {service_name} returned code {res.returncode}: {res.stderr.strip()}")
        except Exception as ex:
            logging.error(f"[VoskLifecycle] Failed to launch {service_name}: {ex}", exc_info=True)

    threading.Thread(target=_launcher, daemon=True, name="VoskDeferredLauncher").start()
    return True


def poll_status_loop() -> None:
    """Non-blocking background loop sampling live in-memory telemetry and Mac Leader state."""
    while True:
        try:
            cfg = network_resolver.load_network_config()
            topology_mode = cfg["topology_mode"]
            if topology_mode not in ["STANDALONE_PI4B", "DUAL_NODE"]:
                raise KeyError(f"Invalid topology_mode '{topology_mode}'. Expected 'STANDALONE_PI4B' or 'DUAL_NODE'")
            STATUS_CACHE["topology_mode"] = topology_mode

            conn_mode = network_resolver.get_active_connection_mode()
            STATUS_CACHE["connection_mode"] = conn_mode
            STATUS_CACHE["pi4b_wlan_ip"] = network_resolver.get_interface_ip("wlan0")

            # Sample authoritative in-memory telemetry directly
            ht = MasterApiHandler.build_status_dict()
            STATUS_CACHE["hardware_telemetry"] = ht
            STATUS_CACHE["last_telemetry_time"] = time.time()
            STATUS_CACHE["daemon_running"] = True

            is_connected = bool(GLOBAL_BACKEND and GLOBAL_BACKEND.hardware_active)
            STATUS_CACHE["backend_online"] = is_connected
            STATUS_CACHE["hardware_connected"] = is_connected

            if isinstance(ht, dict) and "follower" in ht:
                STATUS_CACHE["follower"] = ht["follower"]
                STATUS_CACHE["leader"] = ht["leader"]
                STATUS_CACHE["pokeball"] = ht["pokeball"]
                STATUS_CACHE["servos"] = ht["servos"]
            if isinstance(ht, dict) and "listener" in ht:
                STATUS_CACHE["listener"] = ht["listener"]

            # Sample resident Vosk standby server readiness (:8059/health)
            try:
                vosk_port = int(cfg["ports"]["vosk_server_port"])
                v_url = f"http://127.0.0.1:{vosk_port}/health"
                v_req = urllib.request.Request(v_url, headers={"User-Agent": "TouchUiStatusPoller"})
                with urllib.request.urlopen(v_req, timeout=0.25) as v_resp:
                    STATUS_CACHE["vosk_ready"] = (v_resp.status == 200)
            except Exception:
                STATUS_CACHE["vosk_ready"] = False

            # Update Clack Pose telemetry
            global TAP_DETECTOR
            with TAP_DETECTOR_LOCK:
                if TAP_DETECTOR is not None:
                    STATUS_CACHE["clack_pose"] = TAP_DETECTOR.get_state()
                else:
                    STATUS_CACHE["clack_pose"] = {"running": False, "mode": "CALIBRATION_DETECTION_ONLY"}

        except Exception as loop_err:
            logging.error(f"[PollLoop] Error during status polling: {loop_err}")

        time.sleep(0.33)


class UnifiedHandler(MasterApiHandler):
    """Unified HTTP Request Handler servicing both Touch UI (port 8082) and Robot REST API (port 8085).
    Executes all robot hardware control and application lifecycle logic directly in-memory with zero proxying.
    """

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)

        # 1. Static Web Assets & UI Pages
        if parsed.path in ["/", "/index.html", "/gantry_ui.html"]:
            static_file = os.path.join(DIRECTORY, "static", "index.html")
            if not os.path.exists(static_file):
                static_file = os.path.join(DIRECTORY, "static", "gantry_ui.html")
            if not os.path.exists(static_file):
                static_file = os.path.join(DIRECTORY, "index.html")
            if os.path.exists(static_file):
                with open(static_file, "rb") as f:
                    content = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Cache-Control", "no-cache, no-store, must-revalidate, max-age=0")
                self.send_header("Pragma", "no-cache")
                self.send_header("Expires", "0")
                self.end_headers()
                self.wfile.write(content)
                return

        rel_path = parsed.path.lstrip("/")
        if rel_path and not rel_path.startswith("api/"):
            static_asset = os.path.join(DIRECTORY, "static", rel_path)
            if os.path.isfile(static_asset):
                mime_type = "application/octet-stream"
                if rel_path.endswith(".css"):
                    mime_type = "text/css"
                elif rel_path.endswith(".js"):
                    mime_type = "application/javascript"
                elif rel_path.endswith(".json"):
                    mime_type = "application/json"
                elif rel_path.endswith(".html"):
                    mime_type = "text/html"
                elif rel_path.endswith(".png"):
                    mime_type = "image/png"
                elif rel_path.endswith(".svg"):
                    mime_type = "image/svg+xml"
                with open(static_asset, "rb") as f:
                    content = f.read()
                self.send_response(200)
                self.send_header("Content-Type", mime_type)
                self.send_header("Cache-Control", "no-cache, no-store, must-revalidate, max-age=0")
                self.send_header("Pragma", "no-cache")
                self.send_header("Expires", "0")
                self.end_headers()
                self.wfile.write(content)
                return

        # 2. Port-specific /api/status resolution
        if parsed.path == "/api/status":
            local_port = self.server.server_address[1]
            if local_port == PORT_MASTER_API:
                return self._send_json(self.build_status_dict())

            resp = dict(STATUS_CACHE)
            is_active = bool(GLOBAL_BACKEND and GLOBAL_BACKEND.hardware_active)
            time_since_telem = time.time() - STATUS_CACHE["last_telemetry_time"]
            resp["closed_loop_verified"] = is_active and (time_since_telem < 2.0)
            return self._send_json(resp)

        # 3. Touch UI configuration & media endpoints
        if parsed.path == "/api/get_config":
            return self._send_json({"status": "ok", "config": UI_CONFIG})

        if parsed.path == "/api/pending_audio":
            tmp_path = "/home/carson/pending_audio.wav"
            exists = os.path.exists(tmp_path)
            size = 0
            if exists:
                size = os.path.getsize(tmp_path)
            return self._send_json({"status": "ok", "exists": exists, "bytes": size})

        if parsed.path == "/api/microphone/stream":
            proc = None
            try:
                cmd = ["parecord", "--format=s16le", "--rate=16000", "--channels=1", "--raw"]
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                time.sleep(0.05)
                if proc.poll() is not None:
                    err_msg = ""
                    if proc.stderr:
                        err_msg = proc.stderr.read().decode("utf-8", "replace").strip()
                    return self._send_json({"error": f"Failed to spawn parecord: {err_msg} (exit code {proc.returncode})"}, 503)

                self.send_response(200)
                self.send_header("Content-Type", "audio/x-raw;format=s16le;rate=16000;channels=1")
                self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                self.end_headers()

                import select
                while True:
                    rlist, _, _ = select.select([proc.stdout], [], [], 2.0)
                    if not rlist:
                        if proc.poll() is not None:
                            break
                        continue
                    chunk = proc.stdout.read(2560)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError) as disc_err:
                logging.info(f"[ROBOT MIC STREAM] Client stream disconnected: {disc_err}")
            except Exception as stream_err:
                logging.error(f"[ROBOT MIC STREAM] Unexpected stream error: {stream_err}\n{traceback.format_exc()}")
            finally:
                if proc is not None:
                    try:
                        proc.terminate()
                        proc.wait(timeout=1.0)
                    except Exception:
                        proc.kill()
            return

        # 4. Delegate all standard robot GET endpoints (/api/apps..., /api/arm/presets, etc.) to MasterApiHandler
        return super().do_GET()


    def do_POST(self) -> None:
        global TAP_DETECTOR, ROBOT_MIC_PROC
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        content_type = self.headers.get("Content-Type", "")
        content_length = int(self.headers.get('Content-Length', 0))

        if path == "/api/play_sound" and (content_type.startswith("audio/") or content_type.startswith("application/octet-stream")):
            raw_audio = b""
            if content_length > 0:
                raw_audio = self.rfile.read(content_length)
            if raw_audio:
                tmp_path = "/tmp/incoming_stream.wav"
                with open(tmp_path, "wb") as f:
                    f.write(raw_audio)
                play_sound_helper(wav_path=tmp_path, stop_previous=True)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok", "mode": "stream_audio", "bytes": len(raw_audio)}).encode('utf-8'))
                return

        if path == "/api/pending_audio" and (content_type.startswith("audio/") or content_type.startswith("application/octet-stream")):
            raw_audio = b""
            if content_length > 0:
                raw_audio = self.rfile.read(content_length)
            if raw_audio:
                tmp_path = "/home/carson/pending_audio.wav"
                with open(tmp_path, "wb") as f:
                    f.write(raw_audio)
                print(f"[PENDING AUDIO] Saved {len(raw_audio)} bytes to {tmp_path}", flush=True)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok", "bytes": len(raw_audio), "path": tmp_path}).encode('utf-8'))
                return

        body_bytes = b""
        if content_length > 0:
            body_bytes = self.rfile.read(content_length)
        body = ""
        if body_bytes:
            body = body_bytes.decode('utf-8')
        req_data = {}
        if body:
            try:
                req_data = json.loads(body)
            except json.JSONDecodeError as err:
                logging.warning("JSON decode failed on request body: %s", err)
                req_data = {}

        if path == "/api/pending_audio/play":
            tmp_path = "/home/carson/pending_audio.wav"
            if os.path.exists(tmp_path):
                print(f"[PENDING AUDIO] Playing deferred audio from {tmp_path}", flush=True)
                play_sound_helper(wav_path=tmp_path, stop_previous=True)
                def _cleanup():
                    time.sleep(1.0)
                    try:
                        if os.path.exists(tmp_path):
                            os.remove(tmp_path)
                    except Exception as ce:
                        print(f"[PENDING AUDIO] Cleanup warning: {ce}", flush=True)
                threading.Thread(target=_cleanup, daemon=True).start()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "playing_pending"}).encode('utf-8'))
                return
            else:
                self.send_response(404)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "not_found"}).encode('utf-8'))
                return

        if path == "/api/microphone/cancel":
            with ROBOT_MIC_LOCK:
                if ROBOT_MIC_PROC is not None:
                    try:
                        ROBOT_MIC_PROC.terminate()
                        ROBOT_MIC_PROC.wait(timeout=1.0)
                    except Exception as te:
                        print(f"[ROBOT MIC] Terminate failed: {te}", flush=True)
                        try:
                            ROBOT_MIC_PROC.kill()
                        except Exception as ke:
                            print(f"[ROBOT MIC] Kill failed: {ke}", flush=True)
                    ROBOT_MIC_PROC = None
                if os.path.exists("/tmp/robot_recording.wav"):
                    try:
                        os.remove("/tmp/robot_recording.wav")
                    except Exception as re:
                        print(f"[ROBOT MIC] Remove recording file failed: {re}", flush=True)
            print("[ROBOT MIC] Cancelled microphone recording and discarded audio buffer.", flush=True)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "cancelled"}).encode('utf-8'))
            return

        if path == "/api/microphone/start":
            with ROBOT_MIC_LOCK:
                if ROBOT_MIC_PROC is not None:
                    try:
                        ROBOT_MIC_PROC.terminate()
                        ROBOT_MIC_PROC.wait(timeout=1.0)
                    except Exception:
                        pass
                if os.path.exists("/tmp/robot_recording.wav"):
                    try:
                        os.remove("/tmp/robot_recording.wav")
                    except Exception:
                        pass
                cmd = ["parecord", "--format=s16le", "--rate=16000", "--channels=1", "/tmp/robot_recording.wav"]
                ROBOT_MIC_PROC = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print("[ROBOT MIC] Started onboard microphone recording to /tmp/robot_recording.wav", flush=True)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "recording_started"}).encode())
            return

        if path == "/api/microphone/stop":
            with ROBOT_MIC_LOCK:
                if ROBOT_MIC_PROC is not None:
                    try:
                        ROBOT_MIC_PROC.terminate()
                        ROBOT_MIC_PROC.wait(timeout=1.5)
                    except Exception:
                        try:
                            ROBOT_MIC_PROC.kill()
                        except Exception:
                            pass
                    ROBOT_MIC_PROC = None

            wav_data = b""
            if os.path.exists("/tmp/robot_recording.wav"):
                try:
                    with open("/tmp/robot_recording.wav", "rb") as f:
                        wav_data = f.read()
                except Exception as e:
                    print(f"[ROBOT MIC] Error reading /tmp/robot_recording.wav: {e}", flush=True)

            pc_ip = get_current_pc_ip(port=8058)
            voice_bridge_url = f"http://{pc_ip}:8058/api/voice/process_audio"
            dispatched = False
            if wav_data and voice_bridge_url:
                def _post_audio():
                    try:
                        req = urllib.request.Request(
                            voice_bridge_url,
                            data=wav_data,
                            headers={"Content-Type": "audio/wav"}
                        )
                        with urllib.request.urlopen(req, timeout=45) as resp:
                            print(f"[ROBOT MIC] Dispatched {len(wav_data)} bytes to Voice Bridge: status {resp.status}", flush=True)
                    except Exception as err:
                        print(f"[ROBOT MIC] Failed to dispatch audio to Voice Bridge: {err}", flush=True)
                threading.Thread(target=_post_audio, daemon=True).start()
                dispatched = True

            print(f"[ROBOT MIC] Stopped onboard recording: {len(wav_data)} bytes, dispatched={dispatched}", flush=True)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "status": "recording_stopped",
                "bytes": len(wav_data),
                "dispatched": dispatched
            }).encode())
            return

        if path == "/api/ornith/state":
            if "state" not in req_data:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Missing required 'state' parameter"}).encode('utf-8'))
                return
            state = req_data["state"]
            STATUS_CACHE["ornith_state"] = state
            print(f"[ORNITH STATE] Kiosk state transitioned to: {state}", flush=True)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "state": state}).encode('utf-8'))
            return

        if path == "/api/set_volume":
            if "volume" not in req_data:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Missing required 'volume' parameter"}).encode('utf-8'))
                return
            vol = int(req_data["volume"])
            set_system_volume(vol)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "volume_pct": UI_CONFIG["volume_pct"]}).encode('utf-8'))
            return

        if path == "/api/set_config":
            if "volume_pct" in req_data:
                set_system_volume(req_data["volume_pct"])
            if "clack_threshold" in req_data:
                thresh = max(CONFIG_LIMITS["clack_threshold"]["min"], min(CONFIG_LIMITS["clack_threshold"]["max"], int(req_data["clack_threshold"])))
                UI_CONFIG["clack_threshold"] = thresh
                STATUS_CACHE["config"] = UI_CONFIG
                save_ui_config(UI_CONFIG)
                with TAP_DETECTOR_LOCK:
                    if TAP_DETECTOR is not None:
                        TAP_DETECTOR.set_threshold(thresh)
            if "rover_max_speed_pct" in req_data:
                sync_rover_speed_config(req_data["rover_max_speed_pct"])
            if "arm_speed_sec" in req_data:
                arm_val = max(CONFIG_LIMITS["arm_speed_sec"]["min"], min(CONFIG_LIMITS["arm_speed_sec"]["max"], float(req_data["arm_speed_sec"])))
                UI_CONFIG["arm_speed_sec"] = round(arm_val, 2)
                STATUS_CACHE["config"] = UI_CONFIG
                save_ui_config(UI_CONFIG)
            if "selected_config_var" in req_data:
                UI_CONFIG["selected_config_var"] = str(req_data["selected_config_var"])
                STATUS_CACHE["config"] = UI_CONFIG
                save_ui_config(UI_CONFIG)
            if "config_step_pct" in req_data:
                UI_CONFIG["config_step_pct"] = int(req_data["config_step_pct"])
                STATUS_CACHE["config"] = UI_CONFIG
                save_ui_config(UI_CONFIG)
            if "default_tab" in req_data:
                UI_CONFIG["default_tab"] = str(req_data["default_tab"])
                STATUS_CACHE["config"] = UI_CONFIG
                save_ui_config(UI_CONFIG)
            if "drawer_default_open" in req_data:
                UI_CONFIG["drawer_default_open"] = bool(req_data["drawer_default_open"])
                STATUS_CACHE["config"] = UI_CONFIG
                save_ui_config(UI_CONFIG)
            if "launcher_mode" in req_data:
                UI_CONFIG["launcher_mode"] = str(req_data["launcher_mode"])
                STATUS_CACHE["config"] = UI_CONFIG
                save_ui_config(UI_CONFIG)
            if "carousel_app_index" in req_data:
                UI_CONFIG["carousel_app_index"] = int(req_data["carousel_app_index"])
                STATUS_CACHE["config"] = UI_CONFIG
                save_ui_config(UI_CONFIG)

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "config": UI_CONFIG, "config_limits": CONFIG_LIMITS}).encode('utf-8'))
            return

        if path in ["/api/wifi_disable", "/api/wifi_restore"]:
            action = "enable" if path == "/api/wifi_restore" else "disable"
            try:
                if action == "enable":
                    def _restore_home_wifi():
                        try:
                            subprocess.run(["sudo", "rfkill", "unblock", "wifi"], check=False)
                            subprocess.run(["sudo", "nmcli", "radio", "wifi", "on"], check=False)
                            subprocess.run(["sudo", "nmcli", "connection", "up", "Maestas Mansion"], check=False)
                        except Exception as e:
                            logging.warning(f"Error restoring Pi 4B home wifi: {e}")

                    threading.Thread(target=_restore_home_wifi, daemon=True).start()
                    play_sound_helper(kind="connect")
                else:
                    script_path = "/home/carson/touch_ui/scripts/toggle_wifi_blacklist.py"
                    if not os.path.exists(script_path):
                        script_path = os.path.join(DIRECTORY, "scripts", "toggle_wifi_blacklist.py")
                    if not os.path.exists(script_path):
                        script_path = os.path.join(os.path.dirname(DIRECTORY), "scripts", "toggle_wifi_blacklist.py")
                    subprocess.Popen([sys.executable, script_path, "disable"])
                    play_sound_helper(kind="disconnect")

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok", "action": action, "message": f"Wi-Fi {action} command initiated"}).encode())
                return
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
                return

        if path == "/api/play_sound":
            if not isinstance(req_data, dict):
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Payload must be a JSON object"}).encode('utf-8'))
                return

            if "action" in req_data:
                action = req_data["action"]
                if action in ("stop", "clear"):
                    dur = play_sound_helper(event="stop_audio", wav_path="", stop_previous=True, delay_sec=0.0)
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"status": "ok", "action": "stopped", "duration_sec": dur}).encode('utf-8'))
                    return
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": f"Invalid audio action '{action}'. Permitted: ['stop', 'clear']"}).encode('utf-8'))
                return

            # Strict schema validation: require exact contract keys
            required_keys = ["event", "stop_previous", "delay_sec", "wav_path"]
            missing_keys = [k for k in required_keys if k not in req_data]
            if missing_keys:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "error": f"Schema contract violation on /api/play_sound: missing required keys {missing_keys}"
                }).encode('utf-8'))
                return

            event_name = str(req_data["event"])
            stop_prev = bool(req_data["stop_previous"])
            delay_s = float(req_data["delay_sec"])
            wav_p = str(req_data["wav_path"])

            dur = play_sound_helper(event=event_name, wav_path=wav_p, stop_previous=stop_prev, delay_sec=delay_s)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "sound": event_name or wav_p, "duration_sec": dur}).encode('utf-8'))
            return

        if path == "/api/connect_hotspot":
            def _switch_to_hotspot():
                try:
                    subprocess.run(["sudo", "rfkill", "unblock", "wifi"], check=False)
                    subprocess.run(["sudo", "nmcli", "radio", "wifi", "on"], check=False)
                    subprocess.run(["sudo", "nmcli", "connection", "up", "iPhone"], check=False)
                except Exception as e:
                    logging.warning(f"Error connecting Pi 4B to hotspot: {e}")

            threading.Thread(target=_switch_to_hotspot, daemon=True).start()
            play_sound_helper(kind="connect")

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "status": "ok",
                "message": "Initiated connection to iPhone hotspot on Pi 4B"
            }).encode('utf-8'))
            return

        if path == "/api/clack_pose_toggle":
            if "action" not in req_data:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Schema contract violation: missing required 'action' key", "status": "failed"}).encode())
                return
            action = str(req_data["action"])
            with TAP_DETECTOR_LOCK:
                is_running = bool(TAP_DETECTOR is not None and TAP_DETECTOR.is_alive())
                if action == "toggle":
                    action = "stop" if is_running else "start"

                if action == "start":
                    if GLOBAL_APP_MANAGER:
                        GLOBAL_APP_MANAGER.start_app_by_name("piranha_pose_app")
                    else:
                        start_tap_detector()

                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"status": "ok", "action": "started", "running": True}).encode())
                    return
                else:
                    if GLOBAL_APP_MANAGER:
                        GLOBAL_APP_MANAGER.stop_app("piranha_pose_app")
                    else:
                        stop_tap_detector()

                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"status": "ok", "action": "stopped", "running": False}).encode())
                    return

        if path == "/api/clack_pose_threshold":
            thresh = req_data.get("threshold")
            refractory = req_data.get("refractory_ms")
            with TAP_DETECTOR_LOCK:
                if TAP_DETECTOR is not None:
                    if thresh is not None:
                        TAP_DETECTOR.set_threshold(int(thresh))
                    if refractory is not None:
                        TAP_DETECTOR.set_refractory(int(refractory))
                    st = TAP_DETECTOR.get_state()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"status": "ok", "state": st}).encode())
                    return
                else:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"status": "ok", "message": "Detector not active"}).encode())
                    return

        if path == "/api/backend_restart":
            if "action" not in req_data:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Schema contract violation: missing required 'action' key", "status": "failed"}).encode())
                return

            action = str(req_data["action"]).lower()
            if action not in ["start", "stop", "restart"]:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": f"Invalid action '{action}'. Expected 'start', 'stop', or 'restart'", "status": "failed"}).encode())
                return

            try:
                pid = manage_local_backend(action)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok", "action": action, "pid": pid}).encode())
                return
            except Exception as ex:
                logging.exception(f"Failed to execute backend action '{action}': {ex}")
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": f"Backend lifecycle failure: {ex}", "status": "failed"}).encode())
                return

        if path == "/api/vosk/start":
            launched = launch_vosk_service()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "status": "ok",
                "launched": launched,
                "vosk_ready": bool(STATUS_CACHE["vosk_ready"])
            }).encode())
            return

        # 3. Audio / Tap detector muting during motion sequences
        if TAP_DETECTOR and hasattr(TAP_DETECTOR, "mute"):
            if path in ["/api/arm/attack_sequence", "/api/arm/attack", "/api/arm/execute_sequence"]:
                TAP_DETECTOR.mute(12.0)
            elif path in ["/api/arm/resume_last_pose", "/api/arm/move_to_preset", "/api/arm/move_norm"]:
                TAP_DETECTOR.mute(2.5)
            elif path in ["/api/slider", "/api/pedestal_step", "/api/move", "/api/nudge_physical"]:
                TAP_DETECTOR.mute(1.5)

        if path == "/api/kill_all":
            play_sound_helper(kind="stop_audio", stop_previous=True)
            stop_tap_detector()

        # 4. Delegate all standard robot control POST endpoints to MasterApiHandler
        import io
        self.rfile = io.BytesIO(body_bytes)
        return super().do_POST()


CustomHandler = UnifiedHandler


class ReuseTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    allow_reuse_address = True


def main() -> None:
    global GLOBAL_BACKEND, GLOBAL_APP_MANAGER, GLOBAL_POKEBALL

    cfg = network_resolver.load_network_config()
    serial_port = network_resolver.get_hardware_serial_port()
    rover_port = network_resolver.get_rover_serial_port()

    # Clean up stale processes holding ports and serial devices
    logging.info("Cleaning up stale locks on serial ports and HTTP endpoints...")
    for port_name in [serial_port, rover_port]:
        if os.path.exists(port_name):
            try:
                res = subprocess.run(
                    ["fuser", "-k", port_name],
                    check=False,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=5.0
                )
                if res.returncode == 0 and res.stdout.strip():
                    logging.info(f"Released stale locks on {port_name}: {res.stdout.strip()}")
            except (subprocess.SubprocessError, FileNotFoundError) as port_err:
                logging.warning(f"Port cleanup warning for {port_name}: {port_err}")

    for p in [PORT_TOUCH_UI, PORT_MASTER_API]:
        try:
            subprocess.run(["fuser", "-k", f"{p}/tcp"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5.0)
        except (subprocess.SubprocessError, FileNotFoundError) as ep_err:
            logging.warning(f"Endpoint cleanup warning for port {p}: {ep_err}")

    # 1. Initialize RobotBackend HAL
    logging.info(f"Initializing RobotBackend on {serial_port}...")
    GLOBAL_BACKEND = RobotBackend(port=serial_port, robot_id="follower")
    GLOBAL_BACKEND.connect()

    # 2. Initialize Joy-Con / Pokeball controller service
    if JoyConService is not None:
        logging.info("Initializing JoyConService for Right Joy-Con...")
        GLOBAL_POKEBALL = JoyConService(backend=GLOBAL_BACKEND)
    else:
        logging.info("Initializing PokeballService...")
        GLOBAL_POKEBALL = PokeballService(backend=GLOBAL_BACKEND)
    GLOBAL_POKEBALL.start()

    # 3. Initialize AppManager & register applications
    logging.info("Initializing AppManager & discovering modular applications...")
    GLOBAL_APP_MANAGER = AppManager(GLOBAL_BACKEND)
    GLOBAL_APP_MANAGER.pokeball_service = GLOBAL_POKEBALL
    GLOBAL_APP_MANAGER.joycon_service = GLOBAL_POKEBALL
    GLOBAL_POKEBALL.app_manager = GLOBAL_APP_MANAGER
    GLOBAL_APP_MANAGER.discover_apps()

    def _on_app_started(started_app_name: str) -> None:
        if started_app_name in ["piranha_pose_app", "clack_pose_app"]:
            logging.info(f"[Lifecycle] AppManager started '{started_app_name}', activating AudioTapDetector...")
            start_tap_detector()

    def _on_app_stopped(stopped_app_name: str) -> None:
        if stopped_app_name in ["piranha_pose_app", "clack_pose_app"]:
            logging.info(f"[Lifecycle] AppManager stopped '{stopped_app_name}', stopping AudioTapDetector...")
            stop_tap_detector()

    GLOBAL_APP_MANAGER.register_start_callback(_on_app_started)
    GLOBAL_APP_MANAGER.register_stop_callback(_on_app_stopped)

    # 4. Bind MasterApiHandler class state
    ensure_leader_poller_started()
    set_chime_callback(play_sound_helper)
    MasterApiHandler.backend = GLOBAL_BACKEND
    MasterApiHandler.app_manager = GLOBAL_APP_MANAGER
    MasterApiHandler.pokeball_service = GLOBAL_POKEBALL
    MasterApiHandler.joycon_service = GLOBAL_POKEBALL

    # 5. Start background telemetry polling loop
    threading.Thread(target=poll_status_loop, daemon=True, name="StatusPoller").start()

    # 6. Start Master API Server on Port 8085
    server_8085 = ReuseTCPServer(("", PORT_MASTER_API), UnifiedHandler)
    t8085 = threading.Thread(target=server_8085.serve_forever, daemon=True, name="MasterApi8085")
    t8085.start()
    logging.info(f"Master API Server successfully bound on port {PORT_MASTER_API}")

    # 7. Start Touch UI Server on Port 8082
    server_8082 = ReuseTCPServer(("", PORT_TOUCH_UI), UnifiedHandler)
    logging.info(f"Touch UI Server active on port {PORT_TOUCH_UI}")

    shutdown_event = threading.Event()

    def _sig_handler(signum, frame):
        logging.info(f"Received signal {signum}, initiating graceful shutdown...")
        shutdown_event.set()

    if hasattr(signal, "SIGHUP"):
        signal.signal(signal.SIGHUP, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, _sig_handler)
    signal.signal(signal.SIGINT, _sig_handler)

    try:
        server_thread = threading.Thread(target=server_8082.serve_forever, daemon=True, name="TouchUi8082")
        server_thread.start()
        while not shutdown_event.is_set():
            shutdown_event.wait(timeout=0.5)
    except (KeyboardInterrupt, SystemExit):
        logging.info("Interrupted, shutting down servers...")

    stop_tap_detector()

    if GLOBAL_APP_MANAGER and GLOBAL_APP_MANAGER.active_app is not None:
        try:
            logging.info(f"Stopping active app '{GLOBAL_APP_MANAGER.current_app_name}' on server shutdown...")
            GLOBAL_APP_MANAGER.stop_current_app()
        except (AttributeError, RuntimeError, TypeError, OSError) as e:
            logging.exception(f"Error stopping active app '{GLOBAL_APP_MANAGER.current_app_name}': {e}")

    if GLOBAL_POKEBALL:
        try:
            GLOBAL_POKEBALL.stop()
        except Exception as e:
            logging.warning(f"Error stopping PokeballService: {e}")

    if GLOBAL_BACKEND:
        try:
            GLOBAL_BACKEND.disable_all_torque()
            GLOBAL_BACKEND.close()
        except Exception as e:
            logging.warning(f"Error disconnecting backend: {e}")

    logging.info("Shutting down HTTP servers...")
    try:
        server_8082.shutdown()
        server_8082.server_close()
        server_8085.shutdown()
        server_8085.server_close()
    except Exception as e:
        logging.warning(f"Error during server shutdown: {e}")

    logging.info("SO-101 Unified Service shutdown complete.")


if __name__ == "__main__":
    main()
