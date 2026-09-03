"""
voice_bridge.py - Ornith Voice Bridge Service
Runs on port 8058 on the host workstation.
Bridges:
- CoHere ASR (port 8001) for Speech-to-Text
- LM Studio (port 1234) for Intent Classification & Executive Denoising
- Pocket TTS (port 8057) & Pi 4B (:8082/api/play_sound) for Multi-Destination Speech
- Pi 500 Master Daemon & Pokéball Controller Button B for Tactile Push-to-Talk
"""

import io
import json
import logging
import os
import re
import sys
import threading
import urllib.request
import urllib.parse
from typing import Optional, Dict, Any

import sounddevice as sd
import numpy as np
import wave

from fastapi import FastAPI, File, UploadFile, Request, HTTPException
from fastapi.responses import JSONResponse
import uvicorn

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import tools_speech
import tools_audit
import tools_denoise
import tools_computer_use

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [VOICE_BRIDGE] %(message)s"
)
logger = logging.getLogger("voice_bridge")

class AudioRecorder:
    def __init__(self, samplerate: int = 16000, channels: int = 1):
        self.samplerate = samplerate
        self.channels = channels
        self._stream = None
        self._frames = []
        self._lock = threading.Lock()
        self.is_recording = False

    def _audio_callback(self, indata, frames, time_info, status):
        if status:
            logger.warning(f"Audio record status: {status}")
        with self._lock:
            if self.is_recording:
                self._frames.append(indata.copy())

    def start(self):
        with self._lock:
            self._frames = []
            self.is_recording = True
            if self._stream is not None:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception:
                    pass
            self._stream = sd.InputStream(
                samplerate=self.samplerate,
                channels=self.channels,
                dtype="int16",
                callback=self._audio_callback
            )
            self._stream.start()
        logger.info("🎙️ Started microphone recording from default input...")

    def stop(self) -> bytes:
        with self._lock:
            self.is_recording = False
            if self._stream is not None:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None
            if not self._frames:
                logger.warning("No audio frames recorded")
                return b""
            audio_data = np.concatenate(self._frames, axis=0)
            self._frames = []

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(self.samplerate)
            wf.writeframes(audio_data.tobytes())
        wav_bytes = buf.getvalue()
        logger.info(f"🛑 Stopped recording, generated {len(wav_bytes)} WAV bytes")
        return wav_bytes

RECORDER = AudioRecorder()

app = FastAPI(title="Ornith Voice Bridge", version="1.0.0")

COHERE_ASR_URL = os.environ.get("COHERE_ASR_URL", "http://127.0.0.1:8001/transcribe")
LM_STUDIO_URL = os.environ.get("LM_STUDIO_URL", "http://127.0.0.1:1234/v1")
PORT = int(os.environ.get("VOICE_BRIDGE_PORT", 8058))

def transcribe_audio_bytes(wav_bytes: bytes, timeout_sec: int = 15) -> str:
    """Sends WAV audio bytes to CoHere ASR server on port 8001 and returns transcript."""
    if not wav_bytes:
        raise ValueError("Audio bytes payload cannot be empty")

    boundary = "----WebKitFormBoundaryOrnithVoice"
    parts = [
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"audio_file\"; filename=\"recording.wav\"\r\nContent-Type: audio/wav\r\n\r\n".encode("utf-8"),
        wav_bytes,
        f"\r\n--{boundary}--\r\n".encode("utf-8")
    ]
    body = b"".join(parts)

    req = urllib.request.Request(
        COHERE_ASR_URL,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            if resp.status != 200:
                raise RuntimeError(f"CoHere ASR returned HTTP {resp.status}")
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("text", "").strip()
    except Exception as e:
        logger.error(f"Transcription failed: {e}")
        raise RuntimeError(f"Failed to transcribe audio via CoHere ASR: {str(e)}")

def classify_intent_and_respond(user_text: str, audio_target: str = "pi4b") -> Dict[str, Any]:
    """
    Classifies user intent (Summary Request, Direct Clarification, or Action Directive).
    Executes appropriate routing and audio response.
    """
    clean_prompt = user_text.strip()
    # Normalize common speech artifacts
    clean_prompt = re.sub(r"\s+", " ", clean_prompt)
    lower_prompt = clean_prompt.lower()

    # 1. Check for explicit summary request or reference to Antigravity's previous answer
    summary_indicators = [
        "simplify", "summarize", "distill", "what did you say", "too long",
        "tldr", "tl;dr", "brief me", "recap", "shorten", "condense",
        "last answer", "last response", "previous answer", "previous response",
        "google anti-gravity", "anti-gravity", "antigravity",
        "explain that simpler", "what was that", "can you repeat"
    ]
    if any(ind in lower_prompt for ind in summary_indicators):
        logger.info(f"Detected summary/simplification intent from prompt: '{clean_prompt}'. Distilling latest Antigravity response...")
        return execute_turn_summary(audio_target=audio_target)

    # 2. Check for explicit action directive
    action_prefixes = ["fix ", "deploy ", "restart ", "edit ", "refactor ", "move gantry", "step pedestal", "run "]
    is_action = any(lower_prompt.startswith(p) or f"please {p}" in lower_prompt for p in action_prefixes)

    if is_action:
        logger.info(f"Detected action directive: '{clean_prompt}'")
        feedback_prompt = f"Carson (via Pokéball Voice): {clean_prompt}\n\nPlease proceed and call signal_task_complete when finished."
        inject_res = tools_computer_use.send_feedback_to_antigravity(feedback_prompt, click_send=True)
        ack_text = "I dispatched your instruction to Antigravity. Standing by for task completion."
        speech_res = tools_speech.speak_laura(text=ack_text, target=audio_target)
        return {
            "status": "success",
            "intent": "ACTION",
            "user_prompt": clean_prompt,
            "antigravity_injected": inject_res.get("status") == "success",
            "spoken_ack": ack_text,
            "audio_dispatch": speech_res
        }

    # 3. Direct conversational answer via Ornith in LM Studio
    logger.info(f"Querying Ornith for direct answer to: '{clean_prompt}'")
    system_prompt = (
        "You are Ornith, Carson's direct, plain-spoken robotics AI assistant speaking in Laura's voice.\n"
        "Carson is speaking to you directly through the robot's microphone.\n"
        "Provide a direct, conversational, and technically accurate answer in strictly 35 to 55 words.\n"
        "Lead with the bottom line. Speak naturally in active voice.\n"
        "Do NOT use markdown, code blocks, bullet points, headers, or quotes.\n"
        "Do NOT explain your thinking process."
    )

    try:
        payload = {
            "model": "ornith-1.0-35b",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": clean_prompt}
            ],
            "max_tokens": 4096,
            "temperature": 0.3
        }
        req = urllib.request.Request(
            f"{LM_STUDIO_URL.rstrip('/')}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            msg = data["choices"][0]["message"]
            ans_text = msg.get("content", "").strip()
            if not ans_text and msg.get("reasoning_content"):
                ans_text = msg["reasoning_content"].strip()
            ans_clean = tools_denoise.clean_speech_text(ans_text)
            ans_clean = re.sub(r"(?is)^.*?(?:here's a thinking process|thinking process|analyze user input).*?\n\n", "", ans_clean).strip()
            if not ans_clean:
                ans_clean = "I processed your question, but could not formulate a clear response."
    except Exception as e:
        logger.error(f"Error querying LM Studio for response: {e}", exc_info=True)
        ans_clean = f"I received your inquiry regarding {clean_prompt[:30]}, but encountered an issue contacting the local model."

    logger.info(f"Ornith response: '{ans_clean}'")
    speech_res = tools_speech.speak_laura(text=ans_clean, target=audio_target)
    return {
        "status": "success",
        "intent": "QUERY",
        "user_prompt": clean_prompt,
        "spoken_response": ans_clean,
        "audio_dispatch": speech_res
    }

def execute_turn_summary(audio_target: str = "pi4b") -> Dict[str, Any]:
    """Extracts Antigravity's latest response from active transcript, denoises it, and speaks it."""
    trans = tools_audit.get_active_conversation_transcript(max_turns=2)
    if trans.get("status") != "success":
        err_msg = "Could not locate active conversation transcript to summarize."
        tools_speech.speak_laura(err_msg, target=audio_target)
        return {"status": "error", "error": err_msg, "details": trans}

    latest_resp = trans.get("latest_assistant_response", "")
    if not latest_resp:
        err_msg = "No recent assistant response found to summarize."
        tools_speech.speak_laura(err_msg, target=audio_target)
        return {"status": "error", "error": err_msg}

    denoise_res = tools_denoise.distill_response(raw_text=latest_resp)
    if denoise_res.get("status") != "success":
        err_msg = "Distillation model was unable to process the response."
        tools_speech.speak_laura(err_msg, target=audio_target)
        return denoise_res

    distilled_text = denoise_res.get("distilled_text", "")
    speech_res = tools_speech.speak_laura(text=distilled_text, target=audio_target)

    return {
        "status": "success",
        "distilled_text": distilled_text,
        "word_count": denoise_res.get("word_count", 0),
        "audio_dispatch": speech_res
    }

# -----------------------------------------------------------------------------
# REST API Endpoints
# -----------------------------------------------------------------------------

@app.get("/health")
def health_check():
    """Checks reachability of all interconnected nodes and services."""
    def _check(url, timeout=2.0):
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status in (200, 404)
        except Exception:
            return False

    return {
        "status": "ok",
        "services": {
            "lm_studio_1234": _check(f"{LM_STUDIO_URL}/models"),
            "cohere_asr_8001": _check("http://127.0.0.1:8001/openapi.json"),
            "pocket_tts_8057": _check("http://127.0.0.1:8057/"),
            "pi4b_kiosk_8082": _check("http://192.168.0.86:8082/api/status"),
            "pi500_master_8085": _check("http://192.168.0.130:8085/api/status")
        }
    }

@app.post("/api/voice/process_audio")
async def process_audio_endpoint(request: Request, audio_target: str = "pi4b"):
    """
    Ingests raw WAV audio bytes from mic recording (e.g. from Pokéball release),
    transcribes via CoHere ASR, and processes the intent.
    """
    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" in content_type:
        form = await request.form()
        audio_file = form.get("audio_file")
        if not audio_file:
            raise HTTPException(status_code=400, detail="Missing 'audio_file' in form upload")
        wav_bytes = await audio_file.read()
    else:
        wav_bytes = await request.body()

    if not wav_bytes:
        raise HTTPException(status_code=400, detail="Empty audio payload received")

    try:
        transcription = transcribe_audio_bytes(wav_bytes)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not transcription:
        return JSONResponse({"status": "ignored", "reason": "Empty transcription detected"})

    logger.info(f"CoHere ASR transcribed: '{transcription}'")
    result = classify_intent_and_respond(transcription, audio_target=audio_target)
    result["transcription"] = transcription
    return JSONResponse(result)

@app.post("/api/voice/summarize")
def summarize_endpoint(audio_target: str = "pi4b"):
    """Direct HTTP trigger to immediately summarize and speak Antigravity's latest response."""
    res = execute_turn_summary(audio_target=audio_target)
    return JSONResponse(res)

@app.post("/api/voice/interact")
async def interact_text_endpoint(request: Request):
    """Direct text input endpoint for testing or non-voice clients (e.g. Apple Watch / WatchKit)."""
    try:
        data = await request.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON payload: {str(e)}")
    text = data.get("text", "").strip()
    audio_target = data.get("audio_target", "pi4b")
    if not text:
        raise HTTPException(status_code=400, detail="Missing 'text' field in request")
    res = classify_intent_and_respond(text, audio_target=audio_target)
    return JSONResponse(res)

@app.post("/api/voice/button_event")
async def button_event_endpoint(request: Request):
    """
    Receives Pokéball Plus button events from the Pi 500 daemon:
    - start_listening: starts microphone recording on the PC
    - stop_listening: stops recording, sends to CoHere ASR, and routes to Ornith
    """
    try:
        data = await request.json()
    except Exception:
        data = {}
    button = data.get("button", "B")
    event = data.get("event", "")
    audio_target = data.get("audio_target", "pi4b")
    logger.info(f"Received Pokéball button event: button={button}, event={event}")

    if event == "start_listening":
        RECORDER.start()
        return JSONResponse({"status": "recording_started", "button": button})

    elif event == "stop_listening":
        wav_bytes = RECORDER.stop()
        if not wav_bytes:
            return JSONResponse({"status": "ignored", "reason": "No audio captured"})
        
        try:
            transcription = transcribe_audio_bytes(wav_bytes)
        except Exception as e:
            logger.error(f"Transcription failed: {e}")
            err_text = "I encountered an issue transcribing your audio."
            tools_speech.speak_laura(err_text, target=audio_target)
            return JSONResponse({"status": "error", "error": str(e)})

        logger.info(f"CoHere ASR transcribed: '{transcription}'")
        if not transcription:
            return JSONResponse({"status": "ignored", "reason": "Empty transcription"})

        result = classify_intent_and_respond(transcription, audio_target=audio_target)
        result["transcription"] = transcription
        return JSONResponse(result)

    return JSONResponse({"status": "received", "button": button, "event": event})

@app.post("/api/voice/prompt_connect")
def prompt_connect_endpoint(audio_target: str = "pi4b"):
    """
    Broadcasts the connection instruction in Laura's voice:
    'Go ahead and press the B button to connect to your robot.'
    """
    text = "Go ahead and press the B button to connect to your robot."
    speech_res = tools_speech.speak_laura(text=text, target=audio_target)
    return JSONResponse({"status": "prompted", "text": text, "audio_dispatch": speech_res})

if __name__ == "__main__":
    logger.info(f"Starting Ornith Voice Bridge on port {PORT}...")
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
