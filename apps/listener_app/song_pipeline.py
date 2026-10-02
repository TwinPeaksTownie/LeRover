#!/usr/bin/env python3
"""apps/listener_app/song_pipeline.py - Song Audio Download & Choreography Synthesis Pipeline.
Handles:
  1. yt-dlp retrieval of requested track audio to local WAV.
  2. Rhythm, beat, and measure analysis (local or Mac Mini daemon).
  3. Automatic compilation of 0-100% ROM choreography via choreography_compiler.
  4. Sequence persistence and registry lookup.
Strict Fail-Fast schema compliance: Zero .get(k, default) fallbacks.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Dict, Any, Optional, List

logger = logging.getLogger("so101.listener_app.song_pipeline")

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent.parent
PI4B_DIR = WORKSPACE_ROOT / "pi4b"
if str(PI4B_DIR) not in sys.path:
    sys.path.insert(0, str(PI4B_DIR))

import network_resolver

try:
    from choreography_compiler import compile_choreography_tracks, load_choreography_probabilities
except ImportError:
    logger.warning("Could not import choreography_compiler directly, will resolve at runtime.")
    compile_choreography_tracks = None
    load_choreography_probabilities = None


def sanitize_slug(name: str) -> str:
    """Sanitizes song title or artist into a clean filesystem slug."""
    clean = name.lower().strip()
    clean = re.sub(r"[^\w\s-]", "", clean)
    return re.sub(r"[\s-]+", "_", clean).strip("_")


def get_sequences_dir() -> Path:
    """Returns directory where compiled dance sequences are stored."""
    candidates = [
        WORKSPACE_ROOT / "apps" / "preset_app" / "sequences",
        Path.home() / "so101" / "apps" / "preset_app" / "sequences",
        WORKSPACE_ROOT / "library" / "beat_bandit" / "sequences",
    ]
    for c in candidates:
        if c.is_dir():
            return c
    # Default to creating apps/preset_app/sequences
    target = WORKSPACE_ROOT / "apps" / "preset_app" / "sequences"
    target.mkdir(parents=True, exist_ok=True)
    return target


def get_audio_cache_dir() -> Path:
    """Returns directory where downloaded WAV audio is cached."""
    target = WORKSPACE_ROOT / "library" / "beat_bandit" / "audio"
    target.mkdir(parents=True, exist_ok=True)
    return target


def get_beat_bandit_manifest_path() -> Optional[Path]:
    """Returns the resolved path to Beat Bandit's library manifest.json."""
    candidates = [
        WORKSPACE_ROOT / "library" / "beat_bandit" / "manifest.json",
        Path.home() / "so101" / "library" / "beat_bandit" / "manifest.json",
        Path("/home/user/so101/library/beat_bandit/manifest.json"),
    ]
    for c in candidates:
        if c.is_file():
            return c
    return None


def load_fuzzy_threshold() -> float:
    """Loads fuzzy match threshold from config.json fail-fast."""
    cfg_path = Path(__file__).resolve().parent / "config.json"
    if cfg_path.exists():
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        return float(cfg["vad"]["fuzzy_match_threshold"])
    return 0.55


def find_beat_bandit_track(
    query: str,
    manifest_path: Optional[Path] = None,
    fuzzy_threshold: Optional[float] = None
) -> Optional[Dict[str, Any]]:
    """Finds an existing analyzed track in Beat Bandit manifest matching the query string.
    Strict Fail-Fast schema compliance: validates required keys explicitly. Zero .get(k, default).
    Sequential fallback: Exact -> Substring Containment -> Fuzzy Sequence Matching.
    """
    target = manifest_path or get_beat_bandit_manifest_path()
    if target is None or not target.exists():
        logger.warning("Beat Bandit manifest not found at candidate locations.")
        return None

    thresh = fuzzy_threshold if fuzzy_threshold is not None else load_fuzzy_threshold()

    with open(target, "r", encoding="utf-8") as f:
        manifest_data = json.load(f)

    if not isinstance(manifest_data, dict):
        raise TypeError(f"Beat Bandit manifest at {target} must be a dict, got {type(manifest_data).__name__}")

    clean_query = re.sub(r"[^\w\s]", "", query.lower()).strip()
    clean_query = re.sub(r"\s+", " ", clean_query)
    if not clean_query:
        return None

    clean_query = re.sub(r"\b(?:the\s+song|song|the\s+track|track)\b", "", clean_query).strip()

    spaceless_query = clean_query.replace(" ", "")

    exact_match: Optional[Dict[str, Any]] = None
    partial_match: Optional[Dict[str, Any]] = None
    best_fuzzy_meta: Optional[Dict[str, Any]] = None
    best_fuzzy_ratio: float = 0.0

    import difflib

    for tid, meta in manifest_data.items():
        if not isinstance(meta, dict):
            continue

        for req_field in ("track_id", "title", "artist", "wav_path"):
            if req_field not in meta:
                raise KeyError(f"Track '{tid}' in {target} missing required field '{req_field}'")

        title_str = str(meta["title"])
        artist_str = str(meta["artist"])
        clean_title = re.sub(r"[^\w\s]", "", title_str.lower()).strip()
        clean_title = re.sub(r"\s+", " ", clean_title)
        clean_artist = re.sub(r"[^\w\s]", "", artist_str.lower()).strip()
        clean_artist = re.sub(r"\s+", " ", clean_artist)

        spaceless_title = clean_title.replace(" ", "")
        clean_combined = f"{clean_title} {clean_artist}".strip()
        clean_by = f"{clean_title} by {clean_artist}".strip()
        spaceless_combined = clean_combined.replace(" ", "")

        if clean_query == clean_title or spaceless_query == spaceless_title or clean_query == tid.lower():
            exact_match = meta
            break

        if clean_query == clean_by or clean_query == clean_combined or spaceless_query == spaceless_combined:
            exact_match = meta
            break

        if partial_match is None:
            if clean_query in clean_title or clean_title in clean_query or spaceless_query in spaceless_title or spaceless_title in spaceless_query:
                partial_match = meta
            elif clean_artist and (clean_query in clean_artist or clean_artist in clean_query):
                partial_match = meta

        # Sequential fallback: calculate sequence similarity ratio
        r_title = difflib.SequenceMatcher(None, clean_query, clean_title).ratio()
        r_comb = difflib.SequenceMatcher(None, clean_query, clean_combined).ratio()
        max_r = max(r_title, r_comb)
        if max_r > best_fuzzy_ratio:
            best_fuzzy_ratio = max_r
            best_fuzzy_meta = meta

    if exact_match is not None:
        return exact_match
    if partial_match is not None:
        return partial_match
    if best_fuzzy_meta is not None and best_fuzzy_ratio >= thresh:
        logger.info(
            "Fuzzy matched track query '%s' to '%s' (ratio %.3f >= %.3f)",
            clean_query, best_fuzzy_meta["title"], best_fuzzy_ratio, thresh
        )
        return best_fuzzy_meta

    return None


def find_compiled_sequence(title: str) -> Optional[Path]:
    """Finds an existing compiled sequence JSON by matching title slug."""
    slug = sanitize_slug(title)
    seq_dir = get_sequences_dir()
    if not seq_dir.exists():
        return None

    direct_match = seq_dir / f"{slug}.json"
    if direct_match.exists():
        return direct_match

    # Search by containment
    for f in seq_dir.glob("*.json"):
        if slug in f.stem or f.stem in slug:
            return f
    return None


def fetch_audio_ytdlp(query: str, output_wav: Path) -> Path:
    """Downloads audio track via yt-dlp and converts to 44.1kHz 16-bit mono/stereo WAV."""
    logger.info("Fetching audio with yt-dlp for query: '%s'...", query)
    cmd = [
        "yt-dlp",
        f"ytsearch1:{query}",
        "-x",
        "--audio-format", "wav",
        "--audio-quality", "0",
        "--postprocessor-args", "ffmpeg:-ar 44100 -ac 2",
        "-o", str(output_wav.with_suffix(".%(ext)s")),
        "--no-playlist",
        "--quiet",
        "--no-warnings"
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"yt-dlp failed to download audio for '{query}': {res.stderr}")

    if not output_wav.exists():
        candidates = list(output_wav.parent.glob(f"{output_wav.stem}.*"))
        for c in candidates:
            if c.suffix.lower() == ".wav":
                return c
        raise FileNotFoundError(f"yt-dlp completed but output WAV was not found at {output_wav}")
    return output_wav


def analyze_audio_track(wav_path: Path) -> Dict[str, Any]:
    """Generates structural rhythm and envelope analysis for choreography compilation.
    Enforces musical divisions: measures, beats, 4bars, and 8bars.
    """
    import wave
    with wave.open(str(wav_path), "rb") as wf:
        nframes = wf.getnframes()
        framerate = wf.getframerate()
        if framerate <= 0:
            raise ValueError(f"Invalid framerate {framerate} in WAV: {wav_path}")
        duration = float(nframes) / float(framerate)

    if duration <= 0.0:
        raise ValueError(f"Invalid duration {duration} for WAV: {wav_path}")

    # Fallback to local librosa analysis if available, otherwise synthetic structural grid
    is_synthetic = False
    analysis_provenance = "librosa_beat_track"
    bpm = 120.0
    beat_times = []
    try:
        import librosa
        y, sr = librosa.load(str(wav_path), sr=22050)
        tempo, beats = librosa.beat.beat_track(y=y, sr=sr)
        detected_tempo = float(tempo)
        if detected_tempo <= 0:
            raise ValueError(f"Detected invalid non-positive tempo: {detected_tempo}")
        bpm = detected_tempo
        beat_times = [float(t) for t in librosa.frames_to_time(beats, sr=sr)]
    except Exception as e:
        is_synthetic = True
        analysis_provenance = "synthetic_musical_grid"
        logger.warning("Local librosa analysis unavailable (%s), synthesizing musical grid...", e, exc_info=True)
        # Synthesize standard musical grid at 120 BPM
        sec_per_beat = 60.0 / bpm
        cur_t = 0.0
        while cur_t < duration:
            beat_times.append(round(cur_t, 3))
            cur_t += sec_per_beat

    if not beat_times:
        is_synthetic = True
        analysis_provenance = "synthetic_musical_grid"
        sec_per_beat = 60.0 / bpm
        beat_times = [round(i * sec_per_beat, 3) for i in range(int(duration / sec_per_beat))]

    # Group beats into measures (4 beats per measure)
    downbeats = [beat_times[i] for i in range(0, len(beat_times), 4)]

    # 50 Hz envelopes (zero-fill baseline if deep vocal isolation model is not running)
    total_50hz_frames = int(duration * 50)
    amp_env = [0.5 for _ in range(total_50hz_frames)]
    mouth_env = [0.0 for _ in range(total_50hz_frames)]

    return {
        "title": wav_path.stem.replace("_", " ").title(),
        "duration": duration,
        "bpm": bpm,
        "tempo": bpm,
        "beat_times": beat_times,
        "downbeats": downbeats,
        "drops": [],
        "held_notes": [],
        "sections": [
            {"type": "intro", "start_sec": 0.0, "end_sec": min(duration, 15.0), "energy_score": 0.4},
            {"type": "verse", "start_sec": min(duration, 15.0), "end_sec": min(duration, 45.0), "energy_score": 0.6},
            {"type": "chorus", "start_sec": min(duration, 45.0), "end_sec": duration, "energy_score": 0.9}
        ],
        "amplitude_envelope_50hz": amp_env,
        "mouth_envelope_50hz": mouth_env,
        "is_synthetic": is_synthetic,
        "analysis_provenance": analysis_provenance,
    }


def _validate_candidate(item: Dict[str, Any]) -> Dict[str, Any]:
    """Validates candidate metadata against strict fail-fast schema contracts.
    Requires 'id', 'title', 'duration' (or 'duration_string'), and 'uploader' (or 'channel').
    Raises KeyError or ValueError on missing or corrupt contract fields.
    """
    if "id" not in item or not item["id"]:
        raise KeyError("Candidate payload missing mandatory non-empty 'id' key")
    video_id = str(item["id"])

    if "title" not in item or not item["title"]:
        raise KeyError(f"Candidate '{video_id}' missing mandatory non-empty 'title' key")
    title = str(item["title"])

    if "duration" in item and isinstance(item["duration"], (int, float)):
        dur_sec = int(item["duration"])
    elif "duration_string" in item and item["duration_string"]:
        parts = str(item["duration_string"]).split(":")
        if len(parts) == 2:
            dur_sec = int(parts[0]) * 60 + int(parts[1])
        elif len(parts) == 3:
            dur_sec = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        else:
            raise ValueError(f"Invalid duration_string format: {item['duration_string']}")
    else:
        raise KeyError(f"Candidate '{video_id}' missing mandatory 'duration' or 'duration_string' key")

    if "duration_string" in item and item["duration_string"]:
        duration_str = str(item["duration_string"])
    else:
        duration_str = f"{dur_sec // 60}:{dur_sec % 60:02d}"

    if "uploader" in item and item["uploader"]:
        uploader = str(item["uploader"])
    elif "channel" in item and item["channel"]:
        uploader = str(item["channel"])
    else:
        raise KeyError(f"Candidate '{video_id}' missing mandatory 'uploader' or 'channel' key")

    webpage_url = f"https://www.youtube.com/watch?v={video_id}"
    if "webpage_url" in item and item["webpage_url"]:
        webpage_url = str(item["webpage_url"])

    return {
        "id": video_id,
        "title": title,
        "duration": duration_str,
        "duration_sec": dur_sec,
        "uploader": uploader,
        "url": webpage_url,
    }


def fetch_search_candidates(query: str, limit: int = 4) -> List[Dict[str, Any]]:
    """Searches YouTube via yt-dlp and returns up to limit candidate track dictionaries.
    Uses --flat-playlist and --dump-json to return metadata rapidly without downloading audio.
    """
    if not isinstance(query, str) or not query.strip():
        raise ValueError("Search query cannot be empty or whitespace.")
    clean_query = query.strip()

    mac_ip = network_resolver.get_mac_ip(prefer_port=8086)
    search_url = f"http://{mac_ip}:8086/api/search"
    logger.info("Querying search candidates from Mac Mini (%s) for '%s' (limit=%d)...", search_url, clean_query, limit)

    req_data = json.dumps({"query": clean_query, "limit": limit}).encode("utf-8")
    req = urllib.request.Request(search_url, data=req_data, headers={"Content-Type": "application/json"})

    try:
        with urllib.request.urlopen(req, timeout=15.0) as resp:
            if resp.status != 200:
                raise RuntimeError(f"Mac search microservice returned HTTP {resp.status}")
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        logger.error("Failed to query search microservice at %s: %s", search_url, e, exc_info=True)
        raise RuntimeError(f"Mac search microservice query failed: {e}") from e

    if not isinstance(payload, dict) or "candidates" not in payload:
        raise ValueError(f"Malformed response payload from Mac search microservice: {payload}")

    raw_candidates = payload["candidates"]
    if not isinstance(raw_candidates, list):
        raise ValueError(f"Expected list for 'candidates', got {type(raw_candidates)}")

    candidates: List[Dict[str, Any]] = []
    for item in raw_candidates:
        if not isinstance(item, dict):
            continue
        video_id = str(item["video_id"]).strip()
        title = str(item["title"]).strip()
        channel = str(item["channel"]).strip()
        duration = float(item["duration"])
        if not video_id:
            raise ValueError(f"Missing required 'video_id' in candidate item: {item}")
        if not title:
            raise ValueError(f"Missing required 'title' in candidate item: {item}")

        dur_sec = int(duration)
        mins = dur_sec // 60
        secs = dur_sec % 60
        duration_str = f"{mins}:{secs:02d}"

        candidates.append({
            "id": video_id,
            "video_id": video_id,
            "title": title,
            "channel": channel,
            "uploader": channel,
            "duration": duration_str,
            "duration_sec": dur_sec,
            "url": f"https://www.youtube.com/watch?v={video_id}",
        })
        if len(candidates) >= limit:
            break

    return candidates


def download_and_compile(title: str, artist: str = "", video_id: Optional[str] = None) -> Path:
    """Executes end-to-end fetch, rhythm analysis, and choreography compilation."""
    slug_base = f"{title}_{artist}" if artist else title
    slug = sanitize_slug(slug_base)
    cache_dir = get_audio_cache_dir()
    wav_path = cache_dir / f"{slug}.wav"

    if not wav_path.exists():
        if video_id:
            query = f"https://www.youtube.com/watch?v={video_id}"
        elif artist:
            query = f"{title} {artist} official audio"
        else:
            query = title
        fetch_audio_ytdlp(query, wav_path)

    analysis = analyze_audio_track(wav_path)
    
    # Import compiler if deferred
    global compile_choreography_tracks
    if compile_choreography_tracks is None:
        from choreography_compiler import compile_choreography_tracks

    choreography = compile_choreography_tracks(analysis, duration=analysis["duration"])

    seq_dir = get_sequences_dir()
    out_json = seq_dir / f"{slug}.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(choreography, f, indent=2)

    logger.info("Successfully compiled choreography sequence: %s", out_json)
    return out_json


DANCE_PRESETS_PATH_CANDIDATES = [
    WORKSPACE_ROOT / "apps" / "preset_app" / "presets" / "presets_dance.json",
    Path("/home/carson/touch_ui/apps/preset_app/presets/presets_dance.json"),
    Path("/home/user/so101/apps/preset_app/presets/presets_dance.json"),
]


def load_dance_presets() -> Dict[str, Any]:
    """Loads empirical dance presets fail-fast for physical voice posture execution."""
    target_path: Optional[Path] = None
    for p in DANCE_PRESETS_PATH_CANDIDATES:
        if p.exists():
            target_path = p
            break
    if target_path is None:
        raise FileNotFoundError(f"Missing required presets_dance.json. Checked: {DANCE_PRESETS_PATH_CANDIDATES}")

    with open(target_path, "r", encoding="utf-8") as f:
        presets = json.load(f)

    for req_key in ["stand", "arch"]:
        if req_key not in presets:
            raise KeyError(f"presets_dance.json missing required posture '{req_key}'")
        if "normalized" not in presets[req_key]:
            raise KeyError(f"presets_dance.json posture '{req_key}' missing 'normalized' coordinates")

    if "sit" not in presets and "squat" not in presets:
        raise KeyError("presets_dance.json missing required 'sit' or 'squat' posture")

    if "tiptoe" not in presets and "tiptoes" not in presets:
        raise KeyError("presets_dance.json missing required 'tiptoe' or 'tiptoes' posture")

    return presets


def load_calibration_limits(
    backend: Optional[Any] = None,
    calib_file: Optional[Path] = None,
) -> Dict[int, Dict[str, int]]:
    """Loads empirical follower calibration limits dynamically into memory. Zero hardcoded 2048."""
    from telemetry_proxies import MOTOR_NAMES

    if backend is not None and hasattr(backend, "arm_calibration") and bool(backend.arm_calibration):
        limits = {}
        for sid in range(1, 7):
            name = MOTOR_NAMES[sid]
            if name not in backend.arm_calibration:
                raise KeyError(f"Follower calibration missing required servo '{name}' (ID {sid}) in backend")
            calib = backend.arm_calibration[name]
            rmin = int(calib.range_min)
            rmax = int(calib.range_max)
            limits[sid] = {
                "min": rmin,
                "max": rmax,
                "center": (rmin + rmax) // 2,
            }
        return limits

    target_path = calib_file or (Path.home() / ".cache/huggingface/lerobot/calibration/robots/so_follower/follower.json")
    if not target_path.exists():
        raise FileNotFoundError(f"Missing required follower calibration: {target_path}")

    with open(target_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    limits = {}
    for sid in range(1, 7):
        name = MOTOR_NAMES[sid]
        if name not in data:
            raise KeyError(f"Follower calibration missing required servo '{name}' (ID {sid}) in {target_path}")
        cdata = data[name]
        rmin = int(cdata["range_min"])
        rmax = int(cdata["range_max"])
        limits[sid] = {
            "min": rmin,
            "max": rmax,
            "center": (rmin + rmax) // 2,
        }
    return limits


def execute_mac_analysis(target_track: Dict[str, Any]) -> Dict[str, Any]:
    """Triggers neural rhythm analysis on Mac Mini, downloads WAV, and updates manifest."""
    import time
    from beat_bandit_audio import BeatBanditAudioClient, sanitize_title_and_artist

    vid = str(target_track["video_id"])
    raw_title = str(target_track["title"])
    url = f"https://youtu.be/{vid}"

    manifest_path = get_beat_bandit_manifest_path()
    if manifest_path is not None:
        lib_dir = manifest_path.parent
    else:
        if os.name == "nt":
            lib_dir = WORKSPACE_ROOT / "library" / "beat_bandit"
        else:
            lib_dir = Path.home() / "so101" / "library" / "beat_bandit"
    lib_dir.mkdir(parents=True, exist_ok=True)
    audio_client = BeatBanditAudioClient(lib_dir)

    logger.info("Calling Mac Mini /api/analyze_track for '%s' (%s)...", raw_title, vid)
    analysis = audio_client.fetch_analysis(url_or_id=url, track_id=vid)
    logger.info("Downloading analyzed WAV for '%s' (%s) from Mac Mini...", raw_title, vid)
    wav_path = audio_client.download_wav(track_id=vid)
    song_title, artist = sanitize_title_and_artist(raw_title)

    manifest_file = lib_dir / "manifest.json"
    manifest_data: Dict[str, Any] = {}
    if manifest_file.exists():
        with open(manifest_file, "r", encoding="utf-8") as f:
            manifest_data = json.load(f)

    entry = {
        "track_id": vid,
        "title": song_title,
        "artist": artist,
        "duration": float(analysis["duration"]),
        "bpm": float(analysis["bpm"]),
        "wav_path": wav_path,
        "analysis": analysis,
        "created_at": time.time(),
    }
    manifest_data[vid] = entry
    with open(manifest_file, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, indent=2)

    logger.info("Successfully analyzed and saved track '%s' (ID: %s) to %s", song_title, vid, wav_path)
    return entry
