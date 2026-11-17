"""Marketplace Phase B1 routes: saved items, favourite farmers, alerts, verified reviews, farmer page.

Mounted from routes_market.py (app.py does not change). Customers only for every action.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from chashibondhu.web import repo_market_b1 as b1
from chashibondhu.web.deps import check_csrf, flash, render, require_any_role

router = APIRouter(include_in_schema=False)
BUYER = ("customer",)


def _back(request: Request, fallback: str) -> RedirectResponse:
    """Return to the page the form was on (same site only)."""
    ref = request.headers.get("referer", "")
    base = str(request.base_url)
    target = "/" + ref[len(base):] if ref.startswith(base) else fallback
    return RedirectResponse(target if target.startswith("/") and not target.startswith("//") else fallback,
                            status_code=303)


@router.post("/market/{listing_id}/save")
def save(request: Request, listing_id: int, csrf: Annotated[str, Form()] = ""):
    user = require_any_role(request, BUYER)
    check_csrf(request, csrf)
    res = b1.toggle_saved(user["id"], listing_id)
    if res is None:
        raise HTTPException(status_code=404)
    flash(request, "ok", *(("সংরক্ষণ হয়েছে।", "Saved.") if res else ("সংরক্ষিত তালিকা থেকে সরানো হয়েছে।", "Removed from saved.")))
    return _back(request, f"/market/{listing_id}")


@router.post("/cart/later")
def later(request: Request, listing_id: Annotated[int, Form()], csrf: Annotated[str, Form()] = ""):
    user = require_any_role(request, BUYER)
    check_csrf(request, csrf)
    if b1.save_for_later(user["id"], listing_id):
        flash(request, "ok", "পরে কেনার জন্য সংরক্ষণ হয়েছে।", "Saved for later.")
    return RedirectResponse("/cart", status_code=303)


@router.post("/farmers/{farmer_id}/follow")
def follow(request: Request, farmer_id: int, csrf: Annotated[str, Form()] = ""):
    user = require_any_role(request, BUYER)
    check_csrf(request, csrf)
    res = b1.toggle_follow(user["id"], farmer_id)
    if res is None:
        raise HTTPException(status_code=404)
    flash(request, "ok", *(("প্রিয় কৃষক তালিকায় যোগ হয়েছে। নতুন পণ্য দিলে জানানো হবে।",
                            "Added to favourite farmers. You will be told about new products.") if res
                           else ("প্রিয় কৃষক তালিকা থেকে সরানো হয়েছে।", "Removed from favourite farmers.")))
    return _back(request, f"/market/farmer/{farmer_id}")


@router.post("/market/{listing_id}/alert")
def alert(request: Request, listing_id: int, csrf: Annotated[str, Form()] = "",
          restock: Annotated[str, Form()] = "", price_drop: Annotated[str, Form()] = ""):
    user = require_any_role(request, BUYER)
    check_csrf(request, csrf)
    want_r, want_p = restock == "1", price_drop == "1"
    if not b1.set_alert(user["id"], listing_id, want_r, want_p):
        raise HTTPException(status_code=404)
    if want_r or want_p:
        flash(request, "ok", "ঠিক আছে, পরিবর্তন হলে নোটিফিকেশন পাবেন।", "OK, you will get a notification when it changes.")
    else:
        flash(request, "ok", "এই পণ্যের নোটিফিকেশন বন্ধ।", "Alerts for this product are off.")
    return _back(request, f"/market/{listing_id}")


@router.post("/market/{listing_id}/review")
def review(request: Request, listing_id: int, csrf: Annotated[str, Form()] = "",
           rating: Annotated[str, Form()] = "", comment: Annotated[str, Form()] = "",
           delete: Annotated[str, Form()] = ""):
    user = require_any_role(request, BUYER)
    check_csrf(request, csrf)
    if delete == "1":
        b1.delete_review(user["id"], listing_id)
        flash(request, "ok", "রিভিউ মুছে ফেলা হয়েছে।", "Review deleted.")
        return RedirectResponse(f"/market/{listing_id}#reviews", status_code=303)
    stars = int(rating) if rating in ("1", "2", "3", "4", "5") else 0
    text = " ".join(comment.split())[:1000] or None
    if not stars:
        flash(request, "bad", "১ থেকে ৫ তারা বেছে নিন।", "Choose 1 to 5 stars.")
    elif b1.save_review(user["id"], listing_id, stars, text) == "ok":
        flash(request, "ok", "রিভিউ দেওয়ার জন্য ধন্যবাদ!", "Thank you for your review!")
    else:
        flash(request, "bad", "শুধু ডেলিভারি পাওয়া পণ্যের রিভিউ দেওয়া যায়।", "You can review only products delivered to you.")
    return RedirectResponse(f"/market/{listing_id}#reviews", status_code=303)


@router.get("/customer/saved")
def saved_page(request: Request):
    user = require_any_role(request, BUYER)
    return render(request, "customer/saved.html", {**b1.saved_page(user["id"]), "active": "c_saved"})


@router.get("/market/farmer/{farmer_id}")
def farmer_page(request: Request, farmer_id: int):
    from chashibondhu.web.deps import current_user
    farmer, listings = b1.farmer_listings(farmer_id)
    if not farmer:
        raise HTTPException(status_code=404)
    user = current_user(request)
    following = False
    if user and user.get("role") == "customer":
        following = b1.is_following(user["id"], farmer_id)
    return render(request, "market/farmer.html", {"farmer": farmer, "listings": listings,
                                                  "following": following, "active": "market"})
