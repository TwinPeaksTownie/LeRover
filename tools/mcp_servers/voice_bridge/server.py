"""
server.py - Voice Bridge MCP Server for Antigravity
Exposes Laura Voice Pocket-TTS speech synthesis and spoken alert tools.
"""

import asyncio
import importlib
import json
import logging
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

log_file = os.path.join(BASE_DIR, "mcp_server.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stderr),
        logging.FileHandler(log_file, encoding="utf-8")
    ]
)
logger = logging.getLogger("voice_bridge_mcp")

from mcp.server.mcpserver import MCPServer
import voice_config
import speech

app = MCPServer(
    name="voice-bridge",
    description="Laura Voice TTS & Audio Notification Bridge"
)

def _reload_modules():
    global voice_config, speech
    voice_config = importlib.reload(voice_config)
    speech = importlib.reload(speech)

@app.tool()
def speak_laura(text: str, voice_url: str = None) -> str:
    """
    Synthesizes and speaks text aloud in Laura's voice using Pocket-TTS (port 8057).
    """
    _reload_modules()
    res = speech.speak_laura(text=text, voice_url=voice_url)
    return json.dumps(res, indent=2)

@app.tool()
def notify_user_of_blocker(reason: str) -> str:
    """
    Speaks a high-priority spoken alert when human operator input is required.
    """
    _reload_modules()
    res = speech.notify_user_of_blocker(reason=reason)
    return json.dumps(res, indent=2)

@app.tool()
def notify_task_verified(summary: str, telemetry_delta: str = "") -> str:
    """
    Speaks an official verification completion notice in Laura's voice after all verification states pass.
    """
    _reload_modules()
    res = speech.notify_task_verified(summary=summary, telemetry_delta=telemetry_delta)
    return json.dumps(res, indent=2)

if __name__ == "__main__":
    logger.info("Starting Voice Bridge MCP Server (stdio transport)...")
    app.run("stdio")
