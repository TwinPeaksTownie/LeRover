"""
config_loader.py - Configuration Loader for Device Bridge MCP Server
Loads target and telemetry configuration fail-fast from config/mcp_servers.json.
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
    return data["device_bridge"]
