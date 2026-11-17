"""SQL for Marketplace Phase B1: saved items, favourite farmers, product alerts, verified reviews.

The database enforces the important rules too (migration 006): a review needs a delivered purchase,
alerts are deduplicated, notifications go to active customers only.
"""
from __future__ import annotations

from chashibondhu.web.db import connect, execute, fetch_all, fetch_one

ACTIVE_LISTING = ("SELECT l.id, l.farmer_id FROM listings l JOIN users u ON u.id = l.farmer_id "
                  "WHERE l.id = %s AND l.status = 'active' AND u.status = 'active' AND u.role = 'farmer'")


def _active_listing(listing_id: int) -> dict | None:
    return fetch_one(ACTIVE_LISTING, (listing_id,))


# ---------------------------------------------------------------- saved items
def toggle_saved(customer_id: int, listing_id: int) -> bool | None:
    """-> True saved, False removed, None product not found. Removing works even if the product is gone."""
    with connect() as conn:
        gone = conn.execute("DELETE FROM saved_items WHERE customer_id = %s AND listing_id = %s",
                            (customer_id, listing_id)).rowcount
        if gone:
            return False
        if not conn.execute(ACTIVE_LISTING, (listing_id,)).fetchone():
            return None
        conn.execute("INSERT INTO saved_items (customer_id, listing_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                     (customer_id, listing_id))
        return True


def save_for_later(customer_id: int, listing_id: int) -> bool:
    """Cart -> saved list (one transaction)."""
    with connect() as conn:
        n = conn.execute("DELETE FROM cart_items WHERE customer_id = %s AND listing_id = %s",
                         (customer_id, listing_id)).rowcount
        if not n:
            return False
        conn.execute("INSERT INTO saved_items (customer_id, listing_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                     (customer_id, listing_id))
        return True


# ---------------------------------------------------------------- favourite farmers
def toggle_follow(customer_id: int, farmer_id: int) -> bool | None:
    with connect() as conn:
        if conn.execute("DELETE FROM favourite_farmers WHERE customer_id = %s AND farmer_id = %s",
                        (customer_id, farmer_id)).rowcount:
            return False
        if not conn.execute("SELECT 1 FROM users WHERE id = %s AND role = 'farmer' AND status = 'active'",
                            (farmer_id,)).fetchone():
            return None
        conn.execute("INSERT INTO favourite_farmers (customer_id, farmer_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                     (customer_id, farmer_id))
        return True


def is_following(customer_id: int, farmer_id: int) -> bool:
    return fetch_one("SELECT 1 AS x FROM favourite_farmers WHERE customer_id = %s AND farmer_id = %s",
                     (customer_id, farmer_id)) is not None


# ---------------------------------------------------------------- alerts
def set_alert(customer_id: int, listing_id: int, restock: bool, price_drop: bool) -> bool:
    """Both False = alert removed. False if the product is not active."""
    if not restock and not price_drop:
        execute("DELETE FROM product_alerts WHERE customer_id = %s AND listing_id = %s", (customer_id, listing_id))
        return True
    if not _active_listing(listing_id):
        return False
    execute("INSERT INTO product_alerts (customer_id, listing_id, on_restock, on_price_drop) VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (customer_id, listing_id) DO UPDATE SET on_restock = EXCLUDED.on_restock, "
            "on_price_drop = EXCLUDED.on_price_drop", (customer_id, listing_id, restock, price_drop))
    return True


# ---------------------------------------------------------------- reviews
def save_review(customer_id: int, listing_id: int, rating: int, comment: str | None) -> str:
    """'ok' | 'not_verified'. One review per customer per product; writing again edits it."""
    try:
        execute("INSERT INTO reviews (listing_id, customer_id, rating, comment) VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (listing_id, customer_id) DO UPDATE SET rating = EXCLUDED.rating, "
                "comment = EXCLUDED.comment", (listing_id, customer_id, rating, comment))
        return "ok"
    except Exception as e:  # the trigger refuses reviews without a delivered purchase
        if getattr(e, "sqlstate", None) == "23514" or "delivered purchase" in str(e):
            return "not_verified"
        raise


def delete_review(customer_id: int, listing_id: int) -> int:
    return execute("DELETE FROM reviews WHERE customer_id = %s AND listing_id = %s", (customer_id, listing_id))


# ---------------------------------------------------------------- product page (one call)
def product_extras(customer_id: int | None, listing_id: int, farmer_id: int) -> dict:
    s = fetch_one("SELECT count(*) AS n, round(avg(rating), 1) AS avg FROM reviews "
                  "WHERE listing_id = %s AND status = 'visible'", (listing_id,))
    reviews = fetch_all(
        "SELECT r.rating, r.comment, r.created_at, r.updated_at, split_part(u.full_name, ' ', 1) AS name "
        "FROM reviews r JOIN users u ON u.id = r.customer_id "
        "WHERE r.listing_id = %s AND r.status = 'visible' ORDER BY r.updated_at DESC LIMIT 20", (listing_id,))
    out = {"review_n": int(s["n"] or 0) if s else 0, "review_avg": s["avg"] if s else None, "reviews": reviews,
           "saved": False, "following": False, "alert": None, "can_review": False, "my_review": None}
    if not customer_id:
        return out
    st = fetch_one(
        "SELECT EXISTS (SELECT 1 FROM saved_items WHERE customer_id = %(c)s AND listing_id = %(l)s) AS saved, "
        "EXISTS (SELECT 1 FROM favourite_farmers WHERE customer_id = %(c)s AND farmer_id = %(f)s) AS following, "
        "(SELECT json_build_object('restock', on_restock, 'price_drop', on_price_drop) FROM product_alerts "
        " WHERE customer_id = %(c)s AND listing_id = %(l)s) AS alert, "
        "EXISTS (SELECT 1 FROM order_items i JOIN orders o ON o.id = i.order_id WHERE o.customer_id = %(c)s "
        " AND i.listing_id = %(l)s AND o.status = 'delivered' AND i.farmer_status <> 'rejected') AS can_review",
        {"c": customer_id, "l": listing_id, "f": farmer_id}) or {}
    out.update({k: st.get(k) for k in ("saved", "following", "alert", "can_review")})
    out["my_review"] = fetch_one("SELECT rating, comment, status FROM reviews WHERE customer_id = %s AND listing_id = %s",
                                 (customer_id, listing_id))
    return out


# ---------------------------------------------------------------- "Saved" page
def saved_page(customer_id: int) -> dict:
    items = fetch_all(
        "SELECT l.id, l.title, l.unit, l.image_path, l.listing_type, l.quantity, l.min_order, "
        "COALESCE(l.discount_price, l.price_per_unit) AS price_now, l.price_per_unit, l.discount_price, "
        "(l.status = 'active' AND u.status = 'active') AS on_sale, u.full_name AS farmer_name, s.created_at "
        "FROM saved_items s JOIN listings l ON l.id = s.listing_id JOIN users u ON u.id = l.farmer_id "
        "WHERE s.customer_id = %s ORDER BY s.created_at DESC", (customer_id,))
    farmers = fetch_all(
        "SELECT u.id, u.full_name, u.district_code, u.upazila_code, u.avatar_path, "
        "(SELECT count(*) FROM listings l WHERE l.farmer_id = u.id AND l.status = 'active') AS active_listings "
        "FROM favourite_farmers f JOIN users u ON u.id = f.farmer_id "
        "WHERE f.customer_id = %s AND u.status = 'active' ORDER BY f.created_at DESC", (customer_id,))
    alerts = fetch_all(
        "SELECT a.listing_id, a.on_restock, a.on_price_drop, l.title "
        "FROM product_alerts a JOIN listings l ON l.id = a.listing_id "
        "WHERE a.customer_id = %s ORDER BY a.created_at DESC", (customer_id,))
    return {"items": items, "farmers": farmers, "alerts": alerts}


def farmer_listings(farmer_id: int, limit: int = 24) -> tuple[dict | None, list[dict]]:
    """Public farmer page: name/area + active products."""
    f = fetch_one("SELECT id, full_name, district_code, upazila_code, avatar_path FROM users "
                  "WHERE id = %s AND role = 'farmer' AND status = 'active'", (farmer_id,))
    if not f:
        return None, []
    rows = fetch_all(
        "SELECT l.id, l.title, l.crop_id, l.category, l.unit, l.price_per_unit, l.discount_price, "
        "COALESCE(l.discount_price, l.price_per_unit) AS price_now, l.quantity, l.min_order, l.listing_type, "
        "l.available_from, l.harvest_date, l.image_path, l.is_organic, l.farming_method, l.district_code, "
        "l.upazila_code, l.created_at, %s AS farmer_name, l.farmer_id "
        "FROM listings l WHERE l.farmer_id = %s AND l.status = 'active' ORDER BY l.created_at DESC LIMIT %s",
        (f["full_name"], farmer_id, limit))
    return f, rows
