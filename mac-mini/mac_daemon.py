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
import torchaudio
import re

try:
    import essentia.standard as es
except ImportError:
    es = None

try:
    from sklearn.cluster import AgglomerativeClustering
    from sklearn.neighbors import kneighbors_graph
    from sklearn.preprocessing import StandardScaler
    from scipy.ndimage import uniform_filter1d
except ImportError:
    AgglomerativeClustering = None
    kneighbors_graph = None
    StandardScaler = None
    uniform_filter1d = None

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
_CACHED_WHISPER_MODEL = None

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

def search_youtube_candidates(query: str, limit: int = 4) -> list:
    """Queries YouTube search results via yt-dlp without downloading audio."""
    import yt_dlp
    logger.info(f"Searching YouTube candidates for '{query}' (limit={limit})...")
    ydl_opts = {
        'extract_flat': True,
        'quiet': True,
        'no_warnings': True,
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'ios', 'web']
            }
        }
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        res = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)

    if "entries" not in res or not isinstance(res["entries"], list):
        raise KeyError("Missing or invalid required key 'entries' in yt-dlp search payload")

    entries = res["entries"]
    candidates = []
    for item in entries:
        if not item:
            continue
        if "id" not in item:
            raise KeyError("Missing required key 'id' in yt-dlp search entry")
        if "title" not in item:
            raise KeyError("Missing required key 'title' in yt-dlp search entry")
        if "channel" in item and item["channel"]:
            channel = str(item["channel"])
        elif "uploader" in item and item["uploader"]:
            channel = str(item["uploader"])
        else:
            raise KeyError("Missing required key 'channel' or 'uploader' in yt-dlp search entry")
        if "duration" not in item or item["duration"] is None:
            raise KeyError("Missing required key 'duration' in yt-dlp search entry")

        video_id = str(item["id"])
        title = str(item["title"])
        duration = float(item["duration"])
        candidates.append({
            "video_id": video_id,
            "title": title,
            "channel": channel,
            "duration": duration,
        })
        if len(candidates) >= limit:
            break
    logger.info(f"Found {len(candidates)} candidates for query '{query}'")
    return candidates

def infer_section_labels(segments: list[dict], total_duration: float, first_vocal_sec: Optional[float] = None) -> list[dict]:
    """Infers structural labels (intro, verse, chorus, bridge, outro) from segment energy z-scores,
    timeline position, and empirical vocal onset timestamp.
    """
    if not segments:
        raise ValueError("Cannot infer section labels on empty segment list.")

    energies = np.array([float(s["energy"]) for s in segments])
    mean_e = float(np.mean(energies))
    std_e = float(np.std(energies))
    if std_e < 1e-6:
        std_e = 1.0

    for i, seg in enumerate(segments):
        pos = float(seg["start_sec"]) / max(1.0, total_duration)
        dur = float(seg["duration"])
        e = float(seg["energy"])
        z = (e - mean_e) / std_e

        if i == 0:
            # Physical reality: If vocal delivery starts early in the section, it is Verse 1, not Intro
            if first_vocal_sec is not None and first_vocal_sec < min(3.5, float(seg["end_sec"])):
                label = "verse"
            elif dur < 6.0 and (z < -0.2 or (first_vocal_sec is not None and first_vocal_sec >= float(seg["end_sec"]))):
                label = "intro"
            else:
                label = "verse"
        elif i == len(segments) - 1:
            label = "outro" if (dur < 20.0 and z < 0.1) else "chorus"
        else:
            if z > 0.4:
                label = "chorus"
            elif dur < 8.0:
                label = "bridge"
            elif pos < 0.65:
                label = "verse"
            else:
                label = "chorus" if z > 0.0 else "bridge"

        seg["type"] = label
        seg["energy_score"] = round(float(z), 3)

    return segments

def extract_lyrics_and_breath(vocals_wav_path: Path, mouth_envelope: list, fps: int = 50, chapter_boundaries: Optional[list] = None) -> list:
    """Extracts spoken lyrics using Whisper text transcription + MMS_FA CTC Forced Alignment,
    clusters words into natural acoustic phrases at silence gaps (>=0.25s) or chapter boundaries,
    and snaps visual phrase boundaries flush against the 50Hz MMDenseLSTM vocal envelope.
    """
    logger.info(f"Extracting lyrics and breath landmarks from {vocals_wav_path} via MMS_FA...")
    
    # 1. Load 16kHz mono audio for Whisper & MMS_FA
    y_16k, sr_16k = librosa.load(str(vocals_wav_path), sr=16000, mono=True)
    if len(y_16k) == 0:
        logger.warning(f"Vocals file {vocals_wav_path} is empty.")
        return []
    y_16k = np.ascontiguousarray(y_16k, dtype=np.float32)
    max_abs = np.max(np.abs(y_16k))
    if max_abs > 1e-4:
        y_16k = y_16k / max_abs

    # 2. Text transcription via Whisper
    raw_text = ""
    segments = []
    try:
        try:
            from faster_whisper import WhisperModel
            whisper_model = WhisperModel("base.en", device="cpu", compute_type="int8")
            segments_gen, _ = whisper_model.transcribe(y_16k, beam_size=1, condition_on_previous_text=False)
            for s in segments_gen:
                t = s.text.strip()
                if t:
                    segments.append({"start": float(s.start), "end": float(s.end), "text": t})
            raw_text = " ".join(s["text"] for s in segments).strip()
        except ImportError:
            import whisper
            global _CACHED_WHISPER_MODEL
            if _CACHED_WHISPER_MODEL is None:
                _CACHED_WHISPER_MODEL = whisper.load_model("base.en")
            result = _CACHED_WHISPER_MODEL.transcribe(y_16k, fp16=False)
            if "segments" not in result:
                raise KeyError("Missing required key 'segments' in whisper transcription result")
            for s in result["segments"]:
                if "text" not in s:
                    raise KeyError("Missing required key 'text' in whisper segment")
                t = s["text"].strip()
                if t:
                    segments.append({"start": float(s["start"]), "end": float(s["end"]), "text": t})
            if "text" not in result:
                raise KeyError("Missing required key 'text' in whisper transcription result")
            raw_text = result["text"].strip()
    except Exception as e:
        logger.error(f"Whisper transcription failed on {vocals_wav_path}: {e}")
        return []

    if not raw_text or not segments:
        logger.warning(f"No spoken words transcribed in {vocals_wav_path}")
        return []

    # 3. Padded Phrase-Grouped MMS_FA CTC Forced Alignment (~20-30s batches with song-edge padding)
    all_words = []
    try:
        bundle = torchaudio.pipelines.MMS_FA
        fa_model = bundle.get_model().to("cpu")
        tokenizer = bundle.get_tokenizer()
        aligner = bundle.get_aligner()

        total_duration = len(y_16k) / 16000.0

        batches = []
        current_batch = []
        for s in segments:
            current_batch.append(s)
            batch_span = current_batch[-1]["end"] - current_batch[0]["start"]
            if batch_span >= 25.0:
                batches.append(current_batch)
                current_batch = []
        if current_batch:
            batches.append(current_batch)

        for b_idx, batch_segs in enumerate(batches):
            batch_text = " ".join(s["text"] for s in batch_segs).strip()
            raw_words = [w.strip() for w in batch_text.split() if w.strip()]
            cleaned_words = []
            valid_indices = []
            for idx, w in enumerate(raw_words):
                cw = re.sub(r"[^a-zA-Z']", "", w).lower()
                if cw:
                    cleaned_words.append(cw)
                    valid_indices.append(idx)

            if not cleaned_words:
                continue

            # Generous 3.0s pad at song boundaries; contiguous boundaries between batches to prevent token smearing
            pad_st = max(0.0, batch_segs[0]["start"] - 3.0) if b_idx == 0 else batch_segs[0]["start"]
            pad_en = min(total_duration, batch_segs[-1]["end"] + 3.0) if b_idx == len(batches) - 1 else batch_segs[-1]["end"]

            chunk_st_sample = int(pad_st * 16000)
            chunk_en_sample = int(pad_en * 16000)
            chunk_y = y_16k[chunk_st_sample:chunk_en_sample]

            if len(chunk_y) < 1600:
                continue

            chunk_waveform = torch.from_numpy(chunk_y).unsqueeze(0).float()
            with torch.inference_mode():
                emissions, _ = fa_model(chunk_waveform)
                emissions = torch.log_softmax(emissions, dim=-1)

            emission = emissions[0].cpu().detach()
            tokens = tokenizer(cleaned_words)
            aligned_tokens_list = aligner(emission, tokens)
            ratio = len(chunk_y) / emission.shape[0] / 16000.0

            for word_spans, orig_idx in zip(aligned_tokens_list, valid_indices):
                if not word_spans:
                    continue
                w_start = round(pad_st + float(word_spans[0].start * ratio), 2)
                w_end = round(pad_st + float(word_spans[-1].end * ratio), 2)
                all_words.append({
                    "word": raw_words[orig_idx],
                    "start": w_start,
                    "end": max(round(w_start + 0.04, 2), w_end)
                })
    except Exception as e:
        logger.error(f"MMS_FA forced alignment failed on {vocals_wav_path}: {e}")
        return []

    if not all_words:
        logger.warning(f"No words aligned in {vocals_wav_path}")
        return []

    # 4. Group words into natural acoustic phrases
    chapter_bounds = sorted(chapter_boundaries or [])
    lines = []
    current_words = []

    for w in all_words:
        if not current_words:
            current_words.append(w)
            continue

        prev_w = current_words[-1]
        gap = w["start"] - prev_w["end"]
        prev_word_clean = prev_w["word"].strip().rstrip("\"'”’")
        has_punct = prev_word_clean.endswith((',', '.', '?', '!', ';', ':', '—', '-', '…'))

        # Hard chapter boundary
        crossed_chapter = any(prev_w["end"] <= cb <= w["start"] or (prev_w["start"] < cb <= w["start"]) for cb in chapter_bounds)
        # Acoustic silence gap >= 250ms
        is_acoustic_pause = (gap >= 0.25)

        if crossed_chapter or has_punct or is_acoustic_pause:
            lines.append(current_words)
            current_words = [w]
        else:
            current_words.append(w)

    if current_words:
        lines.append(current_words)

    # 5. Flush Envelope Snapping & Breath Extraction
    blocks = []
    lyric_idx = 1
    breath_idx = 1
    n_lines = len(lines)

    for line_idx, line_words in enumerate(lines):
        line_text = " ".join(w["word"] for w in line_words)
        raw_st = float(line_words[0]["start"])
        raw_en = float(line_words[-1]["end"])
        prev_block_end = blocks[-1]["end_sec"] if blocks else 0.0

        if line_idx + 1 < n_lines:
            next_line_st = float(lines[line_idx + 1][0]["start"])
        else:
            next_line_st = len(mouth_envelope) / fps

        # A. Snap start_sec to the nearest acoustic vocal onset frame (>= 5.0%)
        st_sec = raw_st
        search_start = max(int(prev_block_end * fps), int((raw_st - 0.3) * fps))
        search_end = min(len(mouth_envelope), int((raw_st + 0.3) * fps))
        if search_end > search_start:
            for f_idx in range(search_start, search_end):
                if mouth_envelope[f_idx] >= 5.0:
                    st_sec = round(f_idx / fps, 2)
                    break
        st_sec = max(prev_block_end, st_sec)
        line_words[0]["start"] = st_sec

        # B. Breath Inhale Detection in silence pre-roll
        phrase_start_frame = int(st_sec * fps)
        breath_lookback_frames = int(0.7 * fps)
        breath_end_offset_frames = int(0.15 * fps)

        b_start_frame = max(int(prev_block_end * fps), phrase_start_frame - breath_lookback_frames)
        b_end_frame = max(b_start_frame, phrase_start_frame - breath_end_offset_frames)

        has_breath = False
        b_actual_start = None
        b_actual_end = None

        if b_end_frame > b_start_frame and b_end_frame <= len(mouth_envelope):
            pre_env = mouth_envelope[b_start_frame:b_end_frame]
            active_frames = [idx for idx, val in enumerate(pre_env) if val >= 5.0]
            if len(active_frames) >= int(0.15 * fps):
                has_breath = True
                b_actual_start = round((b_start_frame + active_frames[0]) / fps, 2)
                b_actual_end = round((b_start_frame + active_frames[-1] + 1) / fps, 2)

        if has_breath and b_actual_start is not None and b_actual_end is not None:
            if b_actual_start >= prev_block_end and b_actual_end <= st_sec:
                blocks.append({
                    "id": f"br_{breath_idx:03d}",
                    "name": "Breath Inhale",
                    "text": "[breath]",
                    "original_asr_text": "[breath]",
                    "type": "breath",
                    "is_user_edited": False,
                    "start_sec": b_actual_start,
                    "end_sec": b_actual_end,
                    "duration": round(b_actual_end - b_actual_start, 2)
                })
                breath_idx += 1
                prev_block_end = b_actual_end
                st_sec = max(prev_block_end, st_sec)
                line_words[0]["start"] = st_sec

        # C. Snap end_sec to true vocal energy trailing decay (>= 5.0%)
        en_frame = int(raw_en * fps)
        max_frame = int(next_line_st * fps)
        last_active = max(int(st_sec * fps), en_frame)

        if en_frame < len(mouth_envelope):
            for f_idx in range(en_frame, min(len(mouth_envelope), max_frame)):
                if mouth_envelope[f_idx] >= 5.0:
                    last_active = f_idx
                elif f_idx - last_active > int(0.20 * fps):  # 200ms silence gap
                    break

        snapped_en = round((last_active + 1) / fps, 2)
        en_sec = max(round(st_sec + 0.1, 2), min(snapped_en, next_line_st))
        line_words[-1]["end"] = en_sec
        dur = round(en_sec - st_sec, 2)

        blocks.append({
            "id": f"ly_{lyric_idx:03d}",
            "name": f"Line {lyric_idx}",
            "text": line_text,
            "original_asr_text": line_text,
            "type": "lyric",
            "is_user_edited": False,
            "start_sec": st_sec,
            "end_sec": en_sec,
            "duration": dur,
            "words": line_words
        })
        lyric_idx += 1

    return blocks

def analyze_track_dual_engine(wav_path: Path, track_id: str, title: str = "") -> dict:
    logger.info(f"Starting Essentia dual-engine analysis for {track_id}...")
    
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

    # Extract 50Hz Full Audio Amplitude Envelope (Normalized 0.0 - 1.0)
    audio_mono = np.mean(audio_stereo, axis=0)
    audio_rms = np.zeros(num_frames, dtype=np.float32)
    for i in range(num_frames):
        st = i * hop_length_50hz
        en = min(len(audio_mono), st + frame_len)
        if st < len(audio_mono):
            chunk = audio_mono[st:en]
            audio_rms[i] = np.sqrt(np.mean(chunk**2)) if len(chunk) > 0 else 0.0
    a_peak = np.percentile(audio_rms, 99) if len(audio_rms) > 0 else 1.0
    if a_peak > 1e-4:
        norm_audio_env = np.clip(audio_rms / a_peak, 0.0, 1.0)
    else:
        norm_audio_env = np.zeros_like(audio_rms)
    amplitude_envelope = [round(float(v), 3) for v in norm_audio_env]

    # 3. Librosa Empirical Beat & Rhythm Tracking
    if AgglomerativeClustering is None or StandardScaler is None:
        raise RuntimeError("scikit-learn is missing on Mac Mini for structural segmentation.")

    tempo_val, beat_frames = librosa.beat.beat_track(y=audio_mono, sr=sr)
    tempo = float(tempo_val[0]) if isinstance(tempo_val, np.ndarray) else float(tempo_val)
    beat_times = [round(float(b), 3) for b in librosa.frames_to_time(beat_frames, sr=sr)]
    if not beat_times:
        raise RuntimeError(f"Failed to detect musical beats in {wav_path}")
    downbeats = beat_times[::4]

    # Grounded dynamic complexity & danceability pulse regularity (Zero synthetic scaling multipliers)
    onset_env = librosa.onset.onset_strength(y=audio_mono, sr=sr)
    pulse = librosa.beat.plp(onset_envelope=onset_env, sr=sr)
    p_max = float(np.max(pulse)) if len(pulse) > 0 else 0.0
    danceability = round(float(np.mean(pulse) / (p_max + 1e-6)), 3)
    
    rms_mean = float(np.mean(audio_rms))
    if rms_mean <= 1e-6:
        raise RuntimeError(f"Audio RMS energy is zero for {wav_path}")
    dynamic_complexity = round(float(np.std(audio_rms) / rms_mean), 3)

    # 4. Beat-Synchronous Harmonic (Chroma) & Timbral (MFCC) Feature Extraction
    hop_length = 512
    mfcc_feat = librosa.feature.mfcc(y=audio_mono, sr=sr, n_mfcc=13, hop_length=hop_length)
    chroma_feat = librosa.feature.chroma_stft(y=audio_mono, sr=sr, hop_length=hop_length)
    spectral_features = np.vstack([mfcc_feat, chroma_feat]) # (25, n_frames)

    beat_features = librosa.util.sync(spectral_features, beat_frames, aggregate=np.median).T # (n_beats, 25)
    beat_features_norm = StandardScaler().fit_transform(beat_features)

    # 5. Sequential 1D Temporal Connectivity Graph (Contiguous Macro Sections)
    n_beats = len(beat_features_norm)
    n_macro = max(2, min(12, int(round(duration / 30.0))))
    time_grid = np.arange(n_beats).reshape(-1, 1)
    connectivity = kneighbors_graph(time_grid, n_neighbors=2, mode='connectivity', include_self=False)
    clust = AgglomerativeClustering(n_clusters=n_macro, connectivity=connectivity, linkage='ward')
    c_labels = clust.fit_predict(beat_features_norm)

    change_indices = [0]
    for li in range(1, len(c_labels)):
        if c_labels[li] != c_labels[li - 1]:
            change_indices.append(li)

    raw_b_times = [float(beat_times[min(idx, len(beat_times) - 1)]) for idx in change_indices]

    # Extract ASR lyrics and acoustic breath landmarks
    lyrics_blocks = extract_lyrics_and_breath(vocals_wav_path, mouth_envelope, fps=fps, chapter_boundaries=raw_b_times)
    first_vocal_sec = lyrics_blocks[0]["start_sec"] if lyrics_blocks else None

    # Snap boundary timeline (aligning opening with acoustic feature transitions and vocal onset)
    b_times = [0.0]
    if first_vocal_sec is not None and first_vocal_sec > 0.5:
        b_times.append(round(first_vocal_sec, 2))

    for bt in raw_b_times[1:]:
        if bt > b_times[-1] + 1.0 and bt < duration - 1.0:
            b_times.append(round(bt, 2))
    b_times.append(round(duration, 2))

    raw_sections = []
    for s_i in range(len(b_times) - 1):
        st_sec = b_times[s_i]
        en_sec = b_times[s_i + 1]
        st_sample = int(st_sec * sr)
        en_sample = int(en_sec * sr)
        seg_audio = audio_mono[st_sample:en_sample]
        seg_rms = float(np.sqrt(np.mean(seg_audio**2))) if len(seg_audio) > 0 else 0.0
        seg_beats = sum(1 for b in beat_times if st_sec <= b < en_sec)
        raw_sections.append({
            "start_sec": st_sec,
            "end_sec": en_sec,
            "duration": round(en_sec - st_sec, 2),
            "energy": round(seg_rms, 4),
            "beat_count": seg_beats,
        })

    if not raw_sections:
        raise RuntimeError(f"Structural segmentation failed to identify valid acoustic sections in {wav_path}")

    # Sub-bass drop detection (30 - 120 Hz)
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

    # Infer structural labels with real acoustic energy and vocal onset
    sections = infer_section_labels(raw_sections, duration, first_vocal_sec=first_vocal_sec)

    manifest = {
        "track_id": track_id,
        "title": title or track_id,
        "duration": round(duration, 2),
        "bpm": round(tempo, 1),
        "danceability": danceability,
        "dynamic_complexity": dynamic_complexity,
        "fps": fps,
        "beat_times": beat_times,
        "downbeats": downbeats,
        "drops": drops,
        "sections": sections,
        "held_notes": held_notes,
        "mouth_envelope_50hz": mouth_envelope,
        "amplitude_envelope_50hz": amplitude_envelope,
        "lyrics": lyrics_blocks
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

        elif parsed.path == "/api/search":
            if "query" not in body:
                self._send_json({"error": "Missing required parameter 'query'"}, 400)
                return
            query = str(body["query"]).strip()
            if not query:
                self._send_json({"error": "Query cannot be empty"}, 400)
                return
            if "limit" not in body:
                self._send_json({"error": "Missing required parameter 'limit'"}, 400)
                return
            limit = int(body["limit"])
            try:
                candidates = search_youtube_candidates(query, limit=limit)
                self._send_json({"status": "ok", "query": query, "candidates": candidates})
            except Exception as e:
                logger.error(f"Search API failure for '{query}': {e}", exc_info=True)
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
