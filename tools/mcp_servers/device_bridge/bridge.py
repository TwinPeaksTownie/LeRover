"""
bridge.py - Device Bridge: Hardware Telemetry Sampling & Code Deployment
Consolidates token-efficient SFTP deployment, MD5 parity verification, systemd lifecycle,
and non-blocking HTTP telemetry polling across follower arm and rover chassis.
"""

import hashlib
import json
import logging
import os
import subprocess
import sys
import time
import urllib.request
from typing import Dict, List, Optional, Any

import device_config

logger = logging.getLogger("device_bridge")
REPO_ROOT = device_config.REPO_ROOT

# Ensure tools/ is on sys.path for deploy_to_pi helper
TOOLS_DIR = os.path.join(REPO_ROOT, "tools")
if TOOLS_DIR not in sys.path:
    sys.path.insert(0, TOOLS_DIR)

import deploy_to_pi as deployer

def _log_debug(msg: str):
    sys.stderr.write(f"[DEVICE_BRIDGE] {msg}\n")
    sys.stderr.flush()

def deploy_to_pi(
    files: list,
    node: str = "pi4b",
    restart_service: str = "backend",
    verify_md5: bool = True
) -> dict:
    """Deploys code files or directories to the Pi 4B over SFTP, verifies MD5, and restarts service."""
    _log_debug(f"Deploying {len(files)} items to {node}, restarting {restart_service}...")
    return deployer.deploy_files(
        files_or_dirs=files,
        node=node,
        restart_service=restart_service,
        verify_md5=verify_md5
    )

def check_ssh_health(node: str = "pi4b") -> dict:
    """Diagnoses SSH connectivity, latency, and auth to the target node."""
    return deployer.check_ssh_health(node=node)

def verify_file_deployment(local_file: str, remote_path: str = None, node: str = "pi4b") -> dict:
    """Verifies State 1 of the Verification State Machine: compares local and remote MD5 checksums."""
    if not os.path.isabs(local_file):
        local_file = os.path.join(REPO_ROOT, local_file)

    if not os.path.exists(local_file):
        return {"status": "error", "error": f"Local file not found: {local_file}"}

    cfg = device_config.get_config()
    target_cfg = cfg["targets"][node]
    if remote_path is None:
        rel = os.path.relpath(local_file, REPO_ROOT).replace("\\", "/")
        remote_path = f"{target_cfg['remote_base_dir']}/{rel}"

    hasher = hashlib.md5()
    with open(local_file, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    local_md5 = hasher.hexdigest()

    host = target_cfg["host"]
    user = target_cfg["user"]
    ssh_cmd = [
        "ssh",
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=5",
        "-o", "StrictHostKeyChecking=no",
        f"{user}@{host}",
        f"md5sum {remote_path} 2>/dev/null || echo 'NOT_FOUND'"
    ]

    try:
        proc = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=10)
        out = proc.stdout.strip()
        if "NOT_FOUND" in out or not out:
            return {
                "status": "success",
                "verified": False,
                "match": False,
                "local_file": local_file,
                "remote_path": remote_path,
                "local_md5": local_md5,
                "remote_md5": "FILE_NOT_FOUND",
                "message": f"Remote file {remote_path} does not exist on {node}"
            }
        remote_md5 = out.split()[0]
        match = (local_md5.lower() == remote_md5.lower())
        return {
            "status": "success",
            "verified": match,
            "match": match,
            "local_file": local_file,
            "remote_path": remote_path,
            "node": node,
            "local_md5": local_md5,
            "remote_md5": remote_md5,
            "message": "Checksums match. Deployment verified." if match else "Checksum mismatch."
        }
    except Exception as e:
        return {"status": "error", "error": f"Failed remote MD5 check: {str(e)}"}

def ssh_run_command(node: str, command: str, timeout_sec: int = 15) -> dict:
    """Executes a command over SSH on a target system node."""
    cfg = device_config.get_config()
    if node in cfg["targets"]:
        target_cfg = cfg["targets"][node]
        target = f"{target_cfg['user']}@{target_cfg['host']}"
    else:
        target = node

    ssh_cmd = [
        "ssh",
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=5",
        "-o", "StrictHostKeyChecking=no",
        target,
        command
    ]

    try:
        proc = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=timeout_sec)
        return {
            "status": "success",
            "node": target,
            "exit_code": proc.returncode,
            "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip()
        }
    except Exception as e:
        return {"status": "error", "error": f"SSH execution failed: {str(e)}"}

def sample_motor_telemetry(endpoint_url: str = None, timeout_sec: float = 3.0) -> dict:
    """Queries live motor encoder telemetry via HTTP REST without serial collision (States 2 & 3)."""
    cfg = device_config.get_config()
    if endpoint_url is None:
        endpoint_url = cfg["telemetry_endpoints"]["follower"]

    try:
        req = urllib.request.Request(endpoint_url, headers={"User-Agent": "DeviceBridge/1.0"})
        with urllib.request.urlopen(req, timeout=timeout_sec) as res:
            if res.status == 200:
                data = json.loads(res.read().decode("utf-8"))
                return {
                    "status": "success",
                    "source": "motor_telemetry",
                    "endpoint": endpoint_url,
                    "telemetry": data
                }
    except Exception as e:
        return {"status": "error", "error": f"HTTP motor telemetry query failed ({endpoint_url}): {str(e)}"}

def sample_rover_telemetry(endpoint_url: str = None, timeout_sec: float = 3.0) -> dict:
    """Queries live rover distance sensor, danger zone, and halt status via port 8089."""
    cfg = device_config.get_config()
    if endpoint_url is None:
        endpoint_url = cfg["telemetry_endpoints"]["rover"]

    try:
        req = urllib.request.Request(endpoint_url, headers={"User-Agent": "DeviceBridge/1.0"})
        with urllib.request.urlopen(req, timeout=timeout_sec) as res:
            if res.status == 200:
                data = json.loads(res.read().decode("utf-8"))
                return {
                    "status": "success",
                    "source": "rover_telemetry",
                    "endpoint": endpoint_url,
                    "telemetry": data
                }
    except Exception as e:
        return {"status": "error", "error": f"HTTP rover telemetry query failed ({endpoint_url}): {str(e)}"}

def query_daemon_logs(
    node: str = "pi4b",
    service_name: str = "backend.service",
    lines: int = 50,
    since: str = "10 minutes ago"
) -> dict:
    """Scans systemd journal logs on the target node for serial timeouts and unhandled crashes."""
    cmd = f'journalctl -u {service_name} --since "{since}" -n {lines} --no-pager'
    res = ssh_run_command(node, cmd)
    if "status" not in res or res["status"] != "success":
        return res

    log_text = res["stdout"]
    detected_errors = []
    error_markers = [
        "0 bytes received", "SerialException", "Traceback", "KeyError:",
        "FileNotFoundError:", "TimeoutError", "CRITICAL", "Fatal error", "ERROR:"
    ]

    for line in log_text.splitlines():
        clean_line = line.strip()
        if ' "GET /' in clean_line or ' "POST /' in clean_line:
            continue
        for marker in error_markers:
            if marker.lower() in clean_line.lower():
                detected_errors.append(clean_line)
                break

    return {
        "status": "success",
        "node": node,
        "service": service_name,
        "clean": len(detected_errors) == 0,
        "error_count": len(detected_errors),
        "detected_errors": detected_errors,
        "log_snippet": "\n".join(log_text.splitlines()[-20:])
    }
