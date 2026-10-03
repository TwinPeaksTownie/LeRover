"""
server.py - Device Bridge MCP Server for Antigravity
Exposes hardware telemetry sampling, daemon log auditing, and token-saving SFTP/SSH deployment tools.
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
logger = logging.getLogger("device_bridge_mcp")

from mcp.server.mcpserver import MCPServer
import device_config
import bridge

app = MCPServer(
    name="device-bridge",
    description="Robot Hardware Telemetry & Code Deployment Bridge"
)

def _reload_modules():
    global device_config, bridge
    device_config = importlib.reload(device_config)
    bridge = importlib.reload(bridge)

@app.tool()
def deploy_to_pi(
    files: list,
    node: str = "pi4b",
    restart_service: str = "backend",
    verify_md5: bool = True
) -> str:
    """
    Deploys code files or directories to the Pi 4B over SFTP, verifies MD5 checksums,
    and optionally restarts target systemd services (State 1).
    """
    _reload_modules()
    res = bridge.deploy_to_pi(
        files=files,
        node=node,
        restart_service=restart_service,
        verify_md5=verify_md5
    )
    return json.dumps(res, indent=2)

@app.tool()
def verify_file_deployment(local_file: str, remote_path: str = None, node: str = "pi4b") -> str:
    """
    Verifies State 1 of the Verification State Machine: compares local and remote MD5 checksums.
    """
    _reload_modules()
    res = bridge.verify_file_deployment(local_file=local_file, remote_path=remote_path, node=node)
    return json.dumps(res, indent=2)

@app.tool()
def check_ssh_health(node: str = "pi4b") -> str:
    """
    Diagnoses SSH connectivity, latency, and auth to the target node.
    """
    _reload_modules()
    res = bridge.check_ssh_health(node=node)
    return json.dumps(res, indent=2)

@app.tool()
def ssh_run_command(node: str, command: str, timeout_sec: int = 15) -> str:
    """
    Executes a shell command over SSH on a target system node with strict timeout guard.
    """
    _reload_modules()
    res = bridge.ssh_run_command(node=node, command=command, timeout_sec=timeout_sec)
    return json.dumps(res, indent=2)

@app.tool()
def sample_motor_telemetry(endpoint_url: str = None, timeout_sec: float = 3.0) -> str:
    """
    Queries live follower arm motor telemetry via HTTP REST without serial collision (States 2 & 3).
    """
    _reload_modules()
    res = bridge.sample_motor_telemetry(endpoint_url=endpoint_url, timeout_sec=timeout_sec)
    return json.dumps(res, indent=2)

@app.tool()
def sample_rover_telemetry(endpoint_url: str = None, timeout_sec: float = 3.0) -> str:
    """
    Queries live rover distance sensor and obstacle safety guard status (States 2 & 3).
    """
    _reload_modules()
    res = bridge.sample_rover_telemetry(endpoint_url=endpoint_url, timeout_sec=timeout_sec)
    return json.dumps(res, indent=2)

@app.tool()
def query_daemon_logs(
    node: str = "pi4b",
    service_name: str = "backend.service",
    lines: int = 50,
    since: str = "10 minutes ago"
) -> str:
    """
    Verifies State 4: Scans systemd daemon logs on the target node for serial timeouts or crashes.
    """
    _reload_modules()
    res = bridge.query_daemon_logs(node=node, service_name=service_name, lines=lines, since=since)
    return json.dumps(res, indent=2)

if __name__ == "__main__":
    logger.info("Starting Device Bridge MCP Server (stdio transport)...")
    app.run("stdio")
