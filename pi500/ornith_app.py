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

    def setup(self, backend: RobotBackend) -> None:
        """Pre-run setup hook: verifies motor torque and initializes state."""
        self.backend = backend
        self.logger.info("Setting up OrnithVoiceApp on Pi 500...")
        try:
            backend.set_arm_torque(enable=True)
        except Exception as e:
            self.logger.warning("Could not verify arm torque on setup: %s", e)

        # Check for pending audio waiting to play upon load
        if os.path.exists(PENDING_AUDIO_FILE):
            self.logger.info("Found pending audio file %s to deliver on launch.", PENDING_AUDIO_FILE)
            self._set_kiosk_state("SPEAKING")
            try:
                with open(PENDING_AUDIO_FILE, "rb") as f:
                    wav_data = f.read()
                os.remove(PENDING_AUDIO_FILE)
                # Stream raw audio to Pi 4B
                url = f"{self._get_pi4b_url()}/api/play_sound"
                req = urllib.request.Request(url, data=wav_data, headers={"Content-Type": "audio/wav"})
                with urllib.request.urlopen(req, timeout=5.0):
                    pass
                time.sleep(1.5)
            except Exception as e:
                self.logger.error("Error playing pending audio on launch: %s", e)

        # Enter LISTENING state immediately
        self._set_kiosk_state("LISTENING")
        self._start_robot_mic()

    def run(self, backend: RobotBackend, stop_event: threading.Event) -> None:
        """Main interaction loop. Responds to Button B click for commit, and stop_event for abort."""
        self.logger.info("OrnithVoiceApp interaction loop running.")
        service = getattr(backend, "pokeball_service", None)

        if service and hasattr(service, "button_b_click_event"):
            service.button_b_click_event.clear()

        while not stop_event.is_set():
            # Check for Button B single click event
            if service and hasattr(service, "button_b_click_event") and service.button_b_click_event.is_set():
                service.button_b_click_event.clear()
                self.logger.info("Button B click detected! Finalizing voice turn...")
                self._handle_voice_turn(stop_event)

            time.sleep(0.05)

    def _handle_voice_turn(self, stop_event: threading.Event) -> None:
        """Finalizes audio capture, dispatches cues, invokes Voice Bridge, and plays response."""
        # 1. Dispatch midway gate chime immediately as recording stops and audio is sent
        self._play_pi4b_sound(kind="smw_midway_gate")
        self._set_kiosk_state("THINKING")

        # 2. Stop microphone and command Pi 4B to forward WAV to Voice Bridge
        try:
            vb_url = f"{self._get_voice_bridge_url()}/api/voice/process_audio"
            url = f"{self._get_pi4b_url()}/api/microphone/stop"
            payload = json.dumps({"voice_bridge_url": vb_url}).encode("utf-8")
            req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=20.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                self.logger.info("Microphone stopped and dispatched to Voice Bridge: %s", data)
        except Exception as e:
            self.logger.error("Error stopping and dispatching microphone on Pi 4B: %s", e)
            self._set_kiosk_state("IDLE")
            return

        # Voice Bridge on workstation handles:
        # - smw_chuck_whistle before transcription
        # - CoHere ASR transcription
        # - Intent classification & reasoning
        # - smw_princess_help before Laura TTS
        # - Streaming synthesized speech to Pi 4B speakers

        # Wait briefly for turn processing to settle
        start_wait = time.time()
        while time.time() - start_wait < 15.0:
            if stop_event.is_set():
                self.logger.info("Turn aborted by stop_event (Button A escape hatch).")
                return
            time.sleep(0.5)
            break

        self.logger.info("Voice turn execution complete. Returning to LISTENING.")
        if not stop_event.is_set():
            self._set_kiosk_state("LISTENING")
            self._start_robot_mic()

    def teardown(self, backend: RobotBackend) -> None:
        """Post-run cleanup hook: stops recording, resets kiosk state."""
        self.logger.info("Executing OrnithVoiceApp teardown...")
        self._set_kiosk_state("IDLE")
        try:
            url = f"{self._get_pi4b_url()}/api/microphone/stop"
            req = urllib.request.Request(url, data=b"{}", headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=2.0):
                pass
        except Exception:
            pass
        self.logger.info("OrnithVoiceApp teardown finished.")
