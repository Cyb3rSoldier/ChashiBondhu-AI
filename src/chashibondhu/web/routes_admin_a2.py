"""Admin A2 pages: orders + disputes ('orders'), finance ('finance'), complaints ('complaints').
Mounted from routes_admin.py. Permissions are checked on the server for every page and action."""
from __future__ import annotations

import re
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response

from chashibondhu.web import repo_admin as ra, repo_admin_a2 as r2
from chashibondhu.web.deps import check_csrf, flash, render
from chashibondhu.web.routes_admin import _ctx, _int, _page, _reason, _say, require_perm

router = APIRouter(include_in_schema=False)
MSG = {"not_allowed": ("এই অবস্থায় এটা করা যায় না। পাতাটি আবার খুলে দেখুন।",
                       "This cannot be done in the current state. Reload the page and check.")}


def _say2(request: Request, code: str) -> None:
    if code in MSG:
        flash(request, "bad", *MSG[code])
    else:
        _say(request, code)


def _date(v) -> str:
    try:
        return date.fromisoformat(str(v)).isoformat()
    except (TypeError, ValueError):
        return ""


# ================================================================ orders
@router.get("/admin-orders")
def orders_page(request: Request, page: str = "1"):
    admin = require_perm(request, "orders")
    p = request.query_params
    f = {"q": " ".join(str(p.get("q") or "").split())[:40],
         "status": p.get("status") if p.get("status") in ("pending", "confirmed", "shipped", "delivered", "cancelled") else "",
         "payment": p.get("payment") if p.get("payment") in ("unpaid", "paid", "refunded") else "",
         "farmer": _int(p.get("farmer")), "customer": _int(p.get("customer")),
         "from": _date(p.get("from")), "to": _date(p.get("to"))}
    rows, total = r2.order_list(f, _page(page))
    return render(request, "admin/orders.html", _ctx(admin, "orders", rows=rows, total=total, f=f, page=_page(page),
                                                     page_size=ra.PAGE))


@router.get("/admin-orders/{order_number}")
def order_page(request: Request, order_number: str):
    admin = require_perm(request, "orders")
    o = r2.order_detail(order_number)
    if not o:
        raise HTTPException(status_code=404)
    return render(request, "admin/order_detail.html", _ctx(admin, "orders", o=o))


@router.post("/admin-orders/{order_number}/step")
def order_step(request: Request, order_number: str, step: Annotated[str, Form()],
               reason: Annotated[str, Form()] = "", csrf: Annotated[str, Form()] = ""):
    if step not in ("confirm", "ship", "deliver", "cancel", "paid", "refund"):
        raise HTTPException(status_code=400)
    admin = require_perm(request, "finance" if step in ("paid", "refund") else "orders")
    check_csrf(request, csrf)
    o = r2.order_detail(order_number)
    if not o:
        raise HTTPException(status_code=404)
    why = _reason(reason)
    if step in ("cancel", "refund") and not why:
        _say(request, "reason")
    elif step in ("paid", "refund"):
        _say2(request, r2.payment_step(admin["id"], o["id"], step, why))
    else:
        _say2(request, r2.order_step(admin["id"], o["id"], step, why))
    return RedirectResponse(f"/admin-orders/{order_number}", status_code=303)


# ================================================================ finance
@router.get("/admin-finance")
def finance_page(request: Request, farmer: str = "", page: str = "1"):
    admin = require_perm(request, "finance")
    fid = _int(farmer)
    ledger, total = r2.ledger_rows(fid, _page(page))
    return render(request, "admin/finance.html", _ctx(admin, "finance", s=r2.finance_summary(),
                                                      farmers=r2.farmer_earnings(), ledger=ledger, total=total,
                                                      farmer=fid, page=_page(page), page_size=ra.PAGE))


@router.get("/admin-finance/export/{kind}.csv")
def finance_export(request: Request, kind: str):
    admin = require_perm(request, "finance")
    if kind not in ("payments", "ledger"):
        raise HTTPException(status_code=404)
    body, n = r2.export_csv(kind)
    ra.audit(admin["id"], f"export.{kind}", meta={"rows": n})
    return Response(body, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="chashibondhu-{kind}-{date.today()}.csv"',
                             "Cache-Control": "no-store"})


# ================================================================ complaints
@router.get("/admin-complaints")
def complaints_page(request: Request, page: str = "1"):
    admin = require_perm(request, "complaints")
    p = request.query_params
    st = p.get("status", "active")
    f = {"q": " ".join(str(p.get("q") or "").split())[:60],
         "status": st if st in r2.COMPLAINT_STATUSES + ("active",) else "",
         "category": p.get("category") if re.fullmatch(r"[a-z]{2,20}", p.get("category") or "") else "",
         "role": p.get("role") if p.get("role") in ("farmer", "customer") else "",
         "mine": admin["id"] if p.get("mine") == "1" else None}
    rows, total = r2.complaint_list(f, _page(page))
    return render(request, "admin/complaints.html", _ctx(admin, "complaints", rows=rows, total=total, f=f,
                                                         page=_page(page), page_size=ra.PAGE))


@router.get("/admin-complaints/{complaint_id}")
def complaint_page(request: Request, complaint_id: int):
    admin = require_perm(request, "complaints")
    c = r2.complaint_detail(complaint_id)
    if not c:
        raise HTTPException(status_code=404)
    return render(request, "admin/complaint_detail.html", _ctx(admin, "complaints", c=c, staff=r2.complaint_staff(),
                                                               statuses=r2.COMPLAINT_STATUSES))


@router.post("/admin-complaints/{complaint_id}")
def complaint_post(request: Request, complaint_id: int, csrf: Annotated[str, Form()] = "",
                   status: Annotated[str, Form()] = "", assign: Annotated[str, Form()] = "",
                   reply: Annotated[str, Form()] = "", note: Annotated[str, Form()] = ""):
    admin = require_perm(request, "complaints")
    check_csrf(request, csrf)
    reply_t, note_t = " ".join(reply.split())[:2000], note.strip()[:2000]
    if (reply and len(reply_t) < 2) or (note and len(note_t) < 2):
        _say(request, "reason")
    else:
        _say2(request, r2.complaint_update(
            admin["id"], complaint_id, status=status or None,
            assign=_int(assign) if assign not in ("", "none") else None, unassign=assign == "none",
            reply=reply_t or None, note=note_t or None))
    return RedirectResponse(f"/admin-complaints/{complaint_id}", status_code=303)
