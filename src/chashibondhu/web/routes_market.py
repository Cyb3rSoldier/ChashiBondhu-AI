"""Marketplace (public browsing) + cart + checkout (customers only).

/market                 search, filters, two sections (fresh products / tools & equipment)
/market/suggest         autocomplete JSON (only words that match real active listings)
/market/{id}            product details + related products
/cart, /checkout        customers; prices and stock are always re-checked on the server
"""
from __future__ import annotations

import os
import secrets
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from chashibondhu.web import repo
from chashibondhu.web.deps import check_csrf, crop_ids, current_user, flash, render, require_any_role
from chashibondhu.web.phone import normalize_phone
from chashibondhu.web.routes_farmer import CATEGORIES
from chashibondhu.web.routes_public import parse_decimal

router = APIRouter(include_in_schema=False)
SORTS = ("best", "new", "price_asc", "price_desc")
BUYER = ("customer",)

PROBLEM_MSG = {
    "unavailable": ("পণ্যটি এখন বিক্রি হচ্ছে না", "no longer for sale"),
    "preorder": ("এটি আগাম ফসল — এখন কেনা যায় না", "this is a pre-harvest item, not for sale yet"),
    "below_min": ("সর্বনিম্ন অর্ডারের চেয়ে কম", "below the minimum order"),
    "no_stock": ("এত পরিমাণ নেই", "not enough stock"),
    "own": ("নিজের পণ্য কেনা যায় না", "you cannot buy your own product"),
    "empty": ("কার্ট খালি", "the cart is empty"),
}


def delivery_fee() -> Decimal:
    """Flat delivery charge per order from .env (CB_DELIVERY_FEE, taka). 0 when not set."""
    try:
        v = Decimal(os.environ.get("CB_DELIVERY_FEE", "0"))
        return v if v >= 0 else Decimal("0")
    except ArithmeticError:
        return Decimal("0")


def _num(raw) -> Decimal | None:
    try:
        return parse_decimal(str(raw or ""))
    except ValueError:
        return None


def market_filters(params: dict, districts: list[str]) -> dict:
    """Clean every filter value; anything unknown is ignored."""
    f = {"q": " ".join(str(params.get("q") or "").split())[:80],
         "section": params.get("section") if params.get("section") in ("fresh", "tools") else "",
         "category": params.get("category") if params.get("category") in CATEGORIES else "",
         "district": params.get("district") if params.get("district") in districts else "",
         "min": _num(params.get("min")), "max": _num(params.get("max")),
         "avail": params.get("avail") if params.get("avail") in ("now", "preorder") else "",
         "organic": params.get("organic") == "1",
         "sort": params.get("sort") if params.get("sort") in SORTS else "best"}
    if f["min"] is not None and f["max"] is not None and f["min"] > f["max"]:
        f["min"], f["max"] = f["max"], f["min"]
    return f


@router.get("/market")
def market(request: Request, page: int = 1):
    try:
        districts = repo.market_districts()
    except Exception:  # noqa: BLE001 - page still opens if the database is down
        districts = []
    f = market_filters(dict(request.query_params), districts)
    page = max(1, min(page, 500))
    try:
        rows, total = repo.market_search(f, set(crop_ids()), page)
        db_ok = True
    except Exception:  # noqa: BLE001
        rows, total, db_ok = [], 0, False
    pages = max(1, (total + repo.PAGE_SIZE - 1) // repo.PAGE_SIZE)
    qs = {k: v for k, v in request.query_params.items() if k != "page"}
    return render(request, "market/market.html", {"rows": rows, "total": total, "f": f, "page": page, "pages": pages,
                                                  "districts": districts, "categories": CATEGORIES, "qs": qs,
                                                  "db_ok": db_ok, "active": "market"})


@router.get("/market/suggest")
def market_suggest(q: str = ""):
    q = q.strip()[:40]
    if not q:
        return {"items": []}
    try:
        return {"items": repo.suggest(q, set(crop_ids()))}
    except Exception:  # noqa: BLE001
        return JSONResponse({"items": [], "detail": "unavailable"}, status_code=503)


@router.get("/market/{listing_id}")
def product_page(request: Request, listing_id: int):
    item = repo.get_market_listing(listing_id)
    if not item:
        raise HTTPException(status_code=404)
    user = current_user(request)
    is_customer = bool(user and user.get("role") == "customer")
    from chashibondhu.web import repo_market_b1
    extras = repo_market_b1.product_extras(user["id"] if is_customer else None, item["id"], item["farmer_id"])
    return render(request, "market/product.html", {
        "item": item, "related": repo.related_listings(item), "x": extras,
        "in_compare": item["id"] in (request.session.get("compare") or []),
        "can_buy": is_customer, "active": "market"})


# ================================================================ cart
@router.post("/cart/add")
def cart_add(request: Request, listing_id: Annotated[int, Form()], qty: Annotated[str, Form()],
             csrf: Annotated[str, Form()] = ""):
    user = require_any_role(request, BUYER)
    check_csrf(request, csrf)
    q = _num(qty)
    res = repo.cart_set(user["id"], listing_id, q, add=True) if q and q > 0 else "below_min"
    if res == "ok":
        flash(request, "ok", "কার্টে যোগ হয়েছে।", "Added to cart.")
        return RedirectResponse("/cart", status_code=303)
    flash(request, "bad", *PROBLEM_MSG.get(res, PROBLEM_MSG["unavailable"]))
    return RedirectResponse(f"/market/{listing_id}", status_code=303)


@router.post("/cart/update")
def cart_update(request: Request, listing_id: Annotated[int, Form()], qty: Annotated[str, Form()],
                csrf: Annotated[str, Form()] = ""):
    user = require_any_role(request, BUYER)
    check_csrf(request, csrf)
    q = _num(qty)
    res = repo.cart_set(user["id"], listing_id, q) if q and q > 0 else "below_min"
    if res != "ok":
        flash(request, "bad", *PROBLEM_MSG.get(res, PROBLEM_MSG["unavailable"]))
    return RedirectResponse("/cart", status_code=303)


@router.post("/cart/remove")
def cart_remove(request: Request, listing_id: Annotated[int, Form()], csrf: Annotated[str, Form()] = ""):
    user = require_any_role(request, BUYER)
    check_csrf(request, csrf)
    repo.cart_remove(user["id"], listing_id)
    return RedirectResponse("/cart", status_code=303)


def _cart_view(user_id: int) -> dict:
    lines = repo.cart(user_id)
    for ln in lines:
        ln["problem"] = repo.line_problem(ln, ln["want"])
        ln["line_total"] = (ln["price_now"] * ln["want"]).quantize(Decimal("0.01"))
        ln["saving"] = ((ln["price_per_unit"] - ln["price_now"]) * ln["want"]).quantize(Decimal("0.01"))
    subtotal = sum((ln["line_total"] for ln in lines), Decimal("0"))
    discount = sum((ln["saving"] for ln in lines), Decimal("0"))
    fee = delivery_fee() if lines else Decimal("0")
    return {"lines": lines, "subtotal": subtotal, "discount": discount, "fee": fee, "total": subtotal + fee,
            "blocked": any(ln["problem"] for ln in lines), "farmers": len({ln["farmer_id"] for ln in lines})}


@router.get("/cart")
def cart_page(request: Request):
    user = require_any_role(request, BUYER)
    return render(request, "market/cart.html", {**_cart_view(user["id"]), "active": "cart"})


@router.get("/checkout")
def checkout_page(request: Request):
    user = require_any_role(request, BUYER)
    view = _cart_view(user["id"])
    if not view["lines"]:
        return RedirectResponse("/cart", status_code=303)
    token = secrets.token_urlsafe(16)
    request.session["checkout_token"] = token          # one order per checkout page (double click safe)
    me = repo.get_customer(user["id"]) or {}
    return render(request, "market/checkout.html", {**view, "me": me, "token": token, "active": "cart"})


@router.post("/checkout")
def checkout_submit(request: Request, delivery_address: Annotated[str, Form()], phone: Annotated[str, Form()],
                    full_name: Annotated[str, Form()] = "", note: Annotated[str, Form()] = "",
                    payment: Annotated[str, Form()] = "cod", token: Annotated[str, Form()] = "",
                    csrf: Annotated[str, Form()] = ""):
    user = require_any_role(request, BUYER)
    check_csrf(request, csrf)
    if not token or token != request.session.get("checkout_token"):
        flash(request, "bad", "এই অর্ডারটি আগেই জমা হয়েছে বা পাতাটি পুরনো। আমার অর্ডার দেখুন।",
              "This order was already sent or the page is old. Check My orders.")
        return RedirectResponse("/customer/orders", status_code=303)
    address = " ".join(delivery_address.split())[:300]
    norm = normalize_phone(phone)
    errors = []
    if len(address) < 5:
        errors.append(("ডেলিভারির ঠিকানা লিখুন (যেমন: লটাখোলা, দোহার, ঢাকা)।", "Write the delivery location (e.g. Lotakhole, Dohar, Dhaka)."))
    if not norm:
        errors.append(("সঠিক মোবাইল নম্বর দিন।", "Enter a valid mobile number."))
    if payment != "cod":                                 # only Cash on Delivery is live
        errors.append(("এখন শুধু ক্যাশ অন ডেলিভারি চালু আছে।", "Only Cash on Delivery is available now."))
    name = " ".join(full_name.split())[:100]
    if errors:
        for e in errors:
            flash(request, "bad", *e)
        return RedirectResponse("/checkout", status_code=303)
    if 2 <= len(name) and name != user.get("name"):
        me = repo.get_customer(user["id"]) or {}
        repo.update_customer(user["id"], name, me.get("district_code"), me.get("upazila_code"), me.get("address"))
        request.session["user"] = {**user, "name": name}
    result = repo.place_order(user["id"], address, norm, note.strip()[:500] or None, delivery_fee())
    if not result["ok"]:
        for title, why in result["problems"]:
            bn, en = PROBLEM_MSG.get(why, PROBLEM_MSG["unavailable"])
            flash(request, "bad", f"{title}: {bn}" if title else bn, f"{title}: {en}" if title else en)
        return RedirectResponse("/cart", status_code=303)
    request.session.pop("checkout_token", None)
    flash(request, "ok", f"অর্ডার হয়েছে! নম্বর: {result['order_number']}", f"Order placed! Number: {result['order_number']}")
    return RedirectResponse(f"/customer/orders/{result['order_number']}", status_code=303)


# Phase B1 (saved items, favourite farmers, alerts, reviews, farmer page) lives in routes_market_b1.py
from chashibondhu.web.routes_market_b1 import router as _b1_router  # noqa: E402

router.include_router(_b1_router)

# Phase B2 (product comparison) lives in routes_market_b2.py
from chashibondhu.web.routes_market_b2 import router as _b2_router  # noqa: E402

router.include_router(_b2_router)

# Phase B3 (customer shopping assistant) lives in routes_shop_ai.py
from chashibondhu.web.routes_shop_ai import router as _shop_ai_router  # noqa: E402

router.include_router(_shop_ai_router)
