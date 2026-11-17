"""Small Gemini API client using plain HTTP (requests) (Phase 7).

The key is read from the environment / .env (GEMINI_API_KEY) and sent only in the
x-goog-api-key header. It is never logged or put into error messages.
Model: GEMINI_MODEL (default below). Change it in .env if Google renames models
or the free tier changes; see AI Studio for your current limits.
"""
from __future__ import annotations

import os
from pathlib import Path

import requests

DEFAULT_MODEL = "gemini-3.8-flash"
API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class LLMError(RuntimeError):
    """The language model call failed."""


class RateLimited(LLMError):
    """Free-tier limit reached (HTTP 429)."""


def load_dotenv_if_present(root: Path | None = None) -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    path = (root or Path.cwd()) / ".env"
    if path.exists():
        load_dotenv(path, override=False)


class GeminiClient:
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, timeout: float = 60.0,
                 session: requests.Session | None = None):
        if not api_key:
            raise LLMError("GEMINI_API_KEY is not set (put it in .env)")
        self._key = api_key
        self.model = model
        self.timeout = timeout
        self._session = session or requests.Session()

    @classmethod
    def from_env(cls, root: Path | None = None) -> "GeminiClient":
        load_dotenv_if_present(root)
        return cls(os.environ.get("GEMINI_API_KEY", "").strip(),
                   os.environ.get("GEMINI_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL)

    def generate(self, system: str, user: str) -> str:
        body = {"systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}]}
        try:
            r = self._session.post(API_URL.format(model=self.model), json=body,
                                   headers={"x-goog-api-key": self._key}, timeout=self.timeout)
        except requests.RequestException as e:
            raise LLMError(f"network error calling Gemini: {type(e).__name__}") from None
        if r.status_code == 429:
            raise RateLimited("Gemini free-tier limit reached; try again later")
        if r.status_code != 200:
            try:
                msg = r.json().get("error", {}).get("message", "")[:200]
            except ValueError:
                msg = ""
            raise LLMError(f"Gemini HTTP {r.status_code}: {msg}")
        data = r.json()
        try:
            parts = data["candidates"][0]["content"]["parts"]
        except (KeyError, IndexError, TypeError):
            reason = (data.get("promptFeedback") or {}).get("blockReason", "no candidates")
            raise LLMError(f"Gemini returned no answer ({reason})") from None
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        if not text.strip():
            raise LLMError("Gemini returned empty text")
        return text.strip()
