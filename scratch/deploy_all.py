#!/usr/bin/env python3
"""Remote deployment script to sync local codebase changes to Pi 500 and Pi 4B targets,
and cleanly restart their respective background services.
"""

import subprocess
import sys
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

PI500_HOST = "user@192.168.0.130"
PI4B_HOST = "carson@192.168.0.86"
BASE_DIR = Path(__file__).parent.parent.resolve()

def run_ssh(host: str, cmd: str, timeout: int = 15) -> bool:
    ssh_cmd = ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=5", host, cmd]
    logging.info(f"Executing on {host}: {cmd}")
    res = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=timeout)
    if res.returncode != 0:
        logging.error(f"SSH command failed on {host}: {res.stderr.strip()}")
        return False
    logging.info(f"Response from {host}: {res.stdout.strip()}")
    return True

def run_scp(src: Path, dest_spec: str) -> bool:
    scp_cmd = ["scp", "-r", "-o", "StrictHostKeyChecking=no", str(src), dest_spec]
    logging.info(f"Copying {src} -> {dest_spec}")
    res = subprocess.run(scp_cmd, capture_output=True, text=True, timeout=30)
    if res.returncode != 0:
        logging.error(f"SCP transfer failed: {res.stderr.strip()}")
        return False
    return True

def deploy_pi500() -> bool:
    logging.info("Deploying Pi 500 Master Daemon files...")
    src_dir = BASE_DIR / "pi500"
    if not run_scp(src_dir, f"{PI500_HOST}:/home/user/so101/"):
        return False
    
    # Restart Pi 500 Master Orchestrator
    cmd = "fuser -k 8085/tcp || true; pkill -9 -f main.py || true; sleep 1; cd /home/user/so101/pi500 && nohup /home/user/so101/.venv/bin/python main.py </dev/null >/tmp/so101_master.log 2>&1 &"
    return run_ssh(PI500_HOST, cmd)

def deploy_pi4b() -> bool:
    logging.info("Deploying Pi 4B Touch UI files...")
    src_ui = BASE_DIR / "pi4b" / "touchscreen_ui.py"
    if not run_scp(src_ui, f"{PI4B_HOST}:/home/carson/touch_ui/server.py"):
        return False
    
    # Restart Touch UI service on Pi 4B
    return run_ssh(PI4B_HOST, "sudo systemctl restart touch-ui.service")

def main():
    logging.info("Starting deployment to SO-101 target nodes...")
    p500_ok = deploy_pi500()
    p4b_ok = deploy_pi4b()
    
    if p500_ok and p4b_ok:
        logging.info("Deployment completed successfully across all nodes.")
    else:
        logging.error("Deployment finished with errors. Verify physical network connectivity.")
        sys.exit(1)

if __name__ == "__main__":
    main()
