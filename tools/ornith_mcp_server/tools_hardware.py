"""
tools_hardware.py - Remote Hardware Verification & Telemetry Tools for Ornith
Provides non-colliding hardware verification tools over SSH and HTTP REST:
1. Non-interactive SSH command execution (Pi 500, Pi 4B, Mac Mini)
2. MD5 checksum file deployment verification (Verification State 1)
3. Non-colliding motor telemetry sampling via REST endpoints (States 2 & 3)
4. Systemd daemon journal log scanning for serial timeouts and tracebacks (State 4)
All logging writes strictly to sys.stderr.
"""

import hashlib
import json
import os
import subprocess
import sys
import urllib.request
from typing import Optional, List, Dict, Any

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import ornith_config_loader
_CONFIG = ornith_config_loader.get_ornith_config()

NODE_MAP = {
    "pi4b": "carson@192.168.0.86",
    "pi_4b": "carson@192.168.0.86",
    "192.168.0.86": "carson@192.168.0.86",
    "mac_mini": "twinpeakstownie@192.168.0.149",
    "macmini": "twinpeakstownie@192.168.0.149",
    "mac": "twinpeakstownie@192.168.0.149",
    "192.168.0.149": "twinpeakstownie@192.168.0.149",
    "192.168.0.2": "twinpeakstownie@192.168.0.2"
}

def _log_debug(msg: str):
    sys.stderr.write(f"[HARDWARE] {msg}\n")
    sys.stderr.flush()

def ssh_run_command(node: str, command: str, timeout_sec: int = 30) -> dict:
    """
    Executes a non-interactive command over SSH on a target system node.
    
    Args:
        node: Target node alias ('pi4b', 'mac_mini') or IP address.
        command: Shell command string to execute.
        timeout_sec: Timeout in seconds before terminating.
        
    Returns:
        Dict with exit_code, stdout, stderr, and node address.
    """
    target = NODE_MAP.get(node.lower().strip(), node)
    
    ssh_cmd = [
        "ssh",
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=20",
        "-o", "StrictHostKeyChecking=no",
        target,
        command
    ]
    
    _log_debug(f"Executing SSH on {target}: {command[:80]}")
    
    try:
        proc = subprocess.run(
            ssh_cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_sec
        )
        return {
            "status": "success",
            "node": target,
            "exit_code": proc.returncode,
            "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip(),
            "command": command
        }
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": f"SSH command timed out after {timeout_sec}s on {target}"}
    except Exception as e:
        return {"status": "error", "error": f"SSH execution failed on {target}: {str(e)}"}

def verify_file_deployment(local_file: str, remote_path: str, node: str = "pi4b") -> dict:
    """
    Verifies that a local file matches the deployed remote file by comparing MD5 checksums (State 1).
    
    Args:
        local_file: Absolute or workspace path to the local source file.
        remote_path: Absolute path to the destination file on the remote node.
        node: Remote node alias (defaults to 'pi500').
        
    Returns:
        Dict with match status, local MD5, and remote MD5.
    """
    if not os.path.isabs(local_file):
        local_file = os.path.join(r"i:\aux_servo_interface", local_file)

    if not os.path.exists(local_file):
        return {"status": "error", "error": f"Local file not found: {local_file}"}

    # 1. Calculate local MD5
    hasher = hashlib.md5()
    try:
        with open(local_file, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        local_md5 = hasher.hexdigest()
    except Exception as e:
        return {"status": "error", "error": f"Failed to compute local MD5: {str(e)}"}

    # 2. Query remote MD5
    remote_res = ssh_run_command(node, f"md5sum {remote_path} 2>/dev/null || echo 'NOT_FOUND'")
    if remote_res.get("status") != "success":
        return remote_res

    remote_out = remote_res.get("stdout", "").strip()
    if "NOT_FOUND" in remote_out or not remote_out:
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

    remote_md5 = remote_out.split()[0]
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
        "message": "Checksums match. Deployment verified." if match else "Checksum mismatch. Deployment failed or stale."
    }

def sample_motor_telemetry(
    node: str = "pi4b",
    endpoint_url: str = "http://192.168.0.86:8082/api/telemetry",
    timeout_sec: int = 4
) -> dict:
    """
    Queries live motor telemetry via HTTP REST without locking /dev/ttyACM0 (States 2 & 3).
    Also checks process bus locks if endpoint is unavailable.
    
    Args:
        node: Target node for fallback process check (defaults to 'pi4b').
        endpoint_url: HTTP telemetry endpoint URL.
        timeout_sec: Request timeout.
        
    Returns:
        Dict with telemetry payload or bus status.
    """
    _log_debug(f"Querying REST telemetry from {endpoint_url}")
    
    try:
        req = urllib.request.Request(endpoint_url, headers={"User-Agent": "OrnithSupervisor/1.0"})
        with urllib.request.urlopen(req, timeout=timeout_sec) as res:
            if res.status == 200:
                data = json.loads(res.read().decode("utf-8"))
                return {
                    "status": "success",
                    "source": "http_telemetry",
                    "endpoint": endpoint_url,
                    "telemetry": data
                }
    except Exception as e:
        _log_debug(f"HTTP telemetry query failed ({e}). Checking port lock on {node}...")

    # Fallback: Query port lock status on /dev/ttyACM0 via SSH
    lock_check = ssh_run_command(node, "fuser /dev/ttyACM0 2>/dev/null || lsof /dev/ttyACM0 2>/dev/null || echo 'FREE'")
    lock_out = lock_check.get("stdout", "UNKNOWN")
    
    return {
        "status": "success",
        "source": "serial_lock_check",
        "endpoint_error": f"HTTP endpoint {endpoint_url} unreachable",
        "port_ttyACM0_status": "LOCKED_BY_PROCESS" if lock_out != "FREE" else "PORT_AVAILABLE",
        "raw_lock_info": lock_out
    }

def query_daemon_logs(
    node: str = "pi4b",
    service_name: str = "backend.service",
    lines: Optional[int] = None,
    since: str = "10 minutes ago"
) -> dict:
    """
    Scans systemd journal logs on the target node for serial timeouts, exceptions, and errors (State 4).
    Uses a time window query (--since) by default to prevent access log spam from flushing crash traces.
    
    Args:
        node: Remote node alias (defaults to 'pi4b').
        service_name: Systemd service name to query.
        lines: Optional line count limit. If None, queries entire --since window.
        since: Time window for log query (defaults to '10 minutes ago').
        
    Returns:
        Dict with clean flag, detected errors, and log output.
    """

    if lines is not None and since is None:
        cmd = f"journalctl -u {service_name} -n {lines} --no-pager"
    else:
        cmd = f'journalctl -u {service_name} --since "{since}" --no-pager'

    res = ssh_run_command(node, cmd)
    if res.get("status") != "success":
        return res

    log_text = res.get("stdout", "")
    detected_errors = []
    
    error_markers = [
        "0 bytes received",
        "SerialException",
        "Traceback (most recent call last)",
        "KeyError:",
        "FileNotFoundError:",
        "TimeoutError",
        "JSONDecodeError",
        "Device or resource busy",
        "Permission denied",
        "CRITICAL",
        "Fatal error",
        "ERROR:",
        "Cannot start unknown app",
        "Failed to auto-discover app",
        "Unexpected UTF-8 BOM",
    ]
    
    for line in log_text.splitlines():
        clean_line = line.strip()
        # Filter out benign HTTP access log entries from rapid polling (e.g. GET /api/status HTTP/1.1" 200 -)
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

def verify_remote_directory_exists(node: str = "pi4b", remote_path: str = "/home/carson/so101/library/beat_bandit") -> dict:
    """Verifies that a directory exists on the remote node and returns file count."""
    cmd = f"test -d '{remote_path}' && ls -1 '{remote_path}' | wc -l || echo 'NOT_FOUND'"
    res = ssh_run_command(node, cmd)
    out = res.get("stdout", "").strip()
    if "NOT_FOUND" in out or res.get("exit_code") != 0:
        return {
            "status": "success",
            "exists": False,
            "node": node,
            "remote_path": remote_path,
            "file_count": 0,
            "message": f"Directory '{remote_path}' does not exist on {node}"
        }
    try:
        count = int(out.split()[0])
    except Exception:
        count = 0
    return {
        "status": "success",
        "exists": True,
        "node": node,
        "remote_path": remote_path,
        "file_count": count,
        "message": f"Directory exists with {count} entries."
    }

def check_target_deployments(files: list, repo_path: str = None) -> dict:
    """
    Given a list of modified files, verifies that hardware-target files
    (under pi4b/ or apps/) match their remote deployed MD5 checksums.
    """
    if repo_path is None:
        if "REPO_PATH" in os.environ:
            repo_path = os.environ["REPO_PATH"]
        else:
            repo_path = _CONFIG["repo_paths"][os.name]

    deployments = []
    has_mismatch = False

    for rel_path in files:
        norm_path = rel_path.replace("\\", "/").strip()
        target_node = None
        remote_path = None

        if norm_path.startswith("apps/"):
            target_node = "pi4b"
            remote_path = f"/home/carson/aux_servo_interface/{norm_path}"
        elif norm_path.startswith("pi4b/"):
            target_node = "pi4b"
            remote_rel = norm_path[5:]
            remote_path = f"/home/carson/touch_ui/{remote_rel}"
        elif norm_path.startswith("config/"):
            target_node = "pi4b"
            remote_path = f"/home/carson/touch_ui/{norm_path}"
        elif norm_path.startswith("library/"):
            target_node = "pi4b"
            remote_path = f"/home/carson/so101/{norm_path}"

        if target_node and remote_path:
            local_file = os.path.join(repo_path, norm_path)
            if not os.path.exists(local_file):
                remote_check = ssh_run_command(target_node, f"test -f '{remote_path}' && echo 'EXISTS' || echo 'ABSENT'")
                is_absent = (remote_check.get("stdout") == "ABSENT")
                v_res = {
                    "status": "success",
                    "verified": True,
                    "match": is_absent,
                    "local_file": local_file,
                    "remote_path": remote_path,
                    "node": target_node,
                    "local_md5": "DELETED",
                    "remote_md5": "ABSENT" if is_absent else "EXISTS",
                    "message": "File deleted locally and confirmed absent on remote target." if is_absent else f"Deleted file still exists on remote target: {remote_path}"
                }
                deployments.append(v_res)
                if not is_absent:
                    has_mismatch = True
                continue

            v_res = verify_file_deployment(local_file, remote_path, target_node)
            deployments.append(v_res)
            if "match" in v_res:
                if not v_res["match"]:
                    has_mismatch = True
            else:
                has_mismatch = True

    return {
        "status": "success",
        "checked_files": len(deployments),
        "has_mismatch": has_mismatch,
        "all_verified": (len(deployments) == 0 or not has_mismatch),
        "deployments": deployments
    }

def deploy_to_pi(files: list, node: str = "pi4b", restart_service: str = "backend", verify_md5: bool = True) -> dict:
    """
    Deploys code files to the Pi 4B over SFTP, verifies MD5 checksums,
    and optionally restarts target systemd services.
    """
    tools_dir = os.path.dirname(BASE_DIR)
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    import deploy_to_pi as deployer
    return deployer.deploy_files(
        files_or_dirs=files,
        node=node,
        restart_service=restart_service,
        verify_md5=verify_md5
    )

def check_ssh_health(node: str = "pi4b") -> dict:
    """
    Diagnoses SSH connectivity to the target node.
    """
    tools_dir = os.path.dirname(BASE_DIR)
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    import deploy_to_pi as deployer
    return deployer.check_ssh_health(node=node)

