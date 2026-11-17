"""SQL for Marketplace Phase B2: product comparison rows, demand-request summary for the dashboard."""
from __future__ import annotations

from chashibondhu.web.db import fetch_all, fetch_one


def compare_rows(ids: list[int]) -> list[dict]:
    """Active products by id (any order), with review average. Unknown/hidden ids are simply missing."""
    if not ids:
        return []
    return fetch_all(
        "SELECT l.id, l.title, l.crop_id, l.category, l.unit, l.price_per_unit, l.discount_price, "
        "COALESCE(l.discount_price, l.price_per_unit) AS price_now, l.quantity, l.min_order, l.listing_type, "
        "l.available_from, l.harvest_date, l.image_path, l.farming_method, l.district_code, l.upazila_code, "
        "u.full_name AS farmer_name, u.id AS farmer_id, "
        "(SELECT round(avg(r.rating), 1) FROM reviews r WHERE r.listing_id = l.id AND r.status = 'visible') AS review_avg, "
        "(SELECT count(*) FROM reviews r WHERE r.listing_id = l.id AND r.status = 'visible') AS review_n "
        "FROM listings l JOIN users u ON u.id = l.farmer_id "
        "WHERE l.id = ANY(%s) AND l.status = 'active' AND u.status = 'active' AND u.role = 'farmer'", (ids,))


def request_summary(buyer_id: int) -> dict:
    """Numbers for the dashboard card (real rows only)."""
    return fetch_one("""
        SELECT (SELECT count(*) FROM buyer_demand_requests WHERE buyer_id = %(b)s AND status = 'open') AS open_requests,
               count(*) FILTER (WHERE m.status = 'farmer_offered') AS need_answer,
               count(*) FILTER (WHERE m.status = 'agreed') AS waiting_harvest,
               count(*) FILTER (WHERE m.status = 'qty_confirmed') AS can_order
        FROM harvest_matches m JOIN buyer_demand_requests r ON r.id = m.request_id
        WHERE r.buyer_id = %(b)s""", {"b": buyer_id}) or {}
