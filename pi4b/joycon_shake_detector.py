#!/usr/bin/env python3
"""pi4b/joycon_shake_detector.py - Joy-Con 6-Axis IMU Shake Detector for Piranha Pose App.
Replaces the legacy acoustic microphone AudioTapDetector with physical Joy-Con (R) gestures.
Listens to sharp acceleration spikes decoded by PokeballService from Report 0x30.

Action Mapping:
- 1 Shake: Dry Bones chime (smw_stomp_bones) -> Disarms torque (Arm goes limp for manual posing)
- 2 Shakes: Save Menu chime (smw_save_menu) -> Captures empirical pose, re-engages torque
- 3 Shakes: Vine chime (smw_vine) -> Smoothly resumes/interpolates to the last saved pose
- 4 Shakes: ☠️ Piranha Plant Attack Sequence (Mutes detector for full 12s duration)
"""

import collections
import json
import logging
import os
import sys
import threading
import time
import urllib.request
from typing import Optional, Dict, Any, List, Callable

current_dir = os.path.dirname(os.path.abspath(__file__))
workspace_root = os.path.abspath(os.path.join(current_dir, ".."))
for p in [workspace_root, os.path.join(workspace_root, "config"), current_dir]:
    if os.path.isdir(p) and p not in sys.path:
        sys.path.append(p)

BACKEND_API_URL = "http://127.0.0.1:8085"


def load_shake_detector_config() -> Dict[str, Any]:
    """Loads fail-fast shake detector configuration from preset_app/config.json."""
    candidates = [
        os.path.join(workspace_root, "apps", "preset_app", "config.json"),
        "/home/carson/touch_ui/apps/preset_app/config.json",
        "/home/user/so101/apps/preset_app/config.json",
    ]
    for p in candidates:
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            _ = float(cfg["shake_detector"]["shake_threshold_g"])
            _ = float(cfg["shake_detector"]["shake_cooldown_sec"])
            _ = float(cfg["shake_detector"]["shake_window_sec"])
            _ = float(cfg["shake_detector"]["baseline_alpha"])
            return cfg["shake_detector"]
    raise FileNotFoundError(f"Missing required preset_app config.json for JoyConShakeDetector. Checked: {candidates}")


class JoyConShakeDetector:
    """Listens to Joy-Con (R) IMU shake events and accumulates gestures to command Piranha Pose."""

    def __init__(
        self,
        joycon_service: Optional[Any] = None,
        backend_url: str = BACKEND_API_URL,
        play_sound_cb: Optional[Callable[[str], None]] = None,
        is_active_cb: Optional[Callable[[], bool]] = None,
    ) -> None:
        self.joycon_service = joycon_service
        self.backend_url = backend_url
        self.play_sound_cb = play_sound_cb
        self.is_active_cb = is_active_cb
        self.logger = logging.getLogger("so101.joycon_shake_detector")

        self.config = load_shake_detector_config()
        self.shake_window = float(self.config["shake_window_sec"])
        self.shake_threshold = float(self.config["shake_threshold_g"])

        self._running = False
        self._lock = threading.Lock()
        self._mute_until = 0.0

        self._shake_count = 0
        self._shake_timestamps: List[float] = []
        self._last_shake_time = 0.0
        self._window_timer: Optional[threading.Timer] = None

        self._last_action: Optional[str] = None
        self._last_classification: str = "Joy-Con Shake Detector Active (1 Limp, 2 Save, 3 Resume, 4 Attack)"
        self._last_action_time: float = 0.0
        self._history: collections.deque = collections.deque(maxlen=10)

    def mute(self, duration_sec: float) -> None:
        """Mutes shake detection during motion execution or sound playback."""
        with self._lock:
            self._mute_until = max(self._mute_until, time.time() + duration_sec)
            self.logger.info("[JoyConShakeDetector] Muted for %.2fs (until t=%.2f)", duration_sec, self._mute_until)

    def is_alive(self) -> bool:
        return self._running

    def start(self) -> None:
        """Subscribes to Joy-Con service shake events."""
        with self._lock:
            if self._running:
                return
            self._running = True
            if self.joycon_service is not None:
                self.joycon_service.register_shake_callback(self._on_joycon_shake)
                self.logger.info("JoyConShakeDetector subscribed to Joy-Con service shake events.")
            else:
                self.logger.warning("JoyConShakeDetector started without bound joycon_service.")

    def stop(self) -> None:
        """Unsubscribes from Joy-Con service and cancels active timers."""
        with self._lock:
            self._running = False
            if self._window_timer:
                self._window_timer.cancel()
                self._window_timer = None
            if self.joycon_service is not None:
                self.joycon_service.unregister_shake_callback(self._on_joycon_shake)
            self._shake_count = 0
            self._shake_timestamps.clear()
            self.logger.info("Stopped JoyConShakeDetector.")

    def _play_sound(self, kind: str) -> None:
        """Dispatches audio event via callback. Fails loudly if unconfigured."""
        if not self.play_sound_cb:
            raise RuntimeError(f"Cannot dispatch sound '{kind}': play_sound_cb is not configured on JoyConShakeDetector")
        self.play_sound_cb(kind)

    def _get_api_url(self) -> str:
        try:
            from network_resolver import get_master_backend_ip
        except ImportError:
            from pi4b.network_resolver import get_master_backend_ip
        ip = get_master_backend_ip()
        return f"http://{ip}:8085"

    def _dispatch_action(self, count: int, max_delta: float) -> None:
        """Dispatches verified physical shake actions based on count."""
        if self.is_active_cb is not None and not self.is_active_cb():
            self.logger.warning("[JoyConShakeDetector] Action dispatch rejected: piranha_pose_app is not active.")
            self.stop()
            return
        now = time.time()
        api_url = self._get_api_url()

        if count == 1:
            # 1 Shake: Limp Mode (Torque Off)
            label = "1 Shake: Limp Mode (Torque Off)"
            self.mute(1.0)
            self._play_sound("smw_stomp_bones")
            try:
                payload = json.dumps({"enable": False}).encode("utf-8")
                req = urllib.request.Request(
                    f"{api_url}/api/arm/torque",
                    data=payload,
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=1.5) as resp:
                    self.logger.info("Dispatched 1-shake torque disarm: status=%s", resp.status)
            except Exception as e:
                self.logger.error("Failed to dispatch 1-shake torque disarm: %s", e)

        elif count == 2:
            # 2 Shakes: Capture live pose to runtime memory variable & re-engage torque
            label = "2 Shakes: Temporary Pose Stored (Torque Locked)"
            self.mute(1.5)
            self._play_sound("smw_save_menu")
            try:
                req = urllib.request.Request(
                    f"{api_url}/api/arm/capture_pose",
                    data=b"{}",
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=2.5) as resp:
                    res_data = json.loads(resp.read().decode("utf-8"))
                    self.logger.info("Dispatched 2-shake pose capture: result=%s", res_data)
            except Exception as e:
                self.logger.error("Failed to dispatch 2-shake pose capture: %s", e)

        elif count == 3:
            # 3 Shakes: Fast resume (1.0s) to last_saved_position
            label = "3 Shakes: Fast Resume (1.0s)"
            self.mute(2.5)
            self._play_sound("smw_vine")
            try:
                payload = json.dumps({"duration": 1.0}).encode("utf-8")
                req = urllib.request.Request(
                    f"{api_url}/api/arm/resume_last_pose",
                    data=payload,
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=3.5) as resp:
                    res_data = json.loads(resp.read().decode("utf-8"))
                    self.logger.info("Dispatched 3-shake fast resume: result=%s", res_data)
            except Exception as e:
                self.logger.error("Failed to dispatch 3-shake resume: %s", e)

        else:
            # 4+ Shakes: Piranha Plant Attack Sequence (Mute for 12.0s)
            label = "4 Shakes: ☠️ ATTACK SEQUENCE TRIGGERED"
            self.mute(12.0)
            try:
                payload = json.dumps({"source": "joycon_shake"}).encode("utf-8")
                req = urllib.request.Request(
                    f"{api_url}/api/arm/attack_sequence",
                    data=payload,
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=3.5) as resp:
                    res_data = json.loads(resp.read().decode("utf-8"))
                    self.logger.info("Dispatched 4-shake attack sequence: result=%s", res_data)
            except Exception as e:
                self.logger.error("Failed to dispatch 4-shake attack sequence: %s", e)

        with self._lock:
            self._last_action = f"{count}_shakes_dispatched"
            self._last_classification = label
            self._last_action_time = now
            self._history.append({
                "time": now,
                "count": count,
                "max_delta": max_delta,
                "label": label,
            })

    def _on_window_expire(self) -> None:
        """Called when accumulation window closes without further shakes."""
        with self._lock:
            count = self._shake_count
            self._shake_count = 0
            self._shake_timestamps.clear()
            self._window_timer = None
        if count > 0:
            if self.is_active_cb is not None and not self.is_active_cb():
                self.logger.warning("[JoyConShakeDetector] Window expired but app is no longer active, discarding actions.")
                self.stop()
                return
            threading.Thread(target=self._dispatch_action, args=(count, 0.0), daemon=True).start()

    def _on_joycon_shake(self, accel_mag: float, delta: float) -> None:
        """Callback invoked by PokeballService on validated Joy-Con shake."""
        now = time.time()
        with self._lock:
            if not self._running:
                return

            if self.is_active_cb is not None and not self.is_active_cb():
                self.logger.info("[JoyConShakeDetector] Shake ignored: piranha_pose_app is not active.")
                return

            if now < self._mute_until:
                self.logger.debug("[JoyConShakeDetector] Shake ignored: detector currently muted (motion or audio in progress).")
                return

            self._shake_timestamps.append(now)
            self._last_shake_time = now
            self._shake_count += 1

            self.logger.info("[JoyConShakeDetector] VALID SHAKE registered: count=%d, mag=%.2fG, delta=%.2fG",
                             self._shake_count, accel_mag, delta)

            if self._window_timer:
                self._window_timer.cancel()

            if self._shake_count >= 4:
                count = self._shake_count
                self._shake_count = 0
                self._shake_timestamps.clear()
                self._window_timer = None
                threading.Thread(target=self._dispatch_action, args=(count, delta), daemon=True).start()
                return

            self._window_timer = threading.Timer(self.shake_window, self._on_window_expire)
            self._window_timer.start()

    def get_state(self) -> Dict[str, Any]:
        """Returns structured detector telemetry for server and UI endpoints."""
        accel_mag = 1.0
        baseline = 1.0
        thresh = self.shake_threshold
        if self.joycon_service and hasattr(self.joycon_service, "telemetry"):
            accel_data = self.joycon_service.telemetry["accel"]
            accel_mag = accel_data["mag"]
            baseline = accel_data["baseline"]
            thresh = self.joycon_service.shake_threshold

        with self._lock:
            return {
                "running": self._running,
                "mode": "JOYCON_SHAKE_DETECTOR",
                "count": self._shake_count,
                "last_action": self._last_action,
                "last_classification": self._last_classification,
                "last_action_time": self._last_action_time,
                "current_mag": accel_mag,
                "baseline": baseline,
                "threshold": thresh,
                "muted": bool(time.time() < self._mute_until),
                "history": list(self._history),
            }
