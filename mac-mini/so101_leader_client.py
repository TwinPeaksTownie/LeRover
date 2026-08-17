#!/usr/bin/env python3
import argparse
import json
import logging
import time
import zmq

from lerobot.teleoperators.so_leader import SO101Leader, SOLeaderTeleopConfig
from lerobot.motors import MotorNormMode

PORT_ZMQ_CMD = 5555
PORT_ZMQ_OBS = 5556
FPS = 60

logging.basicConfig(level=logging.INFO)

def create_zmq_sockets(ctx, host):
    cmd_sock = ctx.socket(zmq.PUSH)
    cmd_sock.setsockopt(zmq.CONFLATE, 1)
    cmd_sock.setsockopt(zmq.LINGER, 0)
    cmd_sock.connect(f"tcp://{host}:{PORT_ZMQ_CMD}")
    
    obs_sock = ctx.socket(zmq.PULL)
    obs_sock.setsockopt(zmq.CONFLATE, 1)
    obs_sock.setsockopt(zmq.LINGER, 0)
    obs_sock.connect(f"tcp://{host}:{PORT_ZMQ_OBS}")
    return cmd_sock, obs_sock

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="192.168.0.130")
    ap.add_argument("--port", default="/dev/cu.usbmodem5B415318721")
    ap.add_argument("--id", default="leader")
    args = ap.parse_args()

    logging.info(f"Initializing SO101Leader on {args.port} (Relative Percentage Mode)")
    config = SOLeaderTeleopConfig(port=args.port, id=args.id)
    config.use_degrees = False
    leader = SO101Leader(config)
    
    # Configure motor normalization modes natively prior to connection
    for mname, m in leader.bus.motors.items():
        m.norm_mode = MotorNormMode.RANGE_0_100 if mname == "gripper" else MotorNormMode.RANGE_M100_100

    # Official connect
    leader.connect(calibrate=False)
    logging.info("Leader arm connected successfully with native motor normalization.")

    ctx = zmq.Context()
    cmd_sock, obs_sock = create_zmq_sockets(ctx, args.host)

    logging.info("Streaming ZMQ relative percentage frames...")
    n = 0
    consecutive_zmq_errors = 0
    try:
        while True:
            loop_start = time.time()
            
            try:
                action = leader.get_action()
            except Exception as e:
                logging.debug(f"Telemetry error: {e}")
                time.sleep(0.01)
                continue

            if action and isinstance(action, dict):
                # Clean Network Boundary: strip any .pos suffixes or dataset artifacts before serializing
                clean_action = {}
                for k, v in action.items():
                    clean_k = str(k).removesuffix(".pos")
                    clean_action[clean_k] = float(v.item() if hasattr(v, "item") else v)
                try:
                    cmd_sock.send_string(json.dumps(clean_action), flags=zmq.NOBLOCK)
                    consecutive_zmq_errors = 0
                except Exception as ze:
                    consecutive_zmq_errors += 1
                    if consecutive_zmq_errors > 10:
                        logging.warning("ZMQ stream errors exceeded threshold (%d). Reconnecting sockets to %s...", consecutive_zmq_errors, args.host)
                        try:
                            cmd_sock.close()
                            obs_sock.close()
                        except Exception:
                            pass
                        time.sleep(1.0)
                        cmd_sock, obs_sock = create_zmq_sockets(ctx, args.host)
                        consecutive_zmq_errors = 0

            try:
                obs_sock.recv_string(zmq.NOBLOCK)
            except Exception:
                pass

            n += 1
            if n % 300 == 0:
                logging.info(f"Stream active: {n} frames sent")

            time.sleep(max(1 / FPS - (time.time() - loop_start), 0))
    except KeyboardInterrupt:
        pass
    finally:
        try:
            leader.disconnect()
        except Exception:
            pass
        ctx.term()

if __name__ == "__main__":
    main()
