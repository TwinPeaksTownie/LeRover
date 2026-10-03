"""
config_loader.py - Configuration Loader for Code Auditor MCP Server
Loads configuration from config/mcp_servers.json and secrets fail-fast.
"""

import json
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

def get_config() -> dict:
    config_path = os.path.join(REPO_ROOT, "config", "mcp_servers.json")
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Configuration file not found: {config_path}")
    with open(config_path, "r", encoding="utf-8-sig") as f:
        data = json.load(f)
    return data["code_auditor"]

def get_secret(key_name: str) -> str:
    if key_name in os.environ and os.environ[key_name]:
        return os.environ[key_name]

    candidate_paths = [
        os.path.join(REPO_ROOT, "secrets", "nim_secrets.json"),
        os.path.join(REPO_ROOT, "apps", "ornith_voice", "secrets.json"),
    ]
    for p in candidate_paths:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8-sig") as f:
                    sec = json.load(f)
                if key_name in sec and sec[key_name]:
                    return sec[key_name]
                lower_key = key_name.lower()
                if lower_key in sec and sec[lower_key]:
                    return sec[lower_key]
            except Exception:
                continue

    raise KeyError(f"Required secret '{key_name}' not found in environment or secrets files.")
