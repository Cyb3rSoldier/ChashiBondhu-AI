"""Farm assistant inside the website (same server, so the AI is called directly, no HTTP key).

  GET  /assistant/classic    old chat page (questions + photo help); /assistant is now the AI hub
  POST /app/ai/ask           JSON {"question": "..."}         (header X-CSRF-Token)
  GET  /app/ai/crops         crops for photo help
  POST /app/ai/photo         multipart: crop_id, note, image   (header X-CSRF-Token)
  POST /app/ai/feedback      JSON {"message_id": 1, "helpful": true}

Every question and answer is saved (ai_conversations / ai_messages); photos are NOT saved.
Rate limit per browser session protects the free AI quota.

Access: ONLY logged-in farmers and admins (customers and guests are refused by the server,
not just hidden in the menu). The separate developer API (/assistant/ask with X-API-Key) is unchanged.
"""
from __future__ import annotations

import logging
import time
from typing import Annotated

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse

from chashibondhu.web import repo
from chashibondhu.web.deps import check_csrf, current_user, render, require_any_role

log = logging.getLogger("chashibondhu.web")
router = APIRouter(include_in_schema=False)

LIMIT_GUEST, LIMIT_USER = 15, 60          # AI requests per hour per session
AI_ROLES = ("farmer", "admin")


def _ai_denied(request: Request) -> JSONResponse | None:
    """None if this session may use the AI, else the JSON error to return."""
    user = current_user(request)
    if not user:
        return _err(401, "login_required")
    if user.get("role") not in AI_ROLES:
        return _err(403, "not_allowed")
    return None


def load_assistant():
    from chashibondhu.api.assistant_routes import _load_assistant
    return _load_assistant()


def load_diagnoser():
    from chashibondhu.api.photo_routes import _load_diagnoser
    return _load_diagnoser()


def _err(status: int, code: str) -> JSONResponse:
    return JSONResponse({"detail": code}, status_code=status)


def _rate_ok(request: Request) -> bool:
    now = time.time()
    hits = [h for h in request.session.get("ai_hits", []) if h > now - 3600]
    limit = LIMIT_USER if current_user(request) else LIMIT_GUEST
    if len(hits) >= limit:
        request.session["ai_hits"] = hits
        return False
    request.session["ai_hits"] = (hits + [now])[-LIMIT_USER:]
    return True


def _conversation(request: Request) -> int | None:
    """Current conversation id (created on first use). None if the database is unavailable."""
    user = current_user(request)
    conv = request.session.get("conv_id")
    if conv and request.session.get("conv_user") == (user or {}).get("id"):
        return conv
    try:
        conv = repo.new_conversation(user["id"] if user else None)
    except Exception:  # noqa: BLE001 - chat still works without history
        log.exception("could not create conversation")
        return None
    request.session["conv_id"], request.session["conv_user"] = conv, (user or {}).get("id")
    return conv


def _save(conv: int | None, *args, **kwargs) -> int | None:
    if conv is None:
        return None
    try:
        return repo.add_ai_message(conv, *args, **kwargs)
    except Exception:  # noqa: BLE001
        log.exception("could not save AI message")
        return None


@router.get("/assistant/classic")
def assistant_page(request: Request, q: str = "", photo: str = ""):
    require_any_role(request, AI_ROLES)
    return render(request, "assistant.html", {"start_q": q[:500], "start_photo": photo == "1", "active": "ai"})


@router.post("/app/ai/new")
def new_chat(request: Request):
    check_csrf(request, request.headers.get("x-csrf-token"))
    if (denied := _ai_denied(request)) is not None:
        return denied
    request.session.pop("conv_id", None)
    return {"ok": True}


@router.post("/app/ai/ask")
async def ask(request: Request):
    check_csrf(request, request.headers.get("x-csrf-token"))
    if (denied := _ai_denied(request)) is not None:
        return denied
    try:
        body = await request.json()
    except ValueError:
        return _err(422, "bad_json")
    q = " ".join(str((body or {}).get("question", "")).split())
    if not 2 <= len(q) <= 500:
        return _err(422, "question_length")
    if not _rate_ok(request):
        return _err(429, "too_many")
    from chashibondhu.assistant.llm.gemini import LLMError
    try:
        result = load_assistant().ask(q)
    except LLMError:
        log.exception("assistant LLM error")
        return _err(502, "ai_error")
    except ValueError:
        return _err(422, "question_length")
    except Exception:  # noqa: BLE001 - index/key missing etc.
        log.exception("assistant not available")
        return _err(503, "ai_down")
    if result.get("status") == "rate_limited":
        return _err(429, "ai_busy")
    conv = _conversation(request)
    _save(conv, "user", q)
    mid = _save(conv, "assistant", result.get("answer", ""), status=result.get("status"),
                sources=result.get("sources"), model=result.get("model"))
    return {**result, "message_id": mid}


@router.get("/app/ai/crops")
def photo_crops(request: Request):
    if (denied := _ai_denied(request)) is not None:
        return denied
    try:
        diag = load_diagnoser()
    except Exception:  # noqa: BLE001
        log.exception("photo help not available")
        return _err(503, "ai_down")
    cat = diag.catalogue
    return [{"crop_id": c.crop_id, "name_bn": c.name_bn, "name_en": c.name_en,
             "n_problems": len(cat.for_crop(c.crop_id))} for c in cat.crops.values()]


@router.post("/app/ai/photo")
async def photo(request: Request, crop_id: Annotated[str, Form(min_length=1, max_length=40)],
                image: Annotated[UploadFile, File()], note: Annotated[str, Form(max_length=200)] = ""):
    check_csrf(request, request.headers.get("x-csrf-token"))
    if (denied := _ai_denied(request)) is not None:
        return denied
    if not _rate_ok(request):
        return _err(429, "too_many")
    from chashibondhu.assistant.llm.gemini import LLMError, RateLimited
    try:
        diag = load_diagnoser()
        from chashibondhu.assistant.vision.image_prep import MAX_UPLOAD_BYTES, ImageError
    except Exception:  # noqa: BLE001
        log.exception("photo help not available")
        return _err(503, "ai_down")
    data = await image.read(MAX_UPLOAD_BYTES + 1)
    try:
        result = diag.diagnose(crop_id.strip(), data, note)
    except KeyError:
        return _err(422, "bad_crop")
    except ImageError:
        return _err(422, "not_image")
    except RateLimited:
        return _err(429, "ai_busy")
    except LLMError:
        log.exception("vision LLM error")
        return _err(502, "ai_error")
    conv = _conversation(request)
    _save(conv, "user", note or "(photo)", kind="photo", crop_id=crop_id)
    mid = _save(conv, "assistant", result.get("message_bn", ""), kind="photo", status=result.get("status"),
                crop_id=crop_id, candidates=result.get("candidates"),
                sources=(result.get("book") or {}).get("sources"), model=result.get("model"))
    return {**result, "message_id": mid}


@router.post("/app/ai/feedback")
async def feedback(request: Request):
    check_csrf(request, request.headers.get("x-csrf-token"))
    if (denied := _ai_denied(request)) is not None:
        return denied
    try:
        body = await request.json()
        mid = int(body.get("message_id"))
        helpful = bool(body.get("helpful"))
    except (ValueError, TypeError, AttributeError):
        return _err(422, "bad_feedback")
    conv = request.session.get("conv_id")
    if not conv or not repo.message_in_conversation(mid, conv):
        return _err(404, "not_found")
    user = current_user(request)
    repo.add_feedback(mid, user["id"] if user else None, helpful, None)
    return {"ok": True}


# AI hub + Fosholi (AI-1) live in routes_ai_hub.py; mounted here so app.py does not change.
from chashibondhu.web.routes_ai_hub import router as _hub_router  # noqa: E402

router.include_router(_hub_router)
