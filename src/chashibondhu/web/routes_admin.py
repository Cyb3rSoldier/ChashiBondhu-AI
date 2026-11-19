"""Admin side, part A1: command center, farmers, consumers, products, reviews, staff + permissions, audit log.

Every page checks the permission ON THE SERVER (require_perm). Every change writes the audit log in the same
transaction (repo_admin). Prices, stock and orders are never edited here.
"""
from __future__ import annotations

import re
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from chashibondhu.web import repo_admin as ra
from chashibondhu.web.deps import check_csrf, current_user, flash, render, require_role

router = APIRouter(include_in_schema=False)

PERM_LABELS = {
    "dashboard": ("ড্যাশবোর্ড", "Dashboard"), "farmers": ("কৃষক", "Farmers"), "consumers": ("ক্রেতা", "Consumers"),
    "products": ("পণ্য", "Products"), "reviews": ("রিভিউ", "Reviews"), "orders": ("অর্ডার", "Orders"),
    "complaints": ("অভিযোগ", "Complaints"), "finance": ("হিসাব", "Finance"),
    "notifications": ("নোটিফিকেশন", "Notifications"), "content": ("কনটেন্ট", "Content"),
    "analytics": ("বিশ্লেষণ", "Analytics"), "audit": ("অডিট লগ", "Audit log"), "staff": ("স্টাফ", "Staff")}
MSG = {
    "ok": ("সম্পন্ন হয়েছে।", "Done."), "same": ("আগে থেকেই এই অবস্থায় আছে।", "It is already in that state."),
    "not_found": ("পাওয়া যায়নি।", "Not found."), "self": ("নিজের অ্যাকাউন্টে এটা করা যায় না।", "You cannot do this to your own account."),
    "last_super": ("শেষ সুপার অ্যাডমিনকে সরানো যায় না।", "The last Super Admin cannot be removed."),
    "reason": ("কারণ লিখুন (৩–৩০০ অক্ষর)।", "Write a reason (3–300 characters)."),
}


def require_perm(request: Request, perm: str) -> dict:
    """Logged-in active admin with this permission (Super Admin has all). 403 otherwise, and it is audited."""
    user = require_role(request, "admin")
    staff = ra.staff_row(user["id"])
    allowed = bool(staff and staff["status"] == "active" and (staff["is_super"] or perm in staff["permissions"]))
    if not allowed:
        try:
            ra.audit(user["id"], "access.denied", "page", None, result="denied", meta={"perm": perm,
                                                                                         "path": request.url.path})
        except Exception:  # noqa: BLE001 - never hide the 403 behind a logging error
            pass
        raise HTTPException(status_code=403, detail="no permission")
    request.state.staff = staff
    return {**user, "is_super": staff["is_super"], "perms": set(PERMISSIONS_ALL if staff["is_super"]
                                                               else staff["permissions"])}


PERMISSIONS_ALL = ra.PERMISSIONS


def _ctx(admin: dict, active: str, **kw) -> dict:
    return {"admin": admin, "active": active, "perm_labels": PERM_LABELS, **kw}


def _back(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def _reason(raw: str) -> str | None:
    r = " ".join((raw or "").split())
    return r if 3 <= len(r) <= 300 else None


def _say(request: Request, code: str) -> None:
    flash(request, "ok" if code == "ok" else "bad", *MSG.get(code, MSG["not_found"]))


def _int(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _page(v) -> int:
    return max(_int(v) or 1, 1)


# ================================================================ command center
@router.get("/admin")
def dashboard(request: Request, span: str = "30d", next: str = ""):
    if not current_user(request):
        # Nobody logged in: show the admin sign-in here (the only admin entrance; nothing public links to it).
        # The login form posts to /login with as_role=admin; every admin page still checks role + permission.
        safe_next = next if next.startswith("/admin") and not next.startswith("//") else ""
        return render(request, "admin/login.html", {"next": safe_next, "as_role": "admin"})
    admin = require_perm(request, "dashboard")
    span = span if span in ra.SPANS else "30d"
    ser, b = ra.series(span), ra.breakdowns()
    fmt = "%Y-%m" if ser["unit"] == "month" else "%m-%d"
    charts = {k: [(r["d"].strftime(fmt), r[k]) for r in ser["rows"]] for k in ("orders", "sales", "farmers", "customers")}
    charts.update({k: [(r["k"], r["n"]) for r in b[k]] for k in ("status", "category", "district")})
    return render(request, "admin/dashboard.html", _ctx(admin, "dash", n=ra.dashboard_numbers(), span=span,
                                                        charts=charts, b=b))


# ================================================================ farmers / consumers
ROLE_OF = {"farmers": "farmer", "consumers": "customer"}


def _user_filters(params) -> dict:
    district = params.get("district") or ""
    return {"q": " ".join(str(params.get("q") or "").split())[:60],
            "district": district if re.fullmatch(r"BD\d{4}", district) else "",
            "status": params.get("status") if params.get("status") in ("active", "suspended") else ""}


@router.get("/admin/{kind}")
def users_page(request: Request, kind: str, page: str = "1"):
    if kind not in ROLE_OF:
        raise HTTPException(status_code=404)
    admin = require_perm(request, kind)
    f = _user_filters(request.query_params)
    rows, total = ra.user_list(ROLE_OF[kind], f, _page(page))
    return render(request, "admin/users.html", _ctx(admin, kind, kind=kind, rows=rows, total=total, f=f,
                                                    page=_page(page), page_size=ra.PAGE))


@router.get("/admin/{kind}/{user_id}")
def user_page(request: Request, kind: str, user_id: int):
    if kind not in ROLE_OF:
        raise HTTPException(status_code=404)
    admin = require_perm(request, kind)
    u = ra.user_detail(user_id, ROLE_OF[kind])
    if not u:
        raise HTTPException(status_code=404)
    return render(request, "admin/user_detail.html", _ctx(admin, kind, kind=kind, u=u))


@router.post("/admin/{kind}/{user_id}/status")
def user_status(request: Request, kind: str, user_id: int, action: Annotated[str, Form()],
                reason: Annotated[str, Form()] = "", csrf: Annotated[str, Form()] = ""):
    if kind not in ROLE_OF or action not in ("suspend", "restore"):
        raise HTTPException(status_code=404)
    admin = require_perm(request, kind)
    check_csrf(request, csrf)
    why = _reason(reason)
    if action == "suspend" and not why:
        _say(request, "reason")
    else:
        _say(request, ra.set_user_status(admin["id"], user_id, (ROLE_OF[kind],), action == "suspend", why))
    return _back(f"/admin/{kind}/{user_id}")


# ================================================================ products
@router.get("/admin-products")
def products_page(request: Request, page: str = "1"):
    admin = require_perm(request, "products")
    p = request.query_params
    f = {"q": " ".join(str(p.get("q") or "").split())[:60],
         "category": p.get("category") if re.fullmatch(r"[a-z_]{2,30}", p.get("category") or "") else "",
         "district": p.get("district") if re.fullmatch(r"BD\d{4}", p.get("district") or "") else "",
         "status": p.get("status") if p.get("status") in ("draft", "active", "sold_out", "hidden", "archived") else "",
         "farmer": _int(p.get("farmer")), "avail": p.get("avail") if p.get("avail") in ("out", "preorder", "moderated") else ""}
    rows, total = ra.listing_list(f, _page(page))
    return render(request, "admin/products.html", _ctx(admin, "products", rows=rows, total=total, f=f,
                                                       page=_page(page), page_size=ra.PAGE))


@router.post("/admin-products/{listing_id}/moderate")
def product_moderate(request: Request, listing_id: int, action: Annotated[str, Form()],
                     reason: Annotated[str, Form()] = "", csrf: Annotated[str, Form()] = "",
                     back: Annotated[str, Form()] = ""):
    admin = require_perm(request, "products")
    check_csrf(request, csrf)
    if action not in ("remove", "restore"):
        raise HTTPException(status_code=400)
    why = _reason(reason)
    if not why:
        _say(request, "reason")
    else:
        _say(request, ra.moderate_listing(admin["id"], listing_id, action == "remove", why))
    return _back(back if back.startswith("/admin") else "/admin-products")


# ================================================================ reviews
@router.get("/admin-reviews")
def reviews_page(request: Request, page: str = "1"):
    admin = require_perm(request, "reviews")
    p = request.query_params
    f = {"q": " ".join(str(p.get("q") or "").split())[:60],
         "status": p.get("status") if p.get("status") in ("visible", "hidden") else "",
         "rating": _int(p.get("rating")) if p.get("rating") in ("1", "2", "3", "4", "5") else None}
    rows, total = ra.review_list(f, _page(page))
    return render(request, "admin/reviews.html", _ctx(admin, "reviews", rows=rows, total=total, f=f,
                                                      page=_page(page), page_size=ra.PAGE))


@router.post("/admin-reviews/{review_id}/moderate")
def review_moderate(request: Request, review_id: int, action: Annotated[str, Form()],
                    reason: Annotated[str, Form()] = "", csrf: Annotated[str, Form()] = ""):
    admin = require_perm(request, "reviews")
    check_csrf(request, csrf)
    if action not in ("hide", "restore"):
        raise HTTPException(status_code=400)
    why = _reason(reason)
    if action == "hide" and not why:
        _say(request, "reason")
    else:
        _say(request, ra.moderate_review(admin["id"], review_id, action == "hide", why))
    return _back("/admin-reviews")


# ================================================================ staff (Super Admin or 'staff')
@router.get("/admin-staff")
def staff_page(request: Request):
    admin = require_perm(request, "staff")
    return render(request, "admin/staff.html", _ctx(admin, "staff", rows=ra.list_staff(), all_perms=ra.PERMISSIONS,
                                                    form={}))


def _perms_from(form) -> list[str]:
    return [p for p in ra.PERMISSIONS if p in form.getlist("perms")]


@router.post("/admin-staff/new")
async def staff_new(request: Request):
    admin = require_perm(request, "staff")
    form = await request.form()
    check_csrf(request, form.get("csrf"))
    from chashibondhu.web.identity import password_problem
    from chashibondhu.web.passwords import MIN_LENGTH, hash_password
    from chashibondhu.web.phone import normalize_phone
    name = " ".join(str(form.get("full_name") or "").split())
    phone = normalize_phone(str(form.get("phone") or ""))
    pw = str(form.get("password") or "")
    perms = _perms_from(form)
    if "staff" in perms and not admin["is_super"]:
        perms.remove("staff")                                   # only a Super Admin can make staff managers
    weak = password_problem(pw, max(MIN_LENGTH, 10), phone)
    if not 2 <= len(name) <= 100 or not phone or weak:
        flash(request, "bad", *(weak or ("নাম ও সঠিক মোবাইল নম্বর দিন।", "Enter a name and a valid mobile number.")))
        return _back("/admin-staff")
    uid = ra.create_staff(admin["id"], name, phone, hash_password(pw), perms)
    if uid is None:
        flash(request, "bad", "এই নম্বরে আগেই অ্যাডমিন আছে।", "An admin with this number already exists.")
    else:
        flash(request, "ok", "স্টাফ অ্যাকাউন্ট তৈরি হয়েছে।", "Staff account created.")
    return _back("/admin-staff")


@router.post("/admin-staff/{user_id}/permissions")
async def staff_perms(request: Request, user_id: int):
    admin = require_perm(request, "staff")
    form = await request.form()
    check_csrf(request, form.get("csrf"))
    if user_id == admin["id"]:
        _say(request, "self")
        return _back("/admin-staff")
    perms = _perms_from(form)
    make_super = form.get("is_super") == "1"
    if not admin["is_super"]:                                   # staff managers cannot hand out top powers
        target = ra.staff_row(user_id)
        if make_super or "staff" in perms or (target and target["is_super"]):
            raise HTTPException(status_code=403, detail="only a Super Admin can do this")
    _say(request, ra.set_permissions(admin["id"], user_id, perms, make_super))
    return _back("/admin-staff")


@router.post("/admin-staff/{user_id}/status")
def staff_status(request: Request, user_id: int, action: Annotated[str, Form()],
                 reason: Annotated[str, Form()] = "", csrf: Annotated[str, Form()] = ""):
    admin = require_perm(request, "staff")
    check_csrf(request, csrf)
    if action not in ("suspend", "restore"):
        raise HTTPException(status_code=400)
    target = ra.staff_row(user_id)
    if target and target["is_super"] and not admin["is_super"]:
        raise HTTPException(status_code=403, detail="only a Super Admin can do this")
    why = _reason(reason)
    if action == "suspend" and not why:
        _say(request, "reason")
    else:
        _say(request, ra.set_user_status(admin["id"], user_id, ("admin",), action == "suspend", why))
    return _back("/admin-staff")


# ================================================================ audit log
@router.get("/admin-audit")
def audit_page(request: Request, page: str = "1"):
    admin = require_perm(request, "audit")
    p = request.query_params
    f = {"action": re.sub(r"[^a-z_.]", "", str(p.get("action") or ""))[:40], "actor": _int(p.get("actor")),
         "target_type": re.sub(r"[^a-z_]", "", str(p.get("target_type") or ""))[:20],
         "target_id": _int(p.get("target_id"))}
    rows, total = ra.audit_page(f, _page(page))
    return render(request, "admin/audit.html", _ctx(admin, "audit", rows=rows, total=total, f=f,
                                                    page=_page(page), page_size=ra.PAGE))


# Admin A2 (orders, finance, complaints) lives in routes_admin_a2.py
from chashibondhu.web.routes_admin_a2 import router as _a2_router  # noqa: E402

router.include_router(_a2_router)

# Admin A3 (announcements, content, harvest monitoring, sync log, analytics) lives in routes_admin_a3.py
from chashibondhu.web.routes_admin_a3 import router as _a3_router  # noqa: E402

router.include_router(_a3_router)
