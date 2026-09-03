"""
tools_denoise.py - Executive Denoising & Distillation Engine for Ornith
Consumes dense, jargon-heavy, or defensive agent responses from Antigravity transcripts
and synthesizes a punchy, 35-60 word spoken Bottom Line Up Front (BLUF) via LM Studio (port 1234).
"""

import json
import logging
import os
import re
import urllib.parse
import urllib.request
from typing import Dict, Any, Optional

DEFAULT_LM_STUDIO_URL = os.environ.get("LM_STUDIO_URL", "http://127.0.0.1:1234/v1")
DEFAULT_MODEL_NAME = os.environ.get("ORNITH_MODEL_NAME", "ornith-1.0-35b")

logger = logging.getLogger("ornith_denoise")

DISTILLATION_SYSTEM_PROMPT = """You are Ornith Executive Voice Distillation.
Your job is to translate long, dense, defensive AI assistant responses into a direct, conversational spoken briefing for the operator, Carson.

STRICT EDITING DIRECTIVES:
1. Strip all defensive posturing, apologies, hedging, and rule compliance recitations (e.g. "Per user rules...", "I ensured that no dummy values were used...", "In accordance with Lesson...").
2. Strip all Markdown syntax, code blocks, backticks, file paths, and JSON blobs. Speak only natural English sentences.
3. Structure your briefing strictly with Bottom Line Up Front (BLUF):
   - Sentence 1: The concrete outcome, decision, or physical state.
   - Sentence 2: The operational impact on the robot/system.
   - Sentence 3: The exact next step, physical action, or decision needed from Carson (or declare task complete).
4. Word Budget: Strictly between 35 and 60 words. Speak in clear, active voice.
5. Return ONLY the spoken text. Do not add headers, quotation marks, or prefixes like 'Summary:' or 'BLUF:'."""

def clean_speech_text(text: str) -> str:
    """Strips Markdown syntax, code fences, backticks, asterisks, brackets, and extra whitespace."""
    if not text:
        return ""
    # Remove code blocks
    cleaned = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    # Remove inline code backticks
    cleaned = re.sub(r"`([^`]+)`", r"\1", cleaned)
    # Remove Markdown headers and bold/italics
    cleaned = re.sub(r"^[#\s*_-]+", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"[*_~#\[\]]", "", cleaned)
    # Remove URLs
    cleaned = re.sub(r"https?://\S+|file://\S+", "", cleaned)
    # Normalize whitespace
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned

def distill_response(
    raw_text: str,
    context_hint: str = "",
    lm_studio_url: str = DEFAULT_LM_STUDIO_URL,
    model_name: str = DEFAULT_MODEL_NAME,
    timeout_sec: int = 120
) -> Dict[str, Any]:
    """
    Submits raw assistant response to Ornith in LM Studio for executive denoising.
    Returns dictionary with distilled spoken text and metadata.
    """
    if not raw_text or not raw_text.strip():
        return {
            "status": "error",
            "error": "Input text cannot be empty",
            "distilled_text": "No assistant response was provided to summarize."
        }

    user_content = f"Distill the following assistant response into 35-60 spoken words:\n\n{raw_text.strip()}"
    if context_hint:
        user_content = f"Context: {context_hint}\n\n{user_content}"

    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": DISTILLATION_SYSTEM_PROMPT},
            {"role": "user", "content": user_content}
        ],
        "temperature": 0.3,
        "max_tokens": 4096
    }

    url = f"{lm_studio_url.rstrip('/')}/chat/completions"
    data_bytes = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data_bytes,
        headers={"Content-Type": "application/json"}
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            if resp.status != 200:
                return {
                    "status": "error",
                    "error": f"LM Studio returned HTTP {resp.status}",
                    "distilled_text": ""
                }
            resp_body = resp.read().decode("utf-8", errors="replace")
            res_json = json.loads(resp_body)
            msg = res_json["choices"][0]["message"]
            raw_distilled = msg.get("content", "").strip()
            # If content is empty because reasoning wasn't separated
            if not raw_distilled and msg.get("reasoning_content"):
                # Clean out thinking traces from reasoning if used as fallback
                raw_distilled = re.sub(r"(?i)thinking process:.*?(?=\n\n|\Z)", "", msg["reasoning_content"], flags=re.DOTALL).strip()
    except Exception as e:
        logger.error(f"LM Studio distillation failed: {e}")
        return {
            "status": "error",
            "error": f"Failed to reach LM Studio at {url}: {str(e)}",
            "distilled_text": ""
        }

    # Clean and enforce constraints
    distilled = clean_speech_text(raw_distilled)
    words = distilled.split()
    if len(words) > 70:
        distilled = " ".join(words[:65]) + "."

    return {
        "status": "success",
        "distilled_text": distilled,
        "word_count": len(distilled.split()),
        "model_used": model_name
    }
