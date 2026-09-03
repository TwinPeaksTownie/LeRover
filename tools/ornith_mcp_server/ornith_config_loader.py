"""
ornith_config_loader.py - Canonical Fail-Fast Configuration Loader for Ornith
Loads settings from apps/ornith_voice/config.json with zero dummy fallbacks.
"""

import json
import os

def get_config_path() -> str:
    possible_paths = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "apps", "ornith_voice", "config.json"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json"),
        os.path.join(r"i:\aux_servo_interface", "apps", "ornith_voice", "config.json"),
        os.path.join("/home/user/so101", "apps", "ornith_voice", "config.json"),
    ]
    for p in possible_paths:
        p_abs = os.path.abspath(p)
        if os.path.exists(p_abs):
            return p_abs
    raise FileNotFoundError("Could not locate apps/ornith_voice/config.json in any expected path.")

def get_secret(key_name: str) -> str:
    """
    Retrieves secret credentials fail-fast from environment or git-ignored secrets files.
    Raises KeyError if the secret cannot be found.
    """
    if key_name in os.environ and os.environ[key_name]:
        return os.environ[key_name]

    config_dir = os.path.dirname(get_config_path())
    candidate_paths = [
        os.path.join(config_dir, "secrets.json"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "secrets", "nim_secrets.json"),
        os.path.join(r"i:\aux_servo_interface", "secrets", "nim_secrets.json"),
        os.path.join("/home/user/so101", "secrets", "nim_secrets.json"),
    ]
    for p in candidate_paths:
        p_abs = os.path.abspath(p)
        if os.path.exists(p_abs):
            try:
                with open(p_abs, "r", encoding="utf-8") as f:
                    sec = json.load(f)
                lower_key = key_name.lower()
                if lower_key in sec and sec[lower_key]:
                    return sec[lower_key]
                if key_name in sec and sec[key_name]:
                    return sec[key_name]
            except Exception:
                continue
    raise KeyError(f"Required secret '{key_name}' not found in environment or git-ignored secrets.json files.")

def get_ornith_config() -> dict:
    config_file = get_config_path()
    with open(config_file, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    # Fail-fast key enforcement (Lesson 9)
    _ = cfg["name"]
    _ = cfg["speech"]["target"]
    _ = cfg["speech"]["voice_url"]
    _ = cfg["speech"]["pocket_tts_host"]
    _ = cfg["speech"]["pocket_tts_port"]
    _ = cfg["speech"]["max_words"]
    _ = cfg["audit"]["active_backend"]
    _ = cfg["audit"]["model"]
    _ = cfg["audit"]["lm_studio_url"]
    _ = cfg["audit"]["max_tokens"]
    _ = cfg["audit"]["temperature"]
    _ = cfg["audit"]["default_speak_verdict"]
    _ = cfg["audit"]["uncommitted_fallback_commits"]
    _ = cfg["audit"]["backends"]["local"]["url"]
    _ = cfg["audit"]["backends"]["local"]["model"]
    _ = cfg["audit"]["backends"]["nim"]["url"]
    _ = cfg["audit"]["backends"]["nim"]["model"]
    _ = cfg["voice_bridge"]["host"]
    _ = cfg["voice_bridge"]["port"]
    _ = cfg["voice_bridge"]["cohere_asr_url"]
    _ = cfg["voice_bridge"]["chimes"]["pager"]
    _ = cfg["voice_bridge"]["chimes"]["cancel"]
    _ = cfg["voice_bridge"]["chimes"]["settle"]
    _ = cfg["voice_bridge"]["chimes"]["action"]
    _ = cfg["robot_app"]["cancel_window_sec"]
    _ = cfg["robot_app"]["auto_send_timeout_sec"]
    _ = cfg["robot_app"]["settle_delay_sec"]

    active_b = cfg["audit"]["active_backend"]
    if active_b == "nim":
        _ = get_secret("NVIDIA_API_KEY")

    return cfg

