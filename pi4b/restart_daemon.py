#!/usr/bin/env python3
"""Helper script executed by Touch UI to manage the Pi 500 Master Daemon lifecycle."""
import sys
import subprocess

PI500_IP = "192.168.0.130"
PI500_USER = "user"


def stop_daemon() -> bool:
    """Stops the Pi 500 master daemon cleanly."""
    cmd = [
        "ssh",
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=5",
        f"{PI500_USER}@{PI500_IP}",
        "bash /home/user/so101/pi500/stop_master.sh"
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
    print(f"Master daemon stop output: out='{res.stdout.strip()}' err='{res.stderr.strip()}'")
    return res.returncode == 0


def start_daemon() -> bool:
    """Starts the Pi 500 master daemon after stopping conflicting rover standalone processes."""
    cmd = [
        "ssh",
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=5",
        f"{PI500_USER}@{PI500_IP}",
        "bash /home/user/so101/pi500/start_master.sh"
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
    print(f"Master daemon start output: out='{res.stdout.strip()}' err='{res.stderr.strip()}'")
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

