"""AI Assistance hub + Fosholi (AI-1). Mounted from routes_ai.py.

  GET  /assistant              two cards: Fosholi, Dr. Krishi
  GET  /assistant/fosholi      Fosholi chat (history of the current Fosholi conversation)
  POST /app/fosholi/ask        JSON {"question"} -> NDJSON stream of checked sentences (X-CSRF-Token header)
  POST /app/fosholi/new        start a new Fosholi conversation
  GET  /assistant/drkrishi     Dr. Krishi chat (photos, weather, climate history, general questions)
  POST /app/drkrishi/ask       multipart: question, area (BD code, optional), image (optional) -> NDJSON stream
  POST /app/drkrishi/new       start a new Dr. Krishi conversation
  GET  /assistant/<a>?c=ID     open one of the user's own earlier chats (a = fosholi | drkrishi)
  GET  /app/<a>/conversations?q=         sidebar list (JSON), q searches titles
  POST /app/<a>/conversations/ID/rename  JSON {"title"}
  POST /app/<a>/conversations/ID/delete  hides the chat (kept for admin feedback statistics)
Access: farmers + admins only (same rule as the old assistant, checked on the server).
The old page is still at /assistant/classic.
"""
from __future__ import annotations

import json
import logging
import re

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, StreamingResponse

from chashibondhu.web import repo, repo_ai2
from chashibondhu.web.deps import check_csrf, render, require_any_role

log = logging.getLogger("chashibondhu.web.ai")
router = APIRouter(include_in_schema=False)
AI_ROLES = ("farmer", "admin")
SESSION_KEY = {"fosholi": "ai_conv_fosholi", "drkrishi": "ai_conv_drkrishi"}


def _routes_ai():
    from chashibondhu.web import routes_ai
    return routes_ai


def conversation(request: Request, user: dict, assistant: str, create: bool) -> int | None:
    """The user's current conversation of THIS assistant (kept in the session, checked in the database)."""
    key = SESSION_KEY[assistant]
    conv = request.session.get(key)
    try:
        if conv and repo_ai2.owns(int(conv), int(user["id"]), assistant):
            return int(conv)
        if not create:
            return None
        conv = repo_ai2.new_conversation(int(user["id"]), assistant)
    except Exception:  # noqa: BLE001 - chat still works without history
        log.exception("conversation unavailable")
        return None
    request.session[key] = conv
    return conv


@router.get("/assistant")
def hub(request: Request, q: str = "", photo: str = ""):
    require_any_role(request, AI_ROLES)
    if photo == "1":
        return RedirectResponse("/assistant/drkrishi", status_code=303)
    if q.strip():
        from urllib.parse import quote
        return RedirectResponse(f"/assistant/fosholi?q={quote(q[:500])}", status_code=303)
    return render(request, "ai/hub.html", {"active": "ai"})


@router.get("/assistant/fosholi")
def fosholi_page(request: Request, q: str = "", c: str = ""):
    _warm_up()
    return _chat_page(request, "fosholi", q, c)


def _open(request: Request, user: dict, assistant: str, c: str) -> int | None:
    """?c=ID switches the current chat, only to the user's own visible chat of this assistant."""
    if c.isdigit():
        try:
            if repo_ai2.owns(int(c), int(user["id"]), assistant):
                request.session[SESSION_KEY[assistant]] = int(c)
        except Exception:  # noqa: BLE001
            log.exception("could not open conversation")
    return conversation(request, user, assistant, create=False)


def _chat_page(request: Request, assistant: str, q: str = "", c: str = "", extra: dict | None = None):
    user = require_any_role(request, AI_ROLES)
    conv = _open(request, user, assistant, c)
    history = []
    if conv:
        try:
            history = repo_ai2.messages(conv, int(user["id"]), assistant)
        except Exception:  # noqa: BLE001
            log.exception("history unavailable")
    data = [{"id": m["id"], "role": m["role"], "kind": m.get("kind") or "text", "content": m["content"],
             "sources": m.get("sources") or [], "payload": m.get("payload"),
             "at": m["created_at"].isoformat() if hasattr(m.get("created_at"), "isoformat") else None} for m in history]
    ctx = {"active": "ai", "assistant": assistant, "conv_id": conv or "", "history_json": data,
           "start_q": q[:500], "districts": [], "home_area": ""}
    ctx.update(extra or {})
    return render(request, "ai/chat.html", ctx)


# ------------------------------------------------------------------ sidebar (both assistants)
def _api_user(request: Request):
    ra = _routes_ai()
    if (denied := ra._ai_denied(request)) is not None:
        return None, denied
    from chashibondhu.web.deps import current_user
    return current_user(request), None


@router.get("/app/{assistant}/conversations")
def list_conversations(request: Request, assistant: str, q: str = ""):
    if assistant not in SESSION_KEY:
        return _routes_ai()._err(404, "not_found")
    user, denied = _api_user(request)
    if denied is not None:
        return denied
    try:
        rows = repo_ai2.conversations(int(user["id"]), assistant, q)
    except Exception:  # noqa: BLE001
        log.exception("conversation list failed")
        return _routes_ai()._err(503, "history_down")
    return {"items": [{"id": r["id"], "title": r["title"],
                       "at": r["updated_at"].isoformat() if hasattr(r["updated_at"], "isoformat") else r["updated_at"]}
                      for r in rows]}


@router.post("/app/{assistant}/conversations/{conv_id}/{action}")
async def change_conversation(request: Request, assistant: str, conv_id: int, action: str):
    check_csrf(request, request.headers.get("x-csrf-token"))
    if assistant not in SESSION_KEY or action not in ("rename", "delete"):
        return _routes_ai()._err(404, "not_found")
    user, denied = _api_user(request)
    if denied is not None:
        return denied
    uid = int(user["id"])
    try:
        if action == "rename":
            try:
                title = str((await request.json() or {}).get("title", ""))
            except ValueError:
                return _routes_ai()._err(422, "bad_json")
            if not 1 <= len(" ".join(title.split())) <= repo_ai2.TITLE_MAX:
                return _routes_ai()._err(422, "title_length")
            ok = repo_ai2.rename(conv_id, uid, assistant, title)
        else:
            ok = repo_ai2.hide(conv_id, uid, assistant)
            if ok and request.session.get(SESSION_KEY[assistant]) == conv_id:
                request.session.pop(SESSION_KEY[assistant], None)
    except Exception:  # noqa: BLE001
        log.exception("conversation change failed")
        return _routes_ai()._err(503, "history_down")
    return {"ok": True} if ok else _routes_ai()._err(404, "not_found")


_warming = {"started": False}


def _warm_up() -> None:
    """Load the handbook index + embedding model in the background when the chat page opens,
    so the farmer's first question does not also wait for loading (it is loaded only once per server)."""
    if _warming["started"]:
        return
    _warming["started"] = True
    import threading

    def run():
        try:
            _routes_ai().load_assistant()
        except Exception:  # noqa: BLE001 - the question itself will report the problem
            log.exception("warm-up failed")
            _warming["started"] = False
    threading.Thread(target=run, daemon=True).start()


@router.post("/app/fosholi/new")
def fosholi_new(request: Request):
    check_csrf(request, request.headers.get("x-csrf-token"))
    ra = _routes_ai()
    if (denied := ra._ai_denied(request)) is not None:
        return denied
    request.session.pop(SESSION_KEY["fosholi"], None)
    return {"ok": True}


@router.post("/app/fosholi/ask")
async def fosholi_ask(request: Request):
    check_csrf(request, request.headers.get("x-csrf-token"))
    ra = _routes_ai()
    if (denied := ra._ai_denied(request)) is not None:
        return denied
    try:
        body = await request.json()
    except ValueError:
        return ra._err(422, "bad_json")
    q = " ".join(str((body or {}).get("question", "")).split())
    if not 2 <= len(q) <= 500:
        return ra._err(422, "question_length")
    if not ra._rate_ok(request):
        return ra._err(429, "too_many")
    try:
        assistant = ra.load_assistant()
    except Exception:  # noqa: BLE001 - index or key missing
        log.exception("assistant not available")
        return ra._err(503, "ai_down")
    from chashibondhu.web.deps import current_user
    user = current_user(request)
    conv = conversation(request, user, "fosholi", create=True)

    def events():
        from chashibondhu.assistant.fosholi import ask_stream
        try:
            for ev in ask_stream(assistant, q):
                if ev["t"] == "done":
                    ev["message_id"] = _save(conv, q, ev)
                    ev["conv_id"] = conv
                yield json.dumps(ev, ensure_ascii=False, default=str) + "\n"
        except Exception:  # noqa: BLE001 - never leave the browser waiting
            log.exception("fosholi stream failed")
            yield json.dumps({"t": "error", "code": "ai_error"}) + "\n"

    return StreamingResponse(events(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


def _save(conv: int | None, q: str, done: dict) -> int | None:
    if conv is None:
        return None
    try:
        repo.add_ai_message(conv, "user", q)
        return repo.add_ai_message(conv, "assistant", done.get("answer") or "", status=done.get("status"),
                                   sources=done.get("sources"), model=done.get("model"))
    except Exception:  # noqa: BLE001
        log.exception("could not save Fosholi message")
        return None


# ================================================================ Dr. Krishi (AI-2)
_vision_cache: dict = {}


def load_vision():
    """Groq vision (+ Gemma fallback), the same models as the old photo help. Loaded once."""
    if "v" not in _vision_cache:
        from chashibondhu.assistant.vision.client import VisionClient
        _vision_cache["v"] = VisionClient.from_env()
    return _vision_cache["v"]


def load_text_llm():
    from chashibondhu.assistant.llm.openai_compat import llm_from_env
    if "t" not in _vision_cache:
        _vision_cache["t"] = llm_from_env()
    return _vision_cache["t"]


def _districts() -> list[dict]:
    from chashibondhu.web import geo_points
    pts = [p for c, p in geo_points._points().items() if len(c) == 6]
    return sorted(pts, key=lambda p: p["name_en"])


@router.get("/assistant/drkrishi")
def drkrishi_page(request: Request, q: str = "", c: str = ""):
    user = require_any_role(request, AI_ROLES)
    try:
        home = repo_ai2.user_area(int(user["id"]))
    except Exception:  # noqa: BLE001
        home = None
    return _chat_page(request, "drkrishi", q, c, {"home_area": home or "", "districts": _districts()})


@router.post("/app/drkrishi/new")
def drkrishi_new(request: Request):
    check_csrf(request, request.headers.get("x-csrf-token"))
    ra = _routes_ai()
    if (denied := ra._ai_denied(request)) is not None:
        return denied
    request.session.pop(SESSION_KEY["drkrishi"], None)
    return {"ok": True}


@router.post("/app/drkrishi/ask")
async def drkrishi_ask(request: Request):
    check_csrf(request, request.headers.get("x-csrf-token"))
    ra = _routes_ai()
    if (denied := ra._ai_denied(request)) is not None:
        return denied
    form = await request.form()
    q = " ".join(str(form.get("question") or "").split())[:500]
    upload = form.get("image")
    has_image = hasattr(upload, "read") and bool(getattr(upload, "filename", ""))
    if not has_image and len(q) < 2:
        return ra._err(422, "question_length")
    if not ra._rate_ok(request):
        return ra._err(429, "too_many")
    jpeg = None
    if has_image:
        from chashibondhu.assistant.vision.image_prep import MAX_UPLOAD_BYTES, ImageError, prepare_image
        try:
            jpeg = prepare_image(await upload.read(MAX_UPLOAD_BYTES + 1)).jpeg   # GPS / EXIF removed here
        except ImageError:
            return ra._err(422, "not_image")
    from chashibondhu.web import drkrishi_tools as tools, geo_points
    from chashibondhu.web.deps import current_user
    user = current_user(request)
    code = str(form.get("area") or "")
    if not re.fullmatch(r"BD\d{4}(\d{4})?", code):
        try:
            code = repo_ai2.user_area(int(user["id"])) or ""
        except Exception:  # noqa: BLE001
            code = ""
    area = geo_points.point(code) if code else None
    found = tools.intents(q, has_image)
    try:
        llm = load_text_llm()
        vision = load_vision() if has_image else None
    except Exception:  # noqa: BLE001 - keys missing
        log.exception("Dr. Krishi models not available")
        return ra._err(503, "ai_down")
    conv = conversation(request, user, "drkrishi", create=True)
    try:
        history = repo_ai2.messages(conv, int(user["id"]), "drkrishi", limit=8) if conv else []
    except Exception:  # noqa: BLE001
        history = []

    def events():
        from chashibondhu.assistant.drkrishi import answer
        try:
            for ev in answer(q, llm=llm, intents=found, history=history, image_jpeg=jpeg, vision=vision,
                             weather_fn=tools.weather, climate_fn=tools.climate, area=area,
                             numbers_of=tools.numbers_of):
                if ev["t"] == "done":
                    ev["message_id"] = _save_dr(conv, q, has_image, ev)
                    ev["conv_id"] = conv
                yield json.dumps(ev, ensure_ascii=False, default=str) + "\n"
        except Exception:  # noqa: BLE001
            log.exception("Dr. Krishi stream failed")
            yield json.dumps({"t": "error", "code": "ai_error"}) + "\n"

    return StreamingResponse(events(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


PHOTO_ONLY = "ছবি পাঠানো হয়েছে"


def _save_dr(conv: int | None, q: str, has_image: bool, done: dict) -> int | None:
    if conv is None:
        return None
    try:
        repo.add_ai_message(conv, "user", q or PHOTO_ONLY, kind="photo" if has_image else "text")
        mid = repo.add_ai_message(conv, "assistant", done.get("answer") or "", kind="photo" if has_image else "text",
                                  model=done.get("model"))
        p = done.get("payload")
        if p:
            repo_ai2.set_payload(mid, p)
            if not q and p.get("crop", {}).get("key"):
                name = p["crop"]["bn"] + (" — " + p["diagnosis"]["bn"] if p.get("diagnosis") else "")
                repo_ai2.retitle(conv, PHOTO_ONLY, "ছবি: " + name)
        return mid
    except Exception:  # noqa: BLE001
        log.exception("could not save Dr. Krishi message")
        return None
