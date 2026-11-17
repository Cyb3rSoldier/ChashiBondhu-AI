"""Buyer-side stage names for pre-harvest matching (shown in the customer dashboard).

Pure functions on rows from repo.list_requests / repo.request_matches / repo.potential_forecasts.
Never changes data. A match is interest, never an order; only "Available for Order" can be bought.
"""
from __future__ import annotations

from datetime import date

# main path, in order (index = step number in the progress bar)
STEPS = [
    ("created", "চাহিদা দেওয়া হয়েছে", "Demand request created"),
    ("potential", "সম্ভাব্য মিল", "Potential match"),
    ("interest", "আগ্রহ জানানো", "Interest shown"),
    ("awaiting_harvest", "ফসল তোলার অপেক্ষা", "Awaiting harvest"),
    ("awaiting_qty", "আসল পরিমাণ নিশ্চিতের অপেক্ষা", "Awaiting actual quantity confirmation"),
    ("available", "অর্ডার করা যাবে", "Available for order"),
    ("converted", "অর্ডার হয়েছে", "Converted to order"),
]
STEP_INDEX = {k: i for i, (k, _, _) in enumerate(STEPS)}

LABELS = {
    "created": ("চাহিদা দেওয়া হয়েছে", "Demand request created"),
    "potential": ("সম্ভাব্য মিল আছে", "Potential match"),
    "buyer_interested": ("আপনি আগ্রহী — কৃষকের উত্তরের অপেক্ষা", "Buyer interested — waiting for the farmer"),
    "farmer_interested": ("কৃষক আগ্রহী — আপনার উত্তর দরকার", "Farmer interested — your answer needed"),
    "awaiting_harvest": ("দুজনেই রাজি — ফসল তোলার অপেক্ষা", "Both agreed — awaiting harvest"),
    "awaiting_qty": ("ফসল তোলার সময় — কৃষকের আসল পরিমাণ নিশ্চিতের অপেক্ষা",
                     "Harvest time — awaiting the farmer's actual quantity"),
    "available": ("অর্ডার করা যাবে", "Available for order"),
    "converted": ("অর্ডার হয়েছে", "Converted to order"),
    "cancelled": ("বাতিল", "Cancelled"),
    "expired": ("মেয়াদ শেষ", "Expired"),
}
STAGE_STEP = {"created": "created", "potential": "potential", "buyer_interested": "interest",
              "farmer_interested": "interest", "awaiting_harvest": "awaiting_harvest", "awaiting_qty": "awaiting_qty",
              "available": "available", "converted": "converted"}


def match_stage(m: dict, today: date | None = None) -> str:
    today = today or date.today()
    s = m.get("status")
    if s == "buyer_interested":
        return "buyer_interested"
    if s == "farmer_offered":
        return "farmer_interested"
    if s == "agreed":
        start = m.get("harvest_from")
        return "awaiting_qty" if start and start <= today else "awaiting_harvest"
    if s == "qty_confirmed":
        return "available"
    if s == "converted":
        return "converted"
    if s == "expired":
        return "expired"
    return "cancelled"                     # cancelled, declined, anything unknown


def request_stage(r: dict, today: date | None = None) -> str:
    """The furthest live stage of a request (cancelled/expired requests show that)."""
    if r.get("status") == "cancelled":
        return "cancelled"
    stages = [match_stage(m, today) for m in r.get("matches") or []]
    live = [s for s in stages if s in STAGE_STEP]
    if live:
        return max(live, key=lambda s: STEP_INDEX[STAGE_STEP[s]])
    if r.get("status") == "expired":
        return "expired"
    if stages and all(s in ("cancelled", "expired") for s in stages) and not r.get("potential"):
        return "cancelled" if "cancelled" in stages else "expired"
    return "potential" if r.get("potential") else "created"


def decorate(items: list[dict], today: date | None = None) -> list[dict]:
    """Adds stage keys used by the template: m.stage, r.stage, r.step (index on STEPS or None)."""
    for r in items:
        for m in r.get("matches") or []:
            m["stage"] = match_stage(m, today)
        r["stage"] = request_stage(r, today)
        r["step"] = STEP_INDEX.get(STAGE_STEP.get(r["stage"], ""), None)
    return items
