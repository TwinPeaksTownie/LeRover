#!/usr/bin/env python3
"""Interactive Web-Based Poké Ball Plus & Rover PWM Drivetrain Simulator.
Supports:
1. Physical BLE connection to Poké Ball Plus (MAC: 58:2F:40:8D:50:71 or 'Pokemon PBP').
2. Interactive Web UI with on-screen virtual joystick & Button A hold countdown.
3. Synchronized Mario Kart start audio playback on Rover Mode activation.
4. Live dual-gauge PWM readout showing deviations from the 1500 µs neutral baseline.
"""

import asyncio
import http.server
import json
import logging
import os
import socketserver
import sys
import threading
import time
import urllib.parse
from typing import Dict, Any

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Ensure workspace paths
current_dir = os.path.dirname(os.path.abspath(__file__))
workspace_root = os.path.abspath(os.path.join(current_dir, ".."))
for p in [workspace_root, os.path.join(workspace_root, "pi500"), current_dir]:
    if p not in sys.path:
        sys.path.insert(0, p)

from rover.rover_controller import RoverController
from pokeball_app import PokeballApp

try:
    from bleak import BleakScanner, BleakClient
    BLEAK_AVAILABLE = True
except ImportError:
    BleakScanner = None
    BleakClient = None
    BLEAK_AVAILABLE = False

PORT = 8090
TARGET_MAC = "58:2F:40:8D:50:71"
INPUT_UUID = "6675e16c-f36d-4567-bb55-6b51e27a23e6"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("so101.web_sim")

# --- SIMULATION STATE ---
sim_lock = threading.Lock()
rover_ctrl = RoverController(mock_mode=True)
rover_ctrl.start()

app_instance = PokeballApp(rover_ctrl=rover_ctrl)
app_instance.logger.setLevel(logging.INFO)

latest_event_audio = None
audio_event_seq = 0

ble_state = {
    "connected": False,
    "device_name": "Scanning for Poké Ball...",
    "mac": TARGET_MAC,
    "last_seen": 0.0
}

def on_sound_triggered(kind: str):
    global latest_event_audio, audio_event_seq
    with sim_lock:
        latest_event_audio = kind
        audio_event_seq += 1
    logger.info("🔊 Simulated Audio Event Dispatched: '%s'", kind)

import pokeball_app
pokeball_app.play_chime = on_sound_triggered


# --- PHYSICAL BLE BACKGROUND WORKER ---
def ble_background_worker():
    if not BLEAK_AVAILABLE:
        logger.warning("Bleak not available; physical Bluetooth connection disabled.")
        return

    async def _loop():
        global ble_state
        while True:
            try:
                with sim_lock:
                    ble_state["connected"] = False
                    ble_state["device_name"] = "Scanning for Poké Ball Plus (Press any button)..."

                # Scan for device
                device = await BleakScanner.find_device_by_filter(
                    lambda d, adv: (d.address and d.address.upper() == TARGET_MAC.upper()) or (d.name and ("Pokemon" in d.name or "Poke" in d.name)),
                    timeout=4.0
                )

                if device:
                    logger.info("Found physical Poké Ball Plus (%s, %s)! Connecting...", device.name, device.address)
                    with sim_lock:
                        ble_state["device_name"] = f"Connecting to {device.name or device.address}..."

                    def _on_disconnect(c):
                        logger.info("Physical Poké Ball Plus disconnected callback.")
                        with sim_lock:
                            ble_state["connected"] = False

                    async with BleakClient(device.address, timeout=10.0, disconnected_callback=_on_disconnect) as client:
                        logger.info("✅ Connected to physical Poké Ball Plus over BLE!")
                        with sim_lock:
                            ble_state["connected"] = True
                            ble_state["device_name"] = f"Connected: {device.name or device.address}"
                            ble_state["mac"] = device.address

                        def _on_notify(sender, data):
                            try:
                                with sim_lock:
                                    ble_state["last_seen"] = time.time()
                                app_instance.notification_handler("ble_real", data)
                            except Exception as notify_err:
                                logger.error("Notification processing error: %s", notify_err)

                        await client.start_notify(INPUT_UUID, _on_notify)

                        while client.is_connected:
                            await asyncio.sleep(0.2)

                        logger.info("Physical Poké Ball Plus connection loop ended.")
            except Exception as e:
                with sim_lock:
                    ble_state["connected"] = False
                    ble_state["device_name"] = f"Waiting for device ({e})"
                await asyncio.sleep(1.0)


    asyncio.run(_loop())

threading.Thread(target=ble_background_worker, daemon=True, name="BLEWorker").start()


def generate_packet_bytes(btn_stick: bool, btn_top: bool, norm_x: float, norm_y: float) -> bytearray:
    buttons = 0x00
    if btn_stick:
        buttons |= 0x02  # Button A
    if btn_top:
        buttons |= 0x01  # Button B

    norm_x = max(-1.0, min(1.0, norm_x))
    norm_y = max(-1.0, min(1.0, norm_y))

    raw_x = int(2048 + norm_x * 2048)
    raw_y = int(2048 + norm_y * 2048)
    raw_x = max(0, min(4095, raw_x))
    raw_y = max(0, min(4095, raw_y))

    packet = bytearray(5)
    packet[0] = 0x00
    packet[1] = buttons
    packet[2] = raw_x & 0xFF
    packet[3] = ((raw_x >> 8) & 0x0F) | ((raw_y & 0x0F) << 4)
    packet[4] = (raw_y >> 4) & 0xFF
    return packet


HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Poké Ball & Rover PWM Drivetrain Simulator</title>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;600;700;800&family=JetBrains+Mono:wght@500;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg: #0b0f17;
            --card-bg: #131b26;
            --border: #1e2a38;
            --primary: #ff4757;
            --accent: #2ed573;
            --text-main: #f1f2f6;
            --text-dim: #8b9bb4;
            --left-motor: #3742fa;
            --right-motor: #ffa502;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
            user-select: none;
        }

        body {
            font-family: 'Plus Jakarta Sans', sans-serif;
            background-color: var(--bg);
            color: var(--text-main);
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            align-items: center;
            padding: 24px;
        }

        .header {
            text-align: center;
            margin-bottom: 20px;
        }

        .header h1 {
            font-size: 26px;
            font-weight: 800;
            color: #ffffff;
            letter-spacing: -0.5px;
        }

        .header p {
            color: var(--text-dim);
            font-size: 14px;
            margin-top: 4px;
        }

        .ble-status-bar {
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
            padding: 6px 14px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
            background: #111a24;
            border: 1px solid #1e2b3c;
            margin-top: 10px;
            transition: all 0.3s;
        }

        .ble-status-bar.connected {
            background: rgba(46, 213, 115, 0.12);
            border-color: #2ed573;
            color: #2ed573;
        }

        .grid-container {
            display: grid;
            grid-template-columns: 340px 420px;
            gap: 24px;
            width: 100%;
            max-width: 800px;
        }

        .card {
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 16px;
            padding: 20px;
            display: flex;
            flex-direction: column;
            gap: 16px;
            box-shadow: 0 10px 25px rgba(0,0,0,0.35);
        }

        .card-title {
            font-size: 13px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.8px;
            color: var(--text-dim);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .mode-badge {
            padding: 4px 10px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 700;
            letter-spacing: 0.5px;
            background: #1e293b;
            color: #94a3b8;
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        }

        .mode-badge.rover {
            background: rgba(46, 213, 115, 0.18);
            color: #2ed573;
            border: 1px solid #2ed573;
            box-shadow: 0 0 15px rgba(46, 213, 115, 0.3);
        }

        .mode-badge.aux {
            background: rgba(255, 71, 87, 0.15);
            color: #ff4757;
            border: 1px solid #ff4757;
        }

        /* Virtual Joystick Box */
        .joystick-zone {
            width: 220px;
            height: 220px;
            background: #0d131c;
            border: 2px dashed #243347;
            border-radius: 50%;
            margin: 0 auto;
            position: relative;
            touch-action: none;
            cursor: grab;
            display: flex;
            justify-content: center;
            align-items: center;
        }

        .joystick-knob {
            width: 60px;
            height: 60px;
            background: radial-gradient(circle, #ff4757, #c0392b);
            border-radius: 50%;
            position: absolute;
            box-shadow: 0 6px 14px rgba(255, 71, 87, 0.4);
            pointer-events: none;
            transition: transform 0.05s ease-out;
        }

        /* Hold Button A Trigger */
        .hold-btn-container {
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 10px;
            margin-top: 10px;
        }

        .hold-btn-wrapper {
            position: relative;
            width: 110px;
            height: 110px;
            display: flex;
            justify-content: center;
            align-items: center;
        }

        .progress-ring {
            position: absolute;
            top: 0;
            left: 0;
            transform: rotate(-90deg);
        }

        .progress-ring__circle {
            stroke: #2ed573;
            stroke-dasharray: 326.72;
            stroke-dashoffset: 326.72;
            transition: stroke-dashoffset 0.05s linear;
        }

        .btn-a {
            width: 84px;
            height: 84px;
            border-radius: 50%;
            background: #1c2635;
            border: 2px solid #2e3d52;
            color: white;
            font-size: 12px;
            font-weight: 700;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            z-index: 2;
            transition: all 0.15s;
        }

        .btn-a:active, .btn-a.held {
            background: #2ed573;
            color: #0b0f17;
            border-color: #2ed573;
            transform: scale(0.96);
        }

        .btn-top {
            background: #1e293b;
            border: 1px solid #334155;
            color: #e2e8f0;
            padding: 8px 16px;
            border-radius: 8px;
            font-weight: 600;
            font-size: 12px;
            cursor: pointer;
            transition: 0.15s;
        }

        .btn-top:active, .btn-top.held {
            background: #ff4757;
            color: white;
        }

        /* PWM Gauges */
        .pwm-gauge {
            background: #0d131c;
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 14px;
            display: flex;
            flex-direction: column;
            gap: 8px;
        }

        .pwm-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 13px;
            font-weight: 600;
        }

        .pwm-value {
            font-family: 'JetBrains Mono', monospace;
            font-size: 18px;
            font-weight: 700;
        }

        .meter-bar {
            width: 100%;
            height: 16px;
            background: #16202e;
            border-radius: 8px;
            position: relative;
            overflow: hidden;
        }

        .meter-center {
            position: absolute;
            left: 50%;
            top: 0;
            bottom: 0;
            width: 2px;
            background: rgba(255,255,255,0.25);
            z-index: 2;
        }

        .meter-fill {
            height: 100%;
            position: absolute;
            top: 0;
            transition: all 0.05s linear;
        }

        .cmd-box {
            background: #080c12;
            border: 1px solid #162232;
            border-radius: 8px;
            padding: 10px 14px;
            font-family: 'JetBrains Mono', monospace;
            font-size: 13px;
            color: #00d2d3;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .instructions {
            font-size: 12px;
            color: var(--text-dim);
            line-height: 1.5;
        }

        .instructions strong {
            color: #ffffff;
        }
    </style>
</head>
<body>

    <div class="header">
        <h1>🏎️ Poké Ball Plus & Rover PWM Simulator</h1>
        <p>Live hardware-accurate PWM generation & 3-second hold mode transition</p>
        <div id="bleStatus" class="ble-status-bar">
            <span>⚪</span>
            <span id="bleText">Scanning for physical Poké Ball Plus... (Press top button to wake)</span>
        </div>
    </div>

    <div class="grid-container">

        <!-- Controller Card -->
        <div class="card">
            <div class="card-title">
                <span>Poké Ball Inputs</span>
                <span id="modeBadge" class="mode-badge aux">AUX MODE</span>
            </div>

            <!-- Virtual Joystick -->
            <div class="joystick-zone" id="joyZone">
                <div class="joystick-knob" id="joyKnob"></div>
            </div>

            <div style="display: flex; justify-content: space-around; font-size: 12px; color: var(--text-dim); font-family: 'JetBrains Mono';">
                <span>X: <strong id="valX" style="color: #fff;">0.00</strong></span>
                <span>Y: <strong id="valY" style="color: #fff;">0.00</strong></span>
            </div>

            <!-- Hold Button A with 3s Ring -->
            <div class="hold-btn-container">
                <div class="hold-btn-wrapper">
                    <svg class="progress-ring" width="110" height="110">
                        <circle class="progress-ring__circle" stroke-width="4" fill="transparent" r="52" cx="55" cy="55"/>
                    </svg>
                    <button class="btn-a" id="btnStick">
                        <span>HOLD 3s</span>
                        <small style="font-size: 9px; opacity: 0.7;">BUTTON A</small>
                    </button>
                </div>
                <button class="btn-top" id="btnTop">Top Red (Button B)</button>
            </div>
        </div>

        <!-- Live PWM Telemetry Card -->
        <div class="card">
            <div class="card-title">
                <span>Live Motor PWM Telemetry</span>
                <span style="font-size: 11px; color: #10b981;">● 25Hz GPIO UART</span>
            </div>

            <!-- Left Motor Gauge -->
            <div class="pwm-gauge">
                <div class="pwm-header">
                    <span style="color: var(--left-motor);">Left Wheel ESC (D6 - Inverted)</span>
                    <span id="leftPulse" class="pwm-value" style="color: var(--left-motor);">1500 µs</span>
                </div>
                <div class="meter-bar">
                    <div class="meter-center"></div>
                    <div id="leftFill" class="meter-fill" style="background: var(--left-motor); left: 50%; width: 0%;"></div>
                </div>
                <div style="display: flex; justify-content: space-between; font-size: 10px; color: var(--text-dim);">
                    <span>1000 µs (Full Fwd)</span>
                    <span>1500 µs (Stop)</span>
                    <span>2000 µs (Full Rev)</span>
                </div>
            </div>

            <!-- Right Motor Gauge -->
            <div class="pwm-gauge">
                <div class="pwm-header">
                    <span style="color: var(--right-motor);">Right Wheel ESC (D7 - Normal)</span>
                    <span id="rightPulse" class="pwm-value" style="color: var(--right-motor);">1500 µs</span>
                </div>
                <div class="meter-bar">
                    <div class="meter-center"></div>
                    <div id="rightFill" class="meter-fill" style="background: var(--right-motor); left: 50%; width: 0%;"></div>
                </div>
                <div style="display: flex; justify-content: space-between; font-size: 10px; color: var(--text-dim);">
                    <span>1000 µs (Full Rev)</span>
                    <span>1500 µs (Stop)</span>
                    <span>2000 µs (Full Fwd)</span>
                </div>
            </div>

            <!-- Live Serial Command Packet -->
            <div>
                <div style="font-size: 11px; font-weight: 700; color: var(--text-dim); margin-bottom: 6px; text-transform: uppercase;">
                    Dispatched Serial Packet:
                </div>
                <div class="cmd-box">
                    <span id="cmdStr">CMD:1500,1500,1500,0</span>
                    <span id="audioTag" style="font-size: 11px; color: #f59e0b;"></span>
                    <div class="instructions">
                <p><strong>1. Start Rover Mode</strong>: Hold <strong>Button A (Stick Click)</strong> for 3 seconds. The <em>Mario Kart chime</em> will play, and wheel drive unlocks 1.0s after the audio ends.</p>
                <p style="margin-top: 4px;"><strong>2. Cancel Rover Mode</strong>: Press <strong>Button B (Top Red)</strong> at any time to instantly stop wheels and return to Aux Mode.</p>
                <p style="margin-top: 4px;"><strong>3. 30s Inactivity Timeout</strong>: Rover Mode automatically cancels if the thumbstick rests idle for <strong>30 seconds</strong>.</p>
            </div>
        </div>

    </div>

    <!-- Web Audio Chime Generator -->
    <script>
        const audioCtx = new (window.AudioContext || window.webkitAudioContext)();

        function playMarioKartChime() {
            const now = audioCtx.currentTime;
            [0, 0.8, 1.6].forEach(delay => {
                const osc = audioCtx.createOscillator();
                const gain = audioCtx.createGain();
                osc.frequency.setValueAtTime(440, now + delay); // A4
                gain.gain.setValueAtTime(0.3, now + delay);
                gain.gain.exponentialRampToValueAtTime(0.001, now + delay + 0.3);
                osc.connect(gain);
                gain.connect(audioCtx.destination);
                osc.start(now + delay);
                osc.stop(now + delay + 0.35);
            });

            // Final Go Tone
            const oscGo = audioCtx.createOscillator();
            const gainGo = audioCtx.createGain();
            oscGo.frequency.setValueAtTime(880, now + 2.4); // A5
            gainGo.gain.setValueAtTime(0.4, now + 2.4);
            gainGo.gain.exponentialRampToValueAtTime(0.001, now + 2.4 + 0.8);
            oscGo.connect(gainGo);
            gainGo.connect(audioCtx.destination);
            oscGo.start(now + 2.4);
            oscGo.stop(now + 2.4 + 0.85);
        }

        function playExitChime() {
            const now = audioCtx.currentTime;
            const osc = audioCtx.createOscillator();
            const gain = audioCtx.createGain();
            osc.frequency.setValueAtTime(600, now);
            osc.frequency.exponentialRampToValueAtTime(300, now + 0.25);
            gain.gain.setValueAtTime(0.3, now);
            gain.gain.exponentialRampToValueAtTime(0.001, now + 0.25);
            osc.connect(gain);
            gain.connect(audioCtx.destination);
            osc.start(now);
            osc.stop(now + 0.3);
        }

        // Joystick Interaction State
        let inputState = { btnStick: false, btnTop: false, x: 0.0, y: 0.0 };
        const joyZone = document.getElementById('joyZone');
        const joyKnob = document.getElementById('joyKnob');
        const circle = document.querySelector('.progress-ring__circle');
        const radius = circle.r.baseVal.value;
        const circumference = radius * 2 * Math.PI;
        circle.style.strokeDasharray = `${circumference} ${circumference}`;

        let isDragging = false;
        let joyRect = null;

        function updateJoyPosition(clientX, clientY) {
            if (!joyRect) joyRect = joyZone.getBoundingClientRect();
            const centerX = joyRect.left + joyRect.width / 2;
            const centerY = joyRect.top + joyRect.height / 2;
            const maxR = joyRect.width / 2 - 30;

            let dx = clientX - centerX;
            let dy = clientY - centerY;
            const dist = Math.sqrt(dx * dx + dy * dy);

            if (dist > maxR) {
                dx = (dx / dist) * maxR;
                dy = (dy / dist) * maxR;
            }

            joyKnob.style.transform = `translate(${dx}px, ${dy}px)`;
            inputState.x = parseFloat((dx / maxR).toFixed(3));
            inputState.y = parseFloat((-dy / maxR).toFixed(3));

            document.getElementById('valX').textContent = inputState.x.toFixed(2);
            document.getElementById('valY').textContent = inputState.y.toFixed(2);
        }

        joyZone.addEventListener('pointerdown', (e) => {
            isDragging = true;
            joyRect = joyZone.getBoundingClientRect();
            updateJoyPosition(e.clientX, e.clientY);
        });

        window.addEventListener('pointermove', (e) => {
            if (isDragging) updateJoyPosition(e.clientX, e.clientY);
        });

        window.addEventListener('pointerup', () => {
            if (isDragging) {
                isDragging = false;
                joyKnob.style.transform = `translate(0px, 0px)`;
                inputState.x = 0.0;
                inputState.y = 0.0;
                document.getElementById('valX').textContent = '0.00';
                document.getElementById('valY').textContent = '0.00';
            }
        });

        // Button A (Hold with pointer capture)
        const btnStick = document.getElementById('btnStick');
        btnStick.addEventListener('pointerdown', (e) => {
            e.preventDefault();
            try { btnStick.setPointerCapture(e.pointerId); } catch(err){}
            inputState.btnStick = true;
            btnStick.classList.add('held');
        });
        btnStick.addEventListener('pointerup', (e) => {
            e.preventDefault();
            try { btnStick.releasePointerCapture(e.pointerId); } catch(err){}
            inputState.btnStick = false;
            btnStick.classList.remove('held');
        });
        btnStick.addEventListener('pointercancel', (e) => {
            inputState.btnStick = false;
            btnStick.classList.remove('held');
        });

        // Button B (Top Red)
        const btnTop = document.getElementById('btnTop');
        btnTop.addEventListener('pointerdown', (e) => {
            e.preventDefault();
            try { btnTop.setPointerCapture(e.pointerId); } catch(err){}
            inputState.btnTop = true;
            btnTop.classList.add('held');
        });
        btnTop.addEventListener('pointerup', (e) => {
            e.preventDefault();
            try { btnTop.releasePointerCapture(e.pointerId); } catch(err){}
            inputState.btnTop = false;
            btnTop.classList.remove('held');
        });
        btnTop.addEventListener('pointercancel', (e) => {
            inputState.btnTop = false;
            btnTop.classList.remove('held');
        });

        // Sync loop with backend (30 Hz)
        let lastAudioSeq = 0;
        setInterval(async () => {
            try {
                const hasVirtual = isDragging || inputState.btnStick || inputState.btnTop;
                const payload = hasVirtual ? {
                    virtual_active: true,
                    btnStick: inputState.btnStick,
                    btnTop: inputState.btnTop,
                    x: inputState.x,
                    y: inputState.y
                } : {};
                const res = await fetch('/api/sim/tick', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const data = await res.json();

                // Update BLE Status
                const bleBar = document.getElementById('bleStatus');
                const bleText = document.getElementById('bleText');
                if (data.ble_connected) {
                    bleBar.className = 'ble-status-bar connected';
                    bleBar.firstElementChild.textContent = '🟢';
                    bleText.textContent = `Physical Poké Ball Connected: ${data.ble_name}`;
                } else {
                    bleBar.className = 'ble-status-bar';
                    bleBar.firstElementChild.textContent = '⚪';
                    bleText.textContent = data.ble_name || 'Scanning for physical Poké Ball Plus...';
                }

                // Update Mode Badge
                const badge = document.getElementById('modeBadge');
                if (data.mode === 'ROVER') {
                    if (!data.rover_ready) {
                        badge.textContent = `⏳ COUNTDOWN (${data.ready_countdown.toFixed(1)}s Delay)`;
                        badge.className = 'mode-badge rover';
                    } else {
                        const remain = Math.max(0, 30 - data.inactivity_seconds);
                        badge.textContent = `🏎️ ROVER MODE (${remain.toFixed(0)}s Timeout)`;
                        badge.className = 'mode-badge rover';
                    }
                } else {
                    badge.textContent = '🦾 AUX MODE';
                    badge.className = 'mode-badge aux';
                }

                // If physical controller active and not dragging, update virtual knob
                if (!isDragging && data.norm_x !== undefined && data.norm_y !== undefined) {
                    const maxR = 80;
                    joyKnob.style.transform = `translate(${data.norm_x * maxR}px, ${-data.norm_y * maxR}px)`;
                    document.getElementById('valX').textContent = data.norm_x.toFixed(2);
                    document.getElementById('valY').textContent = data.norm_y.toFixed(2);
                }

                // Update Hold Ring
                const offset = circumference - (data.hold_progress * circumference);
                circle.style.strokeDashoffset = offset;

                // Update PWM Gauges
                document.getElementById('leftPulse').textContent = `${data.left_pulse} µs`;
                document.getElementById('rightPulse').textContent = `${data.right_pulse} µs`;
                document.getElementById('cmdStr').textContent = data.cmd;

                // Update Meters (1500 center)
                const leftDev = ((data.left_pulse - 1500) / 500) * 50;
                const leftFill = document.getElementById('leftFill');
                if (leftDev >= 0) {
                    leftFill.style.left = '50%';
                    leftFill.style.width = `${leftDev}%`;
                } else {
                    leftFill.style.left = `${50 + leftDev}%`;
                    leftFill.style.width = `${-leftDev}%`;
                }

                const rightDev = ((data.right_pulse - 1500) / 500) * 50;
                const rightFill = document.getElementById('rightFill');
                if (rightDev >= 0) {
                    rightFill.style.left = '50%';
                    rightFill.style.width = `${rightDev}%`;
                } else {
                    rightFill.style.left = `${50 + rightDev}%`;
                    rightFill.style.width = `${-rightDev}%`;
                }

                // Audio Event Trigger from Server
                if (data.audio_seq > lastAudioSeq) {
                    lastAudioSeq = data.audio_seq;
                    if (data.latest_audio === 'mario_kart_start') {
                        document.getElementById('audioTag').textContent = '🎵 Mario Kart Start';
                        playMarioKartChime();
                    } else if (data.latest_audio === 'disconnect') {
                        document.getElementById('audioTag').textContent = '🔔 Aux Mode Active';
                        playExitChime();
                    }
                }
            } catch (err) {
                console.error("Sync error:", err);
            }
        }, 33);
    </script>
</body>
</html>
"""


class SimServerHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/" or self.path.startswith("/index"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(HTML_PAGE.encode("utf-8"))
        elif self.path == "/api/sim/telemetry":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            with sim_lock:
                telem = app_instance.telemetry.copy()
                telem["left_pulse"] = rover_ctrl._last_left_pulse
                telem["right_pulse"] = rover_ctrl._last_right_pulse
                telem["cmd"] = rover_ctrl._last_cmd_sent.strip()
                telem["latest_audio"] = latest_event_audio
                telem["audio_seq"] = audio_event_seq
                telem["ble_connected"] = ble_state["connected"]
                telem["ble_name"] = ble_state["device_name"]
            self.wfile.write(json.dumps(telem).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        global latest_event_audio, audio_event_seq
        if self.path == "/api/sim/tick":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
            try:
                inp = json.loads(body)
            except Exception:
                inp = {}

            # ONLY inject virtual packets if user is actively clicking/dragging on screen
            if inp.get("virtual_active"):
                btn_stick = bool(inp.get("btnStick", False))
                btn_top = bool(inp.get("btnTop", False))
                x_val = float(inp.get("x", 0.0))
                y_val = float(inp.get("y", 0.0))
                pkt = generate_packet_bytes(btn_stick, btn_top, x_val, y_val)
                app_instance.notification_handler("web_virtual", pkt)

            # Return latest telemetry snapshot
            with sim_lock:
                telem = app_instance.telemetry.copy()
                resp = {
                    "mode": app_instance.control_mode,
                    "hold_progress": telem.get("hold_progress", 0.0),
                    "rover_ready": telem.get("rover_ready", False),
                    "ready_countdown": telem.get("ready_countdown", 0.0),
                    "inactivity_seconds": telem.get("inactivity_seconds", 0.0),
                    "left_pulse": rover_ctrl._last_left_pulse,
                    "right_pulse": rover_ctrl._last_right_pulse,
                    "norm_x": telem.get("norm_x", 0.0),
                    "norm_y": telem.get("norm_y", 0.0),
                    "cmd": rover_ctrl._last_cmd_sent.strip(),
                    "latest_audio": latest_event_audio,
                    "audio_seq": audio_event_seq,
                    "ble_connected": ble_state["connected"],
                    "ble_name": ble_state["device_name"]
                }
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(resp).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass



def main():
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("0.0.0.0", PORT), SimServerHandler)
    print("\n" + "=" * 80)
    print(f"[SIMULATOR RUNNING] POKE BALL & ROVER PWM INTERACTIVE SIMULATOR")
    print(f"--> Open your browser to: http://localhost:{PORT}")
    print("=" * 80 + "\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down simulator...")
    finally:
        rover_ctrl.shutdown()
        httpd.shutdown()


if __name__ == "__main__":
    main()
