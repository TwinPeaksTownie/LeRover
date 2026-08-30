#!/usr/bin/env python3
"""Beat Bandit Audio Transport & Remote Service Client.
Handles:
  - Mac Mini (192.168.0.2:8086) deep neural analysis retrieval & WAV downloads.
  - In-memory WAV slicing for precise subsection playback.
  - Pi 4B (192.168.0.86:8082) PulseAudio dispatch and stop triggers.
  - Title and artist string sanitization.
"""

from __future__ import annotations

import io
import json
import logging
import os
import re
import urllib.parse
import urllib.request
import wave
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

try:
    import network_resolver
except ImportError:
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import network_resolver

logger = logging.getLogger("so101.beat_bandit_audio")


def get_pi4b_sound_url() -> str:
    pi4b_ip = network_resolver.get_pi4b_ip(prefer_port=8082)
    return f"http://{pi4b_ip}:8082/api/play_sound"


def slice_wav_in_memory(wav_path: str, start_sec: float = 0.0, end_sec: Optional[float] = None) -> bytes:
    """Extracts a precise slice of a WAV file in memory using stdlib wave."""
    if not os.path.exists(wav_path):
        return b""
    try:
        with wave.open(wav_path, "rb") as wf:
            nchannels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            framerate = wf.getframerate()
            nframes = wf.getnframes()
            total_dur = nframes / float(framerate) if framerate > 0 else 0.0

            start_f = int(max(0.0, float(start_sec)) * framerate)
            if end_sec is not None and float(end_sec) > 0.0:
                end_f = int(min(total_dur, float(end_sec)) * framerate)
            else:
                end_f = nframes

            start_f = min(start_f, nframes)
            end_f = max(start_f, min(end_f, nframes))

            wf.setpos(start_f)
            frames_to_read = end_f - start_f
            data = wf.readframes(frames_to_read)

            buf = io.BytesIO()
            with wave.open(buf, "wb") as out_wf:
                out_wf.setnchannels(nchannels)
                out_wf.setsampwidth(sampwidth)
                out_wf.setframerate(framerate)
                out_wf.writeframes(data)
            return buf.getvalue()
    except Exception as e:
        logger.error(f"Failed slicing WAV file '{wav_path}' ({start_sec}s -> {end_sec}s): {e}")
        return b""


def sanitize_title_and_artist(raw_title: str, uploader: str = "") -> Tuple[str, str]:
    """Cleans YouTube video titles to extract pure Song Title and Artist."""
    t = raw_title.strip()
    t = re.sub(r"[\(\[\{][^\)\]\}]*(?:lyrics|official|audio|video|hd|hq|4k|visualizer|soundtrack|ost)[^\)\]\}]*[\)\]\}]", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\|\s*.*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s+", " ", t).strip()

    if " - " in t:
        parts = t.split(" - ", 1)
        artist = parts[0].strip()
        song = parts[1].strip()
    elif " by " in t.lower():
        parts = re.split(r"\s+by\s+", t, flags=re.IGNORECASE, maxsplit=1)
        song = parts[0].strip()
        artist = parts[1].strip()
    else:
        song = t
        artist = uploader or "Unknown Artist"
    return song, artist


def stop_pi4b_audio() -> bool:
    """Sends immediate stop signal to Pi 4B sound service."""
    try:
        stop_req = urllib.request.Request(
            get_pi4b_sound_url(),
            data=json.dumps({"action": "stop"}).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(stop_req, timeout=1.5) as resp:
            return resp.status == 200
    except Exception as e:
        logger.debug(f"Pi 4B audio stop call notice: {e}")
        return False


def dispatch_audio_to_pi4b(wav_path: str, start_sec: float = 0.0, end_sec: Optional[float] = None) -> bool:
    """Dispatches audio payload to Pi 4B PulseAudio service (full or sliced)."""
    try:
        stop_pi4b_audio()

        if not os.path.exists(wav_path):
            logger.warning(f"Audio file not found for dispatch: {wav_path}")
            return False

        if float(start_sec) > 0.05 or (end_sec is not None and float(end_sec) > 0.0):
            logger.info(f"Slicing in-memory WAV audio for section {start_sec:.2f}s to {end_sec if end_sec else 'END'}s...")
            raw_wav = slice_wav_in_memory(wav_path, start_sec=start_sec, end_sec=end_sec)
        else:
            logger.info(f"Dispatching full audio ({os.path.getsize(wav_path)/(1024*1024):.1f} MB) to Pi 4B...")
            with open(wav_path, "rb") as f:
                raw_wav = f.read()

        if raw_wav:
            req = urllib.request.Request(
                get_pi4b_sound_url(),
                data=raw_wav,
                headers={"Content-Type": "audio/wav"}
            )
            with urllib.request.urlopen(req, timeout=7.0) as resp:
                if resp.status == 200:
                    logger.info(f"Audio payload ({len(raw_wav)/1024:.1f} KB) successfully dispatched to Pi 4B.")
                    return True
    except Exception as e:
        logger.warning(f"Audio dispatch warning: {e}")
    return False


class BeatBanditAudioClient:
    """Client for Mac Mini neural audio analysis and Pi 4B sound distribution."""

    def __init__(self, library_dir: Path) -> None:
        self.library_dir = library_dir
        self.library_dir.mkdir(parents=True, exist_ok=True)

    def fetch_analysis(self, url_or_id: str, track_id: str, mac_ip: Optional[str] = None) -> Dict[str, Any]:
        """Calls Mac Deep Audio Analysis Microservice (Port 8086)."""
        target_mac = mac_ip or network_resolver.get_mac_ip(prefer_port=8086)
        mac_url = f"http://{target_mac}:8086/api/analyze_track"
        logger.info(f"Calling Mac Audio Microservice at {mac_url}...")

        target_url = url_or_id if "http" in url_or_id else f"https://youtu.be/{track_id}"
        req_data = json.dumps({"url": target_url, "track_id": track_id}).encode("utf-8")
        req = urllib.request.Request(mac_url, data=req_data, headers={"Content-Type": "application/json"})

        with urllib.request.urlopen(req, timeout=60.0) as resp:
            if resp.status != 200:
                raise RuntimeError(f"Mac Audio Service returned HTTP {resp.status}")
            analysis = json.loads(resp.read().decode("utf-8"))

        if not analysis or "mouth_envelope_50hz" not in analysis:
            raise RuntimeError("Mac Audio Service returned invalid or empty analysis payload")

        return analysis

    def download_wav(self, track_id: str, mac_ip: Optional[str] = None) -> str:
        """Downloads cached WAV file from Mac Mini to local library directory."""
        dest_path = str(self.library_dir / f"{track_id}.wav")
        if os.path.exists(dest_path) and os.path.getsize(dest_path) > 1000:
            return dest_path

        target_mac = mac_ip or network_resolver.get_mac_ip(prefer_port=8086)
        audio_dl_url = f"http://{target_mac}:8086/api/audio/{track_id}"
        logger.info(f"Downloading WAV audio from {audio_dl_url}...")
        urllib.request.urlretrieve(audio_dl_url, dest_path)

        if not os.path.exists(dest_path) or os.path.getsize(dest_path) < 1000:
            raise RuntimeError(f"Failed to retrieve WAV audio for track '{track_id}'")

        return dest_path

    def dispatch_playback(self, wav_path: str, start_sec: float = 0.0, end_sec: Optional[float] = None) -> bool:
        return dispatch_audio_to_pi4b(wav_path, start_sec=start_sec, end_sec=end_sec)

    def stop_playback(self) -> bool:
        return stop_pi4b_audio()
