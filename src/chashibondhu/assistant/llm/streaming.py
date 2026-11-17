"""Real streaming from the LLM (Fosholi, AI-1).

Groq (OpenAI-compatible) streams with Server-Sent Events: `"stream": true`, lines `data: {...}`, end `data: [DONE]`.
Clients that cannot stream (Gemma, Gemini) give their whole text as one piece - nothing is faked.
Fallback order is the same as FallbackChain: if the first model fails BEFORE sending anything, the next one answers.
If a model fails in the middle, the error is raised (the UI offers "try again"; no half answer is cached).
"""
from __future__ import annotations

import json
from typing import Iterator

import requests

from chashibondhu.assistant.llm.gemini import LLMError, RateLimited


def reasoning_effort(model: str) -> str | None:
    """FOSHOLI_REASONING=low|medium|high (default low). Only GPT-OSS models on Groq accept it."""
    import os
    if not str(model).startswith("openai/gpt-oss"):
        return None
    v = os.environ.get("FOSHOLI_REASONING", "low").strip().lower()
    return v if v in ("low", "medium", "high") else "low"


def _can_stream(client) -> bool:
    return all(hasattr(client, a) for a in ("_url", "_key", "_session", "model")) and \
        getattr(client, "provider", "") != "gemma"


def stream_chat(client, system: str, user: str) -> Iterator[str]:
    """Yield text pieces from an OpenAICompatClient-like client (Groq)."""
    body = {"model": client.model, "stream": True,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    effort = reasoning_effort(client.model)
    if effort:
        body["reasoning_effort"] = effort      # gpt-oss "thinks" before writing; low = much faster first sentence
    try:
        r = client._session.post(client._url, json=body, timeout=getattr(client, "timeout", 60.0), stream=True,
                                 headers={"Authorization": f"Bearer {client._key}", "Accept": "text/event-stream"})
    except requests.RequestException as e:
        raise LLMError(f"network error calling {getattr(client, 'provider', 'llm')}: {type(e).__name__}") from None
    if r.status_code == 429:
        raise RateLimited("rate limit reached; try again later")
    if r.status_code != 200:
        raise LLMError(f"HTTP {r.status_code} from {getattr(client, 'provider', 'llm')}")
    try:
        for raw in r.iter_lines():
            if not raw:
                continue
            line = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                obj = json.loads(data)
            except ValueError:
                continue
            if obj.get("error"):
                raise LLMError("stream error from the model")
            choices = obj.get("choices") or [{}]
            piece = (choices[0].get("delta") or {}).get("content")
            if piece:
                yield piece
    except requests.RequestException as e:
        raise LLMError(f"stream broken: {type(e).__name__}") from None
    finally:
        r.close()


def stream_text(llm, system: str, user: str, info: dict) -> Iterator[str]:
    """Stream with the site's fallback order. info["model"] = the model that really answered."""
    clients = list(getattr(llm, "clients", None) or [llm])
    last_exc, all_limited = None, True
    for c in clients:
        started = False
        try:
            if _can_stream(c):
                for piece in stream_chat(c, system, user):
                    if not started:
                        started, info["model"] = True, c.model
                    yield piece
            else:
                text = c.generate(system, user)
                started, info["model"] = True, getattr(c, "model", "llm")
                yield text
            if not started:
                raise LLMError("empty answer")
            if hasattr(llm, "last_model"):
                llm.last_model = info["model"]
            return
        except RateLimited as e:
            if started:
                raise
            last_exc = e
        except LLMError as e:
            if started:
                raise
            last_exc, all_limited = e, False
    if all_limited:
        raise RateLimited("all models are rate-limited; try again later")
    raise last_exc or LLMError("no model answered")
