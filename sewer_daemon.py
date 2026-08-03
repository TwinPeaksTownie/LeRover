#!/usr/bin/env python3
"""SO-101 follower network host with unified auxiliary motor control.
Runs ON the Raspberry Pi (CM4 / Pi 500) connected to the so-101 arm board.

Single master bus controller for Motors 1-6 (SO-101 Arm) and Motors 7-8 (Pedestal & Gantry).
Serves ZMQ teleop ports 5555/5556 and Web API ports 8085 / 5557.
"""

import argparse
import json
import logging
import time
import signal
import sys
import os
import urllib.parse
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
import threading
import zmq

from aux_servo_controller import AuxiliaryServoController
from lerobot.motors import Motor, MotorCalibration, MotorNormMode
from lerobot.motors.feetech import FeetechMotorsBus, OperatingMode

PORT_ZMQ_CMD = 5555
PORT_ZMQ_OBS = 5556
PORT_HTTP_AUX = 8085
PORT_HTTP_HANDOFF = 5557
WATCHDOG_TIMEOUT_MS = 500
MAX_LOOP_FREQ_HZ = 60
MAX_COMM_ERRORS = 30
STATE_FILE = "/home/user/so101/gantry_state.json"
CALIB_FILE = "/home/user/so101/calibration_aux.json"

TRIGGER_HANDOFF = False

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

def ticks_to_degrees_s7(ticks: int) -> float:
    ticks = int(ticks) % 4096
    deg = ((ticks - 1024) * 360.0 / 4096.0) % 360.0
    if deg > 180.0:
        deg -= 360.0
    return round(deg, 1)

def degrees_to_ticks_s7(deg: float) -> int:
    clamped_deg = max(-165.0, min(165.0, float(deg)))
    ticks = int(round(1024 + (clamped_deg * 4096.0 / 360.0))) % 4096
    return ticks

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """Threaded HTTP server to prevent slow clients from blocking API requests."""
    daemon_threads = True

class HardwareState:
    def __init__(self):
        self.lock = threading.Lock()
        self.ctrl = None
        self.raw_positions = {7: 1024, 8: 2500}
        self.accumulated_positions = {7: 1024, 8: 2500}
        self.torque_state = {7: True, 8: True}
        self.is_moving = {7: False, 8: False}
        self.calibration = {
            "7": {"min": 0, "max": 4095, "home": 1024, "home_deg": 0.0},
            "8": {"left": 4500, "right": 400, "min": 400, "max": 4500, "home": 2500}
        }
        self.hardware_active = False
        self.active_port = "/dev/ttyACM0"
        self.error_msg = None
        self.load_state()

    def load_state(self):
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, "r") as f:
                    data = json.load(f)
                    for sid_str, pos in data.items():
                        sid = int(sid_str)
                        self.accumulated_positions[sid] = int(pos)
                        self.raw_positions[sid] = int(pos) % 4096
                logging.info(f"Loaded persistent state from {STATE_FILE}: {data}")
            except Exception as e:
                logging.error(f"Failed to load state file: {e}")

    def save_state(self):
        try:
            with open(STATE_FILE, "w") as f:
                json.dump({"7": self.accumulated_positions.get(7, 1024), "8": self.accumulated_positions.get(8, 2500)}, f, indent=2)
        except Exception as e:
            logging.error(f"Failed to save state: {e}")

    def update_raw_pos(self, sid: int, raw_pos: int):
        raw_pos = int(raw_pos)
        if sid == 8:
            self.raw_positions[sid] = raw_pos
            self.accumulated_positions[sid] = raw_pos
            return raw_pos

        raw_pos = raw_pos % 4096
        self.raw_positions[sid] = raw_pos
        self.accumulated_positions[sid] = raw_pos
        return raw_pos

    def move_target(self, sid: int, target_acc: int, step_size: int = 50, speed: int = 400, max_t: int = 1000):
        with self.lock:
            if not self.ctrl or not self.hardware_active:
                return False, "Hardware offline"
            
            if self.is_moving.get(sid, False):
                logging.warning(f"Rejected move for Servo {sid}: Motor is currently executing a move.")
                return False, "Motor is currently executing a move. Request ignored."

            if not self.torque_state.get(sid, False):
                logging.warning(f"Rejected move for Servo {sid}: Torque is OFF.")
                return False, "Torque is OFF. Enable torque before moving."
            
            self.is_moving[sid] = True
            try:
                self.ctrl.set_torque(sid, True, max_torque_enable=max_t)

                if sid == 8:
                    self.ctrl.set_position_multiturn(8, target_acc, speed=speed)
                    self.accumulated_positions[8] = target_acc
                    time.sleep(0.05)
                    pos = self.ctrl.get_position_multiturn(8)
                    if pos is not None:
                        self.update_raw_pos(8, pos)
                else:
                    if sid == 7:
                        deg = ticks_to_degrees_s7(target_acc)
                        clamped_deg = max(-165.0, min(165.0, deg))
                        target_acc = degrees_to_ticks_s7(clamped_deg)

                    self.ctrl.write_goal_raw(sid, target_acc, speed=speed)
                    self.accumulated_positions[sid] = target_acc
                    self.raw_positions[sid] = target_acc

                    final_raw = self.ctrl.read_pos(sid)
                    if final_raw is not None:
                        self.update_raw_pos(sid, final_raw)
                
                self.save_state()
                return True, "OK"
            finally:
                self.is_moving[sid] = False

hw_state = HardwareState()

class UnifiedWebHandler(BaseHTTPRequestHandler):
    def _send_json(self, data, code=200):
        body = json.dumps(data).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        global TRIGGER_HANDOFF
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/status":
            with hw_state.lock:
                left_b = hw_state.calibration.get("8", {}).get("left", 4500)
                right_b = hw_state.calibration.get("8", {}).get("right", 400)
                curr_acc = hw_state.accumulated_positions.get(8, 2500)
                
                span = max(1, left_b - right_b)
                pct = max(0.0, min(100.0, ((curr_acc - right_b) / span) * 100.0))

                resp = {
                    "status": "online" if hw_state.hardware_active else "offline",
                    "hardware_connected": hw_state.hardware_active,
                    "active_port": hw_state.active_port,
                    "error": hw_state.error_msg,
                    "servos": {
                        "7": {
                            "pos": hw_state.accumulated_positions.get(7, 1024),
                            "raw": hw_state.raw_positions.get(7, 1024),
                            "angle": ticks_to_degrees_s7(hw_state.accumulated_positions.get(7, 1024)),
                            "torque": hw_state.torque_state.get(7, True),
                            "is_moving": hw_state.is_moving.get(7, False)
                        },
                        "8": {
                            "pos": hw_state.accumulated_positions.get(8, 2500),
                            "raw": hw_state.raw_positions.get(8, 2500),
                            "pct": round(pct, 1),
                            "torque": hw_state.torque_state.get(8, True),
                            "is_moving": hw_state.is_moving.get(8, False)
                        }
                    },
                    "calibration": hw_state.calibration
                }
            self._send_json(resp)
        else:
            self._send_json({"status": "ok", "service": "sewer_daemon_unified"})

    def do_POST(self):
        global TRIGGER_HANDOFF
        content_length = int(self.headers.get('Content-Length', 0))
        body_bytes = self.rfile.read(content_length) if content_length > 0 else b'{}'
        parsed = urllib.parse.urlparse(self.path)

        if parsed.path == "/handoff":
            TRIGGER_HANDOFF = True
            self._send_json({"status": "ok", "action": "handoff"})

        elif parsed.path.startswith("/slider") or parsed.path == "/api/slider":
            try:
                query = urllib.parse.parse_qs(parsed.query)
                val = int(query['value'][0]) if 'value' in query else json.loads(body_bytes.decode()).get("value", 2500)
            except Exception:
                val = 2500
            ok, msg = hw_state.move_target(8, val, speed=400, max_t=500)
            self._send_json({"status": "ok" if ok else "error", "message": msg, "target": val})

        elif parsed.path.startswith("/pedestal") or parsed.path == "/api/pedestal":
            try:
                query = urllib.parse.parse_qs(parsed.query)
                val = int(query['value'][0]) if 'value' in query else json.loads(body_bytes.decode()).get("value", 1024)
            except Exception:
                val = 1024
            ok, msg = hw_state.move_target(7, val, speed=400, max_t=500)
            self._send_json({"status": "ok" if ok else "error", "message": msg, "target": val})

        elif parsed.path == "/api/move":
            body = json.loads(body_bytes.decode('utf-8')) if body_bytes else {}
            sid = int(body.get("id", 7))
            if "angle" in body and sid == 7:
                target_acc = degrees_to_ticks_s7(float(body["angle"]))
            else:
                target_acc = int(body.get("target", 1024))
            ok, msg = hw_state.move_target(sid, target_acc, step_size=50, speed=400, max_t=500)
            if not ok:
                self._send_json({"status": "error", "message": msg}, 400)
            else:
                self._send_json({"status": "ok", "id": sid, "target_acc": target_acc, "angle": ticks_to_degrees_s7(target_acc) if sid == 7 else None})

        elif parsed.path == "/api/nudge_physical":
            body = json.loads(body_bytes.decode('utf-8')) if body_bytes else {}
            sid = int(body.get("id", 8))
            direction = str(body.get("direction", "right")).lower()
            amount = abs(int(body.get("amount", 100)))
            delta = amount if direction == "right" else -amount

            with hw_state.lock:
                curr_acc = hw_state.accumulated_positions.get(sid, 2500)
                target_acc = curr_acc + delta

            ok, msg = hw_state.move_target(sid, target_acc, step_size=50, speed=400, max_t=500)
            if not ok:
                self._send_json({"status": "error", "message": msg}, 400)
            else:
                self._send_json({"status": "ok", "id": sid, "direction": direction, "target_acc": target_acc, "current_acc": hw_state.accumulated_positions.get(sid)})

        elif parsed.path == "/api/torque":
            body = json.loads(body_bytes.decode('utf-8')) if body_bytes else {}
            sid = int(body.get("id", 7))
            toggle = body.get("toggle", True)
            with hw_state.lock:
                new_state = not hw_state.torque_state[sid] if toggle else bool(body.get("enable", False))
                hw_state.torque_state[sid] = new_state
                if hw_state.hardware_active and hw_state.ctrl:
                    hw_state.ctrl.set_torque(sid, new_state)
            self._send_json({"status": "ok", "id": sid, "torque": new_state})

        else:
            self._send_json({"error": "Endpoint not found"}, 404)

def _sig_handler(signum, frame):
    logging.info(f"Received signal {signum}, initiating graceful shutdown...")
    raise KeyboardInterrupt()

signal.signal(signal.SIGTERM, _sig_handler)
signal.signal(signal.SIGINT, _sig_handler)

def make_bus(port: str, calibration: dict[str, MotorCalibration]) -> FeetechMotorsBus:
    norm_mode_body = MotorNormMode.DEGREES
    return FeetechMotorsBus(
        port=port,
        motors={
            "shoulder_pan": Motor(1, "sts3215", norm_mode_body),
            "shoulder_lift": Motor(2, "sts3215", norm_mode_body),
            "elbow_flex": Motor(3, "sts3215", norm_mode_body),
            "wrist_flex": Motor(4, "sts3215", norm_mode_body),
            "wrist_roll": Motor(5, "sts3215", norm_mode_body),
            "gripper": Motor(6, "sts3215", MotorNormMode.RANGE_0_100),
        },
        calibration=calibration,
    )

def load_calibration(fpath: Path) -> dict[str, MotorCalibration]:
    with open(fpath) as f:
        raw = json.load(f)
    return {motor: MotorCalibration(**vals) for motor, vals in raw.items()}

def configure(bus: FeetechMotorsBus) -> None:
    RETRY = 2
    try:
        bus.disable_torque(num_retry=RETRY)
    except Exception as e:
        logging.warning("disable_torque warning: %s", e)

    try:
        bus.configure_motors()
    except Exception as e:
        logging.warning("configure_motors warning (continuing startup): %s", e)

    for motor in bus.motors:
        try:
            bus.write("Operating_Mode", motor, OperatingMode.POSITION.value, num_retry=RETRY)
            bus.write("P_Coefficient", motor, 16, num_retry=RETRY)
            bus.write("I_Coefficient", motor, 0, num_retry=RETRY)
            bus.write("D_Coefficient", motor, 32, num_retry=RETRY)
            bus.write("Max_Torque_Limit", motor, 1000, num_retry=RETRY)
            bus.write("Torque_Enable", motor, 1, num_retry=RETRY)
        except Exception as e:
            logging.warning("Failed to configure motor %s: %s", motor, e)
            
    try:
        bus.enable_torque(num_retry=RETRY)
    except Exception as e:
        logging.warning("enable_torque warning: %s", e)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="/dev/ttyACM0")
    ap.add_argument("--id", default="follower")
    ap.add_argument("--no-zmq", action="store_true", help="Disable ZMQ teleoperation listener")
    args = ap.parse_args()

    calib_fpath = (
        Path.home()
        / ".cache/huggingface/lerobot/calibration/robots/so_follower"
        / f"{args.id}.json"
    )
    calibration = load_calibration(calib_fpath)

    bus = None
    ctx = None
    cmd_sock = None
    obs_sock = None
    server_8085 = None
    server_5557 = None

    try:
        bus = make_bus(args.port, calibration)
        try:
            bus.connect()
            if hasattr(bus, "is_calibrated") and not bus.is_calibrated:
                logging.info("writing calibration file values to motors")
                bus.write_calibration(calibration)
            configure(bus)
            logging.info("SO-101 follower arm connected on %s", args.port)
        except Exception as e:
            logging.warning("Arm motor connection warning (continuing with Aux Controller): %s", e)

        # Attach Auxiliary Controller using shared PySerial handle
        ser_handle = getattr(bus.port_handler, "ser", None) if bus and hasattr(bus, "port_handler") else None
        aux_ctrl = AuxiliaryServoController(port=args.port, ser=ser_handle)
        hw_state.ctrl = aux_ctrl
        hw_state.hardware_active = True
        hw_state.active_port = args.port

        if not args.no_zmq:
            ctx = zmq.Context()
            cmd_sock = ctx.socket(zmq.PULL)
            cmd_sock.setsockopt(zmq.CONFLATE, 1)
            cmd_sock.setsockopt(zmq.LINGER, 0)
            cmd_sock.bind(f"tcp://*:{PORT_ZMQ_CMD}")
            obs_sock = ctx.socket(zmq.PUSH)
            obs_sock.setsockopt(zmq.CONFLATE, 1)
            obs_sock.setsockopt(zmq.LINGER, 0)
            obs_sock.bind(f"tcp://*:{PORT_ZMQ_OBS}")
        
        # Launch Unified HTTP Web API Servers (Port 8085 handled by aux_daemon.py)
        try:
            server_8085 = ThreadedHTTPServer(('0.0.0.0', PORT_HTTP_AUX), UnifiedWebHandler)
            threading.Thread(target=server_8085.serve_forever, daemon=True).start()
        except Exception as e:
            logging.info(f"Port {PORT_HTTP_AUX} served by aux_daemon: {e}")

        server_5557 = ThreadedHTTPServer(('0.0.0.0', PORT_HTTP_HANDOFF), UnifiedWebHandler)
        threading.Thread(target=server_5557.serve_forever, daemon=True).start()
        logging.info(f"Sewer Daemon listening on port {PORT_HTTP_HANDOFF} (ZMQ Ports {PORT_ZMQ_CMD}/{PORT_ZMQ_OBS})")

        last_cmd_time = time.time()
        watchdog_active = False
        consecutive_comm_errors = 0
        
        global TRIGGER_HANDOFF
        override_mode = False
        handoff_state = "idle"
        baseline_load = 0
        anim_start_time = 0
        hold_start_time = 0
        start_pose = {}
        poses = {}
        
        if args.no_zmq:
            logging.info("ZMQ tracking disabled. Running in local HTTP-only mode.")
        else:
            logging.info("Waiting for commands on tcp ports %d/%d", PORT_ZMQ_CMD, PORT_ZMQ_OBS)

        while True:
            loop_start = time.time()

            if TRIGGER_HANDOFF:
                TRIGGER_HANDOFF = False
                try:
                    with open("/home/user/so101/handoff_poses.json", "r") as f:
                        poses = json.load(f)
                    
                    raw_start = bus.sync_read("Present_Position")
                    start_pose = {f"{motor}.pos": val for motor, val in raw_start.items()}
                    
                    override_mode = True
                    handoff_state = "animating_to_holding"
                    anim_start_time = time.time()
                    logging.info("Handoff triggered! Animating to holding pose...")
                except Exception as e:
                    logging.error(f"Failed to trigger handoff: {e}")
            
            if override_mode:
                def interp(p1, p2, t):
                    res = {}
                    for k in p2:
                        if k in p1:
                            res[k.removesuffix(".pos")] = p1[k] + (p2[k] - p1[k]) * t
                    return res
                    
                if handoff_state == "animating_to_holding":
                    t = min(1.0, time.time() - anim_start_time)
                    bus.sync_write("Goal_Position", interp(start_pose, poses["holding"], t))
                    if t >= 1.0:
                        handoff_state = "animating_to_lifting"
                        start_pose = poses["holding"]
                        anim_start_time = time.time()
                        logging.info("Holding reached. Animating to lifting pose...")
                        
                elif handoff_state == "animating_to_lifting":
                    t = min(1.0, time.time() - anim_start_time)
                    bus.sync_write("Goal_Position", interp(start_pose, poses["lifting"], t))
                    if t >= 1.0:
                        handoff_state = "waiting_for_load_drop"
                        try:
                            baseline_load = bus.read("Present_Load", "shoulder_lift")
                        except:
                            baseline_load = 0
                        logging.info(f"Lifting pose reached. Waiting for load drop. Baseline: {baseline_load}")
                        
                elif handoff_state == "waiting_for_load_drop":
                    bus.sync_write("Goal_Position", {k.removesuffix(".pos"): v for k, v in poses["lifting"].items()})
                    try:
                        current_load = bus.read("Present_Load", "shoulder_lift")
                        if abs(current_load) < abs(baseline_load) - 30 or abs(current_load) < abs(baseline_load) * 0.6:
                            logging.info(f"Load drop detected! Current: {current_load}")
                            handoff_state = "releasing_gripper"
                            hold_start_time = time.time()
                    except:
                        pass
                        
                elif handoff_state == "releasing_gripper":
                    goal = {k.removesuffix(".pos"): v for k, v in poses["lifting"].items()}
                    goal["gripper"] = 100.0
                    bus.sync_write("Goal_Position", goal)
                    if time.time() - hold_start_time > 1.5:
                        handoff_state = "animating_to_neutral"
                        start_pose = poses["lifting"].copy()
                        start_pose["gripper.pos"] = 100.0
                        anim_start_time = time.time()
                        logging.info("Gripper released. Animating to neutral...")
                        
                elif handoff_state == "animating_to_neutral":
                    t = min(1.0, time.time() - anim_start_time)
                    bus.sync_write("Goal_Position", interp(start_pose, poses["neutral"], t))
                    if t >= 1.0:
                        override_mode = False
                        handoff_state = "idle"
                        logging.info("Handoff complete, returning control to ZMQ")
                
                try:
                    if not args.no_zmq and obs_sock:
                        obs = bus.sync_read("Present_Position")
                        obs = {f"{motor}.pos": val for motor, val in obs.items()}
                        obs_sock.send_string(json.dumps(obs), flags=zmq.NOBLOCK)
                except:
                    pass
                time.sleep(max(1 / MAX_LOOP_FREQ_HZ - (time.time() - loop_start), 0))
                
                try:
                    while not args.no_zmq and cmd_sock:
                        cmd_sock.recv_string(zmq.NOBLOCK)
                except zmq.Again:
                    pass
                continue

            if args.no_zmq:
                if not override_mode and handoff_state == "idle":
                    try:
                        if not poses:
                            with open("/home/user/so101/handoff_poses.json", "r") as f:
                                poses = json.load(f)
                        bus.sync_write("Goal_Position", {k.removesuffix(".pos"): v for k, v in poses["neutral"].items()})
                    except Exception:
                        pass
                time.sleep(max(1 / MAX_LOOP_FREQ_HZ - (time.time() - loop_start), 0))
                continue

            try:
                msg = cmd_sock.recv_string(zmq.NOBLOCK)
                action = json.loads(msg)
                goal_pos = {
                    k.removesuffix(".pos"): v for k, v in action.items() if k.endswith(".pos")
                }
                bus.sync_write("Goal_Position", goal_pos)
                last_cmd_time = time.time()
                if watchdog_active:
                    logging.info("commands resumed")
                watchdog_active = False
            except zmq.Again:
                pass
            except Exception as e:
                logging.error("command handling failed: %s", e)

            if (time.time() - last_cmd_time > WATCHDOG_TIMEOUT_MS / 1000) and not watchdog_active:
                logging.warning("no commands for %dms, holding pose", WATCHDOG_TIMEOUT_MS)
                watchdog_active = True

            try:
                if not args.no_zmq and obs_sock:
                    try:
                        obs = bus.sync_read("Present_Position")
                        obs = {f"{motor}.pos": val for motor, val in obs.items()}
                        obs_sock.send_string(json.dumps(obs), flags=zmq.NOBLOCK)
                    except Exception:
                        pass
                consecutive_comm_errors = 0
            except Exception as e:
                pass

            time.sleep(max(1 / MAX_LOOP_FREQ_HZ - (time.time() - loop_start), 0))
    except KeyboardInterrupt:
        logging.info("KeyboardInterrupt/SIGTERM received, commencing shutdown sequence...")
    except Exception as e:
        logging.error(f"Execution error in follower host: {e}")
    finally:
        logging.info("shutting down, disabling motor torque and closing sockets")
        try:
            if bus and hasattr(bus, "disable_torque"):
                bus.disable_torque(num_retry=2)
        except Exception as e:
            logging.error(f"Error disabling motor torque: {e}")

        try:
            if bus and hasattr(bus, "disconnect"):
                bus.disconnect()
        except Exception as e:
            logging.error(f"Error disconnecting motor bus: {e}")

        try:
            if cmd_sock:
                cmd_sock.close(linger=0)
            if obs_sock:
                obs_sock.close(linger=0)
            if ctx:
                ctx.term()
        except Exception as e:
            logging.error(f"Error closing ZMQ sockets: {e}")

        try:
            if server_8085:
                server_8085.shutdown()
                server_8085.server_close()
            if server_5557:
                server_5557.shutdown()
                server_5557.server_close()
        except Exception as e:
            logging.error(f"Error closing HTTP servers: {e}")

        logging.info("SO-101 follower host cleanup complete.")

if __name__ == "__main__":
    main()
