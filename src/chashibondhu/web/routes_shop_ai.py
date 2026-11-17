"""Customer shopping assistant page (Phase B3). Customers only; separate from the farmer AI (/assistant).

GET  /shop-assistant   page with the question box
POST /shop-assistant   ask (CSRF form). Rate limit per session protects the free AI quota.
Nothing is stored and nothing is ordered here.
"""
from __future__ import annotations

import time
from typing import Annotated

from fastapi import APIRouter, Form, Request

from chashibondhu.web import repo, shop_assistant as sa
from chashibondhu.web.deps import check_csrf, crop_ids, render, require_any_role

router = APIRouter(include_in_schema=False)
ME = ("customer",)
LIMIT_PER_HOUR = 30


def _rate_ok(request: Request) -> bool:
    now = time.time()
    hits = [h for h in request.session.get("shop_ai_hits", []) if h > now - 3600]
    if len(hits) >= LIMIT_PER_HOUR:
        request.session["shop_ai_hits"] = hits
        return False
    request.session["shop_ai_hits"] = hits + [now]
    return True


def _page(request: Request, ctx: dict | None = None, status_code: int = 200):
    return render(request, "customer/shop_assistant.html", {"active": "c_shopai", **(ctx or {})},
                  status_code=status_code)


@router.get("/shop-assistant")
def page(request: Request):
    require_any_role(request, ME)
    return _page(request)


@router.post("/shop-assistant")
def ask(request: Request, question: Annotated[str, Form()] = "", csrf: Annotated[str, Form()] = ""):
    require_any_role(request, ME)
    check_csrf(request, csrf)
    q = " ".join(question.split())
    if not 2 <= len(q) <= 300:
        return _page(request, {"q": q, "error": ("২ থেকে ৩০০ অক্ষরে প্রশ্ন লিখুন।", "Write 2 to 300 characters.")},
                     status_code=400)
    if not _rate_ok(request):
        return _page(request, {"q": q, "error": ("এক ঘণ্টায় অনেক প্রশ্ন হয়েছে। একটু পরে আবার চেষ্টা করুন।",
                                                 "Too many questions this hour. Please try again later.")},
                     status_code=429)
    p = sa.parse(q)
    rows, organic_dropped = [], False
    if p["text"]:
        f = {"q": p["text"], "organic": p["organic"], "sort": "price_asc" if p["cheap"] else ""}
        rows, _ = repo.market_search(f, crop_ids(), 1)
        if not rows and p["organic"]:
            rows, _ = repo.market_search({**f, "organic": False}, crop_ids(), 1)
            organic_dropped = bool(rows)
    rows = sa.enrich(rows, p["qty"], p["unit"])
    result = sa.answer(q, rows, p)
    return _page(request, {"q": q, "p": p, "result": result, "organic_dropped": organic_dropped,
                           "no_text": not p["text"]})
