#!/usr/bin/env python3
"""apps/ornith_voice/app.py - Standalone Ornith Voice Application for SO-101.
Managed by AppManager on the Pi 500 under exclusive RobotAppLock.
Lifecycle state machine:
  LAUNCH -> [Play Pending Audio or LISTENING] -> THINKING -> SPEAKING -> IDLE
Preemption / Escape Hatch:
  Holding Joystick Button A for 3 seconds terminates this app immediately
  and launches PokeballApp teleoperation via PokeballService.
"""

import json
import logging
import os
import sys
import threading
import time
import urllib.request
from typing import Optional, Dict, Any

from app_manager import BaseApp, AppMetadata
from robot_backend import RobotBackend

current_dir = os.path.dirname(os.path.abspath(__file__))
workspace_root = os.path.abspath(os.path.join(current_dir, "..", ".."))
config_dir = os.path.join(workspace_root, "config")
pi500_dir = os.path.join(workspace_root, "pi500")
for p in [workspace_root, config_dir, pi500_dir]:
    if p not in sys.path:
        sys.path.insert(0, p)

import network_resolver
import audio_resolver

APP_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(APP_DIR, "config.json")

def load_ornith_app_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        raise FileNotFoundError(f"Missing required Ornith config file: {CONFIG_PATH}")
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    
    # Strict fail-fast key validation
    _ = cfg["name"]
    _ = cfg["speech"]["target"]
    _ = cfg["voice_bridge"]["port"]
    _ = cfg["voice_bridge"]["chimes"]["app_start"]
    _ = cfg["voice_bridge"]["chimes"]["settle"]
    _ = cfg["voice_bridge"]["chimes"]["cancel"]
    _ = cfg["voice_bridge"]["chimes"]["action"]
    _ = cfg["chimes"]["app_start"]
    _ = cfg["chimes"]["settle"]
    _ = cfg["chimes"]["cancel"]
    _ = cfg["chimes"]["action"]
    _ = cfg["chimes"]["exit"]
    _ = cfg["robot_app"]["double_click_window_sec"]
    _ = cfg["robot_app"]["auto_send_timeout_sec"]
    _ = cfg["robot_app"]["settle_delay_sec"]
    _ = cfg["robot_app"]["pending_audio_file"]
    return cfg


class OrnithVoiceApp(BaseApp):
    _config = load_ornith_app_config()
    metadata = AppMetadata(
        name=_config["name"],
        title=_config["title"],
        description=_config["description"],
        version=_config["version"],
        tags=_config["tags"],
        icon=_config["icon"]
    )

    def __init__(self, running_on_pi: bool = True, config: Optional[dict] = None) -> None:
        super().__init__(running_on_pi=running_on_pi)
        self.logger = logging.getLogger("so101.app.ornith_voice")
        self.config = config or load_ornith_app_config()
        self.backend: Optional[RobotBackend] = None
        self.state = "IDLE"
        self.recording_start_time = 0.0
        self.last_b_click_time = 0.0

    def _get_pi4b_url(self) -> str:
        ip = network_resolver.get_pi4b_ip(prefer_port=8082)
        return f"http://{ip}:8082"

    def _get_voice_bridge_url(self) -> str:
        ip = network_resolver.get_pc_ip(prefer_port=self.config["voice_bridge"]["port"])
        return f"http://{ip}:{self.config['voice_bridge']['port']}"

    def _set_kiosk_state(self, state: str) -> None:
        """Notifies the Pi 4B touchscreen UI of Ornith's current lifecycle state."""
        self.state = state
        def _post():
            try:
                url = f"{self._get_pi4b_url()}/api/ornith/state"
                payload = json.dumps({"state": state}).encode("utf-8")
                req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=1.5):
                    pass
            except Exception as e:
                self.logger.debug("Failed to notify Pi 4B kiosk of state '%s': %s", state, e)
        threading.Thread(target=_post, daemon=True).start()

    def _play_pi4b_sound(self, kind: str, stop_previous: bool = False, delay_sec: float = 0.0) -> None:
        """Dispatches audio cue playback over HTTP to Pi 4B speakers."""
        sound_file = audio_resolver.get_audio_filename(kind)

        def _post():
            try:
                url = f"{self._get_pi4b_url()}/api/play_sound"
                payload = json.dumps({
                    "kind": sound_file,
                    "event": kind,
                    "wav_path": "",
                    "stop_previous": stop_previous,
                    "delay_sec": delay_sec
                }).encode("utf-8")
                req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=2.0):
                    pass
            except Exception as e:
                self.logger.exception("Sound dispatch '%s' (%s) to Pi 4B failed: %s", kind, sound_file, e)
        threading.Thread(target=_post, daemon=True).start()

    def _cancel_robot_mic(self) -> None:
        """Commands Pi 4B to immediately cancel microphone recording and discard audio."""
        try:
            url = f"{self._get_pi4b_url()}/api/microphone/cancel"
            req = urllib.request.Request(url, data=b"{}", headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=2.0):
                pass
            self.logger.info("🛑 Commanded Pi 4B microphone recording CANCEL.")
        except Exception as e:
            self.logger.warning("Failed to cancel Pi 4B microphone: %s", e)

    def _start_robot_mic(self) -> bool:
        """Commands Pi 4B to begin USB microphone recording via parecord."""
        try:
            url = f"{self._get_pi4b_url()}/api/microphone/start"
            req = urllib.request.Request(url, data=b"{}", headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                if resp.status == 200:
                    self.logger.info("🎤 Commanded Pi 4B microphone recording START.")
                    return True
        except Exception as e:
            self.logger.error("Failed to start Pi 4B microphone: %s", e)
        return False

    def _start_listening_turn(self) -> None:
        """Plays chuck whistle cue, enforces configured settle sleep, and arms Pi 4B microphone."""
        settle_cue = self.config["voice_bridge"]["chimes"]["settle"]
        settle_delay = self.config["robot_app"]["settle_delay_sec"]
        self.logger.info("Starting listening turn: playing %s cue...", settle_cue)
        self._set_kiosk_state("LISTENING")
        self._play_pi4b_sound(kind=settle_cue)
        time.sleep(settle_delay)
        self.recording_start_time = time.time()
        self.last_b_click_time = 0.0
        self._start_robot_mic()

    def _check_pending_audio_on_pi4b(self) -> bool:
        """Queries Pi 4B to see if an unread response was buffered while in State B."""
        try:
            url = f"{self._get_pi4b_url()}/api/pending_audio"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    if "exists" not in data:
                        raise KeyError("Missing required 'exists' key in pending_audio response")
                    return bool(data["exists"])
        except Exception as e:
            self.logger.debug("Could not check pending audio on Pi 4B: %s", e)
        return False

    def _play_pending_audio_on_pi4b(self) -> bool:
        """Commands Pi 4B to play buffered response."""
        try:
            url = f"{self._get_pi4b_url()}/api/pending_audio/play"
            req = urllib.request.Request(url, data=b"{}", headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                return resp.status == 200
        except Exception as e:
            self.logger.error("Error playing pending audio on Pi 4B: %s", e)
            return False

    def setup(self, backend: RobotBackend) -> None:
        """Pre-run setup hook: verifies motor torque and initializes state."""
        self.backend = backend
        self.recording_start_time = 0.0
        self.last_b_click_time = 0.0
        pending_file = self.config["robot_app"]["pending_audio_file"]
        self.logger.info("Setting up OrnithVoiceApp on Pi 500...")
        try:
            backend.set_arm_torque(enable=True)
        except Exception as e:
            self.logger.warning("Could not verify arm torque on setup: %s", e)

        # 1. Check for pending audio waiting on Pi 4B or local Pi 500 buffer
        has_local_pending = os.path.exists(pending_file)
        has_pi4b_pending = self._check_pending_audio_on_pi4b()

        if has_local_pending or has_pi4b_pending:
            self.logger.info("Found pending audio response. Enforcing 2.0s settle delay before playback...")
            self._set_kiosk_state("SPEAKING")
            time.sleep(2.0)

            if has_local_pending:
                try:
                    with open(pending_file, "rb") as f:
                        wav_data = f.read()
                    os.remove(pending_file)
                    url = f"{self._get_pi4b_url()}/api/play_sound"
                    req = urllib.request.Request(url, data=wav_data, headers={"Content-Type": "audio/wav"})
                    with urllib.request.urlopen(req, timeout=5.0):
                        pass
                except Exception as e:
                    self.logger.error("Error playing local pending audio: %s", e)
            elif has_pi4b_pending:
                self._play_pending_audio_on_pi4b()

            time.sleep(2.5)
            self._set_kiosk_state("AWAITING_INPUT")
            return

        # 2. First turn: Auto-listen on initial app launch (Whistle -> pause -> mic on)
        self._start_listening_turn()

    def process_button_b_click(self, now: float, stop_event: threading.Event) -> bool:
        """Processes Button B click event. Returns True if turn was committed, False otherwise."""
        double_click_window = self.config["robot_app"]["double_click_window_sec"]
        if self.state == "AWAITING_INPUT":
            self.logger.info("Button B click in AWAITING_INPUT: Starting follow-up listening turn...")
            self._start_listening_turn()
            return False

        if self.state == "LISTENING":
            if self.last_b_click_time > 0.0 and (now - self.last_b_click_time <= double_click_window):
                elapsed_between_clicks = now - self.last_b_click_time
                self.logger.info("Button B double-click detected (%.2fs <= %.2fs). Committing speech turn to LLM...",
                                 elapsed_between_clicks, double_click_window)
                self.last_b_click_time = 0.0
                self._handle_voice_turn(stop_event)
                return True
            else:
                self.last_b_click_time = now
                self.logger.info("Button B first click in LISTENING state. Waiting for second click within %.1fs to commit...",
                                 double_click_window)
                return False
        return False

    def run(self, backend: RobotBackend, stop_event: threading.Event) -> None:
        """Main interaction loop implementing Option B cadence, double-click commit, and A+B chord cancel."""
        self.logger.info("OrnithVoiceApp interaction loop running.")
        if not self.app_manager or not hasattr(self.app_manager, "pokeball_service") or self.app_manager.pokeball_service is None:
            raise AttributeError("OrnithVoiceApp requires authoritative app_manager.pokeball_service from daemon host")
        service = self.app_manager.pokeball_service

        if not hasattr(service, "button_b_click_event") or service.button_b_click_event is None:
            raise AttributeError("PokeballService is missing required 'button_b_click_event' attribute")
        service.button_b_click_event.clear()

        if not hasattr(service, "abort_audio_event") or service.abort_audio_event is None:
            raise AttributeError("PokeballService is missing required 'abort_audio_event' attribute")
        service.abort_audio_event.clear()

        auto_send_timeout = self.config["robot_app"]["auto_send_timeout_sec"]
        self.last_b_click_time = 0.0

        while not stop_event.is_set():
            now = time.time()

            # 1. Check A + B chord abort (1.0s simultaneous hold)
            if service.abort_audio_event.is_set():
                service.abort_audio_event.clear()
                self.logger.info("🛑 [CHORD ABORT] A + B simultaneous chord detected. Cancelling audio recording...")
                self._cancel_robot_mic()
                self._play_pi4b_sound(kind=self.config["voice_bridge"]["chimes"]["cancel"])
                self.last_b_click_time = 0.0
                self._set_kiosk_state("AWAITING_INPUT")

            # 2. Check Button B click event
            if service.button_b_click_event.is_set():
                service.button_b_click_event.clear()
                self.process_button_b_click(now, stop_event)

            # 3. Auto-send safety net: auto_send_timeout elapsed in LISTENING state without manual double-click
            if self.state == "LISTENING" and (now - self.recording_start_time >= auto_send_timeout):
                self.logger.info("%.1f-second auto-send timeout reached. Finalizing voice turn...", auto_send_timeout)
                self.last_b_click_time = 0.0
                self._handle_voice_turn(stop_event)

            time.sleep(0.05)

    def _handle_voice_turn(self, stop_event: threading.Event) -> None:
        """Finalizes audio capture, dispatches midway gate cue, invokes Voice Bridge, and returns to AWAITING_INPUT."""
        wait_timeout = self.config["robot_app"]["playback_wait_timeout_sec"]
        
        # 1. Dispatch midway gate action chime immediately as recording stops
        self._play_pi4b_sound(kind=self.config["voice_bridge"]["chimes"]["action"])
        self._set_kiosk_state("THINKING")

        # 2. Stop microphone and command Pi 4B to forward WAV to Voice Bridge
        try:
            vb_url = f"{self._get_voice_bridge_url()}/api/voice/process_audio"
            url = f"{self._get_pi4b_url()}/api/microphone/stop"
            payload = json.dumps({"voice_bridge_url": vb_url}).encode("utf-8")
            req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=25.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                self.logger.info("Microphone stopped and dispatched to Voice Bridge: %s", data)
        except Exception as e:
            self.logger.error("Error stopping and dispatching microphone on Pi 4B: %s", e)
            if not stop_event.is_set():
                self._set_kiosk_state("AWAITING_INPUT")
            return

        # 3. Wait briefly for turn processing and audio playback to conclude
        start_wait = time.time()
        while time.time() - start_wait < wait_timeout:
            if stop_event.is_set():
                self.logger.info("Turn aborted by stop_event.")
                return
            time.sleep(0.5)
            break

        # 4. Option B Rule: Return to AWAITING_INPUT (mic remains disarmed until next Button B tap)
        if not stop_event.is_set():
            self.logger.info("Voice turn execution complete. Returning to AWAITING_INPUT.")
            self._set_kiosk_state("AWAITING_INPUT")

    def teardown(self, backend: RobotBackend) -> None:
        """Post-run cleanup hook: stops recording, resets kiosk state."""
        self.logger.info("Executing OrnithVoiceApp teardown...")
        self._cancel_robot_mic()
        self._set_kiosk_state("IDLE")
        self.logger.info("OrnithVoiceApp teardown finished.")
