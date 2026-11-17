"""Groq vision client (OpenAI-compatible chat API with one image) (Phase 14).

.env:  GROQ_API_KEY=...   GROQ_VISION_MODEL=qwen/qwen3.8-27b (default; checked with
scripts/list_groq_models.py on 10 Nov 2026 - models change)
Fallback (Phase 14b): with GEMINI_API_KEY set, Gemma 4 vision answers when Groq is
rate-limited or fails. LLM_FALLBACK=off disables it.
The key is sent only in the Authorization header; never logged or put in errors.
"""
from __future__ import annotations

import base64
import os
from pathlib import Path

import requests

from chashibondhu.assistant.llm.gemini import LLMError, RateLimited, load_dotenv_if_present

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_VISION_MODEL = "qwen/qwen3.8-27b"


class VisionClient:
    def __init__(self, api_key: str, model: str, url: str = GROQ_URL, timeout: float = 90.0,
                 session: requests.Session | None = None, provider: str = "groq"):
        if not api_key:
            raise LLMError(f"API key for {provider} is not set (put it in .env)")
        if not model:
            raise LLMError("vision model name is empty")
        self._url, self._key, self.model = url, api_key, model
        self.provider, self.timeout = provider, timeout
        self._session = session or requests.Session()

    @classmethod
    def groq_from_env(cls, root: Path | None = None) -> "VisionClient":
        load_dotenv_if_present(root)
        return cls(os.environ.get("GROQ_API_KEY", "").strip(),
                   os.environ.get("GROQ_VISION_MODEL", DEFAULT_VISION_MODEL).strip()
                   or DEFAULT_VISION_MODEL)

    @classmethod
    def from_env(cls, root: Path | None = None):
        """Groq vision, plus Gemma fallback when enabled. Same analyze() interface."""
        groq = cls.groq_from_env(root)
        from chashibondhu.assistant.llm.openai_compat import fallback_enabled
        if not fallback_enabled():
            return groq
        from chashibondhu.assistant.llm.fallback import FallbackChain
        from chashibondhu.assistant.vision.gemma_client import GemmaVisionClient
        return FallbackChain([groq, GemmaVisionClient.from_env(root)])

    def analyze(self, system: str, text: str, jpeg: bytes) -> str:
        """One photo + text -> model text (expected: one JSON object)."""
        url = "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii")
        body = {"model": self.model, "temperature": 0.2,
                "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": [
                                 {"type": "text", "text": text},
                                 {"type": "image_url", "image_url": {"url": url}}]}]}
        r = self._post(body)
        if r.status_code == 400 and "response_format" in r.text:   # model without JSON mode
            body = {k: v for k, v in body.items() if k != "response_format"}
            r = self._post(body)
        if r.status_code == 429:
            raise RateLimited(f"{self.provider} rate limit reached; try again later")
        if r.status_code != 200:
            try:
                msg = str(r.json().get("error", {}).get("message", ""))[:200]
            except (ValueError, AttributeError):
                msg = ""
            raise LLMError(f"{self.provider} vision HTTP {r.status_code}: {msg}")
        try:
            out = r.json()["choices"][0]["message"].get("content") or ""
        except (ValueError, KeyError, IndexError, TypeError):
            raise LLMError(f"{self.provider} returned an unexpected response") from None
        if not out.strip():
            raise LLMError(f"{self.provider} returned empty text")
        return out.strip()

    def _post(self, body: dict):
        try:
            return self._session.post(self._url, json=body, timeout=self.timeout,
                                      headers={"Authorization": f"Bearer {self._key}"})
        except requests.RequestException as e:
            raise LLMError(f"network error calling {self.provider}: {type(e).__name__}") from None
