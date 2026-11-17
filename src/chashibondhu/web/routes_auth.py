"""Forgot password / reset password, adding an email to old customer accounts, admin reset codes.

Farmer   : phone -> 6-digit code (SMS when a provider is set, otherwise the admin gives the code) -> new password
Customer : email -> single-use link (30 min) -> new password
All answers are the same whether or not an account exists (no account probing).
"""
from __future__ import annotations

import re
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Form, Request
from fastapi.responses import RedirectResponse

from chashibondhu.web import notify, repo_auth
from chashibondhu.web.deps import check_csrf, flash, render, require_any_role
from chashibondhu.web.identity import (clean_code, code_hash, code_matches, new_code, new_link_token,
                                       normalize_email, password_problem, rate_key, token_hash)
from chashibondhu.web.passwords import MIN_LENGTH, hash_password, verify_password
from chashibondhu.web.phone import normalize_phone

router = APIRouter(include_in_schema=False)
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{40,64}$")
LINK_MINUTES, SMS_MINUTES, ADMIN_CODE_MINUTES = 30, 10, 30
NO_STORE = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}
SLOW_DOWN = ("অনেকবার চেষ্টা হয়েছে। এক ঘণ্টা পরে আবার চেষ্টা করুন।", "Too many tries. Please try again in an hour.")
BAD_CODE = ("কোডটি ভুল বা মেয়াদ শেষ। নতুন কোড নিন।", "The code is wrong or expired. Get a new code.")
BAD_LINK = ("লিংকটি ভুল, ব্যবহার করা হয়েছে বা মেয়াদ শেষ। আবার রিসেট চান।",
            "This link is wrong, already used or expired. Please ask for a new one.")


def _page(request: Request, name: str, ctx: dict | None = None, status_code: int = 200):
    resp = render(request, name, ctx, status_code=status_code)
    resp.headers.update(NO_STORE)
    return resp


def _ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _allowed(kind: str, value: str, limit: int, minutes: int = 60) -> bool:
    return repo_auth.rate_hit(rate_key(kind, value), limit, minutes)


# ================================================================ FARMER: phone + code
@router.get("/forgot/farmer")
def forgot_farmer(request: Request):
    return _page(request, "auth/forgot_farmer.html", {"sms": notify.sms_enabled(), "form": {}})


@router.post("/forgot/farmer")
def forgot_farmer_submit(request: Request, background: BackgroundTasks, phone: Annotated[str, Form()] = "",
                         csrf: Annotated[str, Form()] = ""):
    check_csrf(request, csrf)
    norm = normalize_phone(phone)
    if not norm:
        return _page(request, "auth/forgot_farmer.html", {
            "sms": notify.sms_enabled(), "form": {"phone": phone},
            "error": ("সঠিক মোবাইল নম্বর দিন (যেমন ০১৭১২৩৪৫৬৭৮)।", "Enter a valid mobile number (e.g. 01712345678).")},
            status_code=400)
    if not (_allowed("forgot_ip", _ip(request), 10) and _allowed("forgot_phone", norm, 3)):
        return _page(request, "auth/forgot_farmer.html", {"sms": notify.sms_enabled(), "form": {"phone": phone},
                                                          "error": SLOW_DOWN}, status_code=429)
    request.session["reset_phone"] = norm
    if notify.sms_enabled():
        user = repo_auth.find_login_user("farmer", phone=norm)
        if user and user.get("status") == "active":
            code = new_code()
            repo_auth.create_reset(int(user["id"]), "sms", code_hash(code), SMS_MINUTES)
            background.add_task(notify.send_sms, norm,
                                f"ChashiBondhu code: {code}. {SMS_MINUTES} min. Do not share. কোড কাউকে বলবেন না।")
        flash(request, "ok", "এই নম্বরে কৃষক অ্যাকাউন্ট থাকলে SMS-এ ৬ সংখ্যার কোড গেছে।",
              "If this number has a farmer account, a 6-digit code was sent by SMS.")
    return RedirectResponse("/forgot/farmer/code", status_code=303)


@router.get("/forgot/farmer/code")
def farmer_code(request: Request):
    return _page(request, "auth/reset_code.html", {"sms": notify.sms_enabled(),
                                                   "form": {"phone": request.session.get("reset_phone", "")}})


@router.post("/forgot/farmer/code")
def farmer_code_submit(request: Request, phone: Annotated[str, Form()] = "", code: Annotated[str, Form()] = "",
                       password: Annotated[str, Form()] = "", password2: Annotated[str, Form()] = "",
                       csrf: Annotated[str, Form()] = ""):
    check_csrf(request, csrf)
    norm, digits = normalize_phone(phone), clean_code(code)
    ctx = {"sms": notify.sms_enabled(), "form": {"phone": phone}}
    error = None
    if not norm:
        error = ("সঠিক মোবাইল নম্বর দিন।", "Enter a valid mobile number.")
    elif len(digits) != 6:
        error = ("৬ সংখ্যার কোড লিখুন।", "Enter the 6-digit code.")
    else:
        error = password_problem(password, MIN_LENGTH, norm)
        if not error and password != password2:
            error = ("দুইবার একই পাসওয়ার্ড লিখুন।", "The two passwords are not the same.")
    if error:
        return _page(request, "auth/reset_code.html", {**ctx, "error": error}, status_code=400)
    if not _allowed("verify_ip", _ip(request), 20):
        return _page(request, "auth/reset_code.html", {**ctx, "error": SLOW_DOWN}, status_code=429)
    result = repo_auth.complete_code_reset(norm, lambda stored: code_matches(digits, stored), hash_password(password))
    if result != "ok":
        return _page(request, "auth/reset_code.html", {**ctx, "error": BAD_CODE}, status_code=400)
    request.session.clear()
    flash(request, "ok", "পাসওয়ার্ড বদলানো হয়েছে। নতুন পাসওয়ার্ড দিয়ে লগইন করুন।",
          "Password changed. Log in with your new password.")
    return RedirectResponse("/login?as=farmer", status_code=303)


# ================================================================ CUSTOMER: email + link
@router.get("/forgot/customer")
def forgot_customer(request: Request):
    return _page(request, "auth/forgot_customer.html", {"mail": notify.mail_enabled(), "form": {}})


@router.post("/forgot/customer")
def forgot_customer_submit(request: Request, background: BackgroundTasks, email: Annotated[str, Form()] = "",
                           csrf: Annotated[str, Form()] = ""):
    check_csrf(request, csrf)
    mail = normalize_email(email)
    ctx = {"mail": notify.mail_enabled(), "form": {"email": email}}
    if not mail:
        return _page(request, "auth/forgot_customer.html",
                     {**ctx, "error": ("সঠিক ইমেইল দিন।", "Enter a valid email address.")}, status_code=400)
    if not (_allowed("forgot_ip", _ip(request), 10) and _allowed("forgot_email", mail, 3)):
        return _page(request, "auth/forgot_customer.html", {**ctx, "error": SLOW_DOWN}, status_code=429)
    if notify.mail_enabled():
        user = repo_auth.find_login_user("customer", email=mail)
        if user and user.get("status") == "active":
            token = new_link_token()
            repo_auth.create_reset(int(user["id"]), "email", token_hash(token), LINK_MINUTES)
            background.add_task(notify.send_reset_email, mail, user["full_name"], token, LINK_MINUTES)
    return _page(request, "auth/forgot_customer.html", {**ctx, "sent": True})


@router.get("/reset/new")
def reset_new(request: Request):
    tok = request.session.get("reset_token", "")
    user = repo_auth.email_reset_user(token_hash(tok)) if tok else None
    if not user:
        request.session.pop("reset_token", None)
        return _page(request, "auth/reset_password.html", {"bad": BAD_LINK}, status_code=400)
    return _page(request, "auth/reset_password.html", {"email": user["email"]})


@router.post("/reset/new")
def reset_new_submit(request: Request, password: Annotated[str, Form()] = "",
                     password2: Annotated[str, Form()] = "", csrf: Annotated[str, Form()] = ""):
    check_csrf(request, csrf)
    tok = request.session.get("reset_token", "")
    user = repo_auth.email_reset_user(token_hash(tok)) if tok else None
    if not user:
        request.session.pop("reset_token", None)
        return _page(request, "auth/reset_password.html", {"bad": BAD_LINK}, status_code=400)
    error = password_problem(password, MIN_LENGTH)
    if not error and password != password2:
        error = ("দুইবার একই পাসওয়ার্ড লিখুন।", "The two passwords are not the same.")
    if error:
        return _page(request, "auth/reset_password.html", {"email": user["email"], "error": error}, status_code=400)
    if not repo_auth.complete_email_reset(token_hash(tok), hash_password(password)):
        request.session.pop("reset_token", None)
        return _page(request, "auth/reset_password.html", {"bad": BAD_LINK}, status_code=400)
    request.session.clear()
    flash(request, "ok", "পাসওয়ার্ড বদলানো হয়েছে। নতুন পাসওয়ার্ড দিয়ে লগইন করুন।",
          "Password changed. Log in with your new password.")
    return RedirectResponse("/login?as=customer", status_code=303)


@router.get("/reset/{token}")
def reset_link(request: Request, token: str):
    """Email link. The token moves into the session and the address bar is cleaned at once."""
    if not _allowed("link_ip", _ip(request), 30):
        return _page(request, "auth/reset_password.html", {"bad": SLOW_DOWN}, status_code=429)
    if not TOKEN_RE.match(token) or not repo_auth.email_reset_user(token_hash(token)):
        return _page(request, "auth/reset_password.html", {"bad": BAD_LINK}, status_code=400)
    request.session["reset_token"] = token
    return RedirectResponse("/reset/new", status_code=303, headers=NO_STORE)


# ================================================================ old customers: add an email
@router.get("/account/email")
def account_email(request: Request):
    require_any_role(request, ("customer",))
    return _page(request, "auth/add_email.html", {"form": {}})


@router.post("/account/email")
def account_email_submit(request: Request, email: Annotated[str, Form()] = "",
                         password: Annotated[str, Form()] = "", csrf: Annotated[str, Form()] = ""):
    user = require_any_role(request, ("customer",))
    check_csrf(request, csrf)
    mail = normalize_email(email)
    from chashibondhu.web import repo
    row = repo.get_user(user["id"]) or {}
    error = None
    if not mail:
        error = ("সঠিক ইমেইল দিন।", "Enter a valid email address.")
    elif not verify_password(password, row.get("password_hash", "")):
        error = ("পাসওয়ার্ড ভুল।", "Wrong password.")
    elif repo_auth.customer_email_taken(mail, user["id"]) or not repo_auth.set_customer_email(user["id"], mail):
        error = ("এই ইমেইল দিয়ে আগেই অ্যাকাউন্ট আছে।", "This email address is already registered.")
    if error:
        return _page(request, "auth/add_email.html", {"form": {"email": email}, "error": error}, status_code=400)
    request.session.pop("need_email", None)
    flash(request, "ok", "ইমেইল যোগ হয়েছে। এখন থেকে ইমেইল দিয়ে লগইন করবেন।",
          "Email added. From now on, log in with your email.")
    return RedirectResponse("/customer", status_code=303)


# ================================================================ ADMIN: one-time code for a farmer
def _farmers_admin(request: Request) -> dict:
    """Admin with the 'farmers' permission (Admin A1 roles)."""
    from chashibondhu.web.routes_admin import require_perm
    return require_perm(request, "farmers")


@router.get("/admin/reset-code")
def admin_code(request: Request):
    admin = _farmers_admin(request)
    return _page(request, "admin/reset_code.html", {"form": {}, "admin": admin, "active": "reset",
                                                     "perm_labels": {}})


@router.post("/admin/reset-code")
def admin_code_submit(request: Request, phone: Annotated[str, Form()] = "", csrf: Annotated[str, Form()] = ""):
    admin = _farmers_admin(request)
    check_csrf(request, csrf)
    norm = normalize_phone(phone)
    farmer = repo_auth.find_login_user("farmer", phone=norm) if norm else None
    if not farmer or farmer.get("status") != "active":
        return _page(request, "admin/reset_code.html", {
            "admin": admin, "active": "reset", "perm_labels": {},
            "form": {"phone": phone},
            "error": ("এই নম্বরে চালু কোনো কৃষক অ্যাকাউন্ট নেই।", "No active farmer account has this number.")},
            status_code=400)
    code = new_code()
    repo_auth.create_reset(int(farmer["id"]), "admin", code_hash(code), ADMIN_CODE_MINUTES, created_by=int(admin["id"]))
    from chashibondhu.web import repo_admin
    repo_admin.audit(admin["id"], "farmer.reset_code", "user", int(farmer["id"]))          # the code itself is never logged
    return _page(request, "admin/reset_code.html", {"form": {}, "code": code, "farmer": farmer, "admin": admin,
                                                     "active": "reset", "perm_labels": {},
                                                     "minutes": ADMIN_CODE_MINUTES})
