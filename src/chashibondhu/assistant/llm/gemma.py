"""Gemma 4 through the Gemini API (free tier) - used as a FALLBACK when Groq is rate-limited.

.env: GEMINI_API_KEY=...   optional GEMMA_MODEL=gemma-4-31b-it (default)
Gemma "thinks out loud": thought parts are dropped, and the model is asked to put its final
reply between <answer> and </answer>; only that part is returned.
The key is sent only in the x-goog-api-key header; never logged or put in errors.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import requests

from chashibondhu.assistant.llm.gemini import LLMError, RateLimited, load_dotenv_if_present

API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GEMMA_DEFAULT_MODEL = "gemma-4-31b-it"
MAX_OUTPUT_TOKENS = 4096                 # thinking uses tokens too
ANSWER_RULE = ("\n\nIMPORTANT: think silently. Put ONLY your final reply, in exactly the "
               "format asked above, between <answer> and </answer>.")
_THINK_RE = re.compile(r"<think>.*?</think>", re.S | re.I)
_ANSWER_RE = re.compile(r"<answer>(.*?)(?:</answer>|$)", re.S | re.I)


def extract_answer(text: str) -> str:
    """Keep only the last <answer>...</answer> block (or the whole text if none)."""
    text = _THINK_RE.sub("", text)
    blocks = _ANSWER_RE.findall(text)
    return (blocks[-1] if blocks else text).strip()


def post_gemini(session: requests.Session, key: str, model: str, body: dict,
                timeout: float, label: str) -> requests.Response:
    try:
        return session.post(API_URL.format(model=model), json=body, timeout=timeout,
                            headers={"x-goog-api-key": key})
    except requests.RequestException as e:
        raise LLMError(f"network error calling {label}: {type(e).__name__}") from None


def answer_text(r: requests.Response, label: str) -> str:
    """HTTP response -> visible text (thought parts removed). Raises LLMError / RateLimited."""
    if r.status_code == 429:
        raise RateLimited(f"{label} rate limit reached; try again later")
    if r.status_code != 200:
        try:
            msg = str(r.json().get("error", {}).get("message", ""))[:200]
        except (ValueError, AttributeError):
            msg = ""
        raise LLMError(f"{label} HTTP {r.status_code}: {msg}")
    try:
        data = r.json()
        parts = data["candidates"][0]["content"]["parts"]
    except (ValueError, KeyError, IndexError, TypeError):
        raise LLMError(f"{label} returned no answer") from None
    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    if not text.strip():
        raise LLMError(f"{label} returned empty text")
    return text.strip()


class GemmaTextClient:
    """Same interface as the other text clients: generate(system, user) -> str."""
    provider = "gemma"

    def __init__(self, api_key: str, model: str = GEMMA_DEFAULT_MODEL, timeout: float = 120.0,
                 session: requests.Session | None = None):
        if not api_key:
            raise LLMError("GEMINI_API_KEY is not set (put it in .env)")
        self._key, self.model, self.timeout = api_key, model, timeout
        self._session = session or requests.Session()

    @classmethod
    def from_env(cls, root: Path | None = None) -> "GemmaTextClient":
        load_dotenv_if_present(root)
        return cls(os.environ.get("GEMINI_API_KEY", "").strip(),
                   os.environ.get("GEMMA_MODEL", GEMMA_DEFAULT_MODEL).strip()
                   or GEMMA_DEFAULT_MODEL)

    def generate(self, system: str, user: str) -> str:
        # System text goes into the user turn (safe for Gemma, which may not accept
        # a separate system instruction).
        prompt = f"{system}{ANSWER_RULE}\n\n---\n{user}"
        body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"maxOutputTokens": MAX_OUTPUT_TOKENS}}
        r = post_gemini(self._session, self._key, self.model, body, self.timeout, "gemma")
        out = extract_answer(answer_text(r, "gemma"))
        if not out:
            raise LLMError("gemma returned empty text")
        return out
