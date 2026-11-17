"""Admin A3 pages + public articles.
  notifications -> /admin-announcements      content   -> /admin-content (+ public /articles)
  products      -> /admin-harvest            audit     -> /admin-sync (offline sync log, Security Center)
  analytics     -> /admin-analytics (+ CSV)
Mounted from routes_admin.py. Permissions are checked on the server."""
from __future__ import annotations

import re
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response

from chashibondhu.web import notify, repo_admin as ra, repo_admin_a3 as r3
from chashibondhu.web.deps import check_csrf, flash, render
from chashibondhu.web.routes_admin import _ctx, _int, _page, _reason, _say, require_perm
from chashibondhu.web.routes_admin_a2 import _date, _say2

router = APIRouter(include_in_schema=False)


def _clean(v, n: int) -> str:
    return str(v or "").strip()[:n]


# ================================================================ announcements
@router.get("/admin-announcements")
def ann_page(request: Request):
    admin = require_perm(request, "notifications")
    return render(request, "admin/announcements.html", _ctx(
        admin, "announcements", rows=r3.announcements(), form={},
        email_ok=notify.mail_enabled(), sms_ok=notify.sms_enabled()))


@router.post("/admin-announcements/new")
def ann_new(request: Request, title: Annotated[str, Form()] = "", body: Annotated[str, Form()] = "",
            audience: Annotated[str, Form()] = "all", publish: Annotated[str, Form()] = "",
            notify_now: Annotated[str, Form()] = "", csrf: Annotated[str, Form()] = ""):
    admin = require_perm(request, "notifications")
    check_csrf(request, csrf)
    t, b = " ".join(title.split())[:120], body.strip()[:3000]
    if len(t) < 3 or len(b) < 5 or audience not in r3.AUDIENCE_ROLES:
        flash(request, "bad", "শিরোনাম (৩+) ও লেখা (৫+ অক্ষর) দিন।", "Write a title (3+) and a message (5+ characters).")
    else:
        r3.create_announcement(admin["id"], t, b, audience, publish == "1", notify_now == "1")
        flash(request, "ok", "সংরক্ষণ হয়েছে।", "Saved.")
    return RedirectResponse("/admin-announcements", status_code=303)


@router.post("/admin-announcements/{aid}/{action}")
def ann_action(request: Request, aid: int, action: str, csrf: Annotated[str, Form()] = ""):
    if action not in ("publish", "notify", "archive", "restore"):
        raise HTTPException(status_code=404)
    admin = require_perm(request, "notifications")
    check_csrf(request, csrf)
    _say2(request, r3.announcement_action(admin["id"], aid, action))
    return RedirectResponse("/admin-announcements", status_code=303)


# ================================================================ content
KINDS = {"article": ("কৃষি লেখা", "Article"), "news": ("খবর", "News"), "video": ("ভিডিও", "Video")}


@router.get("/admin-content")
def content_page(request: Request, page: str = "1"):
    admin = require_perm(request, "content")
    p = request.query_params
    f = {"status": p.get("status") if p.get("status") in ("draft", "published", "archived") else "",
         "kind": p.get("kind") if p.get("kind") in KINDS else ""}
    rows, total = r3.content_list(f, _page(page))
    return render(request, "admin/content.html", _ctx(admin, "content", rows=rows, total=total, f=f, kinds=KINDS,
                                                      page=_page(page), page_size=ra.PAGE))


@router.get("/admin-content/{cid}")
def content_edit(request: Request, cid: str):
    admin = require_perm(request, "content")
    item = {} if cid == "new" else r3.content_get(_int(cid) or 0)
    if item is None:
        raise HTTPException(status_code=404)
    return render(request, "admin/content_edit.html", _ctx(admin, "content", item=item, kinds=KINDS, errors=[]))


@router.post("/admin-content/{cid}")
async def content_post(request: Request, cid: str):
    admin = require_perm(request, "content")
    form = await request.form()
    check_csrf(request, form.get("csrf"))
    item_id = None if cid == "new" else _int(cid)
    if cid != "new" and not (item_id and r3.content_get(item_id)):
        raise HTTPException(status_code=404)
    action = form.get("action", "save")
    if action in ("published", "archived", "draft") and item_id:
        _say(request, r3.content_status(admin["id"], item_id, action,
                                        date.fromisoformat(_date(form.get("published_at"))) if _date(form.get("published_at")) else None))
        return RedirectResponse(f"/admin-content/{item_id}", status_code=303)
    data = {"kind": form.get("kind") if form.get("kind") in KINDS else "", "title": " ".join(_clean(form.get("title"), 160).split()),
            "summary": _clean(form.get("summary"), 400) or None, "body": _clean(form.get("body"), 20000),
            "media_url": _clean(form.get("media_url"), 500) or None, "source_name": _clean(form.get("source_name"), 160) or None,
            "source_url": _clean(form.get("source_url"), 500) or None}
    errors = []
    if not data["kind"]:
        errors.append(("ধরন বেছে নিন।", "Choose a type."))
    if len(data["title"]) < 3:
        errors.append(("শিরোনাম দিন (৩+ অক্ষর)।", "Write a title (3+ characters)."))
    if len(data["body"]) < 10:
        errors.append(("লেখা দিন (১০+ অক্ষর)।", "Write the text (10+ characters)."))
    if data["media_url"] and not re.match(r"^https://", data["media_url"]):
        errors.append(("ভিডিও লিংক https:// দিয়ে শুরু হতে হবে।", "The video link must start with https://."))
    if data["source_url"] and not re.match(r"^https?://", data["source_url"]):
        errors.append(("উৎসের লিংক http(s):// দিয়ে শুরু হতে হবে।", "The source link must start with http(s)://."))
    if data["kind"] == "news" and not data["source_name"]:
        errors.append(("খবরের উৎস লিখুন।", "News needs a source."))
    if errors:
        return render(request, "admin/content_edit.html", _ctx(admin, "content", item={**data, "id": item_id},
                                                                kinds=KINDS, errors=errors), status_code=400)
    new_id = r3.content_save(admin["id"], item_id, data)
    flash(request, "ok", "সংরক্ষণ হয়েছে।", "Saved.")
    return RedirectResponse(f"/admin-content/{new_id}", status_code=303)


@router.get("/articles")
def public_list(request: Request):
    return render(request, "content/list.html", {"rows": r3.public_posts(), "kinds": KINDS, "active": "articles"})


@router.get("/articles/{cid}")
def public_detail(request: Request, cid: int):
    post = r3.public_post(cid)
    if not post:
        raise HTTPException(status_code=404)
    return render(request, "content/detail.html", {"post": post, "kinds": KINDS, "active": "articles"})


# ================================================================ pre-harvest monitoring
@router.get("/admin-harvest")
def harvest_page(request: Request, tab: str = "forecasts", page: str = "1"):
    admin = require_perm(request, "products")
    tab = tab if tab in ("forecasts", "requests", "matches") else "forecasts"
    p = request.query_params
    f = {"q": " ".join(str(p.get("q") or "").split())[:60],
         "status": re.sub(r"[^a-z_]", "", str(p.get("status") or ""))[:20]}
    fn = {"forecasts": r3.forecasts, "requests": r3.demand_requests, "matches": r3.matches}[tab]
    rows, total = fn(f, _page(page))
    return render(request, "admin/harvest.html", _ctx(admin, "harvest", tab=tab, rows=rows, total=total, f=f,
                                                      c=r3.harvest_counts(), page=_page(page), page_size=ra.PAGE))


@router.post("/admin-harvest/{kind}/{rec_id}/cancel")
def harvest_cancel(request: Request, kind: str, rec_id: int, reason: Annotated[str, Form()] = "",
                   csrf: Annotated[str, Form()] = ""):
    if kind not in ("forecast", "request"):
        raise HTTPException(status_code=404)
    admin = require_perm(request, "products")
    check_csrf(request, csrf)
    why = _reason(reason)
    if not why:
        _say(request, "reason")
    else:
        _say2(request, r3.admin_cancel(admin["id"], kind, rec_id, why))
    return RedirectResponse(f"/admin-harvest?tab={'forecasts' if kind == 'forecast' else 'requests'}", status_code=303)


# ================================================================ offline sync log (Security Center)
@router.get("/admin-sync")
def sync_page(request: Request, page: str = "1"):
    admin = require_perm(request, "audit")
    p = request.query_params
    f = {"result": p.get("result") if p.get("result") in ("problems", "created", "updated", "duplicate", "conflict",
                                                         "rejected", "error") else "",
         "farmer": _int(p.get("farmer"))}
    rows, total, summary = r3.sync_events(f, _page(page))
    return render(request, "admin/sync.html", _ctx(admin, "sync", rows=rows, total=total, f=f, summary=summary,
                                                   page=_page(page), page_size=ra.PAGE))


# ================================================================ analytics + export
def _range(request: Request) -> tuple[date, date]:
    p = request.query_params
    a, b = _date(p.get("from")), _date(p.get("to"))
    return r3.clamp_range(date.fromisoformat(a) if a else None, date.fromisoformat(b) if b else None)


@router.get("/admin-analytics")
def analytics_page(request: Request, report: str = "orders"):
    admin = require_perm(request, "analytics")
    report = report if report in r3.REPORTS else "orders"
    a, b = _range(request)
    headers, rows = r3.report(report, a, b)
    return render(request, "admin/analytics.html", _ctx(
        admin, "analytics", report=report, reports=r3.REPORTS, headers=headers, rows=rows, d_from=a, d_to=b,
        ai_bad=r3.ai_negative_feedback() if report == "ai" else []))


@router.get("/admin-analytics/{report}.csv")
def analytics_csv(request: Request, report: str):
    admin = require_perm(request, "analytics")
    if report not in r3.REPORTS:
        raise HTTPException(status_code=404)
    a, b = _range(request)
    headers, rows = r3.report(report, a, b)
    ra.audit(admin["id"], f"export.report.{report}", meta={"from": a, "to": b, "rows": len(rows)})
    return Response(r3.to_csv(headers, rows), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="chashibondhu-{report}-{a}-{b}.csv"',
                             "Cache-Control": "no-store"})
