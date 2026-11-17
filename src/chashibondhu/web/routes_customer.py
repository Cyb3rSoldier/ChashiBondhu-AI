"""Customer side: sign-up, dashboard, orders (+ invoice, cancel, reorder), notifications, complaints, settings.
Every query is filtered by the logged-in customer's id."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from starlette.datastructures import UploadFile

from chashibondhu.web import repo, repo_auth
from chashibondhu.web.deps import check_csrf, current_user, flash, login_session, render, require_any_role
from chashibondhu.web.passwords import MIN_LENGTH, hash_password, verify_password
from chashibondhu.web.identity import normalize_email, password_problem
from chashibondhu.web.phone import normalize_phone
from chashibondhu.web.routes_farmer import COMPLAINT_CATEGORIES
from chashibondhu.web.routes_public import area_codes, home_for

router = APIRouter(include_in_schema=False)
ME = ("customer",)
PERIODS = ("all", "today", "week", "month")


def back(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


# ---------------------------------------------------------------- sign-up
@router.get("/register/customer")
def register_page(request: Request):
    if current_user(request):
        return back(home_for(current_user(request)))
    return render(request, "customer/register.html", {"form": {}})


EMAIL_TAKEN = ("এই ইমেইল দিয়ে আগেই অ্যাকাউন্ট আছে। লগইন করুন।", "This email address is already registered. Please log in.")


@router.post("/register/customer")
def register_submit(request: Request, full_name: Annotated[str, Form()], password: Annotated[str, Form()],
                    password2: Annotated[str, Form()], phone: Annotated[str, Form()] = "",
                    email: Annotated[str, Form()] = "", csrf: Annotated[str, Form()] = "",
                    upazila_code: Annotated[str, Form()] = "", upazila_label: Annotated[str, Form()] = "",
                    address: Annotated[str, Form()] = ""):
    """Customer = EMAIL required + unique among customers; PHONE required but may be shared."""
    check_csrf(request, csrf)
    name, norm, mail = " ".join(full_name.split()), normalize_phone(phone), normalize_email(email)
    addr = " ".join(address.split())[:300] or None
    form = {"full_name": full_name, "email": email, "phone": phone, "upazila_code": upazila_code,
            "upazila_label": upazila_label, "address": address}
    errors = []
    if not 2 <= len(name) <= 100:
        errors.append(("নাম লিখুন।", "Please write your name."))
    if not email.strip():
        errors.append(("ইমেইল দিতে হবে।", "Email address is required."))
    elif not mail:
        errors.append(("সঠিক ইমেইল দিন (যেমন name@gmail.com)।", "Enter a valid email (e.g. name@gmail.com)."))
    if not phone.strip():
        errors.append(("মোবাইল নম্বর দিতে হবে।", "Phone number is required."))
    elif not norm:
        errors.append(("সঠিক মোবাইল নম্বর দিন (যেমন ০১৭১২৩৪৫৬৭৮)।", "Enter a valid mobile number (e.g. 01712345678)."))
    weak = password_problem(password, MIN_LENGTH, norm)
    if weak:
        errors.append(weak)
    elif password != password2:
        errors.append(("দুইবার একই পাসওয়ার্ড লিখুন।", "The two passwords are not the same."))
    if mail and not errors and repo_auth.customer_email_taken(mail):
        errors.append(EMAIL_TAKEN)
    uid = None
    if not errors:
        district, upa = area_codes(upazila_code)
        uid = repo_auth.create_customer(name, mail, norm, hash_password(password), district, upa, addr)
        if uid is None:                                  # same email registered at the same moment
            errors.append(EMAIL_TAKEN)
    if errors:
        return render(request, "customer/register.html", {"form": form, "errors": errors}, status_code=400)
    login_session(request, {"id": uid, "role": "customer", "full_name": name, "session_version": 0})
    flash(request, "ok", "অ্যাকাউন্ট তৈরি হয়েছে। চাষীবন্ধুতে স্বাগতম!", "Account created. Welcome to ChashiBondhu!")
    return back("/market")


# ---------------------------------------------------------------- dashboard
@router.get("/customer")
def dashboard(request: Request):
    user = require_any_role(request, ME)
    uid = user["id"]
    return render(request, "customer/dashboard.html", {
        "me": repo.get_customer(uid) or {}, "stats": repo.customer_stats(uid), "recent": repo.recent_purchases(uid),
        "unread": repo.unread_count(uid), "cart_n": repo.cart_count(uid), "req": _request_summary(uid),
        "active": "c_dash"})


def _request_summary(uid: int) -> dict:
    from chashibondhu.web import repo_market_b2
    return repo_market_b2.request_summary(uid)


@router.get("/customer/orders")
def orders(request: Request, period: str = "all"):
    user = require_any_role(request, ME)
    period = period if period in PERIODS else "all"
    return render(request, "customer/orders.html", {"items": repo.customer_orders(user["id"], period),
                                                    "period": period, "active": "c_orders"})


@router.get("/customer/orders/{order_number}")
def order_detail(request: Request, order_number: str):
    user = require_any_role(request, ME)
    o = repo.customer_order(user["id"], order_number)
    if not o:
        raise HTTPException(status_code=404)
    return render(request, "customer/order_detail.html", {"o": o, "active": "c_orders"})


@router.get("/customer/orders/{order_number}/invoice")
def invoice(request: Request, order_number: str):
    user = require_any_role(request, ME)
    o = repo.customer_order(user["id"], order_number)
    if not o:
        raise HTTPException(status_code=404)
    return render(request, "customer/invoice.html", {"o": o})


@router.post("/customer/orders/{order_number}/cancel")
def order_cancel(request: Request, order_number: str, csrf: Annotated[str, Form()] = ""):
    user = require_any_role(request, ME)
    check_csrf(request, csrf)
    res = repo.cancel_order(user["id"], order_number)
    if res == "ok":
        flash(request, "ok", "অর্ডার বাতিল হয়েছে।", "Order cancelled.")
    elif res == "too_late":
        flash(request, "bad", "কৃষক অর্ডার নিশ্চিত করেছেন, তাই এখন বাতিল করা যায় না। অভিযোগ বাক্সে লিখুন।",
              "A farmer already confirmed it, so it cannot be cancelled now. Use the complaint box.")
    else:
        raise HTTPException(status_code=404)
    return back(f"/customer/orders/{order_number}")


@router.post("/customer/orders/{order_number}/reorder")
def order_reorder(request: Request, order_number: str, csrf: Annotated[str, Form()] = ""):
    user = require_any_role(request, ME)
    check_csrf(request, csrf)
    r = repo.reorder(user["id"], order_number)
    if r["added"]:
        flash(request, "ok", "আজকের দাম ও স্টক অনুযায়ী কার্টে যোগ হয়েছে: " + ", ".join(r["added"]),
              "Added to cart at today's price and stock: " + ", ".join(r["added"]))
    if r["skipped"]:
        flash(request, "bad", "এখন পাওয়া যাচ্ছে না: " + ", ".join(r["skipped"]),
              "Not available now: " + ", ".join(r["skipped"]))
    return back("/cart")


# ---------------------------------------------------------------- notifications
@router.get("/customer/notifications")
def notifications(request: Request):
    user = require_any_role(request, ME)
    items = repo.list_notifications(user["id"])
    repo.mark_all_read(user["id"])
    return render(request, "customer/notifications.html", {"items": items, "active": "c_notes"})


# ---------------------------------------------------------------- complaints (same table as farmers)
@router.get("/customer/complaints")
def complaints(request: Request):
    user = require_any_role(request, ME)
    return render(request, "customer/complaints.html", {"items": repo.list_complaints(user["id"]),
                                                        "categories": COMPLAINT_CATEGORIES, "form": {},
                                                        "active": "c_complaints"})


@router.post("/customer/complaints")
async def complaint_create(request: Request):
    user = require_any_role(request, ME)
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
        return render(request, "customer/complaints.html", {
            "items": repo.list_complaints(user["id"]), "categories": COMPLAINT_CATEGORIES, "errors": errors,
            "form": {"category": category, "subject": subject, "description": description},
            "active": "c_complaints"}, status_code=400)
    row = repo.create_complaint(user["id"], category, subject, description, image_name)
    n = row.get("complaint_number", "")
    flash(request, "ok", f"অভিযোগ জমা হয়েছে। নম্বর: {n}", f"Complaint sent. Number: {n}")
    return back("/customer/complaints")


@router.get("/customer/complaints/{complaint_id}/image")
def complaint_image(request: Request, complaint_id: int):
    import re
    from fastapi.responses import FileResponse
    from chashibondhu.web.images import folder_dir
    user = require_any_role(request, ME)
    name = (repo.get_complaint(user["id"], complaint_id) or {}).get("image_path") or ""
    if not re.fullmatch(r"[0-9a-f]{24}\.jpg", name) or not (folder_dir("complaints") / name).is_file():
        raise HTTPException(status_code=404)
    return FileResponse(folder_dir("complaints") / name, media_type="image/jpeg",
                        headers={"Cache-Control": "private, no-store"})


# ---------------------------------------------------------------- settings
@router.get("/customer/settings")
def settings(request: Request):
    user = require_any_role(request, ME)
    return render(request, "customer/settings.html", {"me": repo.get_customer(user["id"]) or {},
                                                      "active": "c_settings"})


@router.post("/customer/settings")
def settings_save(request: Request, full_name: Annotated[str, Form()], csrf: Annotated[str, Form()] = "",
                  upazila_code: Annotated[str, Form()] = "", address: Annotated[str, Form()] = ""):
    user = require_any_role(request, ME)
    check_csrf(request, csrf)
    name = " ".join(full_name.split())
    if not 2 <= len(name) <= 100:
        flash(request, "bad", "নাম লিখুন।", "Please write your name.")
        return back("/customer/settings")
    district, upa = area_codes(upazila_code)
    me = repo.get_customer(user["id"]) or {}
    if not upa:                                     # keep the old area when none was chosen
        district, upa = me.get("district_code"), me.get("upazila_code")
    repo.update_customer(user["id"], name, district, upa, " ".join(address.split())[:300] or None)
    request.session["user"] = {**user, "name": name}
    flash(request, "ok", "তথ্য সংরক্ষণ হয়েছে।", "Saved.")
    return back("/customer/settings")


@router.post("/customer/settings/avatar")
async def avatar(request: Request):
    user = require_any_role(request, ME)
    form = await request.form()
    check_csrf(request, form.get("csrf"))
    if form.get("remove") == "1":
        repo.set_avatar(user["id"], None)
        return back("/customer/settings")
    upload = form.get("image")
    if not (isinstance(upload, UploadFile) and upload.filename):
        flash(request, "bad", "একটা ছবি বেছে নিন।", "Choose a photo.")
        return back("/customer/settings")
    from chashibondhu.web.images import BadImage, save_image
    try:
        name = save_image(await upload.read(), "avatars", max_side=512)
    except BadImage:
        flash(request, "bad", "ছবিটা খোলা যাচ্ছে না (৮ MB-এর ছোট ছবি দিন)।", "The photo cannot be used (use a photo under 8 MB).")
        return back("/customer/settings")
    repo.set_avatar(user["id"], f"/media/avatars/{name}")
    flash(request, "ok", "প্রোফাইল ছবি সংরক্ষণ হয়েছে।", "Profile photo saved.")
    return back("/customer/settings")


@router.post("/customer/settings/phone")
def phone_save(request: Request, phone: Annotated[str, Form()], password: Annotated[str, Form()],
               csrf: Annotated[str, Form()] = ""):
    user = require_any_role(request, ME)
    check_csrf(request, csrf)
    row, norm = repo.get_user(user["id"]) or {}, normalize_phone(phone)
    if not row or not verify_password(password, row.get("password_hash", "")):
        flash(request, "bad", "পাসওয়ার্ড ভুল। নম্বর বদলানো হয়নি।", "Wrong password. The number was not changed.")
    elif not norm:
        flash(request, "bad", "সঠিক মোবাইল নম্বর দিন।", "Enter a valid mobile number.")
    else:                                   # customers may share a phone number (only email is unique)
        repo.set_phone(user["id"], norm)
        flash(request, "ok", "মোবাইল নম্বর বদলানো হয়েছে।", "Mobile number changed.")
    return back("/customer/settings")


@router.post("/customer/settings/password")
def password_save(request: Request, current: Annotated[str, Form()], new: Annotated[str, Form()],
                  new2: Annotated[str, Form()], csrf: Annotated[str, Form()] = ""):
    user = require_any_role(request, ME)
    check_csrf(request, csrf)
    row = repo.get_user(user["id"]) or {}
    if not row or not verify_password(current, row.get("password_hash", "")):
        flash(request, "bad", "বর্তমান পাসওয়ার্ড ভুল।", "The current password is wrong.")
    elif password_problem(new, MIN_LENGTH, row.get("phone")):
        bn, en = password_problem(new, MIN_LENGTH, row.get("phone"))
        flash(request, "bad", bn, en)
    elif new != new2:
        flash(request, "bad", "দুইবার একই পাসওয়ার্ড লিখুন।", "The two new passwords are not the same.")
    else:
        repo.set_password_hash(user["id"], hash_password(new))
        flash(request, "ok", "পাসওয়ার্ড বদলানো হয়েছে।", "Password changed.")
    return back("/customer/settings")
