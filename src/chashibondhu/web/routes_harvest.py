"""Phase 2: pre-harvest buyer matching + offline sync.

Farmer:  /farmer/forecasts (list, new, edit, detail, cancel, offer, respond, confirm harvest)
Buyer:   /requests (customer or admin: buyer requests, interest, respond)
Offline: /farmer/drafts (page, filled from IndexedDB by offline.js), /farmer/sync/forecast (JSON),
         /farmer/sync/listing (multipart), /sw.js (service worker at site root)

Rules: a forecast is expected harvest, never stock; a match is interest, never an order; real stock appears
only when the farmer confirms the actual harvest (a normal listing -> existing marketplace + orders).
"""
from __future__ import annotations

import re
import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from starlette.datastructures import UploadFile

from chashibondhu.web import repo
from chashibondhu.web.deps import (WEB_DIR, check_csrf, crop_ids, current_user, flash, render, require_any_role,
                                   require_role)
from chashibondhu.web.routes_farmer import FARMING_METHODS, UNITS, CATEGORIES, _listing_data, parse_date
from chashibondhu.web.routes_public import area_codes, parse_decimal

router = APIRouter(include_in_schema=False)
BUYER_ROLES = ("customer", "admin")
MAX_AHEAD_DAYS = 366

RESULT_MSG = {
    "not_found": ("পাওয়া যায়নি।", "Not found."),
    "closed": ("এটা আর খোলা নেই (বাতিল, শেষ বা মেয়াদ শেষ)।", "This is no longer open (cancelled, finished or expired)."),
    "exists": ("এই দুইটির মধ্যে আগেই যোগাযোগ আছে।", "These two are already connected."),
    "too_much": ("পরিমাণ বেশি হয়ে গেছে। খালি পরিমাণের মধ্যে লিখুন।", "Quantity is too large. Use the free quantity shown."),
    "unit_mismatch": ("একক মেলে না।", "Units do not match."),
    "bad_step": ("এই ধাপে এটা করা যায় না। পাতাটা আবার খুলুন।", "This step is not allowed now. Please reload the page."),
    "conflict": ("অন্য কোথাও থেকে এটি আগেই বদলানো হয়েছে। নতুন তথ্য দেখে আবার বদলান।",
                 "This was changed somewhere else first. Check the newest data and edit again."),
}


def back(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def _msg(request: Request, result: str, ok_bn: str, ok_en: str) -> None:
    if result == "ok":
        flash(request, "ok", ok_bn, ok_en)
    else:
        flash(request, "bad", *RESULT_MSG.get(result, RESULT_MSG["not_found"]))


def _qty(raw) -> Decimal | None:
    try:
        v = parse_decimal(str(raw or ""))
    except ValueError:
        return None
    return v if v is not None and v > 0 else None


def _plan_data(form: dict, kind: str, today: date | None = None) -> tuple[dict, list]:
    """Validate a harvest forecast (kind='forecast') or a buyer request (kind='request')."""
    today = today or date.today()
    errors = []
    qty_key, from_key, to_key = (("expected_qty", "harvest_from", "harvest_to") if kind == "forecast"
                                 else ("quantity", "needed_from", "needed_to"))
    data = {"crop_id": form.get("crop_id") if form.get("crop_id") in crop_ids() else None,
            "product_name": " ".join(str(form.get("product_name") or "").split())[:120],
            "variety": " ".join(str(form.get("variety") or "").split())[:80] or None,
            "unit": form.get("unit") if form.get("unit") in UNITS else None}
    if len(data["product_name"]) < 2:
        errors.append(("ফসল/পণ্যের নাম লিখুন।", "Write the crop or product name."))
    if not data["unit"]:
        errors.append(("একক বেছে নিন।", "Choose a unit."))
    data[qty_key] = _qty(form.get(qty_key))
    if data[qty_key] is None:
        errors.append(("পরিমাণ সঠিক সংখ্যায় লিখুন (০-এর বেশি)।", "Write a quantity above 0."))
    try:
        d1, d2 = parse_date(form.get(from_key)), parse_date(form.get(to_key))
    except ValueError:
        d1 = d2 = None
    if d1 and not d2:
        d2 = d1
    if not d1:
        errors.append(("তারিখ দিন।", "Give the date."))
    elif d2 < d1:
        errors.append(("শেষ তারিখ শুরুর তারিখের পরে হতে হবে।", "The end date must be after the start date."))
    elif d2 < today:
        errors.append(("তারিখ আজকের আগে হতে পারবে না।", "The date cannot be in the past."))
    elif d1 > today + timedelta(days=MAX_AHEAD_DAYS):
        errors.append(("এক বছরের বেশি পরের তারিখ দেওয়া যাবে না।", "The date cannot be more than one year ahead."))
    data[from_key], data[to_key] = d1, d2
    district, upazila = area_codes(form.get("upazila_code"))
    data["district_code"], data["upazila_code"] = district, upazila
    if kind == "forecast":
        data["description"] = str(form.get("description") or "").strip()[:2000] or None
        data["quality_grade"] = " ".join(str(form.get("quality_grade") or "").split())[:60] or None
    else:
        data["note"] = str(form.get("note") or "").strip()[:1000] or None
    return data, errors


def _fill_area(data: dict, user_id: int) -> None:
    """No area chosen -> use the farmer's profile area."""
    if not data.get("district_code"):
        p = repo.get_farmer_profile(user_id)
        data["district_code"], data["upazila_code"] = p.get("district_code"), p.get("upazila_code")


# ================================================================ farmer: forecasts
@router.get("/farmer/forecasts")
def forecasts_page(request: Request):
    user = require_role(request, "farmer")
    repo.expire_stale()
    return render(request, "farmer/forecasts.html", {"items": repo.list_forecasts(user["id"]), "active": "forecasts"})


@router.get("/farmer/forecasts/new")
def forecast_new(request: Request, crop_id: str = ""):
    require_role(request, "farmer")
    item = {"crop_id": crop_id if crop_id in crop_ids() else "", "unit": "kg"}
    return render(request, "farmer/forecast_form.html", {"item": item, "mode": "new", "units": UNITS,
                                                         "active": "forecasts"})


@router.post("/farmer/forecasts/new")
async def forecast_create(request: Request):
    user = require_role(request, "farmer")
    form = dict(await request.form())
    check_csrf(request, form.get("csrf"))
    data, errors = _plan_data(form, "forecast")
    if errors:
        return render(request, "farmer/forecast_form.html", {"item": data, "mode": "new", "units": UNITS,
                                                             "errors": errors, "active": "forecasts"}, status_code=400)
    _fill_area(data, user["id"])
    r = repo.create_forecast(user["id"], data)
    flash(request, "ok", "আগাম ফসলের তথ্য দেওয়া হয়েছে। মিলে যাওয়া ক্রেতা নিচে দেখুন।",
          "Harvest forecast created. See matching buyers below.")
    return back(f"/farmer/forecasts/{r['id']}")


@router.get("/farmer/forecasts/{forecast_id}")
def forecast_detail(request: Request, forecast_id: int):
    user = require_role(request, "farmer")
    f = repo.get_forecast(user["id"], forecast_id)
    if not f:
        raise HTTPException(status_code=404)
    return render(request, "farmer/forecast_detail.html", {
        "f": f, "potential": repo.potential_requests(user["id"], forecast_id) if f["status"] == "open" else [],
        "matches": repo.forecast_matches(user["id"], forecast_id), "methods": FARMING_METHODS,
        "categories": CATEGORIES, "today": date.today().isoformat(), "active": "forecasts"})


@router.get("/farmer/forecasts/{forecast_id}/edit")
def forecast_edit(request: Request, forecast_id: int):
    user = require_role(request, "farmer")
    f = repo.get_forecast(user["id"], forecast_id)
    if not f or f["status"] != "open":
        raise HTTPException(status_code=404)
    return render(request, "farmer/forecast_form.html", {"item": f, "mode": "edit", "units": UNITS,
                                                         "active": "forecasts"})


@router.post("/farmer/forecasts/{forecast_id}/edit")
async def forecast_update(request: Request, forecast_id: int):
    user = require_role(request, "farmer")
    form = dict(await request.form())
    check_csrf(request, form.get("csrf"))
    data, errors = _plan_data(form, "forecast")
    try:
        base = int(form.get("version"))
    except (TypeError, ValueError):
        base = -1                                   # no version -> treat as conflict, never blind overwrite
    if errors:
        return render(request, "farmer/forecast_form.html", {"item": {**data, "id": forecast_id, "version": base},
                                                             "mode": "edit", "units": UNITS, "errors": errors,
                                                             "active": "forecasts"}, status_code=400)
    _fill_area(data, user["id"])
    r = repo.update_forecast(user["id"], forecast_id, data, base)
    if not r["ok"]:
        _msg(request, r["reason"], "", "")
        return back(f"/farmer/forecasts/{forecast_id}")
    flash(request, "ok", "আগাম ফসলের তথ্য বদলানো হয়েছে।", "Forecast updated.")
    return back(f"/farmer/forecasts/{forecast_id}")


@router.post("/farmer/forecasts/{forecast_id}/cancel")
def forecast_cancel(request: Request, forecast_id: int, csrf: Annotated[str, Form()] = ""):
    user = require_role(request, "farmer")
    check_csrf(request, csrf)
    _msg(request, repo.cancel_forecast(user["id"], forecast_id), "আগাম ফসল বাতিল করা হয়েছে।", "Forecast cancelled.")
    return back(f"/farmer/forecasts/{forecast_id}")


@router.post("/farmer/forecasts/{forecast_id}/offer")
def forecast_offer(request: Request, forecast_id: int, request_id: Annotated[int, Form()],
                   qty: Annotated[str, Form()], csrf: Annotated[str, Form()] = ""):
    user = require_role(request, "farmer")
    check_csrf(request, csrf)
    q = _qty(qty)
    result = repo.farmer_offer(user["id"], forecast_id, request_id, q) if q else "too_much"
    _msg(request, result, "ক্রেতাকে প্রস্তাব পাঠানো হয়েছে। ক্রেতার উত্তরের অপেক্ষা।",
         "Offer sent. Waiting for the buyer's answer.")
    return back(f"/farmer/forecasts/{forecast_id}")


@router.post("/farmer/matches/{match_id}/respond")
def farmer_match_respond(request: Request, match_id: int, answer: Annotated[str, Form()],
                         forecast_id: Annotated[int, Form()], csrf: Annotated[str, Form()] = ""):
    user = require_role(request, "farmer")
    check_csrf(request, csrf)
    if answer not in ("accept", "decline"):
        raise HTTPException(status_code=400)
    _msg(request, repo.farmer_respond(user["id"], match_id, answer == "accept"),
         "উত্তর দেওয়া হয়েছে।", "Answer saved.")
    return back(f"/farmer/forecasts/{forecast_id}")


@router.post("/farmer/forecasts/{forecast_id}/confirm")
async def forecast_confirm(request: Request, forecast_id: int):
    user = require_role(request, "farmer")
    form = dict(await request.form())
    check_csrf(request, form.get("csrf"))
    f = repo.get_forecast(user["id"], forecast_id)
    if not f:
        raise HTTPException(status_code=404)
    errors = []
    try:
        actual = parse_decimal(form.get("actual_qty"))
        if actual is None:
            raise ValueError
    except ValueError:
        actual = None
        errors.append(("আসল কত হয়েছে, সংখ্যায় লিখুন (না হলে ০)।", "Write the actual harvest as a number (0 if none)."))
    try:
        hdate = parse_date(form.get("actual_harvest_date"))
    except ValueError:
        hdate = None
    if not hdate or hdate > date.today():
        errors.append(("ফসল তোলার তারিখ দিন (আজ বা আগের দিন)।", "Give the harvest date (today or earlier)."))
    listing = {"title": " ".join(str(form.get("title") or f["product_name"]).split())[:120],
               "category": form.get("category") if form.get("category") in CATEGORIES else "other",
               "farming_method": form.get("farming_method") if form.get("farming_method") in FARMING_METHODS
               else "conventional",
               "description": str(form.get("description") or "").strip()[:2000] or None}
    if actual and actual > 0:
        listing["price_per_unit"] = _qty(form.get("price_per_unit"))
        if listing["price_per_unit"] is None:
            errors.append(("বিক্রির দাম লিখুন (প্রতি একক)।", "Write the selling price per unit."))
        mo = _qty(form.get("min_order"))
        listing["min_order"] = mo or Decimal("1")
    if errors:
        for e in errors:
            flash(request, "bad", *e)
        return back(f"/farmer/forecasts/{forecast_id}#confirm")
    r = repo.confirm_harvest(user["id"], forecast_id, actual, hdate, listing)
    if not r["ok"]:
        _msg(request, r["reason"], "", "")
    elif r["listing_id"]:
        flash(request, "ok", "ফসল তোলা নিশ্চিত হয়েছে। আসল পরিমাণ এখন বাজারে আছে; রাজি হওয়া ক্রেতারা অর্ডার দিতে পারবেন।",
              "Harvest confirmed. The actual quantity is now in the market; agreed buyers can order it.")
    else:
        flash(request, "ok", "ফসল তোলা নিশ্চিত হয়েছে (বিক্রির মতো কিছু হয়নি)।", "Harvest confirmed (nothing to sell).")
    return back(f"/farmer/forecasts/{forecast_id}")


# ================================================================ buyer requests (customer / admin)
@router.get("/requests")
def requests_page(request: Request):
    user = require_any_role(request, BUYER_ROLES)
    repo.expire_stale()
    items = repo.list_requests(user["id"])
    for r in items:
        r["potential"] = repo.potential_forecasts(user["id"], r["id"]) if r["status"] == "open" else []
        r["matches"] = repo.request_matches(user["id"], r["id"])
    from chashibondhu.web import matching_stages
    matching_stages.decorate(items)
    page = "customer/requests.html" if user["role"] == "customer" else "buyer/requests.html"
    return render(request, page, {"items": items, "units": UNITS, "form": {"unit": "kg"}, "active": "requests",
                                  "steps": matching_stages.STEPS, "stage_labels": matching_stages.LABELS})


@router.post("/requests/new")
async def request_create(request: Request):
    user = require_any_role(request, BUYER_ROLES)
    form = dict(await request.form())
    check_csrf(request, form.get("csrf"))
    data, errors = _plan_data(form, "request")
    if errors:
        for e in errors:
            flash(request, "bad", *e)
        return back("/requests")
    repo.create_request(user["id"], data)
    flash(request, "ok", "চাহিদা যোগ হয়েছে। মিলে যাওয়া আগাম ফসল নিচে দেখুন।", "Request added. See matching harvests below.")
    return back("/requests")


@router.post("/requests/{request_id}/cancel")
def request_cancel(request: Request, request_id: int, csrf: Annotated[str, Form()] = ""):
    user = require_any_role(request, BUYER_ROLES)
    check_csrf(request, csrf)
    _msg(request, repo.cancel_request(user["id"], request_id), "চাহিদা বাতিল হয়েছে।", "Request cancelled.")
    return back("/requests")


@router.post("/requests/{request_id}/interest")
def request_interest(request: Request, request_id: int, forecast_id: Annotated[int, Form()],
                     qty: Annotated[str, Form()], csrf: Annotated[str, Form()] = ""):
    user = require_any_role(request, BUYER_ROLES)
    check_csrf(request, csrf)
    q = _qty(qty)
    result = repo.buyer_interest(user["id"], request_id, forecast_id, q) if q else "too_much"
    _msg(request, result, "আগ্রহ জানানো হয়েছে। কৃষকের উত্তরের অপেক্ষা।", "Interest sent. Waiting for the farmer.")
    return back("/requests")


@router.post("/requests/matches/{match_id}/respond")
def buyer_match_respond(request: Request, match_id: int, answer: Annotated[str, Form()],
                        csrf: Annotated[str, Form()] = ""):
    user = require_any_role(request, BUYER_ROLES)
    check_csrf(request, csrf)
    if answer not in ("accept", "decline"):
        raise HTTPException(status_code=400)
    _msg(request, repo.buyer_respond(user["id"], match_id, answer == "accept"), "উত্তর দেওয়া হয়েছে।", "Answer saved.")
    return back("/requests")


# ================================================================ offline
@router.get("/farmer/drafts")
def drafts_page(request: Request):
    require_role(request, "farmer")
    return render(request, "farmer/drafts.html", {"active": "drafts"})


@router.get("/sw.js")
def service_worker():
    """At the site root so it may control /farmer pages."""
    return FileResponse(WEB_DIR / "static" / "sw.js", media_type="text/javascript",
                        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})


def _api_user(request: Request) -> tuple[dict | None, JSONResponse | None]:
    """Sync APIs answer JSON (never a login redirect), check CSRF, role and that the draft owner is this user."""
    user = current_user(request)
    if not user:
        return None, JSONResponse({"detail": "login_required"}, status_code=401)
    if user.get("role") != "farmer":
        return None, JSONResponse({"detail": "not_allowed"}, status_code=403)
    try:
        check_csrf(request, request.headers.get("x-csrf-token"))
    except HTTPException:
        return None, JSONResponse({"detail": "csrf"}, status_code=401)
    return user, None


def _client_id(raw) -> str | None:
    try:
        return str(uuid.UUID(str(raw)))
    except (ValueError, TypeError, AttributeError):
        return None


def _owner_ok(user: dict, owner) -> bool:
    try:
        return int(owner) == int(user["id"])
    except (TypeError, ValueError):
        return False


async def _sync_forecast(request: Request):
    user, err = _api_user(request)
    if err:
        return err
    try:
        body = await request.json()
    except ValueError:
        return JSONResponse({"detail": "bad_json"}, status_code=422)
    if not isinstance(body, dict) or not _owner_ok(user, body.get("owner")):
        return JSONResponse({"detail": "wrong_account"}, status_code=403)
    cid = _client_id(body.get("client_id"))
    if not cid:
        return JSONResponse({"detail": "bad_client_id"}, status_code=422)
    data, errors = _plan_data(body.get("data") or {}, "forecast")
    if errors:
        return JSONResponse({"detail": "invalid", "errors": errors}, status_code=422)
    _fill_area(data, user["id"])
    server_id = body.get("server_id")
    if server_id:                                   # offline edit of an existing forecast
        force = body.get("force") is True
        try:
            base = None if force else int(body.get("base_version"))
            sid = int(server_id)
        except (TypeError, ValueError):
            return JSONResponse({"detail": "bad_version"}, status_code=422)
        r = repo.update_forecast(user["id"], sid, data, base)
        if r["ok"]:
            return {"ok": True, "id": sid, "version": r["version"], "url": f"/farmer/forecasts/{sid}"}
        if r["reason"] == "conflict":
            s = r["server"]
            server = {k: (str(s[k]) if s.get(k) is not None else None) for k in repo.FORECAST_FIELDS}
            return JSONResponse({"detail": "conflict", "server": server, "server_version": s["version"]},
                                status_code=409)
        return JSONResponse({"detail": r["reason"]}, status_code=409 if r["reason"] == "closed" else 404)
    r = repo.create_forecast(user["id"], data, cid)
    return {"ok": True, "id": r["id"], "version": r["version"], "duplicate": r["duplicate"],
            "url": f"/farmer/forecasts/{r['id']}"}


async def _sync_listing(request: Request):
    user, err = _api_user(request)
    if err:
        return err
    form = await request.form()
    if not _owner_ok(user, form.get("owner")):
        return JSONResponse({"detail": "wrong_account"}, status_code=403)
    cid = _client_id(form.get("client_id"))
    if not cid:
        return JSONResponse({"detail": "bad_client_id"}, status_code=422)
    existing = repo.listing_by_client(user["id"], cid)
    if existing:                                    # retry of a draft that already arrived: no duplicate, no new photo
        return {"ok": True, "id": existing["id"], "duplicate": True, "url": "/farmer/listings"}
    fields = {k: v for k, v in form.items() if not isinstance(v, UploadFile)}
    data, errors = _listing_data(fields)
    upload = form.get("image")
    image_name = None
    if not errors and isinstance(upload, UploadFile) and upload.filename:
        from chashibondhu.web.images import BadImage, save_listing_image
        try:
            image_name = save_listing_image(await upload.read())
        except BadImage:
            errors.append(("ছবিটা খোলা যাচ্ছে না (৮ MB-এর ছোট ছবি দিন)।", "The photo cannot be used (use a photo under 8 MB)."))
    if errors:
        return JSONResponse({"detail": "invalid", "errors": errors}, status_code=422)
    profile = repo.get_farmer_profile(user["id"])
    r = repo.create_listing_once(user["id"], data, f"/media/listings/{image_name}" if image_name else None,
                                 profile.get("district_code"), profile.get("upazila_code"), cid)
    return {"ok": True, "id": r["id"], "duplicate": r["duplicate"], "url": "/farmer/listings"}


# ---------------------------------------------------------------- sync log (Admin A3: Security Center)
def _sync_result(resp) -> tuple[str, int, str | None, int | None]:
    """(result, http_status, detail, server_id) from what the sync endpoint answered."""
    if isinstance(resp, dict):
        sid = resp.get("id")
        if resp.get("duplicate"):
            return "duplicate", 200, None, sid
        return ("updated" if "version" in resp and resp.get("version", 1) > 1 else "created"), 200, None, sid
    status = getattr(resp, "status_code", 500)
    detail = None
    try:
        import json
        detail = json.loads(resp.body).get("detail")
    except Exception:  # noqa: BLE001
        pass
    return ("conflict" if status == 409 and detail == "conflict" else "rejected"), status, detail, None


async def _logged(request: Request, record_type: str, handler):
    """Run the real sync handler, then record the outcome (never the draft's content). Logging never breaks sync."""
    try:
        resp = await handler(request)
    except Exception as e:
        _write_sync_log(request, record_type, ("error", 500, type(e).__name__, None))
        raise
    if getattr(resp, "status_code", 200) != 401:
        _write_sync_log(request, record_type, _sync_result(resp))
    return resp


def _write_sync_log(request: Request, record_type: str, outcome) -> None:
    from chashibondhu.web.deps import current_user
    try:
        user = current_user(request)
        if not user or user.get("role") != "farmer":
            return
        cid = None
        try:
            cached = getattr(request, "_json", None)
            if isinstance(cached, dict):
                cid = _client_id(cached.get("client_id"))
            elif getattr(request, "_form", None) is not None:
                cid = _client_id(request._form.get("client_id"))
        except Exception:  # noqa: BLE001
            cid = None
        from chashibondhu.web import repo_admin_a3
        result, status, detail, sid = outcome
        repo_admin_a3.log_sync(int(user["id"]), record_type, cid, result, status, detail, sid)
    except Exception:  # noqa: BLE001 - the farmer's sync must never fail because of the log
        pass


@router.post("/farmer/sync/forecast")
async def sync_forecast(request: Request):
    return await _logged(request, "forecast", _sync_forecast)


@router.post("/farmer/sync/listing")
async def sync_listing(request: Request):
    return await _logged(request, "listing", _sync_listing)
