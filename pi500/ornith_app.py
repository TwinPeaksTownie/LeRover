#!/usr/bin/env python3
"""ornith_app.py - Standalone Ornith Voice Application for SO-101.
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

try:
    import network_resolver
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import network_resolver

PENDING_AUDIO_FILE = "/tmp/pending_ornith_audio.wav"
VOICE_BRIDGE_DEFAULT_PORT = 8058


class OrnithVoiceApp(BaseApp):
    metadata = AppMetadata(
        name="ornith_voice",
        title="Ornith Voice Assistant",
        description="Autonomous Voice & Executive Simplification Assistant",
        version="1.0.0",
        tags=["voice", "ai", "ornith", "cohere", "tts"],
        icon="🎙️"
    )

    def __init__(self, running_on_pi: bool = True) -> None:
        super().__init__(running_on_pi=running_on_pi)
        self.logger = logging.getLogger("so101.app.ornith_voice")
        self.backend: Optional[RobotBackend] = None
        self.state = "IDLE"

    def _get_pi4b_url(self) -> str:
        ip = network_resolver.get_pi4b_ip(prefer_port=8082)
        return f"http://{ip}:8082"

    def _get_voice_bridge_url(self) -> str:
        # Workstation PC host
        return f"http://192.168.0.194:{VOICE_BRIDGE_DEFAULT_PORT}"

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
        def _post():
            try:
                url = f"{self._get_pi4b_url()}/api/play_sound"
                payload = json.dumps({
                    "kind": kind,
                    "stop_previous": stop_previous,
                    "delay_sec": delay_sec
                }).encode("utf-8")
                req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=2.0):
                    pass
            except Exception as e:
                self.logger.warning("Sound dispatch '%s' to Pi 4B failed: %s", kind, e)
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
        """Plays chuck whistle cue, enforces 0.2s settle sleep, and arms Pi 4B microphone."""
        self.logger.info("Starting listening turn: playing smw_chuck_whistle cue...")
        self._set_kiosk_state("LISTENING")
        self._play_pi4b_sound(kind="smw_chuck_whistle")
        # Chuck whistle duration is ~0.4s + 0.2s settle sleep = 0.6s total
        time.sleep(0.65)
        self.recording_start_time = time.time()
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
        self.logger.info("Setting up OrnithVoiceApp on Pi 500...")
        try:
            backend.set_arm_torque(enable=True)
        except Exception as e:
            self.logger.warning("Could not verify arm torque on setup: %s", e)

        # 1. Check for pending audio waiting on Pi 4B or local Pi 500 buffer
        has_local_pending = os.path.exists(PENDING_AUDIO_FILE)
        has_pi4b_pending = self._check_pending_audio_on_pi4b()

        if has_local_pending or has_pi4b_pending:
            self.logger.info("Found pending audio response. Enforcing 2.0s settle delay before playback...")
            self._set_kiosk_state("SPEAKING")
            time.sleep(2.0)

            if has_local_pending:
                try:
                    with open(PENDING_AUDIO_FILE, "rb") as f:
                        wav_data = f.read()
                    os.remove(PENDING_AUDIO_FILE)
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

        # 2. First turn: Auto-listen on initial app launch (Whistle -> 0.2s pause -> mic on)
        self._start_listening_turn()

    def run(self, backend: RobotBackend, stop_event: threading.Event) -> None:
        """Main interaction loop implementing Option B cadence, 3s cancel window, and 30s auto-send."""
        self.logger.info("OrnithVoiceApp Option B interaction loop running.")
        if not hasattr(backend, "pokeball_service") or backend.pokeball_service is None:
            raise AttributeError("RobotBackend is missing required 'pokeball_service' attribute")
        service = backend.pokeball_service

        if not hasattr(service, "button_b_click_event") or service.button_b_click_event is None:
            raise AttributeError("PokeballService is missing required 'button_b_click_event' attribute")
        service.button_b_click_event.clear()

        while not stop_event.is_set():
            now = time.time()

            # Check Button B single click event
            if service.button_b_click_event.is_set():
                service.button_b_click_event.clear()

                if self.state == "AWAITING_INPUT":
                    # Tap-to-Listen follow-up turn
                    self.logger.info("Button B click in AWAITING_INPUT: Starting follow-up listening turn...")
                    self._start_listening_turn()

                elif self.state == "LISTENING":
                    elapsed = now - self.recording_start_time
                    if elapsed < 3.0:
                        # Quick cancel (< 3.0s): abort and play rejection sound
                        self.logger.info("Button B clicked within %.2fs (< 3.0s). Cancelling turn with smw_shell_ricochet.", elapsed)
                        self._cancel_robot_mic()
                        self._play_pi4b_sound(kind="smw_shell_ricochet")
                        self._set_kiosk_state("AWAITING_INPUT")
                    else:
                        # Commit speech (>= 3.0s)
                        self.logger.info("Button B clicked at %.2fs. Committing speech turn...", elapsed)
                        self._handle_voice_turn(stop_event)

            # Auto-send safety net: 30.0s elapsed in LISTENING state without manual tap
            if self.state == "LISTENING" and (now - self.recording_start_time >= 30.0):
                self.logger.info("30-second auto-send timeout reached. Finalizing voice turn...")
                self._handle_voice_turn(stop_event)

            time.sleep(0.05)

    def _handle_voice_turn(self, stop_event: threading.Event) -> None:
        """Finalizes audio capture, dispatches midway gate cue, invokes Voice Bridge, and returns to AWAITING_INPUT."""
        # 1. Dispatch midway gate action chime immediately as recording stops
        self._play_pi4b_sound(kind="smw_midway_gate")
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
        while time.time() - start_wait < 12.0:
            if stop_event.is_set():
                self.logger.info("Turn aborted by stop_event (Button A escape hatch).")
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
