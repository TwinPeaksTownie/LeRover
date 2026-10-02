#!/usr/bin/env python3
"""tools/distance_web_ui.py - Live Network Web UI for Distance Telemetry.
Serves an ultra-responsive 100ms real-time telemetry dashboard on port 8089.
Supports SSE (Server-Sent Events) for zero-latency client broadcasts.
"""

import json
import os
import sys
import time
import threading
import queue
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from typing import Dict, Any, List
import serial


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


def load_configs(base_path: Path) -> Dict[str, Any]:
    """Loads configuration files with direct bracket indexing."""
    net_path = base_path / "config" / "network_config.json"
    rover_path = base_path / "config" / "rover_config.json"

    with open(net_path, "r", encoding="utf-8") as f:
        net_cfg = json.load(f)

    with open(rover_path, "r", encoding="utf-8") as f:
        rover_cfg = json.load(f)

    return {
        "host": net_cfg["endpoints"]["distance_telemetry"]["host"],
        "port": int(net_cfg["endpoints"]["distance_telemetry"]["port"]),
        "serial_port": net_cfg["hardware"]["rover_serial_port"],
        "baudrate": int(net_cfg["hardware"]["rover_baudrate"]),
        "assert_dtr": bool(rover_cfg["hardware_interface"]["assert_dtr"]),
        "assert_rts": bool(rover_cfg["hardware_interface"]["assert_rts"]),
        "watchdog": rover_cfg["watchdog"],
        "sensor": rover_cfg["distance_sensor"],
    }


class TelemetryHub:
    """Thread-safe telemetry collector and SSE broadcaster."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.sensor_cfg = config["sensor"]
        self.adc_max = (1 << int(self.sensor_cfg["adc_resolution_bits"])) - 1
        self.max_volts = float(self.sensor_cfg["max_volts"])
        self.max_dist_mm = float(self.sensor_cfg["max_distance_mm"])

        self._lock = threading.Lock()
        self.subscribers: List[queue.Queue] = []
        self._running = True

        self.min_raw = self.adc_max
        self.max_raw = 0
        self.sample_count = 0
        self.last_sample_time = time.time()
        self.history: List[Dict[str, float]] = []

        self.current_state: Dict[str, Any] = {
            "status": "INITIALIZING",
            "mode": "UNKNOWN",
            "raw_dist": 0,
            "volts": 0.0,
            "dist_mm": 0.0,
            "dist_cm": 0.0,
            "dist_in": 0.0,
            "min_cm": 0.0,
            "max_cm": 0.0,
            "delta_cm": 0.0,
            "dt_ms": 0.0,
            "hz": 0.0,
            "sbus_active": 0,
            "web_active": 0,
            "left_out": 1500,
            "right_out": 1500,
            "sensor_model": self.sensor_cfg["model"],
            "timestamp": time.time(),
        }

    def reset_stats(self) -> None:
        """Resets min/max boundary calculations."""
        with self._lock:
            self.min_raw = self.adc_max
            self.max_raw = 0
            if "raw_dist" in self.current_state and self.current_state["raw_dist"] > 0:
                raw = self.current_state["raw_dist"]
                self.min_raw = raw
                self.max_raw = raw

    def add_subscriber(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=30)
        with self._lock:
            self.subscribers.append(q)
        return q

    def remove_subscriber(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self.subscribers:
                self.subscribers.remove(q)

    def broadcast(self, payload: Dict[str, Any]) -> None:
        data = f"data: {json.dumps(payload)}\n\n"
        with self._lock:
            subs = list(self.subscribers)
        for q in subs:
            try:
                q.put_nowait(data)
            except queue.Full:
                pass

    def _recover_stalled_port(self) -> None:
        """Executes uhubctl hardware power-cycle to recover from USB CDC endpoint stalls."""
        import subprocess
        loc = self.config["watchdog"]["uhubctl_location"]
        port = self.config["watchdog"]["uhubctl_port"]
        cmd = ["sudo", "uhubctl", "-l", loc, "-p", str(port), "-a", "cycle", "-d", "2"]
        try:
            subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=8.0)
        except Exception:
            pass
        time.sleep(1.5)

    def run_serial_loop(self) -> None:
        """Continuously reads 100ms STAT lines from KB2040 with stall auto-recovery."""
        port = self.config["serial_port"]
        baud = self.config["baudrate"]
        stall_timeout = float(self.config["watchdog"]["stall_timeout_sec"])
        auto_recover = bool(self.config["watchdog"]["auto_recover_stalls"])
        rolling_intervals: List[float] = []

        while self._running:
            target_port = port if os.path.exists(port) else "/dev/ttyACM0"
            if not os.path.exists(target_port):
                with self._lock:
                    self.current_state["status"] = f"PORT_NOT_FOUND ({target_port})"
                time.sleep(1.0)
                continue

            ser = None
            try:
                ser = serial.Serial(target_port, baudrate=baud, timeout=0.2)
                if self.config["assert_dtr"]:
                    ser.dtr = True
                if self.config["assert_rts"]:
                    ser.rts = True
                ser.reset_input_buffer()

                with self._lock:
                    self.current_state["status"] = "CONNECTED"

                last_stat_time = time.time()

                while self._running:
                    line_bytes = ser.readline()
                    now = time.time()

                    if not line_bytes:
                        if auto_recover and (now - last_stat_time) > stall_timeout:
                            with self._lock:
                                self.current_state["status"] = "RECOVERING_STALL"
                            break
                        continue

                    line = line_bytes.decode("utf-8", errors="ignore").strip()
                    if not line.startswith("STAT:"):
                        if auto_recover and (now - last_stat_time) > stall_timeout:
                            with self._lock:
                                self.current_state["status"] = "RECOVERING_STALL"
                            break
                        continue

                    last_stat_time = now
                    dt = now - self.last_sample_time
                    self.last_sample_time = now

                    rolling_intervals.append(dt)
                    if len(rolling_intervals) > 10:
                        rolling_intervals.pop(0)
                    avg_dt = sum(rolling_intervals) / len(rolling_intervals)
                    hz = 1.0 / avg_dt if avg_dt > 0.001 else 0.0

                    parts = line[5:].split(",")
                    if len(parts) < 9:
                        continue

                    mode = parts[0]
                    left_out = int(parts[1])
                    right_out = int(parts[2])
                    sbus_active = int(parts[3])
                    web_active = int(parts[4])
                    raw_dist = int(parts[8])

                    with self._lock:
                        self.sample_count += 1
                        self.min_raw = min(self.min_raw, raw_dist)
                        self.max_raw = max(self.max_raw, raw_dist)

                        volts = (raw_dist / float(self.adc_max)) * self.max_volts
                        dist_mm = (raw_dist / float(self.adc_max)) * self.max_dist_mm
                        dist_cm = dist_mm / 10.0
                        dist_in = dist_mm / 25.4

                        min_cm = (self.min_raw / float(self.adc_max)) * self.max_dist_mm / 10.0
                        max_cm = (self.max_raw / float(self.adc_max)) * self.max_dist_mm / 10.0

                        state = {
                            "status": "STREAMING",
                            "mode": mode,
                            "raw_dist": raw_dist,
                            "volts": round(volts, 3),
                            "dist_mm": round(dist_mm, 1),
                            "dist_cm": round(dist_cm, 1),
                            "dist_in": round(dist_in, 2),
                            "min_cm": round(min_cm, 1),
                            "max_cm": round(max_cm, 1),
                            "delta_cm": round(max_cm - min_cm, 1),
                            "dt_ms": round(dt * 1000.0, 1),
                            "hz": round(hz, 1),
                            "sbus_active": sbus_active,
                            "web_active": web_active,
                            "left_out": left_out,
                            "right_out": right_out,
                            "sensor_model": self.sensor_cfg["model"],
                            "timestamp": now,
                        }
                        self.current_state = state

                        self.history.append({"t": round(now, 2), "cm": round(dist_cm, 1)})
                        if len(self.history) > 150:  # ~15 seconds of history
                            self.history.pop(0)

                    self.broadcast(state)

            except Exception as e:
                with self._lock:
                    self.current_state["status"] = f"DISCONNECTED ({e.__class__.__name__})"
            finally:
                if ser and ser.is_open:
                    try:
                        ser.close()
                    except Exception:
                        pass
                ser = None

            if self._running and auto_recover:
                self._recover_stalled_port()


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>LeRover // Distance Telemetry</title>
  <style>
    :root {
      --bg: #090c13;
      --card-bg: #111622;
      --card-border: #1e2638;
      --accent-cyan: #00e5ff;
      --accent-green: #00ff88;
      --accent-amber: #ffb700;
      --accent-red: #ff3366;
      --text-main: #f0f4fc;
      --text-muted: #7e8c9f;
      --font-mono: 'Consolas', 'Courier New', monospace;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background-color: var(--bg);
      color: var(--text-main);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      padding: 16px;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      align-items: center;
    }
    .hud-container {
      width: 100%;
      max-width: 900px;
      display: flex;
      flex-direction: column;
      gap: 16px;
    }
    header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 12px;
      padding: 14px 20px;
    }
    .header-title {
      font-size: 1.15rem;
      font-weight: 800;
      letter-spacing: 1.5px;
      text-transform: uppercase;
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .status-pill {
      font-size: 0.72rem;
      font-weight: 800;
      padding: 4px 10px;
      border-radius: 20px;
      letter-spacing: 1px;
      background: #182233;
      color: var(--accent-cyan);
      border: 1px solid rgba(0, 229, 255, 0.4);
    }
    .status-streaming { background: #072a1b; color: var(--accent-green); border-color: rgba(0, 255, 136, 0.5); }
    .status-disconnected { background: #330d17; color: var(--accent-red); border-color: rgba(255, 51, 102, 0.5); }

    .hero-card {
      background: var(--card-bg);
      border: 1.5px solid var(--card-border);
      border-radius: 14px;
      padding: 24px;
      position: relative;
      overflow: hidden;
      box-shadow: 0 8px 30px rgba(0, 0, 0, 0.4);
    }
    .hero-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 12px;
    }
    .hero-label {
      font-size: 0.85rem;
      font-weight: 700;
      letter-spacing: 2px;
      color: var(--text-muted);
      text-transform: uppercase;
    }
    .unit-switch {
      display: flex;
      background: #090c13;
      border: 1px solid var(--card-border);
      border-radius: 8px;
      overflow: hidden;
    }
    .unit-btn {
      background: none;
      border: none;
      color: var(--text-muted);
      padding: 6px 12px;
      font-size: 0.78rem;
      font-weight: 700;
      cursor: pointer;
      transition: all 0.2s;
    }
    .unit-btn.active {
      background: var(--accent-cyan);
      color: #000;
    }
    .hero-value-wrap {
      display: flex;
      align-items: baseline;
      gap: 12px;
      margin: 8px 0 16px 0;
    }
    .hero-value {
      font-family: var(--font-mono);
      font-size: 4.8rem;
      font-weight: 900;
      line-height: 1;
      color: var(--accent-cyan);
      letter-spacing: -2px;
      transition: color 0.2s;
    }
    .hero-unit {
      font-size: 1.6rem;
      font-weight: 700;
      color: var(--text-muted);
    }
    .proximity-bar-wrap {
      width: 100%;
      height: 22px;
      background: #080c14;
      border: 1px solid var(--card-border);
      border-radius: 11px;
      overflow: hidden;
      position: relative;
      margin-bottom: 10px;
    }
    .proximity-bar-fill {
      height: 100%;
      width: 0%;
      background: linear-gradient(90deg, var(--accent-red) 0%, var(--accent-amber) 30%, var(--accent-green) 70%, var(--accent-cyan) 100%);
      transition: width 0.1s linear;
      border-radius: 11px;
    }
    .proximity-ticks {
      display: flex;
      justify-content: space-between;
      font-size: 0.7rem;
      color: var(--text-muted);
      font-family: var(--font-mono);
    }

    .kpi-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 14px;
    }
    .kpi-card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 12px;
      padding: 16px;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .kpi-title {
      font-size: 0.72rem;
      font-weight: 700;
      letter-spacing: 1.5px;
      color: var(--text-muted);
      text-transform: uppercase;
    }
    .kpi-val {
      font-family: var(--font-mono);
      font-size: 1.7rem;
      font-weight: 800;
      color: var(--text-main);
    }
    .kpi-sub {
      font-size: 0.75rem;
      color: var(--text-muted);
    }

    .chart-card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 14px;
      padding: 18px;
    }
    .chart-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 12px;
    }
    .chart-title {
      font-size: 0.8rem;
      font-weight: 700;
      letter-spacing: 1.5px;
      color: var(--text-muted);
      text-transform: uppercase;
    }
    canvas#scopeCanvas {
      width: 100%;
      height: 180px;
      display: block;
      background: #080c14;
      border: 1px solid var(--card-border);
      border-radius: 8px;
    }

    .footer-bar {
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-size: 0.78rem;
      color: var(--text-muted);
      padding: 0 4px;
    }
    .btn-reset {
      background: #141c2c;
      color: var(--accent-cyan);
      border: 1px solid var(--card-border);
      padding: 6px 14px;
      border-radius: 6px;
      font-weight: 700;
      font-size: 0.75rem;
      cursor: pointer;
      transition: all 0.2s;
    }
    .btn-reset:hover {
      background: #1c2840;
      border-color: var(--accent-cyan);
    }
  </style>
</head>
<body>
  <div class="hud-container">
    <header>
      <div class="header-title">
        <span style="color: var(--accent-cyan)">⬢</span> LeRover Distance Telemetry
      </div>
      <div id="statusPill" class="status-pill">CONNECTING...</div>
    </header>

    <div class="hero-card">
      <div class="hero-header">
        <div class="hero-label">Target Proximity</div>
        <div class="unit-switch">
          <button class="unit-btn active" onclick="setUnit('cm')">CM</button>
          <button class="unit-btn" onclick="setUnit('mm')">MM</button>
          <button class="unit-btn" onclick="setUnit('in')">IN</button>
        </div>
      </div>

      <div class="hero-value-wrap">
        <div id="heroDist" class="hero-value">--.-</div>
        <div id="heroUnit" class="hero-unit">cm</div>
      </div>

      <div class="proximity-bar-wrap">
        <div id="barFill" class="proximity-bar-fill"></div>
      </div>
      <div class="proximity-ticks">
        <span>0 cm</span>
        <span>25 cm</span>
        <span>50 cm</span>
        <span>75 cm</span>
        <span>100 cm</span>
      </div>
    </div>

    <div class="kpi-grid">
      <div class="kpi-card">
        <div class="kpi-title">Analog Voltage</div>
        <div id="valVolts" class="kpi-val">-.--- V</div>
        <div class="kpi-sub">Scale: 0.00V – 3.30V</div>
      </div>

      <div class="kpi-card">
        <div class="kpi-title">Raw 16-Bit ADC</div>
        <div id="valRaw" class="kpi-val">-----</div>
        <div class="kpi-sub">ADC Range: 0 – 65,535</div>
      </div>

      <div class="kpi-card">
        <div class="kpi-title">Sample Rate / Latency</div>
        <div id="valRate" class="kpi-val">--.- Hz</div>
        <div id="valLatency" class="kpi-sub">+--- ms delta</div>
      </div>

      <div class="kpi-card">
        <div class="kpi-title">Dynamic Bounds (CM)</div>
        <div id="valBounds" class="kpi-val">-- / --</div>
        <div id="valDelta" class="kpi-sub">Spread: -- cm</div>
      </div>
    </div>

    <div class="chart-card">
      <div class="chart-header">
        <div class="chart-title">15-Second Continuous Waveform (10 Hz)</div>
        <button class="btn-reset" onclick="resetStats()">Reset Min / Max</button>
      </div>
      <canvas id="scopeCanvas" width="860" height="180"></canvas>
    </div>

    <div class="footer-bar">
      <div>Sensor: <span id="sensorModel" style="color:var(--text-main)">goBILDA Laser</span> | Mode: <span id="roverMode" style="color:var(--accent-cyan)">WEB</span></div>
      <div>Endpoint: 192.168.0.86:8089</div>
    </div>
  </div>

  <script>
    let currentUnit = 'cm';
    const historyPoints = [];
    const maxHistory = 150;

    function setUnit(u) {
      currentUnit = u;
      document.querySelectorAll('.unit-btn').forEach(b => {
        b.classList.toggle('active', b.textContent.toLowerCase() === u);
      });
      document.getElementById('heroUnit').textContent = u;
    }

    function resetStats() {
      fetch('/api/reset_stats', { method: 'POST' }).catch(console.error);
    }

    const canvas = document.getElementById('scopeCanvas');
    const ctx = canvas.getContext('2d');

    function drawChart() {
      const w = canvas.width;
      const h = canvas.height;
      ctx.clearRect(0, 0, w, h);

      // Grid lines
      ctx.strokeStyle = '#141c2c';
      ctx.lineWidth = 1;
      for (let y = 0; y < h; y += 36) {
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(w, y);
        ctx.stroke();
      }

      if (historyPoints.length < 2) return;

      ctx.beginPath();
      ctx.lineWidth = 2.5;
      ctx.strokeStyle = '#00e5ff';

      const step = w / (maxHistory - 1);
      const startX = w - ((historyPoints.length - 1) * step);

      for (let i = 0; i < historyPoints.length; i++) {
        const x = startX + (i * step);
        const cm = historyPoints[i];
        const norm = Math.max(0, Math.min(100, cm)) / 100.0;
        const y = h - (norm * (h - 20) + 10);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();

      // Draw glowing end dot
      const lastX = w;
      const lastCm = historyPoints[historyPoints.length - 1];
      const lastY = h - (Math.max(0, Math.min(100, lastCm)) / 100.0 * (h - 20) + 10);
      ctx.fillStyle = '#00ff88';
      ctx.beginPath();
      ctx.arc(lastX - 2, lastY, 4, 0, Math.PI * 2);
      ctx.fill();
    }

    const evtSource = new EventSource('/events');

    evtSource.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        const statusEl = document.getElementById('statusPill');
        if (data.status === 'STREAMING') {
          statusEl.textContent = 'LIVE // 100ms';
          statusEl.className = 'status-pill status-streaming';
        } else {
          statusEl.textContent = data.status;
          statusEl.className = 'status-pill status-disconnected';
        }

        let distVal = data.dist_cm;
        if (currentUnit === 'mm') distVal = data.dist_mm;
        else if (currentUnit === 'in') distVal = data.dist_in;

        const heroEl = document.getElementById('heroDist');
        heroEl.textContent = distVal.toFixed(1);

        // Color shift based on distance
        if (data.dist_cm < 15.0) heroEl.style.color = 'var(--accent-red)';
        else if (data.dist_cm < 30.0) heroEl.style.color = 'var(--accent-amber)';
        else heroEl.style.color = 'var(--accent-cyan)';

        // Update progress bar (0 to 100 cm)
        const pct = Math.max(0, Math.min(100, data.dist_cm));
        document.getElementById('barFill').style.width = pct + '%';

        document.getElementById('valVolts').textContent = data.volts.toFixed(3) + ' V';
        document.getElementById('valRaw').textContent = data.raw_dist.toLocaleString();
        document.getElementById('valRate').textContent = data.hz.toFixed(1) + ' Hz';
        document.getElementById('valLatency').textContent = '+' + data.dt_ms.toFixed(0) + ' ms delta';
        document.getElementById('valBounds').textContent = data.min_cm.toFixed(1) + ' / ' + data.max_cm.toFixed(1);
        document.getElementById('valDelta').textContent = 'Δ ' + data.delta_cm.toFixed(1) + ' cm spread';

        document.getElementById('sensorModel').textContent = data.sensor_model;
        document.getElementById('roverMode').textContent = data.mode;

        historyPoints.push(data.dist_cm);
        if (historyPoints.length > maxHistory) historyPoints.shift();
        drawChart();

      } catch (err) {
        console.error('Error handling SSE payload:', err);
      }
    };

    evtSource.onerror = () => {
      const statusEl = document.getElementById('statusPill');
      statusEl.textContent = 'RECONNECTING...';
      statusEl.className = 'status-pill status-disconnected';
    };
  </script>
</body>
</html>
"""


class TelemetryRequestHandler(BaseHTTPRequestHandler):
    hub: TelemetryHub = None  # Class-level injection

    def do_HEAD(self) -> None:
        if self.path == "/" or self.path == "/index.html":
            content = DASHBOARD_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            return
        if self.path == "/api/telemetry":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            return
        self.send_error(404, f"Path not found: {self.path}")

    def do_GET(self) -> None:
        if self.path == "/" or self.path == "/index.html":
            content = DASHBOARD_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return

        if self.path == "/events":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            q = self.hub.add_subscriber()
            # Send immediate initial state snapshot
            with self.hub._lock:
                init_data = f"data: {json.dumps(self.hub.current_state)}\n\n"
            try:
                self.wfile.write(init_data.encode("utf-8"))
                self.wfile.flush()

                while True:
                    try:
                        msg = q.get(timeout=2.0)
                        self.wfile.write(msg.encode("utf-8"))
                        self.wfile.flush()
                    except queue.Empty:
                        # Keepalive heartbeat comment
                        self.wfile.write(b": heartbeat\n\n")
                        self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                self.hub.remove_subscriber(q)
            return

        if self.path == "/api/telemetry":
            with self.hub._lock:
                payload = dict(self.hub.current_state)
                payload["history"] = list(self.hub.history)
            data = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(data)
            return

        self.send_error(404, f"Path not found: {self.path}")

    def do_POST(self) -> None:
        if self.path == "/api/reset_stats":
            self.hub.reset_stats()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(b'{"status": "ok"}')
            return

        self.send_error(404, f"Unknown POST endpoint: {self.path}")

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress standard HTTP request logging for high-frequency SSE/API."""
        pass


def main() -> None:
    base_dir = Path(__file__).resolve().parent.parent
    config = load_configs(base_dir)

    hub = TelemetryHub(config)
    TelemetryRequestHandler.hub = hub

    # Start serial poller background thread
    serial_thread = threading.Thread(target=hub.run_serial_loop, daemon=True)
    serial_thread.start()

    host = config["host"]
    port = config["port"]
    server = ThreadingHTTPServer((host, port), TelemetryRequestHandler)

    print(f"\n=======================================================")
    print(f"  LeRover Distance Telemetry Web Server")
    print(f"  Listening at: http://{host}:{port}/")
    print(f"  Serial Port:  {config['serial_port']} @ {config['baudrate']}")
    print(f"  Sensor Model: {config['sensor']['model']}")
    print(f"=======================================================\n", flush=True)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down web server...", flush=True)
    finally:
        hub._running = False
        server.server_close()


if __name__ == "__main__":
    main()
