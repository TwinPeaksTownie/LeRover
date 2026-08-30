#!/usr/bin/env python3
"""Helper script executed by Touch UI to manage the Pi 500 sewer-daemon.service lifecycle.
Dynamically resolves Pi 500 target IP (Ethernet-first fallback).
"""
import os
import subprocess
import sys

try:
    import network_resolver
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import network_resolver

PI500_USER = "user"
SERVICE_NAME = "sewer-daemon.service"


def get_pi500_ip() -> str:
    return network_resolver.get_pi500_ip(prefer_port=22)


def run_systemctl(action: str) -> bool:
    """Executes systemctl action on Pi 500 over SSH."""
    target_ip = get_pi500_ip()
    cmd = [
        "ssh",
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=4",
        f"{PI500_USER}@{target_ip}",
        f"sudo systemctl {action} {SERVICE_NAME}"
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
        print(f"Sewer daemon {action} ({target_ip}): code={res.returncode} out='{res.stdout.strip()}' err='{res.stderr.strip()}'")
        return res.returncode == 0
    except subprocess.TimeoutExpired:
        print(f"Sewer daemon {action} ({target_ip}) timed out after 8s")
        return False
    except Exception as e:
        print(f"Sewer daemon {action} ({target_ip}) failed: {e}")
        return False


def stop_daemon() -> bool:
    return run_systemctl("stop")


def start_daemon() -> bool:
    return run_systemctl("start")


def restart_daemon() -> bool:
    return run_systemctl("restart")


def is_active() -> bool:
    return run_systemctl("is-active")


def main():
    action = sys.argv[1].lower() if len(sys.argv) > 1 else "restart"
    if action == "stop":
        ok = stop_daemon()
    elif action == "start":
        ok = start_daemon()
    elif action in ["status", "is-active"]:
        ok = is_active()
    else:
        ok = restart_daemon()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
