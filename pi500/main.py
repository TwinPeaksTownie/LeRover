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

from robot_backend import RobotBackend
from app_manager import AppManager
from teleop_control_loop import TeleopControlApp
from servo_studio_app import ServoStudioApp
from pokeball_app import PokeballApp
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

    logging.info("Initializing AppManager & registering applications...")
    app_manager = AppManager(backend)
    app_manager.register_app(TeleopControlApp)
    app_manager.register_app(ServoStudioApp)
    app_manager.register_app(PokeballApp)

    logging.info(f"AppManager ready with {len(app_manager.registry)} registered applications.")

    http_server = create_master_http_server("0.0.0.0", args.http_port, backend, app_manager)

    def _sig_handler(signum, frame):
        logging.info(f"Received signal {signum}, initiating graceful shutdown...")
        try:
            http_server.shutdown()
            http_server.server_close()
        except Exception:
            pass
        app_manager.stop_all()
        backend.close()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _sig_handler)
    signal.signal(signal.SIGINT, _sig_handler)

    logging.info(f"Master API Web Server successfully bound on port {args.http_port}")
    try:
        http_server.serve_forever()
    except (KeyboardInterrupt, SystemExit):
        _sig_handler(0, None)


if __name__ == "__main__":
    main()
