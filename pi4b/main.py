#!/usr/bin/env python3
"""Pi 4B Touch UI & Media Gateway Master Orchestrator.
Initializes AudioPlaybackService, TelemetryPollerService, MediaStreamerService,
and runs the Master API Gateway HTTP Server on port 8082.
Zero external framework dependencies required.
"""

import argparse
import logging
import signal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.resolve()))

from audio_service import AudioPlaybackService
from telemetry_poller import TelemetryPollerService
from media_streamer import MediaStreamerService
from api_gateway import create_api_gateway_server

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def main() -> None:
    parser = argparse.ArgumentParser(description="Pi 4B Touch UI & Media Gateway Master Daemon")
    parser.add_argument("--port", type=int, default=8082, help="HTTP API Gateway port (default: 8082)")
    parser.add_argument("--video-device", default="/dev/video0", help="USB Camera V4L2 device path")
    parser.add_argument("--video-port", type=int, default=8083, help="GStreamer MJPEG video streaming port")
    parser.add_argument("--audio-port", type=int, default=5004, help="GStreamer UDP audio streaming port")
    parser.add_argument("--disable-gstreamer", action="store_true", help="Disable GStreamer background media pipelines")
    args = parser.parse_args()

    logging.info("Initializing Pi 4B micro-services...")
    audio_service = AudioPlaybackService()
    
    telemetry_poller = TelemetryPollerService()
    telemetry_poller.start()

    media_streamer = None
    if not args.disable_gstreamer:
        media_streamer = MediaStreamerService(
            video_device=args.video_device,
            video_port=args.video_port,
            audio_port=args.audio_port
        )
        media_streamer.start()

    logging.info(f"Binding API Gateway Server on 0.0.0.0:{args.port}...")
    server = create_api_gateway_server("0.0.0.0", args.port, telemetry_poller, audio_service)

    def _sig_handler(signum, frame):
        logging.info("Received shutdown signal (%s), terminating Pi 4B services...", signum)
        try:
            server.shutdown()
            server.server_close()
        except Exception as ex:
            logging.error("Error shutting down HTTP server: %s", ex)

        if media_streamer:
            media_streamer.stop()

        telemetry_poller.stop()
        logging.info("Pi 4B Master Orchestrator shutdown complete.")
        sys.exit(0)

    signal.signal(signal.SIGTERM, _sig_handler)
    signal.signal(signal.SIGINT, _sig_handler)

    logging.info(f"Pi 4B Master Daemon running successfully on port {args.port}")
    try:
        server.serve_forever()
    except (KeyboardInterrupt, SystemExit):
        _sig_handler(0, None)


if __name__ == "__main__":
    main()
