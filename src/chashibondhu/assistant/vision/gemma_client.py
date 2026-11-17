"""Gemma 4 vision through the Gemini API - FALLBACK for the Groq vision model (Phase 14b).

.env: GEMINI_API_KEY=...   optional GEMMA_VISION_MODEL=gemma-4-31b-it (default)
Same interface as VisionClient: analyze(system, text, jpeg) -> text with one JSON object.
Thought parts are dropped and any thinking text before the JSON is cut off.
"""
from __future__ import annotations

import base64
import os
from pathlib import Path

import requests

from chashibondhu.assistant.llm.gemini import LLMError, load_dotenv_if_present
from chashibondhu.assistant.llm.gemma import (GEMMA_DEFAULT_MODEL, MAX_OUTPUT_TOKENS,
                                              answer_text, extract_answer, post_gemini)

JSON_ANCHOR = '"is_plant_photo"'


def trim_to_json(text: str) -> str:
    """Drop any thinking text before the JSON object our prompt asks for."""
    text = extract_answer(text)
    i = text.rfind(JSON_ANCHOR)
    if i < 0:
        return text
    start = text.rfind("{", 0, i)
    return text[start:] if start >= 0 else text


class GemmaVisionClient:
    provider = "gemma"

    def __init__(self, api_key: str, model: str = GEMMA_DEFAULT_MODEL, timeout: float = 120.0,
                 session: requests.Session | None = None):
        if not api_key:
            raise LLMError("GEMINI_API_KEY is not set (put it in .env)")
        self._key, self.model, self.timeout = api_key, model, timeout
        self._session = session or requests.Session()

    @classmethod
    def from_env(cls, root: Path | None = None) -> "GemmaVisionClient":
        load_dotenv_if_present(root)
        return cls(os.environ.get("GEMINI_API_KEY", "").strip(),
                   os.environ.get("GEMMA_VISION_MODEL", GEMMA_DEFAULT_MODEL).strip()
                   or GEMMA_DEFAULT_MODEL)

    def analyze(self, system: str, text: str, jpeg: bytes) -> str:
        prompt = f"{system}\n\n---\n{text}\nReturn ONLY the JSON object."
        body = {"contents": [{"role": "user", "parts": [
                    {"inline_data": {"mime_type": "image/jpeg",
                                     "data": base64.b64encode(jpeg).decode("ascii")}},
                    {"text": prompt}]}],
                "generationConfig": {"temperature": 0.2, "maxOutputTokens": MAX_OUTPUT_TOKENS,
                                     "responseMimeType": "application/json"}}
        r = post_gemini(self._session, self._key, self.model, body, self.timeout, "gemma vision")
        if r.status_code == 400 and "mime" in r.text.lower():     # JSON mode not supported
            body["generationConfig"].pop("responseMimeType")
            r = post_gemini(self._session, self._key, self.model, body, self.timeout,
                            "gemma vision")
        return trim_to_json(answer_text(r, "gemma vision"))
