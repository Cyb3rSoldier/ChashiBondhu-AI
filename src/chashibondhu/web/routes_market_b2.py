"""Marketplace Phase B2: product comparison (session list, max 4; open to everyone).

Mounted from routes_market.py. The list lives in the visitor's session, nothing is stored in the database.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from chashibondhu.web import compare, repo_market_b2 as b2
from chashibondhu.web.deps import check_csrf, flash, render

router = APIRouter(include_in_schema=False)


def compare_ids(request: Request) -> list[int]:
    return compare.clean_ids(request.session.get("compare"))


@router.post("/compare/toggle")
def toggle(request: Request, listing_id: Annotated[int, Form()], csrf: Annotated[str, Form()] = "",
           go: Annotated[str, Form()] = ""):
    check_csrf(request, csrf)
    ids = compare_ids(request)
    if listing_id in ids:
        ids.remove(listing_id)
        flash(request, "ok", "তুলনা থেকে সরানো হয়েছে।", "Removed from comparison.")
    elif len(ids) >= compare.MAX_ITEMS:
        flash(request, "bad", f"একসাথে সর্বোচ্চ {compare.MAX_ITEMS}টি পণ্য তুলনা করা যায়।",
              f"You can compare up to {compare.MAX_ITEMS} products at a time.")
    else:
        ids.append(listing_id)
        flash(request, "ok", "তুলনায় যোগ হয়েছে।", "Added to comparison.")
    request.session["compare"] = ids
    target = "/compare" if go == "1" else f"/market/{listing_id}"
    return RedirectResponse(target, status_code=303)


@router.post("/compare/clear")
def clear(request: Request, csrf: Annotated[str, Form()] = ""):
    check_csrf(request, csrf)
    request.session["compare"] = []
    return RedirectResponse("/compare", status_code=303)


@router.get("/compare")
def compare_page(request: Request):
    ids = compare_ids(request)
    rows = b2.compare_rows(ids)
    found = {r["id"] for r in rows}
    if found != set(ids):                       # drop products that are no longer for sale
        request.session["compare"] = [i for i in ids if i in found]
    rows.sort(key=lambda r: ids.index(r["id"]))
    groups, alone = compare.groups(rows)
    return render(request, "market/compare.html", {"groups": groups, "alone": alone, "count": len(rows),
                                                   "base_label": compare.BASE_LABEL, "active": "market"})
