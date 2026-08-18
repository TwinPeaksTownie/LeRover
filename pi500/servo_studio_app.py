#!/usr/bin/env python3
"""ServoStudioApp module for SO-101 arm calibration.
Encapsulates complete pi_servo_studio web UI into a managed BaseApp interface running on port 8086.
"""

import json
import logging
import math
import os
import signal
import sys
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Dict, Any, Optional
from urllib.parse import parse_qs, urlparse

from app_manager import BaseApp, AppMetadata
from robot_backend import RobotBackend, SERIAL_LOCK

PORT_WEB = 8086
CALIB_PATH = str(Path.home() / ".cache/huggingface/lerobot/calibration/robots/so_follower/follower.json")

MOTORS = {
    1: "shoulder_pan",
    2: "shoulder_lift",
    3: "elbow_flex",
    4: "wrist_flex",
    5: "wrist_roll",
    6: "gripper",
}

MOTOR_LABELS = {
    1: "Shoulder Pan",
    2: "Shoulder Lift",
    3: "Elbow Flex",
    4: "Wrist Flex",
    5: "Wrist Roll",
    6: "Gripper",
}

HTML_DASHBOARD = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>SO-101 Native Pi 500 Servo Studio</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-color: #0b0f19;
            --card-bg: #151d2a;
            --card-border: #232f45;
            --accent-blue: #38bdf8;
            --accent-purple: #818cf8;
            --accent-green: #22c55e;
            --accent-amber: #f59e0b;
            --accent-red: #ef4444;
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
            --text-dim: #64748b;
        }
        * { box-sizing: border-box; }
        body {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            background-color: var(--bg-color);
            background-image: radial-gradient(circle at 50% 0%, #1e293b 0%, var(--bg-color) 75%);
            color: var(--text-main);
            margin: 0;
            padding: 24px;
            min-height: 100vh;
        }
        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding-bottom: 20px;
            border-bottom: 1px solid var(--card-border);
            margin-bottom: 24px;
        }
        .header-title-box h1 { margin: 0; font-size: 1.6rem; font-weight: 800; color: var(--accent-blue); letter-spacing: -0.02em; }
        .header-title-box p { margin: 4px 0 0 0; color: var(--text-muted); font-size: 0.85rem; }
        .pill-container { display: flex; gap: 10px; }
        .pill {
            padding: 8px 16px;
            border-radius: 9999px;
            font-size: 0.82rem;
            font-weight: 700;
            background: var(--card-bg);
            border: 1px solid var(--card-border);
            display: flex;
            align-items: center;
            gap: 6px;
        }
        .pill.online { background: rgba(34, 197, 94, 0.15); color: var(--accent-green); border-color: rgba(34, 197, 94, 0.4); }
        .pill.offline { background: rgba(239, 68, 68, 0.15); color: var(--accent-red); border-color: rgba(239, 68, 68, 0.4); }
        .controls { display: flex; gap: 12px; margin-bottom: 28px; }
        button {
            padding: 10px 14px;
            border: none;
            border-radius: 8px;
            font-family: 'Inter', sans-serif;
            font-size: 0.82rem;
            font-weight: 700;
            cursor: pointer;
            transition: all 0.15s ease-in-out;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 6px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.2);
            text-align: center;
        }
        button:active { transform: translateY(1px); }
        .btn-danger { background: #dc2626; color: white; padding: 12px 20px; font-size: 0.88rem; }
        .btn-danger:hover { background: #b91c1c; box-shadow: 0 0 12px rgba(239, 68, 68, 0.4); }
        .btn-safe { background: #16a34a; color: white; padding: 12px 20px; font-size: 0.88rem; }
        .btn-safe:hover { background: #15803d; box-shadow: 0 0 12px rgba(34, 197, 94, 0.4); }
        .btn-lock { background: #0284c7; color: white; padding: 12px 20px; font-size: 0.88rem; }
        .btn-lock:hover { background: #0369a1; box-shadow: 0 0 12px rgba(56, 189, 248, 0.4); }
        .btn-secondary { background: var(--card-bg); color: var(--text-main); border: 1px solid var(--card-border); }
        .btn-secondary:hover { background: #1e293b; border-color: var(--accent-blue); }
        .btn-active { background: var(--accent-blue); color: #090d16; }
        
        .btn-calib { background: rgba(245, 158, 11, 0.15); color: var(--accent-amber); border: 1px solid rgba(245, 158, 11, 0.4); }
        .btn-calib:hover { background: rgba(245, 158, 11, 0.3); box-shadow: 0 0 8px rgba(245, 158, 11, 0.3); }
        .btn-home { background: rgba(34, 197, 94, 0.15); color: var(--accent-green); border: 1px solid rgba(34, 197, 94, 0.4); }
        .btn-home:hover { background: rgba(34, 197, 94, 0.3); box-shadow: 0 0 8px rgba(34, 197, 94, 0.3); }
        .btn-mode { background: rgba(129, 140, 248, 0.15); color: var(--accent-purple); border: 1px solid rgba(129, 140, 248, 0.4); }
        .btn-mode:hover { background: rgba(129, 140, 248, 0.3); box-shadow: 0 0 8px rgba(129, 140, 248, 0.3); }
        .btn-mvhome { background: rgba(34, 197, 94, 0.15); color: var(--accent-green); border: 1px solid rgba(34, 197, 94, 0.4); }
        .btn-mvhome:hover { background: rgba(34, 197, 94, 0.3); box-shadow: 0 0 8px rgba(34, 197, 94, 0.3); }
        .btn-hold { background: rgba(56, 189, 248, 0.15); color: var(--accent-blue); border: 1px solid rgba(56, 189, 248, 0.4); }
        .btn-hold:hover { background: rgba(56, 189, 248, 0.3); box-shadow: 0 0 8px rgba(56, 189, 248, 0.3); }

        .btn-flash-success {
            background: #22c55e !important;
            color: #0b0f19 !important;
            box-shadow: 0 0 16px #22c55e !important;
            transform: scale(1.05);
        }

        .cards-grid {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 20px;
        }
        @media (max-width: 1300px) {
            .cards-grid {
                grid-template-columns: repeat(2, 1fr);
            }
        }
        @media (max-width: 800px) {
            .cards-grid {
                grid-template-columns: 1fr;
            }
        }

        .card {
            background: var(--card-bg);
            border-radius: 12px;
            padding: 20px;
            border: 1px solid var(--card-border);
            box-shadow: 0 8px 16px -4px rgba(0, 0, 0, 0.4);
            transition: all 0.2s ease-in-out;
            position: relative;
            overflow: hidden;
        }
        .card.active { border-color: var(--accent-blue); box-shadow: 0 0 20px rgba(56, 189, 248, 0.2); }
        .card-header {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            margin-bottom: 16px;
        }
        .motor-num { font-size: 0.75rem; font-weight: 800; text-transform: uppercase; color: var(--accent-blue); letter-spacing: 0.05em; }
        .card-title { font-weight: 700; font-size: 1.15rem; color: var(--text-main); margin-top: 2px; }
        
        .posture-banner {
            background: rgba(56, 189, 248, 0.08);
            border: 1px solid rgba(56, 189, 248, 0.2);
            border-radius: 8px;
            padding: 10px 14px;
            margin-bottom: 16px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .posture-text { font-weight: 700; font-size: 0.95rem; color: var(--accent-blue); }
        .badge {
            font-size: 0.72rem;
            font-weight: 800;
            padding: 4px 8px;
            border-radius: 4px;
            text-transform: uppercase;
            letter-spacing: 0.04em;
        }
        .badge-home { background: rgba(34, 197, 94, 0.2); color: var(--accent-green); border: 1px solid var(--accent-green); }
        .badge-warn { background: rgba(245, 158, 11, 0.2); color: var(--accent-amber); border: 1px solid var(--accent-amber); }
        .badge-active { background: rgba(56, 189, 248, 0.2); color: var(--accent-blue); border: 1px solid var(--accent-blue); }

        .rom-container { margin-bottom: 18px; }
        .rom-header { display: flex; justify-content: space-between; font-size: 0.8rem; color: var(--text-muted); margin-bottom: 6px; font-weight: 600; }
        .rom-track {
            height: 12px;
            background: #0f172a;
            border-radius: 6px;
            position: relative;
            overflow: hidden;
            border: 1px solid var(--card-border);
        }
        .rom-fill {
            height: 100%;
            background: linear-gradient(90deg, #0284c7 0%, var(--accent-blue) 100%);
            border-radius: 6px;
            transition: width 0.1s linear;
        }
        .rom-home-marker {
            position: absolute;
            top: 0;
            bottom: 0;
            width: 3px;
            background: var(--accent-green);
            box-shadow: 0 0 4px var(--accent-green);
            z-index: 2;
        }

        .metric-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 10px;
            margin-bottom: 16px;
        }
        .metric-box {
            background: rgba(15, 23, 42, 0.5);
            border: 1px solid rgba(255, 255, 255, 0.05);
            border-radius: 8px;
            padding: 10px 12px;
        }
        .metric-lbl { font-size: 0.75rem; color: var(--text-dim); text-transform: uppercase; font-weight: 600; }
        .metric-val { font-size: 1rem; font-weight: 700; color: var(--text-main); margin-top: 2px; font-family: monospace; }

        .calib-actions {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 8px;
            margin-top: 14px;
            padding-top: 14px;
            border-top: 1px dashed var(--card-border);
        }
        
        .toast {
            position: fixed;
            bottom: 24px;
            right: 24px;
            background: var(--card-bg);
            border: 1px solid var(--accent-amber);
            color: var(--accent-amber);
            padding: 14px 20px;
            border-radius: 8px;
            font-weight: 700;
            font-size: 0.9rem;
            box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.5);
            z-index: 999;
            display: none;
        }

        .slider-section { margin-top: 14px; padding-top: 14px; border-top: 1px dashed var(--card-border); }
        .slider-header { display: flex; justify-content: space-between; font-size: 0.82rem; font-weight: 700; color: var(--accent-blue); margin-bottom: 8px; }
        input[type=range] {
            width: 100%;
            accent-color: var(--accent-blue);
            cursor: pointer;
        }
    </style>
</head>
<body>
    <header>
        <div class="header-title-box">
            <h1>SO-100 / SO-101 Servo Studio</h1>
            <p>Direct Hardware Telemetry & Interactive Calibration Studio (Feetech STS3215 @ 1 Mbps)</p>
        </div>
        <div class="pill-container">
            <div id="pill-hw" class="pill online">🟢 HARDWARE: SERIAL PORT LIVE</div>
            <div id="pill-telemetry" class="pill online">🟢 STREAM: 50Hz LIVE</div>
            <div id="pill-torque" class="pill offline">🔴 TORQUE: RELAXED</div>
        </div>
    </header>

    <div class="controls">
        <button class="btn-danger" onclick="emergencyStop()">🛑 Emergency Torque Off</button>
        <button id="btn-home-all" class="btn-home" style="padding: 12px 20px; font-size: 0.88rem; font-weight: 800;" onclick="captureHomeAll()">⚡ Quick Capture Home All</button>
        <button class="btn-lock" onclick="lockCurrentPose()">🔒 Lock Current Pose (30% Torque)</button>
        <button class="btn-safe" onclick="safeHome()">🏠 Safe Home All (30% Torque)</button>
        <button class="btn-secondary" onclick="deselectServo()">🔓 Deselect Active Joint</button>
    </div>

    <div class="cards-grid" id="cards"></div>
    <div id="toast" class="toast"></div>

    <script>
        let currentState = null;
        let isCapturing = false;

        function showToast(msg) {
            const t = document.getElementById('toast');
            t.innerText = msg;
            t.style.display = 'block';
            setTimeout(() => { t.style.display = 'none'; }, 4000);
        }

        function flashButton(btnId) {
            const btn = document.getElementById(btnId);
            if (!btn) return;
            btn.classList.add('btn-flash-success');
            setTimeout(() => { btn.classList.remove('btn-flash-success'); }, 1500);
        }

        async function fetchState() {
            if (isCapturing) return;
            try {
                const res = await fetch('/api/state');
                const data = await res.json();
                currentState = data;
                render(data);
            } catch (e) {
                document.getElementById('pill-telemetry').className = 'pill offline';
                document.getElementById('pill-telemetry').innerText = '🔴 STREAM: OFFLINE';
            }
        }

        function render(data) {
            const torquePill = document.getElementById('pill-torque');
            if (data.torque_enabled) {
                torquePill.className = 'pill online';
                torquePill.innerText = '🟢 TORQUE: ENABLED (SAFE 30%)';
            } else {
                torquePill.className = 'pill offline';
                torquePill.innerText = '🔴 TORQUE: RELAXED (OFF)';
            }

            const cardsDiv = document.getElementById('cards');

            for (let sid in data.joints) {
                const j = data.joints[sid];
                const isActive = (data.active_servo == parseInt(sid));
                let card = document.getElementById(`card-${sid}`);
                
                // Build card shell ONCE to preserve button DOM nodes during 100ms polling
                if (!card || card.dataset.active !== String(isActive)) {
                    if (!card) {
                        card = document.createElement('div');
                        card.id = `card-${sid}`;
                        cardsDiv.appendChild(card);
                    }
                    card.dataset.active = String(isActive);
                    card.className = `card ${isActive ? 'active' : ''}`;

                    card.innerHTML = `
                        <div class="card-header">
                            <div>
                                <div class="motor-num">Motor ${sid} • Feetech STS3215</div>
                                <div class="card-title">${j.label}</div>
                            </div>
                            <button id="btn-select-${sid}" class="${isActive ? 'btn-active' : 'btn-secondary'}" onclick="setActive(${sid})">
                                ${isActive ? 'Selected' : 'Test Joint'}
                            </button>
                        </div>

                        <div class="posture-banner">
                            <span id="posture-text-${sid}" class="posture-text">📍 ${j.posture_desc}</span>
                            <span id="badge-box-${sid}"></span>
                        </div>

                        <div class="rom-container">
                            <div class="rom-header">
                                <span>ROM Utilization</span>
                                <span id="rom-label-${sid}">${j.range_pct}% (${j.follower_raw} Ticks)</span>
                            </div>
                            <div class="rom-track">
                                <div id="rom-fill-${sid}" class="rom-fill" style="width: ${j.range_pct}%;"></div>
                                <div id="rom-home-${sid}" class="rom-home-marker" style="left: ${j.home_pct}%;" title="Home Target (${j.home_tick})"></div>
                            </div>
                        </div>

                        <div class="metric-grid">
                            <div class="metric-box">
                                <div class="metric-lbl">Raw Position</div>
                                <div id="val-raw-${sid}" class="metric-val">${j.follower_raw} <small style="font-size:0.75rem; color:var(--text-dim);">ticks</small></div>
                            </div>
                            <div class="metric-box">
                                <div class="metric-lbl">Distance to Home</div>
                                <div id="val-dist-${sid}" class="metric-val">${j.dist_home} <small style="font-size:0.75rem; color:var(--text-dim);">ticks</small></div>
                            </div>
                            <div class="metric-box">
                                <div class="metric-lbl">Home Target</div>
                                <div id="val-home-${sid}" class="metric-val">${j.home_tick} <small style="font-size:0.75rem; color:var(--text-dim);">ticks</small></div>
                            </div>
                            <div class="metric-box">
                                <div class="metric-lbl">ROM Bounds</div>
                                <div id="val-bounds-${sid}" class="metric-val">[${j.range_min}, ${j.range_max}]</div>
                            </div>
                        </div>

                        <div class="calib-actions">
                            <button id="btn-min-${sid}" class="btn-calib" onclick="captureMin(${sid})">📍 Capture Min (<span id="lbl-min-${sid}">${j.follower_raw}</span>)</button>
                            <button id="btn-home-${sid}" class="btn-home" onclick="captureHome(${sid})">🏠 Capture Home (<span id="lbl-home-${sid}">${j.follower_raw}</span>)</button>
                            <button id="btn-max-${sid}" class="btn-calib" onclick="captureMax(${sid})">📍 Capture Max (<span id="lbl-max-${sid}">${j.follower_raw}</span>)</button>
                            
                            <button id="btn-mode-${sid}" class="btn-mode" onclick="toggleDriveMode(${sid})">🔄 Sign: ${j.drive_mode == 1 ? 'Inverted (1)' : 'Normal (0)'}</button>
                            <button id="btn-mvhome-${sid}" class="btn-mvhome" onclick="moveToHome(${sid})">🏠 Move to Home (<span id="lbl-mvhome-${sid}">${j.home_tick}</span>)</button>
                            <button id="btn-hold-${sid}" class="btn-hold" onclick="hold2048(${sid})">🎯 Move to 2048 (Lock Rest)</button>
                        </div>

                        ${isActive ? `
                            <div class="slider-section">
                                <div class="slider-header">
                                    <span>🎛️ Interactive Position Control</span>
                                    <span>Target: <span id="slider-val-${sid}">${j.follower_raw}</span> Ticks</span>
                                </div>
                                <input type="range" min="${j.range_min}" max="${j.range_max}" value="${j.follower_raw}" 
                                    oninput="document.getElementById('slider-val-${sid}').innerText = this.value; setGoal(${sid}, this.value)">
                            </div>
                        ` : ''}
                    `;
                }

                // Targeted fine-grained DOM updates
                let badgeHtml = '';
                if (isActive) badgeHtml = `<span class="badge badge-active">Active Testing</span>`;
                else if (j.at_home) badgeHtml = `<span class="badge badge-home">At Home Target</span>`;
                else if (j.warning) badgeHtml = `<span class="badge badge-warn">${j.warning}</span>`;

                const postureEl = document.getElementById(`posture-text-${sid}`);
                if (postureEl) postureEl.innerText = `📍 ${j.posture_desc}`;
                
                const badgeBox = document.getElementById(`badge-box-${sid}`);
                if (badgeBox) badgeBox.innerHTML = badgeHtml;

                const romLabel = document.getElementById(`rom-label-${sid}`);
                if (romLabel) romLabel.innerText = `${j.range_pct}% (${j.follower_raw} Ticks)`;

                const romFill = document.getElementById(`rom-fill-${sid}`);
                if (romFill) romFill.style.width = `${j.range_pct}%`;

                const romHome = document.getElementById(`rom-home-${sid}`);
                if (romHome) {
                    romHome.style.left = `${j.home_pct}%`;
                    romHome.title = `Home Target (${j.home_tick})`;
                }

                const rawVal = document.getElementById(`val-raw-${sid}`);
                if (rawVal) rawVal.innerHTML = `${j.follower_raw} <small style="font-size:0.75rem; color:var(--text-dim);">ticks</small>`;

                const distVal = document.getElementById(`val-dist-${sid}`);
                if (distVal) distVal.innerHTML = `${j.dist_home} <small style="font-size:0.75rem; color:var(--text-dim);">ticks</small>`;

                const homeVal = document.getElementById(`val-home-${sid}`);
                if (homeVal) homeVal.innerHTML = `${j.home_tick} <small style="font-size:0.75rem; color:var(--text-dim);">ticks</small>`;

                const boundsVal = document.getElementById(`val-bounds-${sid}`);
                if (boundsVal) boundsVal.innerHTML = `[${j.range_min}, ${j.range_max}]`;

                const lblMin = document.getElementById(`lbl-min-${sid}`);
                if (lblMin) lblMin.innerText = j.follower_raw;

                const lblHome = document.getElementById(`lbl-home-${sid}`);
                if (lblHome) lblHome.innerText = j.follower_raw;

                const lblMax = document.getElementById(`lbl-max-${sid}`);
                if (lblMax) lblMax.innerText = j.follower_raw;

                const lblMvHome = document.getElementById(`lbl-mvhome-${sid}`);
                if (lblMvHome) lblMvHome.innerText = j.home_tick;
            }
        }

        async function captureMin(sid) {
            isCapturing = true;
            flashButton(`btn-min-${sid}`);
            try {
                const res = await fetch(`/api/capture_min?sid=${sid}`);
                const data = await res.json();
                if (data.status === 'ok') {
                    showToast(`✅ Motor ${sid} range_min updated to ${data.range_min} ticks & saved to follower.json!`);
                    isCapturing = false;
                    await fetchState();
                } else {
                    showToast(`❌ Error: ${data.error}`);
                }
            } finally {
                isCapturing = false;
            }
        }

        async function captureMax(sid) {
            isCapturing = true;
            flashButton(`btn-max-${sid}`);
            try {
                const res = await fetch(`/api/capture_max?sid=${sid}`);
                const data = await res.json();
                if (data.status === 'ok') {
                    showToast(`✅ Motor ${sid} range_max updated to ${data.range_max} ticks & saved to follower.json!`);
                    isCapturing = false;
                    await fetchState();
                } else {
                    showToast(`❌ Error: ${data.error}`);
                }
            } finally {
                isCapturing = false;
            }
        }

        async function captureHome(sid) {
            isCapturing = true;
            flashButton(`btn-home-${sid}`);
            try {
                const res = await fetch(`/api/capture_home?sid=${sid}`);
                const data = await res.json();
                if (data.status === 'ok') {
                    showToast(`🏠 Motor ${sid} home target set to ${data.home_tick} ticks (offset: ${data.homing_offset}) & saved to follower.json!`);
                    isCapturing = false;
                    await fetchState();
                } else {
                    showToast(`❌ Error: ${data.error}`);
                }
            } finally {
                isCapturing = false;
            }
        }

        async function captureHomeAll() {
            isCapturing = true;
            flashButton('btn-home-all');
            try {
                const res = await fetch('/api/capture_home_all');
                const data = await res.json();
                if (data.status === 'ok') {
                    showToast(`⚡ QUICK CAPTURED HOME ALL: Live positions captured across all 6 motors & saved to follower.json!`);
                    isCapturing = false;
                    await fetchState();
                } else {
                    showToast(`❌ Error: ${data.error}`);
                }
            } finally {
                isCapturing = false;
            }
        }

        async function toggleDriveMode(sid) {
            isCapturing = true;
            flashButton(`btn-mode-${sid}`);
            try {
                const res = await fetch(`/api/toggle_drive_mode?sid=${sid}`);
                const data = await res.json();
                if (data.status === 'ok') {
                    showToast(`🔄 Motor ${sid} drive_mode set to ${data.drive_mode} & saved to follower.json!`);
                    isCapturing = false;
                    await fetchState();
                } else {
                    showToast(`❌ Error: ${data.error}`);
                }
            } finally {
                isCapturing = false;
            }
        }

        async function hold2048(sid) {
            isCapturing = true;
            flashButton(`btn-hold-${sid}`);
            try {
                const res = await fetch(`/api/hold_2048?sid=${sid}`);
                const data = await res.json();
                if (data.status === 'ok') {
                    showToast(`🎯 Motor ${sid} moving to 2048 (${data.duration}s trajectory) while rest hold pose!`);
                    isCapturing = false;
                    await fetchState();
                } else {
                    showToast(`❌ Error: ${data.error}`);
                }
            } finally {
                isCapturing = false;
            }
        }

        async function moveToHome(sid) {
            isCapturing = true;
            flashButton(`btn-mvhome-${sid}`);
            try {
                const res = await fetch(`/api/move_to_home?sid=${sid}`);
                const data = await res.json();
                if (data.status === 'ok') {
                    showToast(`🏠 Motor ${sid} moving to custom home (${data.home_tick} ticks, ${data.duration}s trajectory) while rest hold pose!`);
                    isCapturing = false;
                    await fetchState();
                } else {
                    showToast(`❌ Error: ${data.error}`);
                }
            } finally {
                isCapturing = false;
            }
        }

        async function lockCurrentPose() {
            isCapturing = true;
            try {
                const res = await fetch('/api/lock_current_pose');
                const data = await res.json();
                if (data.status === 'ok') {
                    showToast(`🔒 Locked all 6 servos at their current live physical positions under 30% torque!`);
                    isCapturing = false;
                    await fetchState();
                } else {
                    showToast(`❌ Error: ${data.error}`);
                }
            } finally {
                isCapturing = false;
            }
        }

        async function setActive(sid) {
            await fetch(`/api/set_active?sid=${sid}`);
            fetchState();
        }

        async function deselectServo() {
            await fetch('/api/set_active?sid=0');
            fetchState();
        }

        async function emergencyStop() {
            await fetch('/api/emergency_stop');
            fetchState();
        }

        async function safeHome() {
            await fetch('/api/safe_home');
            fetchState();
        }

        async function setGoal(sid, val) {
            await fetch(`/api/set_goal?sid=${sid}&goal=${val}`);
        }

        setInterval(fetchState, 100);
        fetchState();
    </script>
</body>
</html>
"""

class ThreadedHTTPServer(HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class StudioHandler(BaseHTTPRequestHandler):
    backend: Optional[RobotBackend] = None
    app_instance: Optional["ServoStudioApp"] = None

    def _send_json(self, data: Dict[str, Any], code: int = 200) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _handle_request(self, method: str) -> None:
        parsed = urlparse(self.path)
        if method == "GET" and parsed.path in ["/", "/index.html"]:
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            html_content = self.app_instance.get_studio_html() if self.app_instance else "<h1>Servo Studio</h1>"
            self.wfile.write(html_content.encode("utf-8"))
            return

        if not self.backend or not self.app_instance:
            return self._send_json({"error": "Uninitialized components"}, 500)

        if parsed.path in ["/api/state", "/api/status"]:
            return self._send_json(self.app_instance.get_full_state())

        qs = parse_qs(parsed.query)
        body = {}
        if method == "POST":
            content_length = int(self.headers.get("Content-Length", 0))
            body_bytes = self.rfile.read(content_length) if content_length > 0 else b"{}"
            try:
                body = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
            except Exception:
                body = {}

        sid = int(body.get("sid", qs.get("sid", [0])[0]))

        if parsed.path == "/api/set_active":
            self.app_instance.active_servo = sid if sid in range(1, 7) else None
            self._send_json({"status": "ok", "active_servo": self.app_instance.active_servo})
        elif parsed.path == "/api/capture_min":
            self._send_json(self.app_instance.capture_min(sid))
        elif parsed.path == "/api/capture_max":
            self._send_json(self.app_instance.capture_max(sid))
        elif parsed.path == "/api/capture_home":
            self._send_json(self.app_instance.capture_home(sid))
        elif parsed.path == "/api/capture_home_all":
            self._send_json(self.app_instance.capture_home_all())
        elif parsed.path == "/api/toggle_drive_mode":
            self._send_json(self.app_instance.toggle_drive_mode(sid))
        elif parsed.path == "/api/hold_2048":
            self._send_json(self.app_instance.hold_2048(sid))
        elif parsed.path == "/api/move_to_home":
            self._send_json(self.app_instance.move_to_home(sid))
        elif parsed.path == "/api/lock_current_pose":
            self._send_json(self.app_instance.lock_current_pose())
        elif parsed.path == "/api/emergency_stop":
            self.app_instance.disable_torque()
            self._send_json({"status": "ok", "action": "emergency_stop"})
        elif parsed.path in ["/api/safe_home", "/api/safe_home_all"]:
            self._send_json(self.app_instance.safe_home_all())
        elif parsed.path == "/api/set_goal":
            goal = int(body.get("goal", qs.get("goal", [2048])[0]))
            self._send_json(self.app_instance.write_active_goal(sid, goal))
        else:
            self._send_json({"status": "ok", "service": "servo_studio_app"})

    def do_GET(self) -> None:
        self._handle_request("GET")

    def do_POST(self) -> None:
        self._handle_request("POST")


class ServoStudioApp(BaseApp):
    """Managed Servo Studio Calibration Application."""
    metadata = AppMetadata(
        name="servo_studio_app",
        title="Servo Studio",
        description="Web dashboard for visual joint calibration and torque management",
        version="1.0.0",
        tags=["calibration", "web", "studio"],
        icon="🛠️"
    )

    def __init__(self, port: int = PORT_WEB) -> None:
        super().__init__()
        self.port = port
        self.calib: Dict[str, Any] = {}
        self.server: Optional[ThreadedHTTPServer] = None
        self.active_servo: Optional[int] = None
        self.load_calibration()

    def load_calibration(self) -> None:
        if os.path.exists(CALIB_PATH):
            try:
                with open(CALIB_PATH, "r") as f:
                    self.calib = json.load(f)
                self.logger.info(f"Loaded studio calibration from {CALIB_PATH}")
            except Exception as e:
                self.logger.error(f"Failed to load calibration JSON: {e}")

    def save_calibration(self) -> None:
        try:
            os.makedirs(os.path.dirname(CALIB_PATH), exist_ok=True)
            with open(CALIB_PATH, "w") as f:
                json.dump(self.calib, f, indent=2)
            self.logger.info(f"Saved studio calibration to {CALIB_PATH}")
        except Exception as e:
            self.logger.error(f"Failed to save calibration JSON to {CALIB_PATH}: {e}")

    def get_home_targets(self) -> Dict[int, int]:
        home_targets = {}
        for sid, name in MOTORS.items():
            if name in self.calib:
                info = self.calib[name]
                rmin = info.get("range_min", 0)
                rmax = info.get("range_max", 4095)
                offset = info.get("homing_offset", 0)
                drive_mode = info.get("drive_mode", 0)
                raw_home = (2048 + offset) if drive_mode == 1 else (2048 - offset)
                home_targets[sid] = max(rmin, min(rmax, raw_home))
            else:
                home_targets[sid] = 2048
        return home_targets

    def get_full_state(self) -> Dict[str, Any]:
        if not self.backend:
            return {"hardware_online": False, "error": "Backend uninitialized"}

        raw_ticks = self.backend.read_raw_arm_ticks()
        home_targets = self.get_home_targets()
        
        joints = {}
        for sid, name in MOTORS.items():
            info = self.calib.get(name, {"range_min": 0, "range_max": 4095, "homing_offset": 0, "drive_mode": 0})
            f_raw = raw_ticks.get(sid, raw_ticks.get(str(sid)))
            rmin = info.get("range_min", 0)
            rmax = info.get("range_max", 4095)
            home_t = home_targets.get(sid, 2048)
            span = max(1, rmax - rmin)

            if f_raw is None:
                pct = 0.0
                dist_home = 0
                at_home = False
                f_deg = 0.0
                desc = "🔴 OFFLINE / UNPLUGGED"
                warning = "DISCONNECTED"
                home_pct = 50.0
            else:
                pct = round(max(0.0, min(100.0, ((f_raw - rmin) / span) * 100.0)), 1)
                home_pct = round(max(0.0, min(100.0, ((home_t - rmin) / span) * 100.0)), 1)
                dist_home = abs(f_raw - home_t)
                at_home = dist_home <= 25

                f_deg = (f_raw - 2048) * (360.0 / 4095.0)
                if info.get("drive_mode", 0) == 1:
                    f_deg = -f_deg
                f_deg = round(f_deg, 1)

                if sid == 1:
                    dir_t = "Centered" if abs(f_deg) < 2.0 else ("Rotated Left (CCW)" if f_deg > 0 else "Rotated Right (CW)")
                    desc = f"{dir_t} ({abs(f_deg)}°)"
                elif sid == 2:
                    dir_t = "Pitched Up/Back" if f_deg > 0 else "Pitched Forward/Down"
                    desc = f"{dir_t} ({abs(f_deg)}°)"
                elif sid == 3:
                    dir_t = "Extended Out" if f_deg > 0 else "Flexed Inward"
                    desc = f"{dir_t} ({abs(f_deg)}°)"
                elif sid == 4:
                    dir_t = "Wrist Pitched Up" if f_deg > 0 else "Wrist Pitched Down"
                    desc = f"{dir_t} ({abs(f_deg)}°)"
                elif sid == 5:
                    dir_t = "Wrist Twisted CW" if f_deg > 0 else "Wrist Twisted CCW"
                    desc = f"{dir_t} ({abs(f_deg)}°)"
                elif sid == 6:
                    desc = f"Gripper Jaws {pct}% Open"
                else:
                    desc = f"{f_deg}° Angle"

                near_min = f_raw <= (rmin + int(span * 0.05))
                near_max = f_raw >= (rmax - int(span * 0.05))
                warning = "NEAR MIN HARDSTOP" if near_min else ("NEAR MAX HARDSTOP" if near_max else None)

            joints[str(sid)] = {
                "name": name,
                "label": MOTOR_LABELS.get(sid, name),
                "follower_raw": f_raw if f_raw is not None else "OFFLINE",
                "follower_deg": f_deg,
                "range_min": rmin,
                "range_max": rmax,
                "home_tick": home_t,
                "home_pct": home_pct,
                "range_pct": pct,
                "dist_home": dist_home,
                "at_home": at_home,
                "posture_desc": desc,
                "warning": warning,
                "drive_mode": info.get("drive_mode", 0),
            }

        return {
            "hardware_online": True,
            "port": "/dev/ttyACM0",
            "baud": 1000000,
            "torque_enabled": getattr(self, "_torque_enabled", False),
            "active_servo": self.active_servo,
            "follower_raw": raw_ticks,
            "home_targets": home_targets,
            "joints": joints,
            "calibration": self.calib,
        }

    def capture_min(self, sid: int) -> Dict[str, Any]:
        name = MOTORS.get(sid)
        if not name or name not in self.calib:
            return {"error": f"Invalid motor sid {sid}"}
        if not self.backend:
            return {"error": "Backend offline"}

        raw_ticks = self.backend.read_raw_arm_ticks()
        raw = raw_ticks.get(sid, raw_ticks.get(str(sid)))
        if raw is None:
            return {"error": f"No telemetry for Motor {sid}"}

        self.calib[name]["range_min"] = int(raw)
        self.save_calibration()
        return {"status": "ok", "sid": sid, "range_min": raw}

    def capture_max(self, sid: int) -> Dict[str, Any]:
        name = MOTORS.get(sid)
        if not name or name not in self.calib:
            return {"error": f"Invalid motor sid {sid}"}
        if not self.backend:
            return {"error": "Backend offline"}

        raw_ticks = self.backend.read_raw_arm_ticks()
        raw = raw_ticks.get(sid, raw_ticks.get(str(sid)))
        if raw is None:
            return {"error": f"No telemetry for Motor {sid}"}

        self.calib[name]["range_max"] = int(raw)
        self.save_calibration()
        return {"status": "ok", "sid": sid, "range_max": raw}

    def capture_home(self, sid: int) -> Dict[str, Any]:
        name = MOTORS.get(sid)
        if not name or name not in self.calib:
            return {"error": f"Invalid motor sid {sid}"}
        if not self.backend:
            return {"error": "Backend offline"}

        raw_ticks = self.backend.read_raw_arm_ticks()
        raw = raw_ticks.get(sid, raw_ticks.get(str(sid)))
        if raw is None:
            return {"error": f"No telemetry for Motor {sid}"}

        drive_mode = self.calib[name].get("drive_mode", 0)
        new_offset = (raw - 2048) if drive_mode == 1 else (2048 - raw)
        self.calib[name]["homing_offset"] = new_offset
        self.save_calibration()
        home_targets = self.get_home_targets()
        return {"status": "ok", "sid": sid, "homing_offset": new_offset, "home_tick": home_targets.get(sid, 2048)}

    def capture_home_all(self) -> Dict[str, Any]:
        if not self.backend:
            return {"error": "Backend offline"}
        raw_ticks = self.backend.read_raw_arm_ticks()
        results = {}
        for sid, name in MOTORS.items():
            raw = raw_ticks.get(sid, raw_ticks.get(str(sid)))
            if raw is not None and name in self.calib:
                drive_mode = self.calib[name].get("drive_mode", 0)
                new_offset = (raw - 2048) if drive_mode == 1 else (2048 - raw)
                self.calib[name]["homing_offset"] = new_offset
                results[sid] = {"name": name, "homing_offset": new_offset}

        self.save_calibration()
        return {"status": "ok", "results": results}

    def toggle_drive_mode(self, sid: int) -> Dict[str, Any]:
        name = MOTORS.get(sid)
        if not name or name not in self.calib:
            return {"error": f"Invalid motor sid {sid}"}
        curr_dm = self.calib[name].get("drive_mode", 0)
        new_dm = 1 if curr_dm == 0 else 0
        self.calib[name]["drive_mode"] = new_dm
        self.save_calibration()
        return {"status": "ok", "sid": sid, "drive_mode": new_dm}

    def disable_torque(self) -> None:
        self._torque_enabled = False
        self.active_servo = None
        if self.backend and self.backend.bus:
            with SERIAL_LOCK:
                try:
                    self.backend.bus.disable_torque()
                except Exception as e:
                    self.logger.warning(f"Disable torque warning: {e}")

    def enable_torque(self) -> None:
        self._torque_enabled = True
        if self.backend and self.backend.bus:
            with SERIAL_LOCK:
                try:
                    self.backend.bus.enable_torque()
                except Exception as e:
                    self.logger.warning(f"Enable torque warning: {e}")

    def hold_2048(self, sid: int) -> Dict[str, Any]:
        if not self.backend or not self.backend.bus:
            return {"error": "Hardware offline"}
        if sid not in range(1, 7):
            return {"error": f"Invalid motor sid {sid}"}

        raw_positions = self.backend.read_raw_arm_ticks()
        self.enable_torque()
        self.active_servo = sid
        start_positions = {s: raw_positions.get(s, 2048) for s in range(1, 7)}
        start_p = start_positions.get(sid, 2048)
        target = 2048
        delta = abs(target - start_p)
        duration = max(1.0, min(3.5, delta / 600.0))

        def _worker():
            steps = max(30, int(duration * 40))
            for i in range(1, steps + 1):
                if self.stop_event.is_set():
                    break
                alpha = (1.0 - math.cos(math.pi * (i / steps))) / 2.0
                interp = int(round(start_p + (target - start_p) * alpha))
                goals = {MOTORS[s]: start_positions[s] for s in range(1, 7)}
                goals[MOTORS[sid]] = interp
                with SERIAL_LOCK:
                    try:
                        self.backend.bus.sync_write("Goal_Position", goals, normalize=False)
                    except Exception as e:
                        self.logger.error(f"Hold 2048 trajectory error: {e}")
                        break
                time.sleep(duration / steps)

        threading.Thread(target=_worker, daemon=True).start()
        return {"status": "ok", "sid": sid, "target": target, "duration": round(duration, 2)}

    def move_to_home(self, sid: int) -> Dict[str, Any]:
        if not self.backend or not self.backend.bus:
            return {"error": "Hardware offline"}
        if sid not in range(1, 7):
            return {"error": f"Invalid motor sid {sid}"}

        home_targets = self.get_home_targets()
        target = home_targets.get(sid, 2048)
        raw_positions = self.backend.read_raw_arm_ticks()
        self.enable_torque()
        self.active_servo = sid
        start_positions = {s: raw_positions.get(s, 2048) for s in range(1, 7)}
        start_p = start_positions.get(sid, 2048)
        delta = abs(target - start_p)
        duration = max(1.0, min(3.5, delta / 600.0))

        def _worker():
            steps = max(30, int(duration * 40))
            for i in range(1, steps + 1):
                if self.stop_event.is_set():
                    break
                alpha = (1.0 - math.cos(math.pi * (i / steps))) / 2.0
                interp = int(round(start_p + (target - start_p) * alpha))
                goals = {MOTORS[s]: start_positions[s] for s in range(1, 7)}
                goals[MOTORS[sid]] = interp
                with SERIAL_LOCK:
                    try:
                        self.backend.bus.sync_write("Goal_Position", goals, normalize=False)
                    except Exception as e:
                        self.logger.error(f"Move to home trajectory error: {e}")
                        break
                time.sleep(duration / steps)

        threading.Thread(target=_worker, daemon=True).start()
        return {"status": "ok", "sid": sid, "home_tick": target, "duration": round(duration, 2)}

    def lock_current_pose(self) -> Dict[str, Any]:
        if not self.backend or not self.backend.bus:
            return {"error": "Hardware offline"}

        raw_positions = self.backend.read_raw_arm_ticks()
        self.enable_torque()
        self.active_servo = None
        goals = {}
        for sid, name in MOTORS.items():
            goals[name] = raw_positions.get(sid, 2048)

        with SERIAL_LOCK:
            try:
                self.backend.bus.sync_write("Goal_Position", goals, normalize=False)
            except Exception as e:
                self.logger.error(f"Lock current pose error: {e}")
                return {"error": str(e)}

        return {"status": "ok", "action": "lock_current_pose", "locked_positions": raw_positions}

    def safe_home_all(self) -> Dict[str, Any]:
        if not self.backend or not self.backend.bus:
            return {"error": "Arm hardware offline"}

        raw_positions = self.backend.read_raw_arm_ticks()
        home_targets = self.get_home_targets()
        self.enable_torque()
        self.active_servo = None

        start_positions = {}
        driven = {}
        for sid, name in MOTORS.items():
            if sid in home_targets:
                curr = raw_positions.get(sid)
                start_positions[sid] = curr if curr is not None else home_targets[sid]
                driven[name] = home_targets[sid]

        def _smooth_home_worker():
            num_steps = 50
            step_delay = 0.04
            for step in range(1, num_steps + 1):
                if self.stop_event.is_set():
                    break
                alpha = step / float(num_steps)
                ease = (1.0 - math.cos(alpha * math.pi)) / 2.0
                goal_dict = {}
                for sid, name in MOTORS.items():
                    if sid in start_positions:
                        s_pos = start_positions[sid]
                        t_pos = home_targets[sid]
                        interp_pos = int(round(s_pos + (t_pos - s_pos) * ease))
                        goal_dict[name] = interp_pos
                with SERIAL_LOCK:
                    try:
                        self.backend.bus.sync_write("Goal_Position", goal_dict, normalize=False)
                    except Exception as e:
                        self.logger.error(f"Smooth home trajectory error: {e}")
                        break
                time.sleep(step_delay)

        threading.Thread(target=_smooth_home_worker, daemon=True).start()
        return {"status": "ok", "mode": "smooth_trajectory", "start_positions": start_positions, "home_targets": driven}

    def write_active_goal(self, sid: int, goal: int) -> Dict[str, Any]:
        name = MOTORS.get(sid)
        if not name or not self.backend or not self.backend.bus:
            return {"error": "Invalid motor or bus offline"}
        with SERIAL_LOCK:
            try:
                self.backend.bus.sync_write("Goal_Position", {name: goal}, normalize=False)
                return {"status": "ok", "sid": sid, "goal": goal}
            except Exception as e:
                return {"error": f"Failed to set goal: {e}"}

    def get_studio_html(self) -> str:
        return HTML_DASHBOARD

    def stop(self) -> None:
        super().stop()
        self.logger.info("ServoStudioApp.stop() called. Closing web server...")
        if self.server:
            try:
                self.server.server_close()
                threading.Thread(target=self.server.shutdown, daemon=True).start()
            except Exception as e:
                self.logger.warning(f"Server close error: {e}")

    def run(self, backend: RobotBackend, stop_event: threading.Event) -> None:
        self.backend = backend
        self._torque_enabled = False
        StudioHandler.backend = backend
        StudioHandler.app_instance = self

        self.disable_torque()
        self.logger.info(f"Starting Servo Studio server on port {self.port} (Default: UNTORQUED)...")
        self.server = ThreadedHTTPServer(("0.0.0.0", self.port), StudioHandler)

        server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        server_thread.start()

        try:
            while not stop_event.is_set():
                stop_event.wait(0.2)
        finally:
            self.logger.info("Stopping Servo Studio server loop...")
            if self.server:
                try:
                    self.server.server_close()
                except Exception:
                    pass
            self.logger.info("Servo Studio server loop finished.")
