"""
deploy_to_pi.py - Robust Paramiko Deployment Helper and CLI for Pi 4B

Handles SSH/SFTP deployment of repository code to the Pi 4B (192.168.0.86),
verifies MD5 transfer integrity, restarts systemd services, and checks journal logs.
Configured strictly via config/network_config.json.
"""

import argparse
import hashlib
import json
import os
import posixpath
import socket
import sys
import time
from typing import Dict, List, Optional, Tuple, Any

import paramiko

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(REPO_ROOT, "config", "network_config.json")

def load_deployment_config(node: str = "pi4b") -> Dict[str, Any]:
    """
    Loads deployment configuration strictly using direct bracket indexing.
    Raises KeyError or FileNotFoundError if configuration is missing.
    """
    if not os.path.exists(CONFIG_PATH):
        raise FileNotFoundError(f"Configuration file missing: {CONFIG_PATH}")

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)

    deployment = config["deployment"]
    target_nodes = deployment["target_nodes"]
    if node not in target_nodes:
        raise KeyError(f"Target node '{node}' not found in deployment.target_nodes. Available: {list(target_nodes.keys())}")

    return target_nodes[node]

def compute_local_md5(file_path: str) -> str:
    """Computes MD5 checksum of a local file."""
    hasher = hashlib.md5()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()

def resolve_remote_path(rel_or_abs_path: str, node_cfg: Dict[str, Any]) -> Tuple[str, str]:
    """
    Resolves a local workspace path to an absolute local path and target remote path.
    Uses path_mappings from configuration.
    
    Returns:
        (local_abs_path, remote_posix_path)
    """
    if os.path.isabs(rel_or_abs_path):
        local_abs = os.path.abspath(rel_or_abs_path)
        rel_path = os.path.relpath(local_abs, REPO_ROOT).replace("\\", "/")
    else:
        rel_path = rel_or_abs_path.replace("\\", "/").lstrip("/")
        local_abs = os.path.join(REPO_ROOT, rel_path)

    path_mappings = node_cfg["path_mappings"]
    
    first_part = rel_path.split("/")[0]
    if first_part in path_mappings:
        remote_base = path_mappings[first_part]
        sub_path = "/".join(rel_path.split("/")[1:])
        if sub_path:
            remote_path = posixpath.join(remote_base, sub_path)
        else:
            remote_path = remote_base
    else:
        remote_path = posixpath.join(node_cfg["remote_base_dir"], "aux_servo_interface", rel_path)

    return local_abs, remote_path

def check_ssh_health(node: str = "pi4b") -> Dict[str, Any]:
    """
    Diagnoses SSH connectivity to the target node.
    """
    cfg = load_deployment_config(node)
    host = cfg["host"]
    port = cfg["port"]
    user = cfg["username"]
    key_path = cfg["key_path"]
    connect_timeout = cfg["connect_timeout_sec"]
    banner_timeout = cfg["banner_timeout_sec"]

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(connect_timeout)
    t0 = time.time()
    try:
        sock.connect((host, port))
        tcp_duration = time.time() - t0
    except (socket.timeout, TimeoutError):
        return {
            "status": "error",
            "code": "HOST_UNREACHABLE",
            "message": f"TCP connection to {host}:{port} timed out after {connect_timeout}s. Target is powered off or disconnected.",
            "host": host,
            "port": port
        }
    except ConnectionRefusedError:
        return {
            "status": "error",
            "code": "CONNECTION_REFUSED",
            "message": f"TCP port {port} refused connection on {host}. SSH daemon is not running.",
            "host": host,
            "port": port
        }
    except Exception as e:
        return {
            "status": "error",
            "code": "SOCKET_ERROR",
            "message": f"Socket error connecting to {host}:{port}: {str(e)}",
            "host": host,
            "port": port
        }
    finally:
        sock.close()

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        client.connect(
            hostname=host,
            port=port,
            username=user,
            key_filename=key_path if os.path.exists(key_path) else None,
            timeout=connect_timeout,
            banner_timeout=banner_timeout,
            allow_agent=True,
            look_for_keys=True
        )
        _stdin, stdout, _stderr = client.exec_command("uname -a", timeout=10)
        uname = stdout.read().decode("utf-8").strip()
        client.close()
        return {
            "status": "success",
            "code": "SUCCESS",
            "message": f"SSH connection verified successfully on {user}@{host}:{port}",
            "host": host,
            "port": port,
            "uname": uname,
            "tcp_latency_sec": round(tcp_duration, 4)
        }
    except paramiko.ssh_exception.SSHException as e:
        err_msg = str(e)
        if "banner" in err_msg.lower():
            return {
                "status": "error",
                "code": "TCP_CONNECTED_USERLAND_FROZEN",
                "message": (
                    f"TCP port 22 connected in {round(tcp_duration, 4)}s, but SSH banner timed out after {banner_timeout}s. "
                    "The Pi 4B Linux kernel is alive, but userland process scheduling is frozen "
                    "(e.g., uninterruptible /dev/ttyACM0 sleep, SD card wait, or memory exhaustion). "
                    "A physical power-cycle or reboot is required."
                ),
                "host": host,
                "port": port,
                "raw_error": err_msg
            }
        elif "authentication" in err_msg.lower() or "auth" in err_msg.lower():
            return {
                "status": "error",
                "code": "AUTH_FAILED",
                "message": f"SSH authentication rejected for user '{user}' with key '{key_path}'.",
                "host": host,
                "port": port,
                "raw_error": err_msg
            }
        else:
            return {
                "status": "error",
                "code": "SSH_EXCEPTION",
                "message": f"SSH protocol exception: {err_msg}",
                "host": host,
                "port": port,
                "raw_error": err_msg
            }
    except Exception as e:
        return {
            "status": "error",
            "code": "CONNECTION_FAILED",
            "message": f"SSH connection failed: {str(e)}",
            "host": host,
            "port": port,
            "raw_error": str(e)
        }

def get_ssh_client(node: str = "pi4b") -> paramiko.SSHClient:
    """
    Connects to the target node with retries and backoff.
    Raises RuntimeError if connection fails after all attempts.
    """
    cfg = load_deployment_config(node)
    host = cfg["host"]
    port = cfg["port"]
    user = cfg["username"]
    key_path = cfg["key_path"]
    connect_timeout = cfg["connect_timeout_sec"]
    banner_timeout = cfg["banner_timeout_sec"]
    max_retries = cfg["max_retries"]
    backoff = cfg["retry_backoff_sec"]

    last_err = None
    for attempt in range(1, max_retries + 1):
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                hostname=host,
                port=port,
                username=user,
                key_filename=key_path if os.path.exists(key_path) else None,
                timeout=connect_timeout,
                banner_timeout=banner_timeout,
                allow_agent=True,
                look_for_keys=True
            )
            return client
        except Exception as e:
            last_err = e
            client.close()
            if attempt < max_retries:
                time.sleep(backoff * attempt)

    raise RuntimeError(f"Failed to connect to {user}@{host}:{port} after {max_retries} attempts: {last_err}")

def sftp_mkdir_p(sftp: paramiko.SFTPClient, remote_dir: str):
    """Recursively creates remote directories via SFTP."""
    parts = remote_dir.replace("\\", "/").strip("/").split("/")
    cur = ""
    for part in parts:
        cur += "/" + part
        try:
            sftp.stat(cur)
        except IOError:
            try:
                sftp.mkdir(cur)
            except IOError as dir_err:
                logger.debug("Remote directory already exists or cannot be created: %s (%s)", cur, dir_err)

def execute_remote_command(command: str, node: str = "pi4b", timeout_sec: int = 30) -> Dict[str, Any]:
    """Executes a command over SSH and returns exit code, stdout, and stderr."""
    client = get_ssh_client(node)
    try:
        _stdin, stdout, stderr = client.exec_command(command, timeout=timeout_sec)
        out = stdout.read().decode("utf-8", errors="replace").strip()
        err = stderr.read().decode("utf-8", errors="replace").strip()
        exit_code = stdout.channel.recv_exit_status()
        return {
            "status": "success" if exit_code == 0 else "error",
            "exit_code": exit_code,
            "stdout": out,
            "stderr": err,
            "command": command
        }
    finally:
        client.close()

def query_remote_md5(client: paramiko.SSHClient, remote_path: str) -> str:
    """Computes MD5 on the remote host via shell command."""
    _stdin, stdout, _stderr = client.exec_command(f"md5sum '{remote_path}' 2>/dev/null || echo 'NOT_FOUND'")
    out = stdout.read().decode("utf-8").strip()
    if not out or "NOT_FOUND" in out:
        return "NOT_FOUND"
    return out.split()[0].lower()

def deploy_files(
    files_or_dirs: List[str],
    node: str = "pi4b",
    restart_service: Optional[str] = "backend",
    verify_md5: bool = True
) -> Dict[str, Any]:
    """
    Deploys a list of files or directories from the repository to the target Pi 4B node.
    Performs SFTP upload, MD5 verification, and optional service restarts.
    """
    node_cfg = load_deployment_config(node)
    
    file_queue: List[Tuple[str, str]] = []
    for item in files_or_dirs:
        local_abs, remote_target = resolve_remote_path(item, node_cfg)
        if not os.path.exists(local_abs):
            raise FileNotFoundError(f"Local source file/directory does not exist: {local_abs}")

        if os.path.isdir(local_abs):
            for root, _dirs, filenames in os.walk(local_abs):
                if "__pycache__" in root or ".git" in root:
                    continue
                for f in filenames:
                    if f.endswith(".pyc") or f.endswith(".swp"):
                        continue
                    full_local = os.path.join(root, f)
                    rel_sub = os.path.relpath(full_local, local_abs).replace("\\", "/")
                    full_remote = posixpath.join(remote_target, rel_sub)
                    file_queue.append((full_local, full_remote))
        else:
            file_queue.append((local_abs, remote_target))

    if not file_queue:
        return {
            "status": "success",
            "message": "No files to deploy",
            "deployed_files": []
        }

    client = get_ssh_client(node)
    sftp = client.open_sftp()

    deployed = []
    has_mismatch = False

    try:
        for local_file, remote_file in file_queue:
            remote_dir = posixpath.dirname(remote_file)
            sftp_mkdir_p(sftp, remote_dir)

            local_md5 = compute_local_md5(local_file)
            sftp.put(local_file, remote_file)

            result_entry = {
                "local_file": os.path.relpath(local_file, REPO_ROOT).replace("\\", "/"),
                "remote_file": remote_file,
                "local_md5": local_md5
            }

            if verify_md5:
                remote_md5 = query_remote_md5(client, remote_file)
                result_entry["remote_md5"] = remote_md5
                match = (local_md5.lower() == remote_md5.lower())
                result_entry["match"] = match
                if not match:
                    has_mismatch = True
            deployed.append(result_entry)

    finally:
        sftp.close()

    service_results: List[Dict[str, Any]] = []
    if restart_service and restart_service.lower() != "none":
        svc_map = node_cfg["services"]
        user_services = node_cfg["user_services"]
        ui_file_indicators = node_cfg["ui_file_indicators"]
        ui_auto_restart_services = node_cfg["ui_auto_restart_services"]

        has_ui_files = any(
            any(ind in f["local_file"] for ind in ui_file_indicators)
            for f in deployed
        )

        raw_svc = restart_service.strip().lower()
        if raw_svc in ["backend_only", "backend-only"]:
            targets = ["backend"]
        elif raw_svc == "auto" or (raw_svc == "backend" and has_ui_files):
            targets = list(ui_auto_restart_services)
        elif raw_svc == "all":
            targets = list(svc_map.keys())
        else:
            targets = [s.strip() for s in restart_service.split(",") if s.strip()]

        for tgt in targets:
            tgt_lower = tgt.lower()
            if tgt_lower in svc_map:
                svc_name = str(svc_map[tgt_lower])
            else:
                svc_name = tgt
            if not svc_name.endswith(".service"):
                svc_name = f"{svc_name}.service"

            is_user = (svc_name in user_services or tgt_lower in user_services)
            systemctl_cmd = "systemctl --user" if is_user else "sudo systemctl"
            journal_cmd = "journalctl --user -u" if is_user else "journalctl -u"

            _stdin, stdout, stderr = client.exec_command(f"{systemctl_cmd} restart {svc_name}")
            restart_code = stdout.channel.recv_exit_status()
            restart_err = stderr.read().decode("utf-8").strip()

            _stdin, stdout, _stderr = client.exec_command(f"{systemctl_cmd} is-active {svc_name}")
            is_active = (stdout.read().decode("utf-8").strip() == "active")

            _stdin, stdout, _stderr = client.exec_command(f"{journal_cmd} {svc_name} -n 15 --no-pager")
            journal_snippet = stdout.read().decode("utf-8").strip()

            service_results.append({
                "service": svc_name,
                "scope": "user" if is_user else "system",
                "restart_code": restart_code,
                "restart_stderr": restart_err,
                "is_active": is_active,
                "journal_snippet": journal_snippet
            })

    client.close()

    service_ok = True
    if service_results:
        service_ok = all(r["is_active"] for r in service_results)

    overall_status = "success" if (not has_mismatch and service_ok) else "warning"

    return {
        "status": overall_status,
        "node": node,
        "file_count": len(deployed),
        "has_mismatch": has_mismatch,
        "deployed_files": deployed,
        "service_restart": service_results[0] if len(service_results) == 1 else service_results,
        "service_restarts": service_results
    }

def main():
    parser = argparse.ArgumentParser(description="Deploy repository code to Pi 4B over SFTP")
    parser.add_argument("--check", action="store_true", help="Perform SSH health check and diagnosis on Pi 4B")
    parser.add_argument("--node", default="pi4b", help="Target node alias in network_config.json")
    parser.add_argument("--files", nargs="+", help="Specific files or directories to deploy")
    parser.add_argument("--all-pi4b", action="store_true", help="Deploy all files in pi4b/ directory")
    parser.add_argument("--restart", default="backend", help="Service to restart ('backend', 'touchscreen', 'touch_ui', 'none')")
    parser.add_argument("--cmd", help="Execute an arbitrary remote command on the Pi 4B")
    parser.add_argument("--no-verify", action="store_true", help="Skip remote MD5 verification")

    args = parser.parse_args()

    if args.check:
        res = check_ssh_health(node=args.node)
        print(json.dumps(res, indent=2))
        sys.exit(0 if res.get("status") == "success" else 1)

    if args.cmd:
        res = execute_remote_command(args.cmd, node=args.node)
        print(json.dumps(res, indent=2))
        sys.exit(0 if res.get("status") == "success" else 1)

    files_to_deploy = []
    if args.all_pi4b:
        files_to_deploy.append("pi4b")
    if args.files:
        files_to_deploy.extend(args.files)

    if not files_to_deploy:
        print("Error: No files specified. Use --check, --cmd, --files <paths>, or --all-pi4b", file=sys.stderr)
        sys.exit(1)

    try:
        res = deploy_files(
            files_or_dirs=files_to_deploy,
            node=args.node,
            restart_service=args.restart,
            verify_md5=not args.no_verify
        )
        print(json.dumps(res, indent=2))
        sys.exit(0 if res.get("status") == "success" else 1)
    except Exception as e:
        print(json.dumps({"status": "error", "error": str(e)}, indent=2), file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
