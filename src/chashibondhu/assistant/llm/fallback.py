"""Fallback chain: try clients in order; on rate limit or error, try the next one.

Works for text clients (generate) and vision clients (analyze).
`last_model` / `model` tell which model actually answered (for honest reporting).
If every client was rate-limited, RateLimited is raised, so callers' rate-limit
handling keeps working; otherwise the last LLMError is raised.
"""
from __future__ import annotations

from chashibondhu.assistant.llm.gemini import LLMError, RateLimited


class FallbackChain:
    provider = "fallback"

    def __init__(self, clients: list):
        if not clients:
            raise LLMError("fallback chain is empty")
        self.clients = list(clients)
        self.last_model = ""
        self.last_errors: list[str] = []

    @property
    def model(self) -> str:
        return self.last_model or self.clients[0].model

    @property
    def models(self) -> list[str]:
        return [c.model for c in self.clients]

    def _call(self, method: str, *args):
        self.last_errors, last_exc, all_limited = [], None, True
        for c in self.clients:
            try:
                out = getattr(c, method)(*args)
            except RateLimited as e:
                self.last_errors.append(f"{c.model}: rate limited")
                last_exc = e
            except LLMError as e:
                self.last_errors.append(f"{c.model}: {str(e)[:120]}")
                last_exc, all_limited = e, False
            else:
                self.last_model = c.model
                return out
        self.last_model = ""
        if all_limited:
            raise RateLimited("all models are rate-limited; try again later")
        raise last_exc

    def generate(self, system: str, user: str) -> str:
        return self._call("generate", system, user)

    def analyze(self, system: str, text: str, jpeg: bytes) -> str:
        return self._call("analyze", system, text, jpeg)
