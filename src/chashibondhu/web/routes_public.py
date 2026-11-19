"""Public pages: home (with market search), farmer registration, login, logout, listing photos."""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import FileResponse, RedirectResponse

from chashibondhu.web import repo, repo_auth
from chashibondhu.web.deps import (check_csrf, crop_ids, current_user, flash, login_session, render)
from chashibondhu.web.passwords import MIN_LENGTH, hash_password, verify_password
from chashibondhu.web.identity import normalize_email, password_problem
from chashibondhu.web.phone import normalize_phone

router = APIRouter(include_in_schema=False)
UPAZILA_RE = re.compile(r"^BD\d{8}$")


def home_for(user: dict | None) -> str:
    if not user:
        return "/"
    return {"farmer": "/farmer", "customer": "/customer", "admin": "/admin"}.get(user.get("role", ""), "/")


def parse_decimal(raw: str | None, max_value: float = 1_000_000) -> Decimal | None:
    s = (raw or "").strip().translate(str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789"))
    if not s:
        return None
    try:
        d = Decimal(s)
    except InvalidOperation as e:
        raise ValueError("not a number") from e
    if d < 0 or d > Decimal(str(max_value)):
        raise ValueError("out of range")
    return d.quantize(Decimal("0.01"))


def area_codes(upazila_code: str | None) -> tuple[str | None, str | None]:
    """Upazila code BD20190009 -> (district BD2019, upazila BD20190009)."""
    code = (upazila_code or "").strip()
    if not UPAZILA_RE.match(code):
        return None, None
    return code[:6], code


LISTING_TYPES = {"available", "expected"}
LOGIN_ROLES = {"customer", "farmer", "admin"}
FARMER_PHONE_TAKEN = ("এই নম্বরে আগেই একটি কৃষক অ্যাকাউন্ট আছে। লগইন করুন।",
           "This phone number is already registered as a Farmer account. Please log in.")


def market_filters(q: str, crop: str, type_: str) -> dict:
    """Clean the market search box values (anything unknown is ignored)."""
    query = " ".join((q or "").split())[:60]
    return {"q": query,
            "crop": crop if crop in crop_ids() else "",
            "type": type_ if type_ in LISTING_TYPES else ""}


@router.get("/")
def home(request: Request, q: str = "", crop: str = "",
         type: Annotated[str, Query(alias="type")] = ""):  # noqa: A002 - URL name stays "type"
    f = market_filters(q, crop, type)
    try:
        if f["q"] or f["crop"] or f["type"]:
            listings = repo.market_listings(f["q"], f["crop"] or None, f["type"] or None, limit=24)
        else:
            listings = repo.public_listings(12)
        counts = repo.public_counts()
    except Exception:  # noqa: BLE001 - home page still opens if the database is down
        listings, counts = [], None
    return render(request, "home.html", {"listings": with_area_names(listings), "counts": counts, "f": f})


def with_area_names(rows: list[dict]) -> list[dict]:
    """Add district_bn / district_en so a card shows "ঢাকা", not a code, without any page script."""
    from chashibondhu.web import geo_points
    for r in rows:
        try:
            p = geo_points.point(r.get("district_code"))
        except Exception:  # noqa: BLE001 - names are a nice-to-have; the card still shows
            p = None
        if p:
            r["district_bn"], r["district_en"] = p["name_bn"], p["name_en"]
    return rows


@router.get("/login")
def login_page(request: Request, next: str = "", as_role: Annotated[str, Query(alias="as")] = "farmer"):
    if current_user(request):
        return RedirectResponse(home_for(current_user(request)), status_code=303)
    if as_role == "admin":                     # admin sign-in lives only at /admin (not linked anywhere public)
        return RedirectResponse("/admin", status_code=303)
    role = as_role if as_role in ("customer", "farmer") else "farmer"
    return render(request, "login.html", {"next": next if next.startswith("/") else "", "as_role": role})


WRONG_LOGIN = {"customer": ("ইমেইল বা পাসওয়ার্ড ভুল।", "Wrong email or password."),
               "farmer": ("ফোন নম্বর বা পাসওয়ার্ড ভুল।", "Wrong phone number or password."),
               "admin": ("ফোন নম্বর বা পাসওয়ার্ড ভুল।", "Wrong phone number or password.")}
_DUMMY_HASH = hash_password("timing-equaliser-not-a-real-password")


def find_login_user(role: str, login_id: str) -> tuple[dict | None, bool]:
    """-> (user, legacy). Farmer/admin by phone, customer by email. Old customers without an email
    may still log in by phone once (legacy=True) and are then asked to add an email."""
    if role == "customer":
        email = normalize_email(login_id)
        if email:
            return repo_auth.find_login_user("customer", email=email), False
        norm = normalize_phone(login_id)
        return (repo_auth.find_legacy_customer(norm), True) if norm else (None, False)
    norm = normalize_phone(login_id)
    return (repo_auth.find_login_user(role, phone=norm) if norm else None), False


@router.post("/login")
def login_submit(request: Request, password: Annotated[str, Form()], phone: Annotated[str, Form()] = "",
                 email: Annotated[str, Form()] = "", csrf: Annotated[str, Form()] = "",
                 next: Annotated[str, Form()] = "", as_role: Annotated[str, Form()] = "farmer"):
    check_csrf(request, csrf)
    role = as_role if as_role in LOGIN_ROLES else "farmer"
    login_id = (email or phone) if role == "customer" else phone
    user, legacy = find_login_user(role, login_id)
    error = None
    if not user:
        verify_password(password, _DUMMY_HASH)          # same time as a real check (no account probing)
        error = WRONG_LOGIN[role]
    elif repo.is_locked(user):
        error = ("অনেকবার ভুল হয়েছে। ১৫ মিনিট পরে আবার চেষ্টা করুন।",
                 "Too many wrong tries. Please try again in 15 minutes.")
    elif not verify_password(password, user["password_hash"]):
        repo.record_login(user["id"], ok=False)
        error = WRONG_LOGIN[role]
        if role == "admin":
            _admin_audit(None, "admin.login_failed", user["id"], result="failed")
    elif user["status"] != "active":
        error = ("এই অ্যাকাউন্ট এখন বন্ধ আছে। অ্যাডমিনের সাথে যোগাযোগ করুন।",
                 "This account is not active. Please contact the admin.")
    if error:
        page = "admin/login.html" if role == "admin" else "login.html"
        return render(request, page, {"error": error, "phone": phone, "email": email, "next": next,
                                      "as_role": role}, status_code=400)
    repo.record_login(user["id"], ok=True)
    login_session(request, user)
    if role == "admin":
        _admin_audit(user["id"], "admin.login", user["id"])
    if legacy:
        request.session["need_email"] = True
        flash(request, "ok", "লগইন হয়েছে। এখন থেকে ইমেইল দিয়ে লগইন করবেন, তাই একটি ইমেইল যোগ করুন।",
              "Logged in. From now on customers log in with email, so please add your email.")
        return RedirectResponse("/account/email", status_code=303)
    flash(request, "ok", f"স্বাগতম, {user['full_name']}!", f"Welcome, {user['full_name']}!")
    target = next if next.startswith("/") and not next.startswith("//") else home_for(user)
    return RedirectResponse(target, status_code=303)


def _admin_audit(actor_id, action: str, target_id, result: str = "ok") -> None:
    """Admin login/logout go to the audit log; a logging problem never blocks the login itself."""
    try:
        from chashibondhu.web import repo_admin
        repo_admin.audit(actor_id, action, "user", target_id, result=result)
    except Exception:  # noqa: BLE001
        pass


@router.post("/logout")
def logout(request: Request, csrf: Annotated[str, Form()] = ""):
    check_csrf(request, csrf)
    me = current_user(request)
    if me and me.get("role") == "admin":
        _admin_audit(me["id"], "admin.logout", me["id"])
    request.session.clear()
    return RedirectResponse("/", status_code=303)


@router.get("/register")
def register_page(request: Request):
    if current_user(request):
        return RedirectResponse(home_for(current_user(request)), status_code=303)
    return render(request, "register.html", {"form": {}})


@router.post("/register")
def register_submit(request: Request,
                    full_name: Annotated[str, Form()], password: Annotated[str, Form()],
                    password2: Annotated[str, Form()], phone: Annotated[str, Form()] = "",
                    csrf: Annotated[str, Form()] = "", upazila_code: Annotated[str, Form()] = "",
                    upazila_label: Annotated[str, Form()] = "", land: Annotated[str, Form()] = "",
                    land_unit: Annotated[str, Form()] = "decimal",
                    main_crops: Annotated[list[str] | None, Form()] = None):
    check_csrf(request, csrf)
    form = {"full_name": full_name, "phone": phone, "upazila_code": upazila_code,
            "upazila_label": upazila_label, "land": land, "land_unit": land_unit,
            "main_crops": main_crops or []}
    errors = []
    name = " ".join(full_name.split())
    norm = normalize_phone(phone)
    if not 2 <= len(name) <= 100:
        errors.append(("নাম লিখুন।", "Please write your name."))
    if not phone.strip():
        errors.append(("মোবাইল নম্বর দিতে হবে।", "Phone number is required."))
    elif not norm:
        errors.append(("সঠিক মোবাইল নম্বর দিন (যেমন ০১৭১২৩৪৫৬৭৮)।", "Enter a valid mobile number (e.g. 01712345678)."))
    weak = password_problem(password, MIN_LENGTH, norm)
    if weak:
        errors.append(weak)
    elif password != password2:
        errors.append(("দুইবার একই পাসওয়ার্ড লিখুন।", "The two passwords are not the same."))
    land_decimal, land_text = None, None
    try:
        amount = parse_decimal(land)
        if amount is not None:
            factor = {"decimal": Decimal("1"), "bigha": Decimal("33"), "acre": Decimal("100")}.get(land_unit)
            if factor is None:
                raise ValueError("unit")
            land_decimal = (amount * factor).quantize(Decimal("0.01"))
            land_text = f"{land.strip()} {land_unit}"
    except ValueError:
        errors.append(("জমির পরিমাণ সংখ্যায় লিখুন।", "Write the land size as a number."))
    crops_ok = [c for c in (main_crops or []) if c in crop_ids()]
    district_code, upa = area_codes(upazila_code)
    if norm and not errors and repo_auth.farmer_phone_taken(norm):     # only FARMER phones count
        errors.append(FARMER_PHONE_TAKEN)
    user_id = None
    if not errors:
        user_id = repo_auth.create_farmer(name, norm, hash_password(password), district_code, upa,
                                          land_decimal, land_text, crops_ok)
        if user_id is None:                         # lost a race to the same phone: the DB index said no
            errors.append(FARMER_PHONE_TAKEN)
    if errors:
        return render(request, "register.html", {"form": form, "errors": errors}, status_code=400)
    login_session(request, {"id": user_id, "role": "farmer", "full_name": name, "session_version": 0})
    flash(request, "ok", "অ্যাকাউন্ট তৈরি হয়েছে। চাষীবন্ধুতে স্বাগতম!", "Account created. Welcome to ChashiBondhu!")
    return RedirectResponse("/farmer", status_code=303)


@router.get("/media/avatars/{name}")
def avatar_image(name: str):
    return _public_image("avatars", name)


@router.get("/media/listings/{name}")
def listing_image(name: str):
    return _public_image("listings", name)


def _public_image(folder: str, name: str):
    from chashibondhu.web.images import folder_dir
    if not re.fullmatch(r"[0-9a-f]{24}\.jpg", name):
        raise HTTPException(status_code=404)
    path = folder_dir(folder) / name
    if not path.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})


# password reset pages live in routes_auth.py; they are mounted here so app.py does not change
from chashibondhu.web.routes_auth import router as _auth_router  # noqa: E402

router.include_router(_auth_router)

from chashibondhu.web.routes_geo import router as _geo_router  # noqa: E402

router.include_router(_geo_router)
