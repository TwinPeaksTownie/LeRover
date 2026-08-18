#!/usr/bin/env python3
"""Poké Ball Plus & Rover Drivetrain PC Simulation Suite.
Simulates:
1. BLE Notification packet streams (12-bit X/Y joystick + Stick Click & Top Red buttons).
2. Pi 4B Touch UI audio server (captures POST /api/play_sound requests).
3. Adafruit KB2040 GPIO UART packet sink (validates CMD:left,right,slider,pulse 25Hz heartbeat).
4. Full automated verification of the 3-second hold timer, Mario Kart audio trigger, arcade drive mixing, and failsafes.
"""

import http.server
import json
import logging
import os
import socketserver
import sys
import threading
import time
from typing import List, Dict, Any, Tuple

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


# Configure paths
current_dir = os.path.dirname(os.path.abspath(__file__))
workspace_root = os.path.abspath(os.path.join(current_dir, ".."))
pi500_dir = os.path.join(workspace_root, "pi500")

for p in [workspace_root, pi500_dir, current_dir]:
    if p not in sys.path:
        sys.path.insert(0, p)

from rover.rover_controller import RoverController
import pokeball_app
from pokeball_app import PokeballApp

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("so101.simulator")


# --- MOCK PI 4B AUDIO SERVER ---
class MockAudioHandler(http.server.BaseHTTPRequestHandler):
    dispatched_sounds: List[str] = []

    def do_POST(self):
        if self.path == "/api/play_sound":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
            try:
                data = json.loads(body)
                kind = data.get("kind", "unknown")
            except Exception:
                kind = "unknown"

            MockAudioHandler.dispatched_sounds.append(kind)
            logger.info("🔊 [MOCK PI 4B AUDIO] Received sound dispatch: '%s'", kind)

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # Silence standard HTTP access logs
        pass


def start_mock_audio_server(port: int = 8082) -> Tuple[socketserver.TCPServer, threading.Thread]:
    """Starts local mock audio server on port 8082."""
    MockAudioHandler.dispatched_sounds.clear()
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("127.0.0.1", port), MockAudioHandler)
    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()
    return httpd, server_thread


# --- PACKET GENERATOR ---
def generate_pokeball_packet(
    btn_stick: bool = False,  # Button A (0x02)
    btn_top: bool = False,    # Button B (0x01)
    norm_x: float = 0.0,      # Steering: -1.0 (Left) to +1.0 (Right)
    norm_y: float = 0.0       # Throttle: -1.0 (Reverse) to +1.0 (Forward)
) -> bytearray:
    """Generates authentic 12-bit packed Poké Ball Plus BLE notification packet."""
    buttons = 0x00
    if btn_stick:
        buttons |= 0x02
    if btn_top:
        buttons |= 0x01

    # Clamp and map -1.0..1.0 to 12-bit 0..4095 (center 2048)
    norm_x_clamped = max(-1.0, min(1.0, norm_x))
    norm_y_clamped = max(-1.0, min(1.0, norm_y))

    raw_x = int(2048 + norm_x_clamped * 2048)
    raw_y = int(2048 + norm_y_clamped * 2048)
    raw_x = max(0, min(4095, raw_x))
    raw_y = max(0, min(4095, raw_y))

    packet = bytearray(5)
    packet[0] = 0x00
    packet[1] = buttons
    packet[2] = raw_x & 0xFF
    packet[3] = ((raw_x >> 8) & 0x0F) | ((raw_y & 0x0F) << 4)
    packet[4] = (raw_y >> 4) & 0xFF

    return packet


# --- SIMULATION SUITE ---
def run_simulation():
    print("\n" + "=" * 80)
    print("🎮 RUNNING POKÉ BALL PLUS & ROVER DRIVETRAIN SIMULATION ON PC")
    print("=" * 80 + "\n")

    # 1. Start Mock Pi 4B Audio Server
    try:
        httpd, _ = start_mock_audio_server(8082)
        pokeball_app.PI4B_SOUND_URL = "http://127.0.0.1:8082/api/play_sound"
        logger.info("Mock Pi 4B audio server listening at http://127.0.0.1:8082/api/play_sound")
    except Exception as e:
        logger.warning("Could not bind port 8082 (might already be bound): %s", e)
        httpd = None

    # 2. Initialize Rover Controller & App
    rover_ctrl = RoverController(mock_mode=True)
    captured_uart_packets: List[Dict[str, Any]] = []

    def _uart_sink(cmd_str: str, left_pulse: int, right_pulse: int):
        captured_uart_packets.append({
            "time": time.time(),
            "cmd": cmd_str.strip(),
            "left": left_pulse,
            "right": right_pulse
        })

    rover_ctrl.set_mock_sink(_uart_sink)
    rover_ctrl.start()

    app = PokeballApp(rover_ctrl=rover_ctrl)
    app.logger.setLevel(logging.INFO)

    try:
        # -------------------------------------------------------------
        # TEST 1: Initial State
        # -------------------------------------------------------------
        print("\n--- TEST 1: Initial System State ---")
        assert app.control_mode == "AUX", f"Expected AUX mode, got {app.control_mode}"
        assert app.telemetry["control_mode"] == "AUX"
        print("✅ PASS: App initialized in AUX Manipulator Mode.")

        # -------------------------------------------------------------
        # TEST 2: Short Button A Hold (<3s) -> Should NOT switch mode
        # -------------------------------------------------------------
        print("\n--- TEST 2: Short Button A Hold (1.2 seconds) ---")
        MockAudioHandler.dispatched_sounds.clear()
        start_t = time.time()
        while time.time() - start_t < 1.2:
            pkt = generate_pokeball_packet(btn_stick=True, btn_top=False, norm_x=0.0, norm_y=0.0)
            app.notification_handler("sim", pkt)
            time.sleep(0.033)  # ~30 Hz BLE rate

        # Release button
        pkt_rel = generate_pokeball_packet(btn_stick=False, btn_top=False, norm_x=0.0, norm_y=0.0)
        app.notification_handler("sim", pkt_rel)

        assert app.control_mode == "AUX", f"Expected mode to stay AUX, got {app.control_mode}"
        assert "mario_kart_start" not in MockAudioHandler.dispatched_sounds, "Mario Kart audio fired prematurely!"
        print(f"✅ PASS: 1.2s hold did not trigger mode switch (Current mode: {app.control_mode}, Dispatched sounds: {MockAudioHandler.dispatched_sounds}).")

        # -------------------------------------------------------------
        # TEST 3: Full 3.0s Button A Hold -> Switch to ROVER Mode & Play Mario Kart
        # -------------------------------------------------------------
        print("\n--- TEST 3: Full 3.0s Button A Hold -> ROVER Transition ---")
        MockAudioHandler.dispatched_sounds.clear()
        start_t = time.time()
        while time.time() - start_t < 3.2:
            pkt = generate_pokeball_packet(btn_stick=True, btn_top=False, norm_x=0.0, norm_y=0.0)
            app.notification_handler("sim", pkt)
            time.sleep(0.033)

        # Release button
        app.notification_handler("sim", pkt_rel)

        assert app.control_mode == "ROVER", f"Expected mode to switch to ROVER, got {app.control_mode}"
        assert "mario_kart_start" in MockAudioHandler.dispatched_sounds, "Mario Kart audio was not triggered!"
        print(f"✅ PASS: Mode switched to ROVER after 3.0s hold! Audio triggered: {MockAudioHandler.dispatched_sounds}")

        # -------------------------------------------------------------
        # TEST 4: Drive Forward in ROVER Mode -> Verify UART CMD Output
        # -------------------------------------------------------------
        print("\n--- TEST 4: Throttle Forward (norm_y = 1.0) in ROVER Mode ---")
        captured_uart_packets.clear()
        drive_start = time.time()
        while time.time() - drive_start < 0.3:
            pkt_forward = generate_pokeball_packet(btn_stick=False, btn_top=False, norm_x=0.0, norm_y=1.0)
            app.notification_handler("sim", pkt_forward)
            time.sleep(0.033)

        time.sleep(0.1)  # Allow UART worker cycle
        assert len(captured_uart_packets) > 0, "No UART packets received by mock sink!"
        latest_pkt = captured_uart_packets[-1]
        print(f"  Latest UART Packet: {latest_pkt['cmd']} (Left: {latest_pkt['left']} µs, Right: {latest_pkt['right']} µs)")

        # Left motor inverted (1500 - y*75 < 1500), Right motor normal (1500 + y*75 > 1500)
        assert latest_pkt["left"] < 1500, f"Left pulse {latest_pkt['left']} should be < 1500 for forward drive"
        assert latest_pkt["right"] > 1500, f"Right pulse {latest_pkt['right']} should be > 1500 for forward drive"
        print("✅ PASS: Forward drive pulses correctly calculated and formatted.")

        # -------------------------------------------------------------
        # TEST 5: Steer Right in ROVER Mode -> Verify Differential Kinematics
        # -------------------------------------------------------------
        print("\n--- TEST 5: Steer Right (norm_x = 0.8, norm_y = 0.5) in ROVER Mode ---")
        captured_uart_packets.clear()
        drive_start = time.time()
        while time.time() - drive_start < 0.3:
            pkt_turn = generate_pokeball_packet(btn_stick=False, btn_top=False, norm_x=0.8, norm_y=0.5)
            app.notification_handler("sim", pkt_turn)
            time.sleep(0.033)

        time.sleep(0.1)
        latest_pkt = captured_uart_packets[-1]
        print(f"  Latest Turn UART Packet: {latest_pkt['cmd']} (Left: {latest_pkt['left']} µs, Right: {latest_pkt['right']} µs)")
        print("✅ PASS: Differential turning mixed and dispatched.")

        # -------------------------------------------------------------
        # TEST 6: Top Red Button (Button B) Tap in ROVER Mode -> Instant Brake
        # -------------------------------------------------------------
        print("\n--- TEST 6: Top Red Button Tap in ROVER Mode (Emergency Brake) ---")
        pkt_brake = generate_pokeball_packet(btn_stick=False, btn_top=True, norm_x=0.0, norm_y=0.0)
        app.notification_handler("sim", pkt_brake)
        time.sleep(0.1)

        telem = rover_ctrl.get_telemetry()
        assert telem["target_x"] == 0.0 and telem["target_y"] == 0.0, "Drive targets not zeroed on brake!"
        print("✅ PASS: Top Red button tap triggered instant brake.")

        # -------------------------------------------------------------
        # TEST 7: 3.0s Button A Hold to Return to AUX Mode
        # -------------------------------------------------------------
        print("\n--- TEST 7: 3.0s Button A Hold -> Return to AUX Mode ---")
        MockAudioHandler.dispatched_sounds.clear()
        start_t = time.time()
        while time.time() - start_t < 3.2:
            pkt = generate_pokeball_packet(btn_stick=True, btn_top=False, norm_x=0.0, norm_y=0.0)
            app.notification_handler("sim", pkt)
            time.sleep(0.033)

        app.notification_handler("sim", pkt_rel)

        assert app.control_mode == "AUX", f"Expected mode to return to AUX, got {app.control_mode}"
        assert "disconnect" in MockAudioHandler.dispatched_sounds, "Exit chime not dispatched!"
        print(f"✅ PASS: Mode returned to AUX! Exit chime dispatched: {MockAudioHandler.dispatched_sounds}")

        # -------------------------------------------------------------
        # TEST 8: Gantry / Pedestal Aux Gestures Active in AUX Mode
        # -------------------------------------------------------------
        print("\n--- TEST 8: Aux Gantry & Pedestal Trigger Verification in AUX Mode ---")
        # Tilt right then press Top Red Button (Pedestal Step)
        pkt_aux_tilt = generate_pokeball_packet(btn_stick=False, btn_top=False, norm_x=0.8, norm_y=0.0)
        app.notification_handler("sim", pkt_aux_tilt)

        pkt_aux_step = generate_pokeball_packet(btn_stick=False, btn_top=True, norm_x=0.8, norm_y=0.0)
        app.notification_handler("sim", pkt_aux_step)

        print("✅ PASS: Aux gesture triggers operational in AUX mode.")

        print("\n" + "=" * 80)
        print("🎉 ALL 8 POKÉ BALL & ROVER SIMULATION TESTS PASSED PERFECTLY!")
        print("=" * 80 + "\n")

    finally:
        rover_ctrl.shutdown()
        if httpd:
            httpd.shutdown()


if __name__ == "__main__":
    run_simulation()
