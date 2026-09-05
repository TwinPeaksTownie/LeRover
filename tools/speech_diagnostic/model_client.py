"""
model_client.py - Backend Client for Speech-to-Speech Diagnostics
Handles:
- Dynamic discovery of NVIDIA NIM and LM Studio models
- Streaming model invocation with precise TTFT and total latency timing
- Clean parsing of reasoning traces (Kimi, DeepSeek, Nemotron) vs spoken responses
- Audio transcription via local Whisper (port 8001)
- Speech synthesis via local Pocket TTS (port 8057)
- Parallel execution of Model A vs Model B
Strict adherence to project contract rules: fail-fast key checking, zero dummy fallbacks.
"""

import concurrent.futures
import io
import json
import os
import re
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from typing import Dict, Any, List, Optional, Tuple

import requests

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

def load_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        raise FileNotFoundError(f"Missing required diagnostic config: {CONFIG_PATH}")
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    _ = cfg["endpoints"]["asr_url"]
    _ = cfg["endpoints"]["pocket_tts_url"]
    _ = cfg["endpoints"]["lm_studio_url"]
    _ = cfg["endpoints"]["nim_base_url"]
    _ = cfg["defaults"]["model_a"]
    _ = cfg["defaults"]["model_b"]
    _ = cfg["defaults"]["max_tokens"]
    _ = cfg["persona_audit"]["target_min_words"]
    _ = cfg["persona_audit"]["target_max_words"]
    return cfg

def get_nvidia_api_key() -> str:
    """Retrieves NVIDIA API key fail-fast from environment or secrets file, raising KeyError if missing."""
    if "NVIDIA_API_KEY" in os.environ and os.environ["NVIDIA_API_KEY"]:
        return os.environ["NVIDIA_API_KEY"]

    candidate_paths = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "apps", "ornith_voice", "secrets.json"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "secrets", "nim_secrets.json"),
        r"i:\aux_servo_interface\apps\ornith_voice\secrets.json",
        r"i:\aux_servo_interface\secrets\nim_secrets.json"
    ]
    for p in candidate_paths:
        abs_p = os.path.abspath(p)
        if os.path.exists(abs_p):
            try:
                with open(abs_p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if "nvidia_api_key" in data and data["nvidia_api_key"]:
                    return data["nvidia_api_key"]
                if "NVIDIA_API_KEY" in data and data["NVIDIA_API_KEY"]:
                    return data["NVIDIA_API_KEY"]
            except Exception as e:
                sys.stderr.write(f"[ModelClient] Error reading secret {abs_p}: {e}\n")
                continue

    raise KeyError("Required secret 'nvidia_api_key' not found in environment or git-ignored secrets.json files.")

def fetch_nim_models(api_key: Optional[str] = None) -> List[str]:
    """Queries NVIDIA NIM /v1/models and returns available model IDs. Fails fast if request fails."""
    key = api_key if api_key else get_nvidia_api_key()
    url = "https://integrate.api.nvidia.com/v1/models"
    headers = {"Authorization": f"Bearer {key}"}
    resp = requests.get(url, headers=headers, timeout=10)
    if resp.status_code != 200:
        raise RuntimeError(f"NVIDIA NIM model query failed (HTTP {resp.status_code}): {resp.text}")
    data = resp.json()
    if "data" not in data or not isinstance(data["data"], list):
        raise KeyError("NVIDIA NIM /v1/models response missing required 'data' list")
    models = [m["id"] for m in data["data"] if "id" in m]
    if not models:
        raise ValueError("NVIDIA NIM /v1/models returned empty model list")
    return sorted(models)

def fetch_lm_studio_models(base_url: str = "http://127.0.0.1:1234/v1") -> List[str]:
    """Queries LM Studio /v1/models. Returns list of local models if server is active, else empty list."""
    try:
        resp = requests.get(f"{base_url.rstrip('/')}/models", timeout=3)
        if resp.status_code == 200:
            data = resp.json()
            if "data" in data and isinstance(data["data"], list):
                return [f"local:{m['id']}" for m in data["data"] if "id" in m]
    except Exception as e:
        sys.stderr.write(f"[ModelClient] LM Studio offline at {base_url}: {e}\n")
    return []

def split_reasoning_and_content(reasoning_accum: str, content_accum: str) -> Tuple[str, str]:
    """Extracts thinking/reasoning process cleanly from the spoken dialogue."""
    clean_r = reasoning_accum.strip()
    clean_c = content_accum.strip()

    # 1. Nemotron plain-text thinking pattern
    nemotron_match = re.match(r"(?is)^(?:here['’]?s a thinking process[:\s]*)(.*?)(?:\n\n|\r\n\r\n)(.*)$", clean_c)
    if nemotron_match:
        if not clean_r:
            clean_r = nemotron_match.group(1).strip()
        clean_c = nemotron_match.group(2).strip()

    # 2. DeepSeek / standard <think> tags
    think_match = re.match(r"(?is)^<think>(.*?)</think>(.*)$", clean_c)
    if think_match:
        if not clean_r:
            clean_r = think_match.group(1).strip()
        clean_c = think_match.group(2).strip()

    # 3. Strip any residual markdown preambles or think labels
    clean_c = re.sub(r"(?is)^.*?(?:thinking process|analyze user input).*?\n\n", "", clean_c).strip()

    return clean_r, clean_c

def audit_spoken_persona(text: str) -> Dict[str, Any]:
    """Evaluates text against configured Ornith conversational and speech rules."""
    cfg = load_config()
    target_min = int(cfg["persona_audit"]["target_min_words"])
    target_max = int(cfg["persona_audit"]["target_max_words"])

    words = text.strip().split()
    word_count = len(words)
    within_bounds = target_min <= word_count <= target_max

    markdown_issues = []
    if re.search(r"^\s*[-*#]\s+", text, re.MULTILINE):
        markdown_issues.append("Contains bullet points or markdown headers")
    if "```" in text or "`" in text:
        markdown_issues.append("Contains code blocks or backticks")
    if re.search(r"\*\*[^*]+\*\*", text):
        markdown_issues.append("Contains markdown bold formatting")

    status_str = "PASS" if within_bounds else ("TOO_SHORT" if word_count < target_min else "TOO_LONG")

    return {
        "word_count": word_count,
        "target_range": f"{target_min}–{target_max} words",
        "length_status": status_str,
        "markdown_clean": len(markdown_issues) == 0,
        "markdown_issues": markdown_issues
    }

def call_single_model(
    model_name: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.3,
    max_tokens: int = 2000,
    timeout_sec: int = 60,
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    Invokes a single model (NIM or LM Studio) with streaming chunk telemetry.
    Fails fast with success: False on any HTTP, network, or chunk decode error.
    """
    cfg = load_config()
    key = api_key if api_key else get_nvidia_api_key()

    is_local = model_name.startswith("local:")
    actual_model = model_name.replace("local:", "") if is_local else model_name

    if is_local:
        endpoint = f"{cfg['endpoints']['lm_studio_url'].rstrip('/')}/chat/completions"
        headers = {"Content-Type": "application/json"}
    else:
        endpoint = f"{cfg['endpoints']['nim_base_url'].rstrip('/')}/chat/completions"
        if not key:
            raise ValueError("Missing NVIDIA API Key. Provide it in secrets.json or the UI.")
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json"
        }

    payload = {
        "model": actual_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": float(temperature),
        "max_tokens": int(max_tokens),
        "stream": True
    }

    t0 = time.perf_counter()
    first_token_time = None
    reasoning_chunks = []
    content_chunks = []
    status_code = 200

    try:
        resp = requests.post(endpoint, headers=headers, json=payload, stream=True, timeout=timeout_sec)
        status_code = resp.status_code
        if resp.status_code != 200:
            return {
                "success": False,
                "model": model_name,
                "status_code": resp.status_code,
                "error": f"HTTP {resp.status_code}: {resp.text}",
                "total_duration_ms": int((time.perf_counter() - t0) * 1000)
            }

        for line in resp.iter_lines():
            if not line:
                continue
            decoded = line.decode("utf-8").strip()
            if decoded.startswith("data: "):
                data_str = decoded[6:]
                if data_str == "[DONE]":
                    break
                try:
                    data = json.loads(data_str)
                except Exception as ex:
                    return {
                        "success": False,
                        "model": model_name,
                        "status_code": status_code,
                        "error": f"Malformed SSE chunk JSON decode error: {str(ex)}",
                        "total_duration_ms": int((time.perf_counter() - t0) * 1000)
                    }

                if "choices" in data and len(data["choices"]) > 0:
                    first_choice = data["choices"][0]
                    if "delta" in first_choice and isinstance(first_choice["delta"], dict):
                        delta = first_choice["delta"]
                        r_token = ""
                        if "reasoning_content" in delta and delta["reasoning_content"] is not None:
                            r_token = delta["reasoning_content"]
                        c_token = ""
                        if "content" in delta and delta["content"] is not None:
                            c_token = delta["content"]

                        if (r_token or c_token) and first_token_time is None:
                            first_token_time = time.perf_counter()

                        if r_token:
                            reasoning_chunks.append(r_token)
                        if c_token:
                            content_chunks.append(c_token)

    except Exception as e:
        return {
            "success": False,
            "model": model_name,
            "status_code": status_code,
            "error": str(e),
            "total_duration_ms": int((time.perf_counter() - t0) * 1000)
        }

    total_duration = time.perf_counter() - t0
    ttft = (first_token_time - t0) if first_token_time else total_duration

    raw_reasoning = "".join(reasoning_chunks)
    raw_content = "".join(content_chunks)
    clean_reasoning, clean_spoken = split_reasoning_and_content(raw_reasoning, raw_content)

    total_tokens = len(reasoning_chunks) + len(content_chunks)
    tps = (total_tokens / total_duration) if total_duration > 0 else 0.0

    osc_hz = cfg["robot_thinking"]["servo5_oscillation_hz"]
    estimated_cycles = round(total_duration * osc_hz, 2)

    audit = audit_spoken_persona(clean_spoken)

    return {
        "success": True,
        "model": model_name,
        "status_code": status_code,
        "ttft_ms": int(ttft * 1000),
        "total_duration_ms": int(total_duration * 1000),
        "thinking_duration_sec": round(total_duration, 2),
        "estimated_servo5_cycles": estimated_cycles,
        "tokens_per_sec": round(tps, 1),
        "total_tokens": total_tokens,
        "reasoning_trace": clean_reasoning,
        "spoken_response": clean_spoken,
        "raw_response": raw_content,
        "audit": audit
    }

def run_parallel_comparison(
    model_a: str,
    model_b: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.3,
    max_tokens: int = 2000,
    timeout_sec: int = 60,
    api_key: Optional[str] = None
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Runs Model A and Model B concurrently in a thread pool."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        future_a = executor.submit(
            call_single_model, model_a, system_prompt, user_prompt, temperature, max_tokens, timeout_sec, api_key
        )
        future_b = executor.submit(
            call_single_model, model_b, system_prompt, user_prompt, temperature, max_tokens, timeout_sec, api_key
        )
        res_a = future_a.result()
        res_b = future_b.result()

    return res_a, res_b

def transcribe_audio_file(audio_path: str, asr_url: Optional[str] = None) -> Dict[str, Any]:
    """Transcribes an audio file via the local Whisper/CoHere ASR server on port 8001."""
    cfg = load_config()
    url = asr_url if asr_url else cfg["endpoints"]["asr_url"]

    if not audio_path or not os.path.exists(audio_path):
        return {"success": False, "error": f"Audio file not found: {audio_path}", "latency_ms": 0}

    t0 = time.perf_counter()
    try:
        with open(audio_path, "rb") as f:
            files = {"audio_file": (os.path.basename(audio_path), f, "audio/wav")}
            resp = requests.post(url, files=files, timeout=30)

        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        if resp.status_code != 200:
            return {
                "success": False,
                "error": f"ASR returned HTTP {resp.status_code}: {resp.text}",
                "latency_ms": elapsed_ms
            }

        data = resp.json()
        if "text" not in data:
            raise KeyError("ASR response missing required 'text' field")
        if "engine" not in data:
            raise KeyError("ASR response missing required 'engine' field")
        asr_engine = data["engine"]

        return {
            "success": True,
            "text": data["text"].strip(),
            "engine": asr_engine,
            "latency_ms": elapsed_ms
        }
    except Exception as e:
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        return {"success": False, "error": str(e), "latency_ms": elapsed_ms}

def synthesize_speech(
    text: str,
    voice_url: Optional[str] = None,
    tts_url: Optional[str] = None
) -> Dict[str, Any]:
    """Synthesizes speech via Pocket TTS on port 8057 and saves to temporary WAV."""
    cfg = load_config()
    url = tts_url if tts_url else cfg["endpoints"]["pocket_tts_url"]
    v_url = voice_url if voice_url else cfg["endpoints"]["voice_url"]

    if not text or not text.strip():
        return {"success": False, "error": "Cannot synthesize empty text", "latency_ms": 0}

    t0 = time.perf_counter()
    try:
        payload = urllib.parse.urlencode({"text": text.strip(), "voice_url": v_url}).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req, timeout=15) as res:
            if res.status != 200:
                raise RuntimeError(f"Pocket TTS returned HTTP {res.status}")
            wav_bytes = res.read()

        elapsed_ms = int((time.perf_counter() - t0) * 1000)

        temp_dir = tempfile.gettempdir()
        out_path = os.path.join(temp_dir, f"diagnostic_tts_{int(time.time()*1000)}.wav")
        with open(out_path, "wb") as f:
            f.write(wav_bytes)

        return {
            "success": True,
            "audio_path": out_path,
            "latency_ms": elapsed_ms,
            "bytes_len": len(wav_bytes)
        }
    except Exception as e:
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        return {"success": False, "error": str(e), "latency_ms": elapsed_ms}
