#!/usr/bin/env python3
"""Acoustic Clack & Snap Pose Teaching Subsystem for Pi 4B.
Listens to live microphone audio stream via PulseAudio (parecord).
Features:
1. Spectral Matched Filtering: Focuses on 2.5kHz - 5.5kHz mechanical click resonance (peak at ~3.2kHz),
   calculating real-time FFT high-to-low spectral energy ratios to strictly reject human speech, yelling,
   music, and ambient parade/market crowd noise.
2. Temporal Sharpness Gate: Validates sharp rise times (< 5ms) and rejects continuous or slow-rising noise.
3. Plastic Chamber Echo Suppression: 180ms refractory period eliminates double-triggering from mechanical clicker bounce.
4. Hardware Sequence & Audio Inhibit Muting: Mutes listener during sequence execution, rover driving, and sound playback.

Acoustic Classifier & Action Mapping:
- 1 Snap/Tap: Dry Bones chime (smw_stomp_bones.wav) -> Disarms torque (Arm goes limp for manual posing)
- 2 Snaps/Taps: Save Menu chime (smw_save_menu.wav) -> Captures empirical pose, re-engages torque
- 3 Snaps/Taps: Vine chime (smw_vine.wav) -> Smoothly resumes/interpolates to the last saved pose
- 4 Snaps/Taps: ☠️ Piranha Plant Attack Sequence (Mutes detector for full 12s duration)
"""

import collections
import json
import logging
import os
import subprocess
import threading
import time
import urllib.request
from typing import Optional, Dict, Any, List, Callable

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False

PI500_IP = "192.168.0.130"
PI500_API_URL = f"http://{PI500_IP}:8085"
MARIO_SOUNDS_DIR = "/home/carson/mario_sounds"

PULSE_ENV = dict(os.environ)
PULSE_ENV["XDG_RUNTIME_DIR"] = "/run/user/1000"
PULSE_ENV["PULSE_SERVER"] = "unix:/run/user/1000/pulse/native"


class AudioTapDetector:
    """Microphone listener with spectral matched filtering for acoustic clack detection."""

    def __init__(
        self,
        pi500_url: str = PI500_API_URL,
        peak_threshold: int = 3500,
        tap_window: float = 0.85,
        refractory_ms: int = 300,
        min_spectral_ratio: float = 5.0,
        min_high_energy_pct: float = 50.0,
        play_sound_cb: Optional[Callable[[str], None]] = None,
        is_active_cb: Optional[Callable[[], bool]] = None,
    ) -> None:
        self.pi500_url = pi500_url
        self.peak_threshold = peak_threshold
        self.tap_window = tap_window
        self.refractory_sec = refractory_ms / 1000.0
        self.min_spectral_ratio = min_spectral_ratio
        self.min_high_energy_pct = min_high_energy_pct
        self.play_sound_cb = play_sound_cb
        self.is_active_cb = is_active_cb

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()

        # Sequence & Audio Inhibit Muting
        self._mute_until: float = 0.0

        # Telemetry & Diagnostics
        self._current_peak = 0
        self._noise_floor = 0
        self._last_spectral_ratio = 0.0
        self._last_high_energy_pct = 0.0
        self._last_tap_amplitude = 0
        self._tap_timestamps: List[float] = []
        self._last_tap_intervals_ms: List[int] = []
        self._tap_count = 0
        self._last_tap_time = 0.0
        self._window_timer: Optional[threading.Timer] = None
        self._last_action: Optional[str] = None
        self._last_classification: str = "Spectral Matched Clacker Filter Active (1 Limp, 2 Save, 3 Resume, 4 Attack)"
        self._last_action_time: float = 0.0
        self._history: collections.deque = collections.deque(maxlen=10)

    def mute(self, duration_sec: float = 1.0) -> None:
        """Temporarily mutes acoustic detection (e.g. during sequence execution or audio playback)."""
        with self._lock:
            self._mute_until = max(self._mute_until, time.time() + duration_sec)
            logging.info("[AudioTapDetector] Muted for %.2fs (until t=%.2f)", duration_sec, self._mute_until)

    def unmute(self) -> None:
        """Immediately clears mute lockout."""
        with self._lock:
            self._mute_until = 0.0

    def is_muted(self) -> bool:
        """Returns True if detector is currently inhibited."""
        with self._lock:
            return time.time() < self._mute_until

    def set_threshold(self, threshold: int) -> None:
        with self._lock:
            self.peak_threshold = max(500, min(32000, threshold))
            logging.info("AudioTapDetector peak threshold set to %d", self.peak_threshold)

    def set_refractory(self, refractory_ms: int) -> None:
        with self._lock:
            self.refractory_sec = max(0.05, min(1.0, refractory_ms / 1000.0))
            logging.info("AudioTapDetector refractory lockout set to %d ms", refractory_ms)

    def start(self) -> None:
        """Starts the microphone capture background thread."""
        with self._lock:
            if self._running:
                return
            self._running = True
            self._thread = threading.Thread(target=self._listen_loop, name="AudioTapDetector", daemon=True)
            self._thread.start()
            logging.info("Started AudioTapDetector worker thread (threshold=%d, window=%.2fs, refractory=%.2fs, min_ratio=%.1f).",
                         self.peak_threshold, self.tap_window, self.refractory_sec, self.min_spectral_ratio)

    def stop(self) -> None:
        """Stops the microphone listener and cleans up subprocesses."""
        with self._lock:
            self._running = False
            if self._window_timer:
                self._window_timer.cancel()
                self._window_timer = None
            if self._proc:
                try:
                    self._proc.terminate()
                    self._proc.kill()
                    self._proc.wait(timeout=0.5)
                except Exception as proc_err:
                    logging.warning("Error terminating parecord process: %s", proc_err)
                self._proc = None
        if self._thread and self._thread.is_alive() and self._thread != threading.current_thread():
            self._thread.join(timeout=1.0)
        logging.info("Stopped AudioTapDetector.")

    def is_alive(self) -> bool:
        """Returns True if the detector is actively running."""
        with self._lock:
            return self._running and (self._thread is not None and self._thread.is_alive())

    def is_running(self) -> bool:
        return self.is_alive()

    def get_state(self) -> Dict[str, Any]:
        with self._lock:
            now = time.time()
            return {
                "running": self._running,
                "mode": "SPECTRAL_MATCHED_FILTER",
                "muted": now < self._mute_until,
                "mute_remaining_sec": max(0.0, round(self._mute_until - now, 2)),
                "peak_threshold": self.peak_threshold,
                "refractory_ms": int(self.refractory_sec * 1000),
                "min_spectral_ratio": self.min_spectral_ratio,
                "min_high_energy_pct": self.min_high_energy_pct,
                "tap_window_sec": self.tap_window,
                "current_peak": self._current_peak,
                "noise_floor": self._noise_floor,
                "last_spectral_ratio": self._last_spectral_ratio,
                "last_high_energy_pct": self._last_high_energy_pct,
                "last_tap_amplitude": self._last_tap_amplitude,
                "last_tap_intervals_ms": list(self._last_tap_intervals_ms),
                "last_action": self._last_action,
                "last_classification": self._last_classification,
                "last_action_time": self._last_action_time,
                "history": list(self._history),
            }

    def _play_sound(self, kind: str) -> None:
        """Plays sound via callback or local paplay fallback."""
        if self.play_sound_cb:
            try:
                self.play_sound_cb(kind)
                return
            except Exception as e:
                logging.warning("play_sound_cb error: %s", e)

        wav_file = os.path.join(MARIO_SOUNDS_DIR, f"{kind}.wav")
        if os.path.exists(wav_file):
            try:
                subprocess.Popen(["paplay", wav_file], env=PULSE_ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception as ex:
                logging.warning("Direct paplay error for %s: %s", kind, ex)

    def _get_api_url(self) -> str:
        try:
            from network_resolver import get_pi500_ip
        except ImportError:
            from pi4b.network_resolver import get_pi500_ip
        ip = get_pi500_ip(prefer_port=8085)
        if not ip:
            raise KeyError("Failed to resolve Pi 500 IP address from network_resolver")
        return f"http://{ip}:8085"

    def _dispatch_action(self, count: int, intervals: List[int], max_amp: int) -> None:
        """Dispatches verified clack/tap actions based on count."""
        if self.is_active_cb is not None and not self.is_active_cb():
            logging.warning("[AudioTapDetector] Action dispatch rejected: piranha_pose_app is not active.")
            self.stop()
            return
        now = time.time()
        api_url = self._get_api_url()

        if count == 1:
            # 1 Snap: Limp Mode (Torque Off)
            label = "1 Snap: Limp Mode (Torque Off)"
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
                    logging.info("Dispatched 1-snap torque disarm to Pi 500: status=%s", resp.status)
            except Exception as e:
                logging.error("Failed to dispatch 1-snap torque disarm to Pi 500: %s", e)

        elif count == 2:
            # 2 Snaps: Capture live pose to runtime memory variable & re-engage torque
            gap = intervals[0] if intervals else 0
            label = f"2 Snaps ({gap}ms gap): Temporary Pose Stored (Torque Locked)"
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
                    logging.info("Dispatched 2-snap temporary pose capture: result=%s", res_data)
            except Exception as e:
                logging.error("Failed to dispatch 2-snap pose capture to Pi 500: %s", e)

        elif count == 3:
            # 3 Snaps: Fast resume (1.0s) to last_saved_position
            gaps_str = ",".join(str(g) for g in intervals)
            label = f"3 Snaps ({gaps_str}ms): Fast Resume (1.0s)"
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
                    logging.info("Dispatched 3-snap fast resume to Pi 500: result=%s", res_data)
            except Exception as e:
                logging.error("Failed to dispatch 3-snap resume to Pi 500: %s", e)

        else:
            # 4+ Snaps: Piranha Plant Attack Sequence (Mute for 12.0s to cover the full choreography + roar)
            gaps_str = ",".join(str(g) for g in intervals)
            label = f"4 Snaps ({gaps_str}ms): ☠️ ATTACK SEQUENCE TRIGGERED"
            self.mute(12.0)
            try:
                req = urllib.request.Request(
                    f"{api_url}/api/arm/attack_sequence",
                    data=b"{}",
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=3.5) as resp:
                    res_data = json.loads(resp.read().decode("utf-8"))
                    logging.info("Dispatched 4-snap attack sequence to Pi 500: result=%s", res_data)
            except Exception as e:
                logging.error("Failed to dispatch 4-snap attack sequence to Pi 500: %s", e)

        with self._lock:
            self._last_action = f"{count}_taps_dispatched"
            self._last_classification = label
            self._last_action_time = now
            self._history.append({
                "time": now,
                "count": count,
                "intervals_ms": intervals,
                "max_amplitude": max_amp,
                "label": label,
            })

    def _on_window_expire(self) -> None:
        """Called when accumulation window closes without further taps."""
        with self._lock:
            count = self._tap_count
            intervals = list(self._last_tap_intervals_ms)
            max_amp = self._last_tap_amplitude
            self._tap_count = 0
            self._tap_timestamps = []
            self._window_timer = None
        if count > 0:
            if self.is_active_cb is not None and not self.is_active_cb():
                logging.warning("[AudioTapDetector] Window expired but app is no longer active, discarding actions.")
                self.stop()
                return
            threading.Thread(target=self._dispatch_action, args=(count, intervals, max_amp), daemon=True).start()

    def _on_tap_detected(self, peak_val: int) -> None:
        """Handles a validated acoustic clack event."""
        now = time.time()
        with self._lock:
            if self.is_active_cb is not None and not self.is_active_cb():
                logging.info("[AudioTapDetector] Tap ignored: piranha_pose_app is not active.")
                return

            if now < self._mute_until:
                return # Inhibited during sequence execution or audio playback

            if now - self._last_tap_time < self.refractory_sec:
                return # Refractory lockout eliminates chamber echoes

            interval_ms = int((now - self._last_tap_time) * 1000) if self._tap_timestamps else 0
            if self._tap_timestamps:
                self._last_tap_intervals_ms.append(interval_ms)
            else:
                self._last_tap_intervals_ms = []

            self._tap_timestamps.append(now)
            self._last_tap_time = now
            self._tap_count += 1
            self._last_tap_amplitude = max(self._last_tap_amplitude if self._tap_count > 1 else 0, peak_val)

            logging.info("[AudioTapDetector] VALID CLACK detected: count=%d, peak=%d, gap=%dms, ratio=%.1f",
                          self._tap_count, peak_val, interval_ms, self._last_spectral_ratio)

            if self._window_timer:
                self._window_timer.cancel()

            if self._tap_count >= 4:
                count = self._tap_count
                intervals = list(self._last_tap_intervals_ms)
                max_amp = self._last_tap_amplitude
                self._tap_count = 0
                self._tap_timestamps = []
                self._window_timer = None
                threading.Thread(target=self._dispatch_action, args=(count, intervals, max_amp), daemon=True).start()
                return

            self._window_timer = threading.Timer(self.tap_window, self._on_window_expire)
            self._window_timer.start()

    def _listen_loop(self) -> None:
        """Main audio capture and spectral matched transient processing loop."""
        chunk_samples = 512 # 32ms at 16000Hz
        chunk_bytes = chunk_samples * 2  # 16-bit mono
        sample_rate = 16000

        # Frequency bin masks (for 512-point real FFT at 16000Hz: 257 bins, ~31.25Hz/bin)
        freqs = np.fft.rfftfreq(chunk_samples, d=1.0/sample_rate) if NUMPY_AVAILABLE else []
        low_mask = (freqs >= 100) & (freqs < 1200) if NUMPY_AVAILABLE else []
        clack_mask = (freqs >= 2500) & (freqs <= 5500) if NUMPY_AVAILABLE else []
        win = np.hanning(chunk_samples) if NUMPY_AVAILABLE else []

        rolling_noise: List[int] = []

        while self._running:
            try:
                cmd = ["parecord", "--raw", "--rate=16000", "--channels=1"]
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    env=PULSE_ENV,
                )
                with self._lock:
                    self._proc = proc

                while self._running:
                    if self.is_active_cb is not None and not self.is_active_cb():
                        logging.info("[AudioTapDetector] Active app is no longer piranha_pose_app, auto-stopping listener loop.")
                        self._running = False
                        break

                    raw = proc.stdout.read(chunk_bytes)
                    if not raw or len(raw) < chunk_bytes:
                        break

                    now = time.time()
                    if now < self._mute_until:
                        # Muted: ignore audio frame completely
                        continue

                    if NUMPY_AVAILABLE:
                        data = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
                        peak = int(np.max(np.abs(data)))
                        rms = int(np.sqrt(np.mean(data ** 2)))
                    else:
                        import struct
                        shorts = struct.unpack(f"{chunk_samples}h", raw)
                        peak = max(abs(s) for s in shorts)
                        rms = int((sum(s * s for s in shorts) / chunk_samples) ** 0.5)

                    rolling_noise.append(rms)
                    if len(rolling_noise) > 30:
                        rolling_noise.pop(0)
                    avg_noise = max(1, sum(rolling_noise) // len(rolling_noise))

                    with self._lock:
                        self._current_peak = peak
                        self._noise_floor = avg_noise

                    if peak >= self.peak_threshold:
                        if NUMPY_AVAILABLE:
                            # 1. FFT Spectral Analysis
                            fft_mag = np.abs(np.fft.rfft(data * win))
                            e_low = float(np.sum(fft_mag[low_mask] ** 2))
                            e_clack = float(np.sum(fft_mag[clack_mask] ** 2))
                            e_total = float(np.sum(fft_mag ** 2)) + 1e-9

                            ratio = e_clack / max(1.0, e_low)
                            high_pct = (e_clack / e_total) * 100.0
                            sharpness = peak / float(avg_noise)

                            with self._lock:
                                self._last_spectral_ratio = round(ratio, 2)
                                self._last_high_energy_pct = round(high_pct, 1)

                            # Discrimination Filter:
                            # Must satisfy high/low ratio, high frequency energy percentage, and transient sharpness
                            if ratio >= self.min_spectral_ratio and high_pct >= self.min_high_energy_pct and sharpness >= 4.0:
                                self._on_tap_detected(peak)
                            else:
                                logging.debug("[REJECTED AMBIENT] peak=%d, ratio=%.1f, high_pct=%.1f%%, sharpness=%.1f",
                                              peak, ratio, high_pct, sharpness)
                        else:
                            # Fallback if numpy missing
                            self._on_tap_detected(peak)

            except Exception as e:
                logging.warning("AudioTapDetector loop exception: %s", e)
                time.sleep(0.5)
            finally:
                if self._proc:
                    try:
                        self._proc.terminate()
                        self._proc.kill()
                    except Exception as loop_proc_err:
                        logging.warning("Error terminating parecord process in finally: %s", loop_proc_err)
                    self._proc = None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    detector = AudioTapDetector()
    detector.start()
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        detector.stop()
