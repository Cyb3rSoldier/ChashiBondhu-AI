"""Farmer side: overview, add/my products, orders, earnings, market prices, tips, complaints, settings,
my farm (plots + plantings).

Every query is filtered by the logged-in farmer's id (ownership is checked in SQL, not only in the page).
"""
from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from starlette.datastructures import UploadFile
from fastapi.responses import FileResponse, RedirectResponse

from chashibondhu.web import repo
from chashibondhu.web.deps import check_csrf, crop_ids, flash, render, require_role
from chashibondhu.web.passwords import MIN_LENGTH, hash_password, verify_password
from chashibondhu.web.phone import normalize_phone
from chashibondhu.web.routes_public import area_codes, parse_decimal

router = APIRouter(prefix="/farmer", include_in_schema=False)

UNITS = ("kg", "gram", "maund", "piece", "dozen", "litre", "packet")
CATEGORIES = ("vegetable", "fruit", "grain", "pulse", "oilseed", "spice", "fish", "meat_poultry", "dairy",
              "eggs", "seeds_inputs", "tools_equipment", "other")
FARMING_METHODS = ("organic", "conventional", "other")
ORDER_PERIODS = ("all", "today", "week", "month")
COMPLAINT_CATEGORIES = ("order", "payment", "product", "account", "website", "other")
LAND_TYPES = ("high", "medium_high", "medium_low", "low", "very_low")
SEASONS = ("rabi", "kharif1", "kharif2")
PLANTING_STATUS = ("planned", "growing", "harvested", "failed")
ITEM_STATUS = ("accepted", "packed", "handed_over", "rejected")
ITEM_RESULT_MSG = {
    "not_found": ("অর্ডারটি পাওয়া যায়নি।", "Order item not found."),
    "bad_step": ("এই ধাপে এটা করা যায় না। পাতাটা আবার খুলুন।", "This step is not allowed now. Please reload the page."),
    "order_closed": ("অর্ডারটি আর বদলানো যায় না (বাতিল বা ডেলিভারি হয়ে গেছে)।",
                     "This order can no longer change (cancelled or delivered)."),
    "no_stock": ("আপনার পণ্যে এত পরিমাণ নেই। আগে পরিমাণ বাড়ান অথবা অর্ডারটি বাতিল করুন।",
                 "Not enough stock for this order. Increase the quantity first or reject the order."),
    "no_listing": ("পণ্যটি আর নেই, তাই স্টক মেলানো যাচ্ছে না।", "The product no longer exists, so stock cannot be checked."),
}


def season_now(today: date | None = None) -> str:
    """Display-only season from the date (Rabi mid-Oct..mid-Mar, Kharif-1 ..mid-Jul, Kharif-2)."""
    d = today or date.today()
    md = d.month * 100 + d.day
    if md >= 1016 or md <= 315:
        return "rabi"
    return "kharif1" if md <= 715 else "kharif2"


def parse_date(raw: str | None) -> date | None:
    s = (raw or "").strip()
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError as e:
        raise ValueError("bad date") from e


def back(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


# ---------------------------------------------------------------- dashboard
@router.get("")
def dashboard(request: Request):
    user = require_role(request, "farmer")
    uid = user["id"]
    return render(request, "farmer/dashboard.html", {
        "profile": repo.get_farmer_profile(uid), "stats": repo.farmer_stats(uid),
        "plantings": [p for p in repo.list_plantings(uid) if p["status"] in ("planned", "growing")][:4],
        "recent": repo.recent_questions(uid, 4), "season": season_now(), "active": "dash",
        "farmer_code": farmer_code(uid)})


def farmer_code(user_id: int) -> str:
    """Display ID for the farmer, e.g. CBF-000042 (the real key stays the database id)."""
    return f"CBF-{int(user_id):06d}"


# ---------------------------------------------------------------- profile
@router.get("/profile")
def profile_page(request: Request):
    user = require_role(request, "farmer")
    return render(request, "farmer/profile.html", {"p": repo.get_farmer_profile(user["id"]), "active": "profile"})


@router.post("/profile")
def profile_save(request: Request, full_name: Annotated[str, Form()], csrf: Annotated[str, Form()] = "",
                 upazila_code: Annotated[str, Form()] = "", land_decimal: Annotated[str, Form()] = "",
                 has_irrigation: Annotated[str, Form()] = "",
                 main_crops: Annotated[list[str] | None, Form()] = None,
                 address: Annotated[str | None, Form()] = None):
    user = require_role(request, "farmer")
    check_csrf(request, csrf)
    name = " ".join(full_name.split())
    try:
        land = parse_decimal(land_decimal)
    except ValueError:
        flash(request, "bad", "জমির পরিমাণ সংখ্যায় লিখুন।", "Write the land size as a number.")
        return back("/farmer/profile")
    if not 2 <= len(name) <= 100:
        flash(request, "bad", "নাম লিখুন।", "Please write your name.")
        return back("/farmer/profile")
    current = repo.get_farmer_profile(user["id"])
    district, upa = area_codes(upazila_code) if upazila_code else (current.get("district_code"),
                                                                   current.get("upazila_code"))
    irrigation = {"yes": True, "no": False}.get(has_irrigation)
    repo.update_farmer_profile(user["id"], name, district, upa, land,
                               current.get("land_text") if land == current.get("land_decimal") else None,
                               [c for c in (main_crops or []) if c in crop_ids()], irrigation)
    if address is not None:                      # field present on the settings page
        repo.set_address(user["id"], " ".join(address.split())[:300] or None)
    request.session["user"] = {**user, "name": name}
    flash(request, "ok", "তথ্য সংরক্ষণ হয়েছে।", "Saved.")
    return back("/farmer/profile")


# ---------------------------------------------------------------- my farm
@router.get("/farm")
def farm_page(request: Request):
    user = require_role(request, "farmer")
    return render(request, "farmer/farm.html", {
        "plots": repo.list_plots(user["id"]), "plantings": repo.list_plantings(user["id"]),
        "season": season_now(), "today": date.today().isoformat(), "active": "farm"})


@router.post("/farm/plots")
def plot_add(request: Request, name: Annotated[str, Form()], csrf: Annotated[str, Form()] = "",
             area_decimal: Annotated[str, Form()] = "", land_type: Annotated[str, Form()] = "",
             irrigation: Annotated[str, Form()] = ""):
    user = require_role(request, "farmer")
    check_csrf(request, csrf)
    name = " ".join(name.split())[:80]
    try:
        area = parse_decimal(area_decimal)
        if area is not None and area <= 0:
            raise ValueError
    except ValueError:
        flash(request, "bad", "জমির পরিমাণ সঠিক সংখ্যায় লিখুন।", "Write the plot size as a number.")
        return back("/farmer/farm")
    if not name:
        flash(request, "bad", "জমির একটা নাম দিন (যেমন: বাড়ির পাশের জমি)।", "Give the plot a name (e.g. field near home).")
        return back("/farmer/farm")
    profile = repo.get_farmer_profile(user["id"])
    repo.add_plot(user["id"], name, area, land_type if land_type in LAND_TYPES else None,
                  {"yes": True, "no": False}.get(irrigation), profile.get("upazila_code"))
    flash(request, "ok", "জমি যোগ হয়েছে।", "Plot added.")
    return back("/farmer/farm")


@router.post("/farm/plots/{plot_id}/delete")
def plot_delete(request: Request, plot_id: int, csrf: Annotated[str, Form()] = ""):
    user = require_role(request, "farmer")
    check_csrf(request, csrf)
    repo.delete_plot(user["id"], plot_id)
    flash(request, "ok", "জমি মুছে ফেলা হয়েছে।", "Plot removed.")
    return back("/farmer/farm")


@router.post("/farm/plantings")
def planting_add(request: Request, plot_id: Annotated[int, Form()], crop_id: Annotated[str, Form()],
                 csrf: Annotated[str, Form()] = "", variety: Annotated[str, Form()] = "",
                 season: Annotated[str, Form()] = "", planted_on: Annotated[str, Form()] = "",
                 expected_harvest_on: Annotated[str, Form()] = "", status: Annotated[str, Form()] = "growing"):
    user = require_role(request, "farmer")
    check_csrf(request, csrf)
    if crop_id not in crop_ids():
        flash(request, "bad", "ফসল বেছে নিন।", "Choose a crop.")
        return back("/farmer/farm")
    try:
        p_on, h_on = parse_date(planted_on), parse_date(expected_harvest_on)
    except ValueError:
        flash(request, "bad", "তারিখ ঠিক নেই।", "The date is not valid.")
        return back("/farmer/farm")
    if p_on and h_on and h_on < p_on:
        flash(request, "bad", "ফসল তোলার তারিখ লাগানোর তারিখের পরে হতে হবে।", "Harvest date must be after planting date.")
        return back("/farmer/farm")
    new_id = repo.add_planting(user["id"], plot_id, crop_id, variety.strip()[:80] or None,
                               season if season in SEASONS else None, p_on, h_on,
                               status if status in PLANTING_STATUS else "growing")
    if new_id is None:
        raise HTTPException(status_code=404, detail="plot not found")
    flash(request, "ok", "ফসল যোগ হয়েছে।", "Crop added.")
    return back("/farmer/farm")


@router.post("/farm/plantings/{planting_id}/status")
def planting_status(request: Request, planting_id: int, status: Annotated[str, Form()],
                    csrf: Annotated[str, Form()] = ""):
    user = require_role(request, "farmer")
    check_csrf(request, csrf)
    if status not in PLANTING_STATUS:
        raise HTTPException(status_code=400, detail="bad status")
    repo.set_planting_status(user["id"], planting_id, status)
    return back("/farmer/farm")


# ---------------------------------------------------------------- my listings
@router.get("/listings")
def listings_page(request: Request):
    user = require_role(request, "farmer")
    return render(request, "farmer/listings.html", {"listings": repo.list_my_listings(user["id"]),
                                                    "active": "listings"})


@router.get("/listings/new")
def listing_new(request: Request, crop_id: str = "", type: str = "available"):
    require_role(request, "farmer")
    item = {"listing_type": "expected" if type == "expected" else "available",
            "crop_id": crop_id if crop_id in crop_ids() else "", "unit": "kg", "min_order": 1,
            "category": "vegetable", "status": "active", "farming_method": "conventional"}
    return render(request, "farmer/listing_form.html", {"item": item, "mode": "new", "units": UNITS,
                                                        "categories": CATEGORIES, "methods": FARMING_METHODS,
                                                        "active": "add"})


@router.get("/listings/{listing_id}/edit")
def listing_edit(request: Request, listing_id: int):
    user = require_role(request, "farmer")
    item = repo.get_my_listing(user["id"], listing_id)
    if not item:
        raise HTTPException(status_code=404)
    return render(request, "farmer/listing_form.html", {"item": item, "mode": "edit", "units": UNITS,
                                                        "categories": CATEGORIES, "methods": FARMING_METHODS,
                                                        "active": "listings"})


def _listing_data(form: dict) -> tuple[dict, list]:
    errors = []
    data = {"listing_type": "expected" if form.get("listing_type") == "expected" else "available",
            "crop_id": form.get("crop_id") if form.get("crop_id") in crop_ids() else None,
            "title": " ".join((form.get("title") or "").split())[:120],
            "category": form.get("category") if form.get("category") in CATEGORIES else "other",
            "description": (form.get("description") or "").strip()[:2000] or None,
            "unit": form.get("unit") if form.get("unit") in UNITS else None,
            "status": "active" if form.get("status") != "draft" else "draft",
            "extra_info": (form.get("extra_info") or "").strip()[:1000] or None}
    method = form.get("farming_method")
    if method not in FARMING_METHODS:            # old form: only the "organic" tick box
        method = "organic" if form.get("is_organic") == "1" else "conventional"
    data["farming_method"] = method
    data["is_organic"] = method == "organic"     # badge only when the farmer chose organic
    if len(data["title"]) < 2:
        errors.append(("পণ্যের নাম লিখুন।", "Write the product name."))
    if not data["unit"]:
        errors.append(("একক বেছে নিন।", "Choose a unit."))
    for key, bn, en, minimum in (("price_per_unit", "দাম", "Price", 0.01), ("quantity", "পরিমাণ", "Quantity", 0),
                                 ("min_order", "সর্বনিম্ন অর্ডার", "Minimum order", 0.01)):
        try:
            v = parse_decimal(form.get(key))
            if v is None or float(v) < minimum:
                raise ValueError
            data[key] = v
        except ValueError:
            errors.append((f"{bn} সঠিক সংখ্যায় লিখুন।", f"{en}: write a valid number."))
            data[key] = None
    for key in ("available_from", "harvest_date"):
        try:
            data[key] = parse_date(form.get(key))
        except ValueError:
            data[key] = None
            errors.append(("তারিখ ঠিক নেই।", "The date is not valid."))
    if data["listing_type"] == "expected" and not data["available_from"]:
        errors.append(("ফসল কবে উঠবে সেই তারিখ দিন।", "Give the expected harvest date."))
    data["discount_price"] = None                  # optional; the farmer decides (must be below the price)
    raw = (form.get("discount_price") or "").strip()
    if raw:
        try:
            d = parse_decimal(raw)
            if d is None or d <= 0 or data.get("price_per_unit") is None or d >= data["price_per_unit"]:
                raise ValueError
            data["discount_price"] = d
        except ValueError:
            errors.append(("ছাড়ের দাম আসল দামের চেয়ে কম হতে হবে (না চাইলে খালি রাখুন)।",
                           "The discount price must be lower than the price (leave empty for none)."))
    return data, errors


async def _save_listing(request: Request, listing_id: int | None):
    user = require_role(request, "farmer")
    form = await request.form()
    check_csrf(request, form.get("csrf"))
    data, errors = _listing_data(dict(form))
    image_name = None
    upload = form.get("image")
    if isinstance(upload, UploadFile) and upload.filename:
        from chashibondhu.web.images import BadImage, save_listing_image
        try:
            image_name = save_listing_image(await upload.read())
        except BadImage:
            errors.append(("ছবিটা খোলা যাচ্ছে না (৮ MB-এর ছোট ছবি দিন)।", "The photo cannot be used (use a photo under 8 MB)."))
    if errors:
        item = {**data, "id": listing_id}
        return render(request, "farmer/listing_form.html", {
            "item": item, "mode": "edit" if listing_id else "new", "errors": errors,
            "units": UNITS, "categories": CATEGORIES, "methods": FARMING_METHODS,
            "active": "add" if not listing_id else "listings"}, status_code=400)
    path = f"/media/listings/{image_name}" if image_name else None
    if listing_id:
        if not repo.update_listing(user["id"], listing_id, data, path):
            raise HTTPException(status_code=404)
        flash(request, "ok", "পণ্য আপডেট হয়েছে।", "Product updated.")
    else:
        profile = repo.get_farmer_profile(user["id"])
        repo.create_listing(user["id"], data, path, profile.get("district_code"), profile.get("upazila_code"))
        flash(request, "ok", "পণ্য বাজারে দেওয়া হয়েছে।", "Product listed in the market.")
    return back("/farmer/listings")


@router.post("/listings/new")
async def listing_create(request: Request):
    return await _save_listing(request, None)


@router.post("/listings/{listing_id}/edit")
async def listing_update(request: Request, listing_id: int):
    return await _save_listing(request, listing_id)


@router.post("/listings/{listing_id}/status")
def listing_status(request: Request, listing_id: int, status: Annotated[str, Form()],
                   csrf: Annotated[str, Form()] = ""):
    user = require_role(request, "farmer")
    check_csrf(request, csrf)
    if status not in ("active", "sold_out", "hidden"):
        raise HTTPException(status_code=400, detail="bad status")
    repo.set_listing_status(user["id"], listing_id, status)
    return back("/farmer/listings")


@router.post("/listings/{listing_id}/delete")
def listing_delete(request: Request, listing_id: int, csrf: Annotated[str, Form()] = ""):
    user = require_role(request, "farmer")
    check_csrf(request, csrf)
    if repo.archive_listing(user["id"], listing_id):
        flash(request, "ok", "পণ্যটি মুছে ফেলা হয়েছে। পুরনো অর্ডারের তথ্য ঠিক থাকবে।",
              "Product deleted. Old order records are kept.")
    return back("/farmer/listings")


# ---------------------------------------------------------------- orders
@router.get("/orders")
def orders_page(request: Request, period: str = "all"):
    user = require_role(request, "farmer")
    period = period if period in ORDER_PERIODS else "all"
    items = repo.farmer_order_items(user["id"]) if period == "all" else repo.farmer_order_items(user["id"], period)
    return render(request, "farmer/orders.html", {"items": items,
                                                  "period": period, "active": "orders"})


@router.post("/orders/items/{item_id}")
def order_item_status(request: Request, item_id: int, status: Annotated[str, Form()],
                      csrf: Annotated[str, Form()] = ""):
    user = require_role(request, "farmer")
    check_csrf(request, csrf)
    if status not in ITEM_STATUS:
        raise HTTPException(status_code=400, detail="bad status")
    result = repo.set_item_farmer_status(user["id"], item_id, status)
    if isinstance(result, str) and result in ITEM_RESULT_MSG:
        flash(request, "bad", *ITEM_RESULT_MSG[result])
    else:
        flash(request, "ok", "অর্ডারের অবস্থা বদলানো হয়েছে।", "Order status updated.")
    return back("/farmer/orders")


# ---------------------------------------------------------------- earnings
@router.get("/earnings")
def earnings_page(request: Request, span: str = "7d"):
    user = require_role(request, "farmer")
    span = span if span in ("7d", "30d", "12m") else "7d"
    uid = user["id"]
    series = repo.earnings_series(uid, span)
    peak = max([float(r["amount"]) for r in series] + [0.0])
    return render(request, "farmer/earnings.html", {
        "summary": repo.earnings_summary(uid), "stats": repo.farmer_stats(uid), "series": series, "peak": peak,
        "span": span, "history": repo.earnings_history(uid), "top": repo.top_products(uid), "active": "earnings"})


# ---------------------------------------------------------------- market prices (information only)
@router.get("/prices")
def prices_page(request: Request, product: str = ""):
    require_role(request, "farmer")
    products = repo.price_products()
    keys = [p["product_key"] for p in products]
    product = product if product in keys else (keys[0] if keys else "")
    latest = repo.latest_prices(product) if product else []
    history = repo.price_history(product) if product else []
    return render(request, "farmer/prices.html", {"products": products, "product": product, "latest": latest,
                                                  "history": history, "active": "prices"})


# ---------------------------------------------------------------- tips
@router.get("/tips")
def tips_page(request: Request):
    require_role(request, "farmer")
    try:
        tips = repo.farmer_tips()
    except Exception:  # noqa: BLE001 - page still opens
        tips = []
    return render(request, "farmer/tips.html", {"tips": tips, "active": "tips"})


# ---------------------------------------------------------------- complaint box
@router.get("/complaints")
def complaints_page(request: Request):
    user = require_role(request, "farmer")
    return render(request, "farmer/complaints.html", {"items": repo.list_complaints(user["id"]),
                                                      "categories": COMPLAINT_CATEGORIES, "form": {},
                                                      "active": "complaints"})


@router.post("/complaints")
async def complaint_create(request: Request):
    user = require_role(request, "farmer")
    form = await request.form()
    check_csrf(request, form.get("csrf"))
    category = form.get("category") if form.get("category") in COMPLAINT_CATEGORIES else ""
    subject = " ".join(str(form.get("subject") or "").split())[:120]
    description = str(form.get("description") or "").strip()[:3000]
    errors = []
    if not category:
        errors.append(("অভিযোগের ধরন বেছে নিন।", "Choose a complaint type."))
    if len(subject) < 3:
        errors.append(("ছোট করে বিষয় লিখুন।", "Write a short subject."))
    if len(description) < 10:
        errors.append(("সমস্যাটা একটু খুলে লিখুন (অন্তত ১০ অক্ষর)।", "Describe the problem (at least 10 characters)."))
    image_name = None
    upload = form.get("image")
    if not errors and isinstance(upload, UploadFile) and upload.filename:
        from chashibondhu.web.images import BadImage, save_image
        try:
            image_name = save_image(await upload.read(), "complaints")
        except BadImage:
            errors.append(("ছবিটা খোলা যাচ্ছে না (৮ MB-এর ছোট ছবি দিন)।", "The photo cannot be used (use a photo under 8 MB)."))
    if errors:
        return render(request, "farmer/complaints.html", {
            "items": repo.list_complaints(user["id"]), "categories": COMPLAINT_CATEGORIES, "errors": errors,
            "form": {"category": category, "subject": subject, "description": description},
            "active": "complaints"}, status_code=400)
    row = repo.create_complaint(user["id"], category, subject, description, image_name)
    number = row.get("complaint_number", "")
    flash(request, "ok", f"অভিযোগ জমা হয়েছে। নম্বর: {number}", f"Complaint sent. Number: {number}")
    return back("/farmer/complaints")


@router.get("/complaints/{complaint_id}/image")
def complaint_image(request: Request, complaint_id: int):
    """Private photo: only the owner gets it."""
    user = require_role(request, "farmer")
    c = repo.get_complaint(user["id"], complaint_id)
    name = (c or {}).get("image_path") or ""
    import re
    if not re.fullmatch(r"[0-9a-f]{24}\.jpg", name):
        raise HTTPException(status_code=404)
    from chashibondhu.web.images import folder_dir
    path = folder_dir("complaints") / name
    if not path.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, no-store"})


# ---------------------------------------------------------------- settings: photo, phone, password
@router.post("/settings/avatar")
async def avatar_save(request: Request):
    user = require_role(request, "farmer")
    form = await request.form()
    check_csrf(request, form.get("csrf"))
    upload = form.get("image")
    if form.get("remove") == "1":
        repo.set_avatar(user["id"], None)
        flash(request, "ok", "ছবি সরানো হয়েছে।", "Photo removed.")
        return back("/farmer/profile")
    if not (isinstance(upload, UploadFile) and upload.filename):
        flash(request, "bad", "একটা ছবি বেছে নিন।", "Choose a photo.")
        return back("/farmer/profile")
    from chashibondhu.web.images import BadImage, save_image
    try:
        name = save_image(await upload.read(), "avatars", max_side=512)
    except BadImage:
        flash(request, "bad", "ছবিটা খোলা যাচ্ছে না (৮ MB-এর ছোট ছবি দিন)।", "The photo cannot be used (use a photo under 8 MB).")
        return back("/farmer/profile")
    repo.set_avatar(user["id"], f"/media/avatars/{name}")
    flash(request, "ok", "প্রোফাইল ছবি সংরক্ষণ হয়েছে।", "Profile photo saved.")
    return back("/farmer/profile")


@router.post("/settings/phone")
def phone_save(request: Request, phone: Annotated[str, Form()], password: Annotated[str, Form()],
               csrf: Annotated[str, Form()] = ""):
    user = require_role(request, "farmer")
    check_csrf(request, csrf)
    row = repo.get_user(user["id"]) or {}
    norm = normalize_phone(phone)
    if not row or not verify_password(password, row.get("password_hash", "")):
        flash(request, "bad", "পাসওয়ার্ড ভুল। নম্বর বদলানো হয়নি।", "Wrong password. The number was not changed.")
    elif not norm:
        flash(request, "bad", "সঠিক মোবাইল নম্বর দিন (যেমন ০১৭১২৩৪৫৬৭৮)।", "Enter a valid mobile number (e.g. 01712345678).")
    elif repo.phone_taken(norm, user["id"]):
        flash(request, "bad", "এই নম্বরে অন্য অ্যাকাউন্ট আছে।", "Another account uses this number.")
    else:
        repo.set_phone(user["id"], norm)
        flash(request, "ok", "মোবাইল নম্বর বদলানো হয়েছে। এখন থেকে নতুন নম্বর দিয়ে লগইন করবেন।",
              "Mobile number changed. Log in with the new number from now on.")
    return back("/farmer/profile")


@router.post("/settings/password")
def password_save(request: Request, current: Annotated[str, Form()], new: Annotated[str, Form()],
                  new2: Annotated[str, Form()], csrf: Annotated[str, Form()] = ""):
    user = require_role(request, "farmer")
    check_csrf(request, csrf)
    row = repo.get_user(user["id"]) or {}
    if not row or not verify_password(current, row.get("password_hash", "")):
        flash(request, "bad", "বর্তমান পাসওয়ার্ড ভুল।", "The current password is wrong.")
    elif len(new) < MIN_LENGTH:
        flash(request, "bad", f"নতুন পাসওয়ার্ড অন্তত {MIN_LENGTH} অক্ষরের হতে হবে।",
              f"The new password must have at least {MIN_LENGTH} characters.")
    elif new != new2:
        flash(request, "bad", "দুইবার একই পাসওয়ার্ড লিখুন।", "The two new passwords are not the same.")
    else:
        repo.set_password_hash(user["id"], hash_password(new))
        flash(request, "ok", "পাসওয়ার্ড বদলানো হয়েছে।", "Password changed.")
    return back("/farmer/profile")
