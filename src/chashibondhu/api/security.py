"""Shared-secret check for AI endpoints (Phase 9b).

When CHASHIBONDHU_API_KEY is set in .env, requests to /assistant/* and /photo/* must send
the header  X-API-Key: <same value>  (the PHP site does this in ai_proxy.php).
When it is not set (local development), the endpoints stay open, e.g. for the /chat test page.
"""
from __future__ import annotations

import hmac
import os
from functools import lru_cache
from typing import Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

PROTECTED_PREFIXES = ("/assistant", "/photo")


@lru_cache(maxsize=1)
def configured_key() -> str:
    from chashibondhu.api.config import get_settings
    from chashibondhu.assistant.llm.gemini import load_dotenv_if_present
    load_dotenv_if_present(get_settings().root)
    return os.environ.get("CHASHIBONDHU_API_KEY", "").strip()


def install_api_key_check(app: FastAPI, key_fn: Callable[[], str] = configured_key) -> None:
    @app.middleware("http")
    async def _require_api_key(request: Request, call_next):
        key = key_fn()
        if key and request.url.path.startswith(PROTECTED_PREFIXES):
            given = request.headers.get("x-api-key", "")
            if not hmac.compare_digest(given.encode("utf-8"), key.encode("utf-8")):
                return JSONResponse(status_code=401, content={"detail": "missing or wrong API key"})
        return await call_next(request)
