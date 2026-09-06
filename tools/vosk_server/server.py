#!/usr/bin/env python3
"""tools/vosk_server/server.py - Resident Vosk Standby Server for Pi 4B.

Pre-loads vosk-model-en-us-0.22 in a background thread (~120s cold-load time)
and exposes:
  GET /health     -> 503 while loading, 200 {"status": "ready", ...} when ready
  POST /recognize -> Ingests 16kHz 16-bit mono PCM, optional X-Grammar header,
                     and returns {"text": "<transcript>"} in <300ms.
Strict Fail-Fast schema compliance: Zero .get(k, default) fallbacks.
"""

from __future__ import annotations

import json
import asyncio
import logging
import os
import sys
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, Any, Optional, List
import urllib.parse
import websockets

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("VoskStandbyServer")

CONFIG_PATH_CANDIDATES = [
    Path("/home/carson/vosk_server/vosk_config.json"),
    Path(__file__).resolve().parent.parent.parent / "config" / "vosk_config.json",
    Path(__file__).resolve().parent / "vosk_config.json",
]


def load_vosk_config() -> Dict[str, Any]:
    target_path: Optional[Path] = None
    for p in CONFIG_PATH_CANDIDATES:
        if p.exists():
            target_path = p
            break
    if target_path is None:
        raise FileNotFoundError(f"Missing canonical Vosk configuration. Checked: {CONFIG_PATH_CANDIDATES}")

    with open(target_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    # Strict fail-fast schema validation
    _ = str(cfg["host"])
    _ = int(cfg["port"])
    _ = int(cfg["websocket_port"])
    _ = str(cfg["model_path"])
    _ = int(cfg["sample_rate"])
    _ = int(cfg["timeout_sec"])
    return cfg


CONFIG = load_vosk_config()

# Global state
_model: Optional[Any] = None
_model_ready: bool = False
_model_error: Optional[str] = None
_start_time: float = time.time()
_loaded_time: Optional[float] = None
_model_lock = threading.Lock()
_cached_rec: Optional[Any] = None
_cached_grammar: Optional[str] = None
_rec_lock = threading.Lock()


def _load_model_background(model_path_str: str) -> None:
    global _model, _model_ready, _model_error, _loaded_time
    logger.info("Background model loading started for: %s (estimated ~120s on Pi 4B)...", model_path_str)
    t0 = time.time()
    try:
        import vosk
        vosk.SetLogLevel(-1)  # Mute C++ verbose kaldi logs
        mpath = Path(model_path_str)
        if not mpath.exists():
            raise FileNotFoundError(f"Vosk model path does not exist: {model_path_str}")
        loaded = vosk.Model(str(mpath))
        with _model_lock:
            _model = loaded
            _model_ready = True
            _loaded_time = time.time()
        dur = _loaded_time - t0
        logger.info("Vosk model successfully loaded in %.1f seconds! Server is READY.", dur)
    except Exception as e:
        logger.error("Failed to load Vosk model from %s: %s", model_path_str, e, exc_info=True)
        with _model_lock:
            _model_error = str(e)
            _model_ready = False


class VoskHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/health":
            self.handle_health()
        else:
            self.send_error(404, f"Path not found: {parsed.path}")

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/recognize":
            self.handle_recognize()
        else:
            self.send_error(404, f"Path not found: {parsed.path}")

    def handle_health(self) -> None:
        global _model_ready, _model_error, _start_time, _loaded_time
        with _model_lock:
            ready = _model_ready
            err = _model_error

        if err is not None:
            payload = {
                "status": "error",
                "error": err,
                "elapsed_sec": round(time.time() - _start_time, 1)
            }
            body = json.dumps(payload).encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if not ready:
            payload = {
                "status": "loading",
                "model": CONFIG["model_path"],
                "elapsed_sec": round(time.time() - _start_time, 1)
            }
            body = json.dumps(payload).encode("utf-8")
            self.send_response(503)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError) as disc_err:
                logger.debug("Client disconnected during 503 response: %s", disc_err)
            return

        if _loaded_time is None:
            raise RuntimeError("Model is marked ready but _loaded_time is None")
        load_dur = round((_loaded_time - _start_time), 1)
        payload = {
            "status": "ready",
            "model": CONFIG["model_path"],
            "load_duration_sec": load_dur,
            "sample_rate": CONFIG["sample_rate"],
            "websocket_port": CONFIG["websocket_port"]
        }
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError) as disc_err:
            logger.debug("Client disconnected during 200 response: %s", disc_err)

    def handle_recognize(self) -> None:
        global _model, _model_ready
        with _model_lock:
            ready = _model_ready
            model_inst = _model

        if not ready or model_inst is None:
            self.send_error(503, "Vosk model is still loading in background")
            return

        # Read PCM audio from request body
        content_len_hdr = self.headers.get("Content-Length")
        if not content_len_hdr:
            self.send_error(400, "Missing Content-Length header")
            return
        content_len = int(content_len_hdr)
        if content_len <= 0:
            self.send_error(400, "Empty audio buffer")
            return

        pcm_data = self.rfile.read(content_len)

        # Grammar extraction from X-Grammar header (JSON string array)
        grammar_header = self.headers.get("X-Grammar")
        sample_rate = int(CONFIG["sample_rate"])

        t0 = time.time()
        import vosk
        global _cached_rec, _cached_grammar
        with _rec_lock:
            if grammar_header:
                if _cached_grammar == grammar_header and _cached_rec is not None:
                    rec = _cached_rec
                    rec.Reset()
                else:
                    try:
                        phrases = json.loads(grammar_header)
                        if not isinstance(phrases, list):
                            raise ValueError("X-Grammar header must be a JSON array of strings")
                        if "[unk]" not in phrases:
                            phrases.append("[unk]")
                        rec = vosk.KaldiRecognizer(model_inst, sample_rate, json.dumps(phrases))
                        _cached_rec = rec
                        _cached_grammar = grammar_header
                    except Exception as ge:
                        logger.warning("Failed parsing X-Grammar header ('%s'): %s. Using open vocabulary.", grammar_header, ge)
                        rec = vosk.KaldiRecognizer(model_inst, sample_rate)
            else:
                if _cached_grammar is None and _cached_rec is not None:
                    rec = _cached_rec
                    rec.Reset()
                else:
                    rec = vosk.KaldiRecognizer(model_inst, sample_rate)
                    _cached_rec = rec
                    _cached_grammar = None

            # Feed PCM data to recognizer
            rec.AcceptWaveform(pcm_data)
            res = json.loads(rec.FinalResult())
        text = str(res["text"]).strip()
        elapsed_ms = round((time.time() - t0) * 1000, 1)
        logger.info("Transcribed (%d bytes, %.1f ms): '%s'", len(pcm_data), elapsed_ms, text)

        resp_payload = {
            "text": text,
            "elapsed_ms": elapsed_ms
        }
        body = json.dumps(resp_payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError) as disc_err:
            logger.debug("Client disconnected during recognize response: %s", disc_err)

    def log_message(self, format: str, *args: Any) -> None:
        # Override to keep daemon logs clean from routine polling
        return


async def _ws_client_handler(websocket) -> None:
    """Asynchronous WebSocket client session handler for real-time streaming recognition."""
    global _model, _model_ready
    with _model_lock:
        ready = _model_ready
        m = _model

    if not ready or m is None:
        try:
            await websocket.send(json.dumps({"type": "error", "message": "Model still loading"}))
            await websocket.close(1013, "Model still loading")
        except Exception as ex_send:
            logger.debug("Could not send model loading error to WebSocket: %s", ex_send)
        return

    import vosk
    sample_rate = int(CONFIG["sample_rate"])
    rec = vosk.KaldiRecognizer(m, sample_rate)

    try:
        await websocket.send(json.dumps({"type": "ready", "sample_rate": sample_rate}))
    except Exception as ex_ready:
        logger.debug("WebSocket client disconnected before ready ack: %s", ex_ready)
        return

    try:
        async for message in websocket:
            if isinstance(message, bytes):
                # Binary audio chunk (16-bit mono PCM)
                if rec.AcceptWaveform(message):
                    res = json.loads(rec.Result())
                    text = str(res["text"]).strip()
                    await websocket.send(json.dumps({
                        "type": "final",
                        "text": text
                    }))
                else:
                    pres = json.loads(rec.PartialResult())
                    partial_text = str(pres["partial"]).strip()
                    await websocket.send(json.dumps({
                        "type": "partial",
                        "text": partial_text
                    }))
            else:
                # Text/JSON control command
                try:
                    cmd = json.loads(message)
                    cmd_type = str(cmd["type"])
                    if cmd_type == "final":
                        fres = json.loads(rec.FinalResult())
                        final_text = str(fres["text"]).strip()
                        await websocket.send(json.dumps({
                            "type": "final_result",
                            "text": final_text
                        }))
                    elif cmd_type == "reset":
                        rec.Reset()
                        await websocket.send(json.dumps({"type": "reset_ack"}))
                except Exception as ex:
                    await websocket.send(json.dumps({"type": "error", "message": str(ex)}))
    except (websockets.exceptions.ConnectionClosed, BrokenPipeError, ConnectionResetError) as ex_close:
        logger.debug("WebSocket client connection ended cleanly: %s", ex_close)
    except Exception as e:
        logger.error("Error in WebSocket client session: %s", e)


def _run_websocket_server(host: str, port: int) -> None:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def _serve():
        async with websockets.serve(_ws_client_handler, host, port):
            logger.info("Vosk WebSocket Streaming Server listening on ws://%s:%d", host, port)
            await asyncio.Future()  # Keep running indefinitely

    try:
        loop.run_until_complete(_serve())
    except Exception as e:
        logger.error("WebSocket server encountered error: %s", e)


def main() -> None:
    host = str(CONFIG["host"])
    port = int(CONFIG["port"])
    ws_port = int(CONFIG["websocket_port"])
    model_path = str(CONFIG["model_path"])

    http_server = ThreadingHTTPServer((host, port), VoskHandler)
    logger.info("Vosk Standby Server HTTP listening on http://%s:%d", host, port)

    # Launch model load in background thread so HTTP health check is active immediately
    loader_thread = threading.Thread(target=_load_model_background, args=(model_path,), daemon=True)
    loader_thread.start()

    # Launch WebSocket streaming server in background thread
    ws_thread = threading.Thread(target=_run_websocket_server, args=(host, ws_port), daemon=True)
    ws_thread.start()

    try:
        http_server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down Vosk Standby Server...")
    finally:
        http_server.server_close()


if __name__ == "__main__":
    main()
