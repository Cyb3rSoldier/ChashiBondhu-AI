"""POST /assistant/ask (Phase 7). Loaded lazily: the rest of the API works even if the
book index or the Gemini key is missing (then this endpoint returns 503)."""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from chashibondhu.api.config import get_settings

log = logging.getLogger("chashibondhu.api")
router = APIRouter(prefix="/assistant", tags=["assistant"])


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    question: str = Field(min_length=2, max_length=500, examples=["আলু কখন লাগাতে হয়?"])


class SourceOut(BaseModel):
    n: int
    source: str
    source_id: str
    printed_page: int | None = None
    pdf_page: int
    excerpt: str


class AskResponse(BaseModel):
    question: str
    status: str     # verified | verified_and_advice | advice_only | need_more_info
    answer: str     # full farmer-facing text with ✅ / 💡 labels
    verified: str   # book-verified part only ("" if none)
    advice: str     # AI advice part only ("" if none)
    sources: list[SourceOut]
    removed_sentences: list[str]
    notes: list[str]
    search_query: str
    model: str
    cached: bool
    llm_requests: int


@lru_cache(maxsize=1)
def _load_assistant():
    from chashibondhu.assistant.service import Assistant
    return Assistant.from_env(get_settings().root)


def get_assistant():
    try:
        return _load_assistant()
    except Exception as e:  # index missing, key missing, model download failed ...
        log.exception("assistant load failed")
        raise HTTPException(status_code=503,
                            detail=f"assistant not available: {type(e).__name__}: {e}") from e


Asst = Annotated[object, Depends(get_assistant)]


@router.post("/ask", response_model=AskResponse)
def ask(req: AskRequest, assistant: Asst) -> AskResponse:
    from chashibondhu.assistant.llm.gemini import LLMError
    try:
        result = assistant.ask(req.question)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except LLMError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    if result["status"] == "rate_limited":
        raise HTTPException(status_code=429, detail=result["answer"])
    return AskResponse(**result)
