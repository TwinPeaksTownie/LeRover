"""
app.py - Standalone Speech-to-Speech & Model Inference Diagnostic Bench
Powered by Gradio 6.x.
Provides:
- Stage 1: Whisper ASR Audio Transcription & Latency
- Stage 2: Parallel Multi-Model LLM Arena (Kimi Moonshot vs Nemotron 3.5 & NIM/LM Studio models)
- Stage 3: Pocket TTS Laura Voice Synthesis & In-Browser Playback
- Robot Persona Audit (word count, markdown filtering) & Servo 5 Thinking Cycle Estimation
Strict compliance with contract rules: zero swallowed exceptions, fail-fast key checking.
"""

import json
import os
import sys
import time
from typing import Optional, Tuple

# Ensure UTF-8 output on Windows console
if sys.stdout and sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception as e:
        sys.stderr.write(f"[INIT] Failed to reconfigure console encoding: {e}\n")

import gradio as gr

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

import model_client

CFG = model_client.load_config()
DEFAULT_PORT = int(CFG["server"]["port"])
DEFAULT_HOST = CFG["server"]["host"]

PRESET_PROMPTS = {
    "Robot Status": "Give me a 40-word operational status report on your 6-DOF arm and auxiliary gantry.",
    "Servo Coordination": "Explain how normalized percentage mapping synchronizes follower servos with leader input.",
    "Philosophical Joke": "Tell me a short philosophical joke about robots discovering friction in 40 words.",
    "Choreography Timing": "How should a robot align its 8-bar motion sequence to a 120 BPM musical track?"
}

def check_service_health() -> str:
    """Checks reachability of local and cloud endpoints."""
    import requests

    services = []

    # 1. ASR
    try:
        r = requests.get("http://127.0.0.1:8001/openapi.json", timeout=1.5)
        services.append(f"🎙️ **Whisper ASR (8001)**: {'ONLINE' if r.status_code == 200 else 'HTTP ' + str(r.status_code)}")
    except Exception as e:
        services.append(f"🎙️ **Whisper ASR (8001)**: 🔴 OFFLINE ({type(e).__name__})")

    # 2. TTS
    try:
        r = requests.get("http://127.0.0.1:8057/", timeout=1.5)
        services.append(f"🔊 **Pocket TTS (8057)**: {'ONLINE' if r.status_code in (200, 404) else 'HTTP ' + str(r.status_code)}")
    except Exception as e:
        services.append(f"🔊 **Pocket TTS (8057)**: 🔴 OFFLINE ({type(e).__name__})")

    # 3. LM Studio
    try:
        r = requests.get("http://127.0.0.1:1234/v1/models", timeout=1.5)
        services.append(f"🖥️ **LM Studio (1234)**: {'ONLINE' if r.status_code == 200 else 'HTTP ' + str(r.status_code)}")
    except Exception as e:
        services.append("🖥️ **LM Studio (1234)**: ⚪ Not Running")

    # 4. NIM API
    key = model_client.get_nvidia_api_key()
    if key:
        services.append("☁️ **NVIDIA NIM API**: 🟢 Key Loaded")
    else:
        services.append("☁️ **NVIDIA NIM API**: 🟡 Missing Key")

    return " | ".join(services)

def get_initial_models():
    nim_models = model_client.fetch_nim_models()
    lm_models = model_client.fetch_lm_studio_models()
    all_models = nim_models + lm_models
    if not all_models:
        raise ValueError("Failed to discover any models from NVIDIA NIM or LM Studio.")
    def_a = CFG["defaults"]["model_a"]
    def_b = CFG["defaults"]["model_b"]
    if def_a not in all_models:
        raise KeyError(f"Configured default model_a '{def_a}' not found in discovered models.")
    if def_b not in all_models:
        raise KeyError(f"Configured default model_b '{def_b}' not found in discovered models.")
    return all_models

ALL_MODELS = get_initial_models()

def refresh_model_dropdowns(api_key: str):
    new_models = model_client.fetch_nim_models(api_key) + model_client.fetch_lm_studio_models()
    if not new_models:
        raise ValueError("No models available from NIM or LM Studio.")
    def_a = CFG["defaults"]["model_a"]
    def_b = CFG["defaults"]["model_b"]
    if def_a not in new_models:
        raise KeyError(f"Configured default model_a '{def_a}' not found in refreshed models.")
    if def_b not in new_models:
        raise KeyError(f"Configured default model_b '{def_b}' not found in refreshed models.")
    return (
        gr.update(choices=new_models, value=def_a),
        gr.update(choices=new_models, value=def_b)
    )

def handle_transcription(audio_file):
    if audio_file is None:
        return "Please record or upload an audio file first.", "ASR Standby: No file provided"
    res = model_client.transcribe_audio_file(audio_file)
    if res["success"]:
        return res["text"], f"✅ ASR Latency: {res['latency_ms']} ms (Engine: {res['engine']})"
    else:
        return f"Transcription failed: {res['error']}", f"❌ ASR Error: {res['latency_ms']} ms"

def run_arena_comparison(
    model_a: str,
    model_b: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float,
    max_tokens: int,
    timeout_sec: int,
    api_key: str
):
    if not user_prompt.strip():
        empty_res = "Please enter or transcribe a prompt to test."
        return (
            "No telemetry", empty_res, "", "No audit",
            "No telemetry", empty_res, "", "No audit",
            "Prompt cannot be empty."
        )

    t_start = time.perf_counter()
    res_a, res_b = model_client.run_parallel_comparison(
        model_a=model_a,
        model_b=model_b,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout_sec=timeout_sec,
        api_key=api_key
    )
    total_arena_duration_sec = round(time.perf_counter() - t_start, 2)

    def format_telemetry(res):
        if not res["success"]:
            return f"❌ FAILED: {res['error']} (HTTP {res['status_code']})"
        return (
            f"⏱️ **Thinking Latency**: {res['thinking_duration_sec']}s ({res['total_duration_ms']} ms) | "
            f"⚡ **TTFT**: {res['ttft_ms']} ms | "
            f"🚀 **Speed**: {res['tokens_per_sec']} t/s ({res['total_tokens']} tok) | "
            f"🤖 **Servo 5 Cycles**: ~{res['estimated_servo5_cycles']} osc"
        )

    def format_audit(res):
        if not res["success"]:
            return "No audit available."
        aud = res["audit"]
        badge = "🟢 PASS" if aud["length_status"] == "PASS" else ("🟡 " + aud["length_status"])
        clean_badge = "🟢 Clean Speech" if aud["markdown_clean"] else "🔴 Contains Markdown: " + ", ".join(aud["markdown_issues"])
        return f"**Length**: {aud['word_count']} words ({aud['target_range']}) → {badge}\n**TTS Formatting**: {clean_badge}"

    telemetry_a = format_telemetry(res_a)
    if res_a["success"]:
        spoken_a = res_a["spoken_response"]
        reasoning_a = res_a["reasoning_trace"]
        dur_a_str = f"{res_a['thinking_duration_sec']}s"
    else:
        spoken_a = res_a["error"]
        reasoning_a = "No reasoning captured."
        dur_a_str = "FAILED"
    audit_a = format_audit(res_a)

    telemetry_b = format_telemetry(res_b)
    if res_b["success"]:
        spoken_b = res_b["spoken_response"]
        reasoning_b = res_b["reasoning_trace"]
        dur_b_str = f"{res_b['thinking_duration_sec']}s"
    else:
        spoken_b = res_b["error"]
        reasoning_b = "No reasoning captured."
        dur_b_str = "FAILED"
    audit_b = format_audit(res_b)

    summary_note = (
        f"⚡ Completed parallel execution in **{total_arena_duration_sec} seconds**. "
        f"Model A completed in {dur_a_str}; "
        f"Model B completed in {dur_b_str}."
    )

    return (
        telemetry_a, spoken_a, reasoning_a, audit_a,
        telemetry_b, spoken_b, reasoning_b, audit_b,
        summary_note
    )

def handle_tts(text_to_speak: str):
    if not text_to_speak or not text_to_speak.strip():
        return None, "No text provided for speech synthesis."
    res = model_client.synthesize_speech(text_to_speak)
    if res["success"]:
        return res["audio_path"], f"🔊 Synthesized in {res['latency_ms']} ms ({res['bytes_len']} bytes)"
    else:
        return None, f"❌ Synthesis failed: {res['error']}"

# Build Gradio Interface
with gr.Blocks(title="Speech-to-Speech & Model Inference Arena") as demo:
    gr.Markdown("# 🎙️ SO-101 Speech-to-Speech & AI Model Diagnostic Arena")
    gr.Markdown("Test and benchmark transcription accuracy, LLM thinking windows, and Pocket TTS latency side-by-side.")

    with gr.Accordion("🔌 Active System Services Health", open=False):
        health_status = gr.Markdown(value=check_service_health())
        refresh_health_btn = gr.Button("🔄 Refresh Health Status", size="sm")
        refresh_health_btn.click(fn=check_service_health, outputs=health_status)

    with gr.Tabs():
        # TAB 1: ARENA
        with gr.Tab("🥊 Model Inference Arena"):
            with gr.Row():
                # LEFT: Prompt & Audio input
                with gr.Column(scale=1):
                    gr.Markdown("### 1. Input Modality")
                    audio_input = gr.Audio(sources=["microphone", "upload"], type="filepath", label="Voice Input (Mic / WAV)")
                    transcribe_btn = gr.Button("🎙️ Transcribe Audio (Whisper 8001)", variant="secondary")
                    asr_status = gr.Markdown(value="ASR Standby")

                    prompt_input = gr.Textbox(
                        label="User Prompt / Transcribed Speech",
                        lines=3,
                        placeholder="Speak into mic or type your test prompt here...",
                        value="What is your status, and how do you calibrate your 6-DOF follower arm?"
                    )

                    gr.Markdown("**Quick Presets:**")
                    with gr.Row():
                        for label, text in PRESET_PROMPTS.items():
                            btn = gr.Button(label, size="sm")
                            btn.click(fn=lambda t=text: t, outputs=prompt_input)

                    with gr.Accordion("⚙️ Persona & API Credentials", open=False):
                        system_prompt_input = gr.Textbox(
                            label="System Prompt",
                            lines=4,
                            value=CFG["defaults"]["system_prompt"]
                        )
                        with gr.Row():
                            temp_input = gr.Slider(minimum=0.0, maximum=1.5, value=CFG["defaults"]["temperature"], step=0.05, label="Temperature")
                            max_tokens_input = gr.Slider(minimum=64, maximum=4000, value=CFG["defaults"]["max_tokens"], step=64, label="Max Tokens")
                        with gr.Row():
                            timeout_input = gr.Slider(minimum=10, maximum=180, value=CFG["defaults"]["timeout_sec"], step=5, label="Timeout (sec)")
                            api_key_input = gr.Textbox(
                                label="NVIDIA API Key Override",
                                type="password",
                                placeholder="Uses secrets.json by default",
                                value=""
                            )

                # RIGHT: Model Selectors & Launch
                with gr.Column(scale=1):
                    gr.Markdown("### 2. Select Models for Comparison")
                    with gr.Row():
                        model_a_dropdown = gr.Dropdown(
                            choices=ALL_MODELS,
                            value=CFG["defaults"]["model_a"],
                            label="Model A (Left Panel)"
                        )
                        model_b_dropdown = gr.Dropdown(
                            choices=ALL_MODELS,
                            value=CFG["defaults"]["model_b"],
                            label="Model B (Right Panel)"
                        )
                    refresh_models_btn = gr.Button("🔄 Refresh NIM & LM Studio Model List", size="sm")

                    gr.Markdown("### 3. Run Benchmark")
                    run_btn = gr.Button("⚡ Run Side-by-Side Comparison (Parallel)", variant="primary", size="lg")
                    arena_summary = gr.Markdown(value="Standing by for benchmark run.")

            transcribe_btn.click(
                fn=handle_transcription,
                inputs=audio_input,
                outputs=[prompt_input, asr_status]
            )

            refresh_models_btn.click(
                fn=refresh_model_dropdowns,
                inputs=api_key_input,
                outputs=[model_a_dropdown, model_b_dropdown]
            )

            gr.Markdown("---")
            gr.Markdown("## 📊 Side-by-Side Evaluation & Voice Synthesis")

            with gr.Row():
                # PANEL A
                with gr.Column(scale=1):
                    gr.Markdown("### Model A Output")
                    telemetry_a_box = gr.Markdown(value="Awaiting execution...")
                    spoken_a_box = gr.Textbox(label="Spoken Response (Clean)", lines=5)
                    audit_a_box = gr.Markdown(value="")
                    with gr.Accordion("🧠 Reasoning Trace / Chain of Thought", open=False):
                        reasoning_a_box = gr.Textbox(label="Raw Thinking Process", lines=6)
                    tts_a_btn = gr.Button("🔊 Synthesize Laura Voice (Model A)", variant="secondary")
                    audio_a_out = gr.Audio(label="Model A Laura Voice Playback", interactive=False)
                    tts_a_status = gr.Markdown(value="")

                # PANEL B
                with gr.Column(scale=1):
                    gr.Markdown("### Model B Output")
                    telemetry_b_box = gr.Markdown(value="Awaiting execution...")
                    spoken_b_box = gr.Textbox(label="Spoken Response (Clean)", lines=5)
                    audit_b_box = gr.Markdown(value="")
                    with gr.Accordion("🧠 Reasoning Trace / Chain of Thought", open=False):
                        reasoning_b_box = gr.Textbox(label="Raw Thinking Process", lines=6)
                    tts_b_btn = gr.Button("🔊 Synthesize Laura Voice (Model B)", variant="secondary")
                    audio_b_out = gr.Audio(label="Model B Laura Voice Playback", interactive=False)
                    tts_b_status = gr.Markdown(value="")

            run_btn.click(
                fn=run_arena_comparison,
                inputs=[
                    model_a_dropdown, model_b_dropdown,
                    system_prompt_input, prompt_input,
                    temp_input, max_tokens_input, timeout_input,
                    api_key_input
                ],
                outputs=[
                    telemetry_a_box, spoken_a_box, reasoning_a_box, audit_a_box,
                    telemetry_b_box, spoken_b_box, reasoning_b_box, audit_b_box,
                    arena_summary
                ]
            )

            tts_a_btn.click(
                fn=handle_tts,
                inputs=spoken_a_box,
                outputs=[audio_a_out, tts_a_status]
            )

            tts_b_btn.click(
                fn=handle_tts,
                inputs=spoken_b_box,
                outputs=[audio_b_out, tts_b_status]
            )

        # TAB 2: EXPLANATION & ROBOT TIMING GUIDE
        with gr.Tab("⏱️ Robot Thinking Timing Guide"):
            gr.Markdown("""
            ### Designing Physical Thinking States for the Follower Arm
            When testing models with deliberate chain-of-thought (e.g. Kimi Moonshot or Nemotron 3.5), the **Thinking Latency** directly determines the animation budget for your physical actuators.

            #### Recommended Physical Indicators During LLM Thinking:
            1. **Servo 5 Wrist Roll Oscillation (1.0 Hz)**:
               - An oscillation formula like `angle = center + amplitude * sin(2 * pi * t)` lets the robot visibly "ponder" the question.
               - A 2.5-second thinking window provides **2.5 smooth oscillation cycles**.
            2. **Motor 7 Pedestal Spinner Subtle Sweep**:
               - A gentle ±10° slow oscillation on Motor 7 signals perceptual orientation.
            3. **Acoustic Thinking Hum**:
               - A low-pass modulated electronic purr or thinking chime can loop continuously until the LLM returns the first content token.
            """)

def main():
    print("==================================================")
    print("Starting Speech-to-Speech Diagnostic Arena")
    print(f"Host: {DEFAULT_HOST} | Port: {DEFAULT_PORT}")
    print(f"URL:  http://{DEFAULT_HOST}:{DEFAULT_PORT}")
    print("==================================================")
    sys.stdout.flush()
    demo.launch(server_name=DEFAULT_HOST, server_port=DEFAULT_PORT, theme=gr.themes.Soft(), show_error=True)

if __name__ == "__main__":
    main()
