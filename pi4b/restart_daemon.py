#!/usr/bin/env python3
"""Helper script executed by Touch UI to manage the Pi 500 Master Daemon lifecycle.
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


def get_pi500_ip() -> str:
    return network_resolver.get_pi500_ip(prefer_port=22)


def stop_daemon() -> bool:
    """Stops the Pi 500 master daemon cleanly."""
    target_ip = get_pi500_ip()
    cmd = [
        "ssh",
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=4",
        f"{PI500_USER}@{target_ip}",
        "bash /home/user/so101/pi500/stop_master.sh"
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=6)
    print(f"Master daemon stop ({target_ip}): out='{res.stdout.strip()}' err='{res.stderr.strip()}'")
    return res.returncode == 0


def start_daemon() -> bool:
    """Starts the Pi 500 master daemon after stopping conflicting rover standalone processes."""
    target_ip = get_pi500_ip()
    cmd = [
        "ssh",
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=4",
        f"{PI500_USER}@{target_ip}",
        "bash /home/user/so101/pi500/start_master.sh"
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=6)
    print(f"Master daemon start ({target_ip}): out='{res.stdout.strip()}' err='{res.stderr.strip()}'")
    return res.returncode == 0


def restart_daemon() -> bool:
    start_daemon()
    return True


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else "restart"
    if action == "stop":
        stop_daemon()
    elif action == "start":
        start_daemon()
    else:
        restart_daemon()


if __name__ == "__main__":
    main()
