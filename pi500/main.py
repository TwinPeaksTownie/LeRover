#!/usr/bin/env python3
"""SO-101 Master Orchestrator Main Entry Point.
Initializes RobotBackend, AppManager, starts default applications, and runs Master API HTTP server on port 8085.
Zero external framework dependencies required.
"""

import argparse
import logging
import signal
import sys
import threading
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.resolve()))
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

from robot_backend import RobotBackend
from app_manager import AppManager
from teleop_control_loop import TeleopControlApp
from servo_studio_app import ServoStudioApp
from pokeball_app import PokeballApp, PokeballService
from clack_pose_app import PiranhaPoseApp, ClackPoseApp
from beat_bandit_app import BeatBanditApp
from ornith_app import OrnithVoiceApp
from api_server import create_master_http_server

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def main() -> None:
    ap = argparse.ArgumentParser(description="SO-101 Master Daemon Orchestrator")
    ap.add_argument("--port", default="/dev/ttyACM0", help="Serial port for motors")
    ap.add_argument("--id", default="follower", help="Robot follower ID")
    ap.add_argument("--no-zmq", action="store_true", help="Disable ZMQ teleoperation listener")
    ap.add_argument("--http-port", type=int, default=8085, help="HTTP API port")
    args = ap.parse_args()

    # Clean up stale processes holding serial port prior to connection
    try:
        subprocess.run(["fuser", "-k", args.port], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        logging.warning("Serial port cleanup warning: %s", e)

    logging.info(f"Initializing SO-101 Robot Backend on {args.port}...")
    backend = RobotBackend(port=args.port, robot_id=args.id)
    backend.connect()

    logging.info("Initializing PokeballService (intrinsic daemon BLE manager)...")
    pokeball_service = PokeballService(backend=backend)
    backend.pokeball_service = pokeball_service
    pokeball_service.start()

    logging.info("Initializing AppManager & registering applications...")
    app_manager = AppManager(backend)
    pokeball_service.app_manager = app_manager

    # 1. Auto-discover self-contained modular applications from apps/
    discovered = app_manager.discover_apps()

    # 2. Register fallback classes if not already discovered
    fallback_apps = [
        TeleopControlApp,
        ServoStudioApp,
        PokeballApp,
        PiranhaPoseApp,
        ClackPoseApp,
        BeatBanditApp,
        OrnithVoiceApp,
    ]
    for app_cls in fallback_apps:
        if app_cls.metadata.name not in app_manager.registry:
            app_manager.register_app(app_cls)

    logging.info(f"AppManager ready with {len(app_manager.registry)} registered applications.")

    http_server = create_master_http_server("0.0.0.0", args.http_port, backend, app_manager)
    server_thread = threading.Thread(target=http_server.serve_forever, daemon=True)
    server_thread.start()
    logging.info(f"Master API Web Server successfully bound on port {args.http_port}")

    shutdown_event = threading.Event()

    def _sig_handler(signum, frame):
        logging.info(f"Received signal {signum}, initiating graceful shutdown...")
        shutdown_event.set()

    if hasattr(signal, "SIGHUP"):
        signal.signal(signal.SIGHUP, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, _sig_handler)
    signal.signal(signal.SIGINT, _sig_handler)

    try:
        while not shutdown_event.is_set():
            shutdown_event.wait(timeout=0.5)
    except (KeyboardInterrupt, SystemExit):
        logging.info("Interrupted, shutting down...")

    logging.info("Shutting down Master API HTTP server...")
    try:
        http_server.shutdown()
        http_server.server_close()
    except Exception as e:
        logging.warning("Error during HTTP server shutdown: %s", e)

    server_thread.join(timeout=2.0)

    if pokeball_service:
        try:
            pokeball_service.stop()
        except Exception as e:
            logging.warning("Error stopping PokeballService: %s", e)

    try:
        app_manager.stop_all()
    except Exception as e:
        logging.warning("Error stopping applications: %s", e)

    try:
        backend.close()
    except Exception as e:
        logging.warning("Error closing RobotBackend: %s", e)

    logging.info("SO-101 Master Daemon shutdown complete.")
    sys.exit(0)


if __name__ == "__main__":
    main()
