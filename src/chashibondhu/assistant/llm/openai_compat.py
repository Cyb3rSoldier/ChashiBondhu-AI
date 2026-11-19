"""OpenAI-compatible chat client (used for Groq's free tier) + provider factory (Phase 7d).

Choose the provider in .env:
  LLM_PROVIDER=groq            GROQ_API_KEY=...   GROQ_MODEL=openai/gpt-oss-120b (default)
  LLM_PROVIDER=gemini          GEMINI_API_KEY=... GEMINI_MODEL=...
The key is sent only in the Authorization header; never logged or put in errors.
Any other OpenAI-compatible service can be used with LLM_BASE_URL + LLM_API_KEY + LLM_MODEL.
Fallback (Phase 14b): with LLM_PROVIDER=groq and GEMINI_API_KEY set, Gemma 4 answers when Groq
is rate-limited or fails. LLM_FALLBACK=off disables it. Optional GEMMA_MODEL=gemma-4-31b-it.
"""
from __future__ import annotations

import os
from pathlib import Path

import requests

from chashibondhu.assistant.llm.gemini import (GeminiClient, LLMError, RateLimited,
                                               load_dotenv_if_present)

GROQ_URL = "https://api.groq.com/openai/v1"
GROQ_DEFAULT_MODEL = "openai/gpt-oss-120b"


class OpenAICompatClient:
    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 60.0,
                 session: requests.Session | None = None, provider: str = "openai-compatible"):
        if not api_key:
            raise LLMError(f"API key for {provider} is not set (put it in .env)")
        if not model:
            raise LLMError("model name is empty")
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._key = api_key
        self.model = model
        self.provider = provider
        self.timeout = timeout
        self._session = session or requests.Session()

    def generate(self, system: str, user: str) -> str:
        body = {"model": self.model,
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": user}]}
        if os.environ.get("LLM_FAST_GENERATE", "1") != "0":
            from chashibondhu.assistant.llm.streaming import reasoning_effort
            effort = reasoning_effort(self.model)
            if effort:          # gpt-oss thinks before answering; "low" cuts that wait (FOSHOLI_REASONING)
                body["reasoning_effort"] = effort
        try:
            r = self._session.post(self._url, json=body, timeout=self.timeout,
                                   headers={"Authorization": f"Bearer {self._key}"})
        except requests.RequestException as e:
            raise LLMError(f"network error calling {self.provider}: {type(e).__name__}") from None
        if r.status_code == 429:
            raise RateLimited(f"{self.provider} rate limit reached; try again later")
        if r.status_code != 200:
            try:
                msg = str(r.json().get("error", {}).get("message", ""))[:200]
            except (ValueError, AttributeError):
                msg = ""
            raise LLMError(f"{self.provider} HTTP {r.status_code}: {msg}")
        try:
            text = r.json()["choices"][0]["message"].get("content") or ""
        except (ValueError, KeyError, IndexError, TypeError):
            raise LLMError(f"{self.provider} returned an unexpected response") from None
        if not text.strip():
            raise LLMError(f"{self.provider} returned empty text")
        return text.strip()


def fallback_enabled() -> bool:
    """Gemma fallback is on when GEMINI_API_KEY is set and LLM_FALLBACK is not 'off'."""
    off = os.environ.get("LLM_FALLBACK", "gemma").strip().lower() in ("off", "0", "no", "none")
    return not off and bool(os.environ.get("GEMINI_API_KEY", "").strip())


def llm_from_env(root: Path | None = None):
    """Build the LLM client chosen in .env (default: groq, with Gemma fallback)."""
    load_dotenv_if_present(root)
    provider = os.environ.get("LLM_PROVIDER", "groq").strip().lower()
    if provider == "groq":
        groq = OpenAICompatClient(GROQ_URL, os.environ.get("GROQ_API_KEY", "").strip(),
                                  os.environ.get("GROQ_MODEL", GROQ_DEFAULT_MODEL).strip()
                                  or GROQ_DEFAULT_MODEL, provider="groq")
        if fallback_enabled():
            from chashibondhu.assistant.llm.fallback import FallbackChain
            from chashibondhu.assistant.llm.gemma import GemmaTextClient
            return FallbackChain([groq, GemmaTextClient.from_env(root)])
        return groq
    if provider == "gemini":
        return GeminiClient.from_env(root)
    if provider == "custom":
        return OpenAICompatClient(os.environ.get("LLM_BASE_URL", ""),
                                  os.environ.get("LLM_API_KEY", "").strip(),
                                  os.environ.get("LLM_MODEL", "").strip(), provider="custom")
    raise LLMError(f"unknown LLM_PROVIDER '{provider}' (use groq, gemini or custom)")
