#!/usr/bin/env python3
"""Unified Mac HTTP API & Audio Analysis Daemon for SO-101 Leader & Beat Bandit.
Runs on Mac Mini (192.168.0.149 / 174.165.47.128:8086) on Port 8086.
Provides:
  1. Low-latency Leader teleop process control (<2ms)
  2. MMDenseLSTM Apple Silicon vocal isolation (50Hz envelope)
  3. Librosa structural rhythm & bass drop analysis
"""

from __future__ import annotations

import http.server
import socketserver
import json
import urllib.parse
import subprocess
import os
import sys
import time
import logging
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf
import librosa
import torch

# Base directories
BASE_DIR = Path("/Users/twinpeakstownie/reachy_mini")
REACHY_MIX_DIR = BASE_DIR / "reachy_ultradancemix_9000"
if REACHY_MIX_DIR.exists():
    sys.path.insert(0, str(REACHY_MIX_DIR))

from reachy_ultradancemix_9000.vendor.audyn.models.mm_dense_lstm import MMDenseLSTM

PORT = 8086
LEADER_SCRIPT = "/Users/twinpeakstownie/lerobot/so101_leader_client.py"
LEROBOT_PYTHON = "/Users/twinpeakstownie/lerobot/.venv/bin/python"

CACHE_DIR = BASE_DIR / "audio_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("unified_mac_daemon")

# Model Cache
MODEL_CACHE = {
    "mmdense": None,
    "device": "cpu"
}

def get_mmdense_model():
    if MODEL_CACHE["mmdense"] is not None:
        return MODEL_CACHE["mmdense"], MODEL_CACHE["device"]

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    logger.info(f"Loading MMDenseLSTM model on device: {device}...")
    
    pretrained_root = REACHY_MIX_DIR / "pretrained"
    base_model = MMDenseLSTM.build_from_pretrained(
        root=str(pretrained_root),
        task="musdb18",
        sample_rate=44100,
        target="vocals",
        quiet=True
    )
    base_model.eval()
    
    wrapper = MMDenseLSTM.TimeDomainWrapper(
        base_model,
        n_fft=base_model.n_fft,
        hop_length=base_model.hop_length,
        window_fn=base_model.window_fn
    )
    wrapper.eval()
    if device == "mps":
        wrapper = wrapper.to("mps")
    
    MODEL_CACHE["mmdense"] = wrapper
    MODEL_CACHE["device"] = device
    logger.info("MMDenseLSTM model initialized and cached.")
    return wrapper, device

# Leader Arm Process Management
def check_leader_running():
    try:
        res = subprocess.run(["pgrep", "-f", "so101_leader_client.py"], capture_output=True, text=True, timeout=1.0)
        if res.returncode == 0 and res.stdout.strip():
            pid = res.stdout.strip().split()[0]
            return True, pid
        return False, ""
    except Exception:
        return False, ""

def kill_leader():
    try:
        subprocess.run(["pkill", "-9", "-f", "so101_leader_client.py"], check=False)
        subprocess.run(["pkill", "-9", "-f", "leader_webui_server.py"], check=False)
        res = subprocess.run(["lsof", "-t", "/dev/cu.usbmodem5B415318721"], capture_output=True, text=True, timeout=1.0)
        if res.returncode == 0 and res.stdout.strip():
            for p in res.stdout.strip().split():
                subprocess.run(["kill", "-9", p], check=False)
        time.sleep(0.3)
        return True
    except Exception as e:
        logger.error(f"Error in kill_leader: {e}")
        return False

def start_leader():
    kill_leader()
    try:
        cmd = f"export PYTHONUNBUFFERED=1; nohup {LEROBOT_PYTHON} {LEADER_SCRIPT} > /tmp/leader.log 2>&1 &"
        subprocess.Popen(["zsh", "-c", cmd])
        time.sleep(0.5)
        running, pid = check_leader_running()
        return running, pid
    except Exception as e:
        logger.error(f"Error launching leader: {e}")
        return False, ""

# Audio Processing Pipeline
def download_audio_from_youtube(url: str, track_id: str) -> Path:
    target_wav = CACHE_DIR / f"{track_id}.wav"
    if target_wav.exists() and target_wav.stat().st_size > 10000:
        logger.info(f"Using existing cached audio: {target_wav}")
        return target_wav

    logger.info(f"Downloading audio from {url} via yt_dlp Python module...")
    import yt_dlp
    temp_prefix = str(CACHE_DIR / f"temp_{track_id}")
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': f"{temp_prefix}.%(ext)s",
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'ios', 'web']
            }
        },
        'quiet': True,
        'no_warnings': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    downloaded = list(CACHE_DIR.glob(f"temp_{track_id}.*"))
    if not downloaded:
        raise RuntimeError("yt-dlp failed to download audio file")
    
    raw_path = downloaded[0]
    y, sr = librosa.load(str(raw_path), sr=44100, mono=False)
    if y.ndim == 1:
        y = np.stack([y, y], axis=0)
    elif y.shape[0] > 2:
        y = y[:2, :]

    sf.write(str(target_wav), y.T, 44100, subtype='PCM_16')
    try:
        raw_path.unlink()
    except Exception:
        pass
    
    logger.info(f"Standardized audio to 44.1kHz stereo: {target_wav}")
    return target_wav

def analyze_track_dual_engine(wav_path: Path, track_id: str, title: str = "") -> dict:
    logger.info(f"Starting dual-engine analysis for {track_id}...")
    
    audio_stereo, sr = librosa.load(str(wav_path), sr=44100, mono=False)
    if audio_stereo.ndim == 1:
        audio_stereo = np.stack([audio_stereo, audio_stereo], axis=0)
    
    duration = audio_stereo.shape[1] / sr
    total_samples = audio_stereo.shape[1]
    logger.info(f"Audio duration: {duration:.2f}s, samples: {total_samples}")

    # 1. MMDenseLSTM Vocal Isolation
    model, device = get_mmdense_model()
    chunk_samples = 44100 * 10
    vocals_stereo = np.zeros_like(audio_stereo)
    
    for start in range(0, total_samples, chunk_samples):
        end = min(start + chunk_samples, total_samples)
        chunk = audio_stereo[:, start:end]
        tensor_chunk = torch.from_numpy(chunk).unsqueeze(0).float()
        if device == "mps":
            tensor_chunk = tensor_chunk.to("mps")
        
        with torch.no_grad():
            v_out = model(tensor_chunk)
        
        vocals_chunk = v_out.squeeze(0).cpu().numpy()
        vocals_stereo[:, start:end] = vocals_chunk

    # Save isolated vocals WAV
    vocals_wav_path = CACHE_DIR / f"{track_id}_vocals.wav"
    sf.write(str(vocals_wav_path), vocals_stereo.T, 44100, subtype='PCM_16')

    # 2. Extract 50Hz Mouth Envelope (Capped at 45%)
    vocals_mono = np.mean(vocals_stereo, axis=0)
    fps = 50
    hop_length_50hz = int(sr / fps)
    frame_len = hop_length_50hz * 2
    pad_amt = frame_len // 2
    padded_vocals = np.pad(vocals_mono, pad_amt, mode='reflect')
    
    num_frames = int(np.ceil(len(vocals_mono) / hop_length_50hz))
    vocal_rms = np.zeros(num_frames, dtype=np.float32)
    
    for i in range(num_frames):
        st = i * hop_length_50hz
        en = st + frame_len
        chunk = padded_vocals[st:en]
        vocal_rms[i] = np.sqrt(np.mean(chunk**2))
    
    noise_floor = np.percentile(vocal_rms, 15)
    peak_val = np.percentile(vocal_rms, 98)
    if peak_val > noise_floor + 1e-4:
        norm_env = np.clip((vocal_rms - noise_floor) / (peak_val - noise_floor), 0.0, 1.0)
    else:
        norm_env = np.zeros_like(vocal_rms)
    
    # 45% maximum mouth opening
    mouth_envelope = (norm_env * 45.0).round(2).tolist()

    # Held note detection (>= 1.2s of sustained vocal energy > 18%)
    held_notes = []
    min_held_frames = int(1.2 * fps)
    cur_start = None
    
    for i, val in enumerate(norm_env):
        if val > 0.18:
            if cur_start is None:
                cur_start = i
        else:
            if cur_start is not None:
                if (i - cur_start) >= min_held_frames:
                    held_notes.append({
                        "start_sec": round(cur_start / fps, 2),
                        "end_sec": round(i / fps, 2),
                        "duration": round((i - cur_start) / fps, 2)
                    })
                cur_start = None
    if cur_start is not None and (len(norm_env) - cur_start) >= min_held_frames:
        held_notes.append({
            "start_sec": round(cur_start / fps, 2),
            "end_sec": round(len(norm_env) / fps, 2),
            "duration": round((len(norm_env) - cur_start) / fps, 2)
        })

    # 3. Librosa Rhythm & Structural Drop Detection
    audio_mono = librosa.to_mono(audio_stereo)
    tempo, beat_frames = librosa.beat.beat_track(y=audio_mono, sr=sr)
    if isinstance(tempo, np.ndarray):
        tempo = float(tempo[0])
    tempo = float(tempo)
    beat_times = librosa.frames_to_time(beat_frames, sr=sr).round(3).tolist()
    downbeats = beat_times[::4]

    stft_spec = np.abs(librosa.stft(audio_mono, n_fft=2048, hop_length=hop_length_50hz))
    freqs = librosa.fft_frequencies(sr=sr, n_fft=2048)
    
    idx_sub = np.where((freqs >= 30) & (freqs <= 120))[0]
    sub_energy = np.mean(stft_spec[idx_sub, :], axis=0) if len(idx_sub) else np.zeros(num_frames)
    norm_sub = sub_energy / (np.max(sub_energy) + 1e-6)
    
    drops = []
    window_pts = int(fps * 2.0)
    for i in range(window_pts, len(norm_sub) - window_pts, int(fps * 0.5)):
        prev_min = np.min(norm_sub[i - window_pts : i])
        cur_max = np.max(norm_sub[i : i + int(fps * 0.5)])
        if prev_min < 0.15 and cur_max > 0.65:
            drop_sec = round(i / fps, 2)
            if not any(abs(d["drop_sec"] - drop_sec) < 15.0 for d in drops):
                drops.append({
                    "drop_sec": drop_sec,
                    "anticipation_start_sec": max(0.0, round(drop_sec - 4.0, 2)),
                    "vacuum_start_sec": max(0.0, round(drop_sec - 1.0, 2))
                })

    # Extract real acoustic segments using Librosa agglomerative clustering on MFCCs
    try:
        mfcc = librosa.feature.mfcc(y=audio_mono, sr=sr, n_mfcc=13)
        num_seg = max(2, min(10, int(duration // 25)))
        bound_frames = librosa.segment.agglomerative(mfcc, k=num_seg)
        bound_times = librosa.frames_to_time(bound_frames, sr=sr).tolist()
        bound_times = [0.0] + sorted(list(set([round(t, 2) for t in bound_times if 0.0 < t < duration]))) + [round(duration, 2)]

        sections = []
        for idx in range(len(bound_times) - 1):
            s_start = bound_times[idx]
            s_end = bound_times[idx + 1]
            if s_end - s_start < 2.0:
                continue
            sections.append({
                "type": f"SECTION_{idx + 1}",
                "start_sec": s_start,
                "end_sec": s_end
            })
    except Exception as seg_err:
        logger.warning(f"Acoustic segmentation warning: {seg_err}")
        sections = [{
            "type": "SECTION_1",
            "start_sec": 0.0,
            "end_sec": round(duration, 2)
        }]

    manifest = {
        "track_id": track_id,
        "title": title or track_id,
        "duration": round(duration, 2),
        "bpm": round(tempo, 1),
        "fps": fps,
        "beat_times": beat_times,
        "downbeats": downbeats,
        "drops": drops,
        "sections": sections,
        "held_notes": held_notes,
        "mouth_envelope_50hz": mouth_envelope
    }

    manifest_path = CACHE_DIR / f"{track_id}_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    logger.info(f"Analysis complete for {track_id}. Written to: {manifest_path}")
    return manifest

class UnifiedDaemonHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _send_json(self, data, code=200):
        body = json.dumps(data).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        
        if path == "/api/status":
            running, pid = check_leader_running()
            self._send_json({"running": running, "pid": pid, "host": "mac"})
        elif path == "/api/health":
            mps_avail = torch.backends.mps.is_available()
            self._send_json({
                "status": "ok",
                "service": "unified_mac_daemon",
                "mps_available": mps_avail,
                "device": "mps" if mps_avail else "cpu",
                "cache_dir": str(CACHE_DIR)
            })
        elif path.startswith("/api/manifest/"):
            track_id = path.replace("/api/manifest/", "").strip("/")
            manifest_path = CACHE_DIR / f"{track_id}_manifest.json"
            if manifest_path.exists():
                with open(manifest_path, "r", encoding="utf-8") as f:
                    self._send_json(json.load(f))
            else:
                self._send_json({"error": "Manifest not found"}, 404)
        elif path.startswith("/api/audio/"):
            track_id = path.replace("/api/audio/", "").strip("/")
            wav_path = CACHE_DIR / f"{track_id}.wav"
            if wav_path.exists():
                data = wav_path.read_bytes()
                self.send_response(200)
                self.send_header('Content-Type', 'audio/wav')
                self.send_header('Content-Length', str(len(data)))
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(data)
            else:
                self._send_json({"error": "Audio file not found"}, 404)
        else:
            self._send_json({"status": "ok", "service": "unified_mac_daemon_8086"})

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        content_length = int(self.headers.get('Content-Length', 0))
        body_bytes = self.rfile.read(content_length) if content_length > 0 else b'{}'
        try:
            body = json.loads(body_bytes.decode('utf-8')) if body_bytes else {}
        except Exception:
            body = {}

        if parsed.path in ["/api/leader_toggle", "/api/start", "/api/stop"]:
            action = body.get("action", "toggle")
            if parsed.path == "/api/start":
                action = "start"
            elif parsed.path == "/api/stop":
                action = "stop"

            running, pid = check_leader_running()
            if action == "toggle":
                action = "stop" if running else "start"

            if action == "start":
                run_ok, new_pid = start_leader()
                self._send_json({"status": "ok", "action": "start", "running": run_ok, "pid": new_pid})
            elif action in ["stop", "kill"]:
                kill_leader()
                self._send_json({"status": "ok", "action": "stop", "running": False, "pid": ""})
            else:
                self._send_json({"error": f"Unknown action: {action}"}, 400)

        elif parsed.path == "/api/analyze_track":
            url = body.get("url", "")
            track_id = body.get("track_id", "")
            force_recompute = body.get("force_recompute", False)
            
            if not track_id:
                if "v=" in url:
                    track_id = url.split("v=")[1].split("&")[0]
                elif "youtu.be/" in url:
                    track_id = url.split("youtu.be/")[1].split("?")[0]
                else:
                    track_id = "custom_track"

            manifest_path = CACHE_DIR / f"{track_id}_manifest.json"
            if manifest_path.exists() and not force_recompute:
                logger.info(f"Returning cached manifest for {track_id}")
                with open(manifest_path, "r", encoding="utf-8") as f:
                    self._send_json(json.load(f))
                return

            try:
                wav_path = download_audio_from_youtube(url, track_id)
                manifest = analyze_track_dual_engine(wav_path, track_id)
                self._send_json(manifest)
            except Exception as e:
                logger.error(f"Analysis error: {e}", exc_info=True)
                self._send_json({"error": str(e)}, 500)
        else:
            self._send_json({"error": "Endpoint not found"}, 404)

class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True

def main():
    print(f"Starting Unified Mac HTTP API & Audio Daemon on port {PORT}...", flush=True)
    server = ThreadedHTTPServer(('0.0.0.0', PORT), UnifiedDaemonHandler)
    server.serve_forever()

if __name__ == "__main__":
    main()
