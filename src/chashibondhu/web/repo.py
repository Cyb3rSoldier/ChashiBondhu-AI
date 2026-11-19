"""All SQL for the website lives here (parameterised queries only).

Routes call these functions, so tests can replace them with an in-memory fake.
"""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

from chashibondhu.web.db import connect, execute, fetch_all, fetch_one

MAX_FAILED_LOGINS = 5
LOCK_MINUTES = 15


# ---------------------------------------------------------------- users
def get_user_by_phone(phone: str) -> dict | None:
    return fetch_one("SELECT * FROM users WHERE phone = %s", (phone,))


def get_user(user_id: int) -> dict | None:
    return fetch_one("SELECT * FROM users WHERE id = %s", (user_id,))


def create_farmer(full_name: str, phone: str, password_hash: str, district_code: str | None,
                  upazila_code: str | None, land_decimal: Decimal | None, land_text: str | None,
                  main_crops: list[str]) -> int:
    with connect() as conn:
        row = conn.execute(
            "INSERT INTO users (role, full_name, phone, password_hash, district_code, upazila_code) "
            "VALUES ('farmer', %s, %s, %s, %s, %s) RETURNING id",
            (full_name, phone, password_hash, district_code, upazila_code)).fetchone()
        conn.execute("INSERT INTO farmer_profiles (user_id, land_decimal, land_text, main_crops) "
                     "VALUES (%s, %s, %s, %s)", (row["id"], land_decimal, land_text, main_crops))
        return int(row["id"])


def is_locked(user: dict) -> bool:
    r = fetch_one("SELECT (locked_until IS NOT NULL AND locked_until > now()) AS locked "
                  "FROM users WHERE id = %s", (user["id"],))
    return bool(r and r["locked"])


def record_login(user_id: int, ok: bool) -> None:
    if ok:
        execute("UPDATE users SET failed_logins = 0, locked_until = NULL, last_login_at = now() "
                "WHERE id = %s", (user_id,))
    else:
        execute("UPDATE users SET failed_logins = failed_logins + 1, "
                "locked_until = CASE WHEN failed_logins + 1 >= %s "
                "THEN now() + make_interval(mins => %s) ELSE locked_until END WHERE id = %s",
                (MAX_FAILED_LOGINS, LOCK_MINUTES, user_id))


def get_farmer_profile(user_id: int) -> dict:
    return fetch_one(
        "SELECT u.id, u.full_name, u.phone, u.district_code, u.upazila_code, u.preferred_lang, "
        "u.address, u.avatar_path, u.created_at, p.land_decimal, p.land_text, p.main_crops, p.has_irrigation, p.verified_at "
        "FROM users u LEFT JOIN farmer_profiles p ON p.user_id = u.id WHERE u.id = %s", (user_id,)) or {}


def update_farmer_profile(user_id: int, full_name: str, district_code: str | None,
                          upazila_code: str | None, land_decimal: Decimal | None,
                          land_text: str | None, main_crops: list[str],
                          has_irrigation: bool | None) -> None:
    with connect() as conn:
        conn.execute("UPDATE users SET full_name = %s, district_code = %s, upazila_code = %s "
                     "WHERE id = %s", (full_name, district_code, upazila_code, user_id))
        conn.execute(
            "INSERT INTO farmer_profiles (user_id, land_decimal, land_text, main_crops, has_irrigation) "
            "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (user_id) DO UPDATE SET "
            "land_decimal = EXCLUDED.land_decimal, land_text = EXCLUDED.land_text, "
            "main_crops = EXCLUDED.main_crops, has_irrigation = EXCLUDED.has_irrigation",
            (user_id, land_decimal, land_text, main_crops, has_irrigation))


# ---------------------------------------------------------------- dashboard numbers
def farmer_stats(farmer_id: int) -> dict:
    """All overview numbers for ONE farmer, straight from the database."""
    return fetch_one("""
        SELECT
          (SELECT count(*) FROM listings WHERE farmer_id = %(f)s AND status <> 'archived') AS total_products,
          (SELECT count(*) FROM listings WHERE farmer_id = %(f)s AND status = 'active' AND quantity > 0)
                                                                                         AS active_listings,
          (SELECT count(*) FROM listings WHERE farmer_id = %(f)s AND status <> 'archived'
                                         AND (status = 'sold_out' OR quantity <= 0))     AS out_of_stock,
          (SELECT count(*) FROM plantings WHERE farmer_id = %(f)s AND status IN ('planned', 'growing')) AS growing,
          (SELECT count(DISTINCT order_id) FROM order_items WHERE farmer_id = %(f)s)    AS total_orders,
          (SELECT count(DISTINCT oi.order_id) FROM order_items oi JOIN orders o ON o.id = oi.order_id
            WHERE oi.farmer_id = %(f)s AND o.status <> 'cancelled'
              AND oi.farmer_status IN ('pending', 'accepted', 'packed'))                AS pending_orders,
          (SELECT count(DISTINCT order_id) FROM order_items WHERE farmer_id = %(f)s
                                                  AND farmer_status = 'pending')         AS new_orders,
          (SELECT count(DISTINCT oi.order_id) FROM order_items oi JOIN orders o ON o.id = oi.order_id
            WHERE oi.farmer_id = %(f)s AND o.status = 'delivered'
              AND oi.farmer_status <> 'rejected')                                       AS completed_orders,
          (SELECT COALESCE(sum(amount), 0) FROM farmer_ledger WHERE farmer_id = %(f)s)  AS earned,
          (SELECT COALESCE(sum(oi.line_total), 0) FROM order_items oi JOIN orders o ON o.id = oi.order_id
            WHERE oi.farmer_id = %(f)s AND o.status <> 'cancelled' AND o.payment_status <> 'refunded'
              AND oi.farmer_status IN ('accepted', 'packed', 'handed_over')
              AND NOT EXISTS (SELECT 1 FROM farmer_ledger l WHERE l.order_item_id = oi.id))
                                                                                         AS pending_earnings
    """, {"f": farmer_id}) or {}


# ---------------------------------------------------------------- farm plots + plantings
def list_plots(farmer_id: int) -> list[dict]:
    return fetch_all("SELECT * FROM farm_plots WHERE farmer_id = %s ORDER BY created_at", (farmer_id,))


def add_plot(farmer_id: int, name: str, area_decimal: Decimal | None, land_type: str | None,
             irrigation: bool | None, upazila_code: str | None) -> int:
    r = fetch_one("INSERT INTO farm_plots (farmer_id, name, area_decimal, land_type, irrigation, upazila_code) "
                  "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                  (farmer_id, name, area_decimal, land_type, irrigation, upazila_code))
    return int(r["id"])


def delete_plot(farmer_id: int, plot_id: int) -> int:
    return execute("DELETE FROM farm_plots WHERE id = %s AND farmer_id = %s", (plot_id, farmer_id))


def list_plantings(farmer_id: int) -> list[dict]:
    return fetch_all("SELECT pl.*, fp.name AS plot_name FROM plantings pl JOIN farm_plots fp ON fp.id = pl.plot_id "
                     "WHERE pl.farmer_id = %s ORDER BY pl.status = 'harvested', pl.expected_harvest_on NULLS LAST, pl.id DESC",
                     (farmer_id,))


def add_planting(farmer_id: int, plot_id: int, crop_id: str, variety: str | None, season: str | None,
                 planted_on: date | None, expected_harvest_on: date | None, status: str) -> int | None:
    r = fetch_one("INSERT INTO plantings (plot_id, farmer_id, crop_id, variety, season, planted_on, "
                  "expected_harvest_on, status) SELECT id, %s, %s, %s, %s, %s, %s, %s FROM farm_plots "
                  "WHERE id = %s AND farmer_id = %s RETURNING id",
                  (farmer_id, crop_id, variety, season, planted_on, expected_harvest_on, status,
                   plot_id, farmer_id))
    return int(r["id"]) if r else None


def set_planting_status(farmer_id: int, planting_id: int, status: str) -> int:
    return execute("UPDATE plantings SET status = %s, harvested_on = CASE WHEN %s = 'harvested' "
                   "THEN COALESCE(harvested_on, CURRENT_DATE) ELSE harvested_on END "
                   "WHERE id = %s AND farmer_id = %s", (status, status, planting_id, farmer_id))


# ---------------------------------------------------------------- listings
def list_my_listings(farmer_id: int) -> list[dict]:
    return fetch_all("SELECT * FROM listings WHERE farmer_id = %s AND status <> 'archived' "
                     "ORDER BY status = 'hidden', created_at DESC", (farmer_id,))


def get_my_listing(farmer_id: int, listing_id: int) -> dict | None:
    return fetch_one("SELECT * FROM listings WHERE id = %s AND farmer_id = %s AND status <> 'archived'",
                     (listing_id, farmer_id))


LISTING_FIELDS = ("listing_type", "crop_id", "title", "category", "description", "unit", "price_per_unit",
                  "quantity", "min_order", "is_organic", "available_from", "status",
                  "farming_method", "harvest_date", "extra_info", "discount_price")


def create_listing(farmer_id: int, data: dict, image_path: str | None,
                   district_code: str | None, upazila_code: str | None) -> int:
    cols = list(LISTING_FIELDS) + ["image_path", "district_code", "upazila_code", "farmer_id"]
    vals = [data[k] for k in LISTING_FIELDS] + [image_path, district_code, upazila_code, farmer_id]
    r = fetch_one(f"INSERT INTO listings ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))}) "
                  "RETURNING id", tuple(vals))
    return int(r["id"])


def update_listing(farmer_id: int, listing_id: int, data: dict, image_path: str | None) -> int:
    sets = [f"{k} = %s" for k in LISTING_FIELDS]
    vals = [data[k] for k in LISTING_FIELDS]
    if image_path:
        sets.append("image_path = %s")
        vals.append(image_path)
    return execute(f"UPDATE listings SET {', '.join(sets)} WHERE id = %s AND farmer_id = %s "
                   "AND status <> 'archived'", tuple(vals + [listing_id, farmer_id]))


def set_listing_status(farmer_id: int, listing_id: int, status: str) -> int:
    return execute("UPDATE listings SET status = %s WHERE id = %s AND farmer_id = %s AND status <> 'archived'",
                   (status, listing_id, farmer_id))


def archive_listing(farmer_id: int, listing_id: int) -> int:
    """"Delete" for the farmer = soft delete. Old orders keep their link; the market stops showing it."""
    return execute("UPDATE listings SET status = 'archived', archived_at = now() "
                   "WHERE id = %s AND farmer_id = %s AND status <> 'archived'", (listing_id, farmer_id))


def public_listings(limit: int = 8) -> list[dict]:
    """Newest active products for the home page. Same columns and rules as the bazar (MARKET_COLS / MARKET_FROM),
    so the home page and the bazar always show the same price, discount, stock and district."""
    return fetch_all(f"SELECT {MARKET_COLS} {MARKET_FROM} ORDER BY l.created_at DESC LIMIT %s", (limit,))


def market_listings(q: str, crop_id: str | None, listing_type: str | None, limit: int = 24) -> list[dict]:
    """Home-page search: active products filtered by title text, crop and type (same columns as the bazar)."""
    sql = f"SELECT {MARKET_COLS} {MARKET_FROM}"
    params: list = []
    if q:
        safe = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        sql += " AND l.title ILIKE %s"
        params.append(f"%{safe}%")
    if crop_id:
        sql += " AND l.crop_id = %s"
        params.append(crop_id)
    if listing_type:
        sql += " AND l.listing_type = %s"
        params.append(listing_type)
    sql += " ORDER BY l.created_at DESC LIMIT %s"
    params.append(int(limit))
    return fetch_all(sql, tuple(params))


def public_counts() -> dict:
    return fetch_one("SELECT (SELECT count(*) FROM users WHERE role = 'farmer' AND status = 'active') AS farmers, "
                     "(SELECT count(*) FROM listings WHERE status = 'active') AS listings, "
                     "(SELECT count(DISTINCT district_code) FROM users WHERE role = 'farmer' "
                     " AND district_code IS NOT NULL) AS districts") or {}


# ---------------------------------------------------------------- orders for a farmer
ORDER_PERIODS = {"today": "1 day", "week": "7 days", "month": "30 days"}


def farmer_order_items(farmer_id: int, period: str = "all") -> list[dict]:
    """Only THIS farmer's items. Customer phone/address are shown only after the farmer confirms."""
    sql = ("SELECT oi.*, o.order_number, o.status AS order_status, o.payment_status, o.payment_method, "
           "o.created_at, u.full_name AS customer_name, "
           "CASE WHEN oi.farmer_status IN ('accepted', 'packed', 'handed_over') THEN o.delivery_address END "
           "AS delivery_address, "
           "CASE WHEN oi.farmer_status IN ('accepted', 'packed', 'handed_over') THEN o.phone END AS customer_phone "
           "FROM order_items oi JOIN orders o ON o.id = oi.order_id JOIN users u ON u.id = o.customer_id "
           "WHERE oi.farmer_id = %s")
    params: list = [farmer_id]
    if period in ORDER_PERIODS:
        sql += " AND o.created_at >= now() - %s::interval"
        params.append(ORDER_PERIODS[period])
    sql += " ORDER BY o.created_at DESC LIMIT 200"
    return fetch_all(sql, tuple(params))


# farmer step -> allowed next steps (server-side check, the page buttons are only a convenience)
ITEM_FLOW = {"pending": ("accepted", "rejected"), "accepted": ("packed", "rejected"), "packed": ("handed_over",)}


def set_item_farmer_status(farmer_id: int, item_id: int, status: str) -> str:
    """Move one order item to the next step, in ONE transaction with row locks.

    accepted  -> stock is taken from the listing once (never below zero, so no overselling)
    rejected  -> stock is given back if it was taken
    Returns: "ok", "not_found", "bad_step", "order_closed", "no_stock", "no_listing".
    """
    with connect() as conn:
        item = conn.execute(
            "SELECT oi.id, oi.listing_id, oi.quantity, oi.farmer_status, oi.stock_deducted, o.status AS order_status "
            "FROM order_items oi JOIN orders o ON o.id = oi.order_id "
            "WHERE oi.id = %s AND oi.farmer_id = %s FOR UPDATE OF oi", (item_id, farmer_id)).fetchone()
        if not item:
            return "not_found"
        if status not in ITEM_FLOW.get(item["farmer_status"], ()):
            return "bad_step"
        if item["order_status"] in ("cancelled", "delivered"):
            return "order_closed"
        deducted = item["stock_deducted"]
        if status == "accepted":
            if item["listing_id"] is None:
                return "no_listing"
            listing = conn.execute("SELECT id, quantity FROM listings WHERE id = %s AND farmer_id = %s FOR UPDATE",
                                   (item["listing_id"], farmer_id)).fetchone()
            if not listing:
                return "no_listing"
            if listing["quantity"] < item["quantity"]:
                return "no_stock"
            conn.execute("UPDATE listings SET quantity = quantity - %s, "
                         "status = CASE WHEN quantity - %s <= 0 AND status = 'active' THEN 'sold_out' ELSE status END "
                         "WHERE id = %s", (item["quantity"], item["quantity"], listing["id"]))
            deducted = True
        elif status == "rejected" and deducted and item["listing_id"] is not None:
            conn.execute("UPDATE listings SET quantity = quantity + %s, "
                         "status = CASE WHEN status = 'sold_out' THEN 'active' ELSE status END "
                         "WHERE id = %s AND farmer_id = %s", (item["quantity"], item["listing_id"], farmer_id))
            deducted = False
        conn.execute("UPDATE order_items SET farmer_status = %s, stock_deducted = %s WHERE id = %s",
                     (status, deducted, item_id))
        return "ok"


# ---------------------------------------------------------------- earnings (ledger)
def earnings_summary(farmer_id: int) -> dict:
    return fetch_one("""
        SELECT
          COALESCE(sum(amount) FILTER (WHERE entry_type = 'sale_credit'), 0)     AS lifetime_sales,
          COALESCE(sum(amount) FILTER (WHERE entry_type = 'refund_reversal'), 0) AS reversals,
          COALESCE(sum(amount), 0)                                               AS balance,
          count(*) FILTER (WHERE entry_type = 'sale_credit')                     AS completed_count
        FROM farmer_ledger WHERE farmer_id = %s""", (farmer_id,)) or {}


def earnings_series(farmer_id: int, span: str) -> list[dict]:
    """Daily totals for '7d' / '30d', monthly totals for '12m' (Bangladesh time). Empty periods = 0."""
    if span == "12m":
        sql = """
          SELECT to_char(m, 'YYYY-MM') AS label, COALESCE(sum(l.amount), 0) AS amount
          FROM generate_series(date_trunc('month', (now() AT TIME ZONE 'Asia/Dhaka')) - interval '11 months',
                               date_trunc('month', (now() AT TIME ZONE 'Asia/Dhaka')), interval '1 month') AS m
          LEFT JOIN farmer_ledger l ON l.farmer_id = %s
               AND date_trunc('month', l.created_at AT TIME ZONE 'Asia/Dhaka') = m
          GROUP BY m ORDER BY m"""
        return fetch_all(sql, (farmer_id,))
    days = 30 if span == "30d" else 7
    sql = """
      SELECT to_char(d, 'MM-DD') AS label, COALESCE(sum(l.amount), 0) AS amount
      FROM generate_series((now() AT TIME ZONE 'Asia/Dhaka')::date - (%s - 1), (now() AT TIME ZONE 'Asia/Dhaka')::date,
                           interval '1 day') AS d
      LEFT JOIN farmer_ledger l ON l.farmer_id = %s AND (l.created_at AT TIME ZONE 'Asia/Dhaka')::date = d::date
      GROUP BY d ORDER BY d"""
    return fetch_all(sql, (days, farmer_id))


def earnings_history(farmer_id: int, limit: int = 50) -> list[dict]:
    return fetch_all("SELECT l.entry_type, l.amount, l.created_at, oi.title, oi.quantity, oi.unit, o.order_number "
                     "FROM farmer_ledger l JOIN order_items oi ON oi.id = l.order_item_id "
                     "JOIN orders o ON o.id = oi.order_id WHERE l.farmer_id = %s "
                     "ORDER BY l.created_at DESC LIMIT %s", (farmer_id, limit))


def top_products(farmer_id: int, limit: int = 5) -> list[dict]:
    """Best sellers by credited money (refunded items drop out because the reversal cancels them)."""
    return fetch_all("SELECT oi.title, oi.unit, sum(oi.quantity) AS quantity, sum(l.amount) AS amount "
                     "FROM farmer_ledger l JOIN order_items oi ON oi.id = l.order_item_id "
                     "WHERE l.farmer_id = %s GROUP BY oi.title, oi.unit HAVING sum(l.amount) > 0 "
                     "ORDER BY amount DESC LIMIT %s", (farmer_id, limit))


# ---------------------------------------------------------------- market prices (observed only)
def price_products() -> list[dict]:
    return fetch_all("SELECT product_key, max(product_name_bn) AS name_bn, max(product_name_en) AS name_en, "
                     "max(observed_at) AS last_seen FROM market_prices GROUP BY product_key ORDER BY product_key")


def latest_prices(product_key: str) -> list[dict]:
    """Newest observation per market for one product (comparison across locations)."""
    return fetch_all("SELECT DISTINCT ON (market_name) * FROM market_prices WHERE product_key = %s "
                     "ORDER BY market_name, observed_at DESC", (product_key,))


def price_history(product_key: str, limit: int = 60) -> list[dict]:
    return fetch_all("SELECT observed_at, market_name, unit, price_min, price_max, price_avg, source_name "
                     "FROM market_prices WHERE product_key = %s ORDER BY observed_at DESC LIMIT %s",
                     (product_key, limit))


# ---------------------------------------------------------------- tips (admin announcements)
def farmer_tips(limit: int = 30) -> list[dict]:
    return fetch_all("SELECT id, title, body, created_at FROM announcements WHERE audience IN ('all', 'farmer') AND status = 'published' "
                     "ORDER BY created_at DESC LIMIT %s", (limit,))


# ---------------------------------------------------------------- complaints
def create_complaint(user_id: int, category: str, subject: str, description: str,
                     image_path: str | None) -> dict:
    return fetch_one("INSERT INTO complaints (user_id, category, subject, description, image_path) "
                     "VALUES (%s, %s, %s, %s, %s) RETURNING id, complaint_number",
                     (user_id, category, subject, description, image_path)) or {}


def list_complaints(user_id: int) -> list[dict]:
    return fetch_all("SELECT * FROM complaints WHERE user_id = %s ORDER BY created_at DESC LIMIT 100", (user_id,))


def get_complaint(user_id: int, complaint_id: int) -> dict | None:
    return fetch_one("SELECT * FROM complaints WHERE id = %s AND user_id = %s", (complaint_id, user_id))


# ---------------------------------------------------------------- account settings
def set_avatar(user_id: int, avatar_path: str | None) -> int:
    return execute("UPDATE users SET avatar_path = %s WHERE id = %s", (avatar_path, user_id))


def set_address(user_id: int, address: str | None) -> int:
    return execute("UPDATE users SET address = %s WHERE id = %s", (address, user_id))


def phone_taken(phone: str, except_user_id: int) -> bool:
    return fetch_one("SELECT 1 AS x FROM users WHERE phone = %s AND id <> %s", (phone, except_user_id)) is not None


def set_phone(user_id: int, phone: str) -> int:
    return execute("UPDATE users SET phone = %s WHERE id = %s", (phone, user_id))


def set_password_hash(user_id: int, password_hash: str) -> int:
    return execute("UPDATE users SET password_hash = %s WHERE id = %s", (password_hash, user_id))


# ---------------------------------------------------------------- AI history
def new_conversation(user_id: int | None) -> int:
    r = fetch_one("INSERT INTO ai_conversations (user_id) VALUES (%s) RETURNING id", (user_id,))
    return int(r["id"])


def add_ai_message(conversation_id: int, role: str, content: str, kind: str = "text", status: str | None = None,
                   crop_id: str | None = None, sources=None, candidates=None, model: str | None = None) -> int:
    from psycopg.types.json import Jsonb
    r = fetch_one("INSERT INTO ai_messages (conversation_id, role, kind, content, status, crop_id, sources, "
                  "candidates, model) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                  (conversation_id, role, kind, content, status, crop_id,
                   Jsonb(sources) if sources is not None else None,
                   Jsonb(candidates) if candidates is not None else None, model))
    execute("UPDATE ai_conversations SET updated_at = now(), title = COALESCE(title, left(%s::text, 80)) "
            "WHERE id = %s", (content if role == "user" else None, conversation_id))
    return int(r["id"])


def add_feedback(message_id: int, user_id: int | None, helpful: bool, comment: str | None) -> None:
    if user_id is None:
        execute("INSERT INTO ai_feedback (message_id, user_id, helpful, comment) VALUES (%s, NULL, %s, %s)",
                (message_id, helpful, comment))
    else:
        execute("INSERT INTO ai_feedback (message_id, user_id, helpful, comment) VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (message_id, user_id) DO UPDATE SET helpful = EXCLUDED.helpful, "
                "comment = EXCLUDED.comment", (message_id, user_id, helpful, comment))


def message_in_conversation(message_id: int, conversation_id: int) -> bool:
    return fetch_one("SELECT 1 AS ok FROM ai_messages WHERE id = %s AND conversation_id = %s",
                     (message_id, conversation_id)) is not None


def recent_questions(user_id: int, limit: int = 5) -> list[dict]:
    return fetch_all("SELECT m.content, m.kind, m.created_at FROM ai_messages m "
                     "JOIN ai_conversations c ON c.id = m.conversation_id "
                     "WHERE c.user_id = %s AND m.role = 'user' ORDER BY m.created_at DESC LIMIT %s",
                     (user_id, limit))


# ================================================================ Phase 2: pre-harvest buyer matching
# A forecast is an EXPECTED harvest, never stock. A match is interest, never an order.
ACTIVE_MATCH = ("buyer_interested", "farmer_offered", "agreed", "qty_confirmed", "converted")
FORECAST_FIELDS = ("crop_id", "product_name", "variety", "expected_qty", "unit", "harvest_from", "harvest_to",
                   "district_code", "upazila_code", "description", "quality_grade")
REQUEST_FIELDS = ("crop_id", "product_name", "variety", "quantity", "unit", "needed_from", "needed_to",
                  "district_code", "upazila_code", "note")
_ACTIVE_SQL = "('buyer_interested', 'farmer_offered', 'agreed', 'qty_confirmed', 'converted')"


def expire_stale() -> None:
    """Close what is clearly out of date (cheap; called when lists are opened)."""
    with connect() as conn:
        conn.execute("UPDATE harvest_forecasts SET status = 'expired' "
                     "WHERE status = 'open' AND harvest_to < CURRENT_DATE - 14")
        conn.execute("UPDATE buyer_demand_requests SET status = 'expired' "
                     "WHERE status = 'open' AND needed_to < CURRENT_DATE")
        conn.execute("UPDATE harvest_matches m SET status = 'expired' WHERE m.status IN "
                     "('buyer_interested', 'farmer_offered', 'agreed') AND EXISTS (SELECT 1 FROM harvest_forecasts f "
                     "WHERE f.id = m.forecast_id AND f.status = 'expired')")


# ---------------------------------------------------------------- forecasts (farmer)
def create_forecast(farmer_id: int, data: dict, client_id: str | None = None) -> dict:
    """Idempotent when client_id is given: the same offline draft returns the same forecast."""
    if client_id:
        old = fetch_one("SELECT id, version FROM harvest_forecasts WHERE farmer_id = %s AND client_id = %s",
                        (farmer_id, client_id))
        if old:
            return {**old, "duplicate": True}
    cols = list(FORECAST_FIELDS) + ["farmer_id", "client_id"]
    vals = [data[k] for k in FORECAST_FIELDS] + [farmer_id, client_id]
    r = fetch_one(f"INSERT INTO harvest_forecasts ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))}) "
                  "ON CONFLICT (farmer_id, client_id) DO NOTHING RETURNING id, version", tuple(vals))
    if r is None:        # a parallel retry inserted it first
        r = fetch_one("SELECT id, version FROM harvest_forecasts WHERE farmer_id = %s AND client_id = %s",
                      (farmer_id, client_id))
        return {**r, "duplicate": True}
    return {**r, "duplicate": False}


def update_forecast(farmer_id: int, forecast_id: int, data: dict, base_version: int | None) -> dict:
    """Optimistic lock: only updates when the farmer edited the newest version (or base_version is None = force).
    Returns {"ok": True, "version": n} or {"ok": False, "reason": "not_found"|"closed"|"conflict", "server": row}."""
    with connect() as conn:
        row = conn.execute("SELECT * FROM harvest_forecasts WHERE id = %s AND farmer_id = %s FOR UPDATE",
                           (forecast_id, farmer_id)).fetchone()
        if not row:
            return {"ok": False, "reason": "not_found"}
        if row["status"] != "open":
            return {"ok": False, "reason": "closed", "server": row}
        if base_version is not None and int(base_version) != row["version"]:
            return {"ok": False, "reason": "conflict", "server": row}
        sets = ", ".join(f"{k} = %s" for k in FORECAST_FIELDS)
        r = conn.execute(f"UPDATE harvest_forecasts SET {sets}, version = version + 1 WHERE id = %s "
                         "RETURNING version", tuple([data[k] for k in FORECAST_FIELDS] + [forecast_id])).fetchone()
        return {"ok": True, "version": r["version"]}


def list_forecasts(farmer_id: int) -> list[dict]:
    return fetch_all(f"""
        SELECT f.*,
          (SELECT count(*) FROM harvest_matches m WHERE m.forecast_id = f.id
             AND m.status = 'buyer_interested') AS need_response,
          (SELECT COALESCE(sum(m.match_qty), 0) FROM harvest_matches m WHERE m.forecast_id = f.id
             AND m.status IN {_ACTIVE_SQL}) AS matched_qty
        FROM harvest_forecasts f WHERE f.farmer_id = %s
        ORDER BY f.status <> 'open', f.harvest_from, f.id DESC""", (farmer_id,))


def get_forecast(farmer_id: int, forecast_id: int) -> dict | None:
    return fetch_one("SELECT * FROM harvest_forecasts WHERE id = %s AND farmer_id = %s", (forecast_id, farmer_id))


def potential_requests(farmer_id: int, forecast_id: int, limit: int = 30) -> list[dict]:
    """Open buyer requests that fit this open forecast: same crop (or same name), same unit, overlapping dates
    (7 days slack), compatible variety, quantity still free on both sides. Nearest areas first."""
    return fetch_all(f"""
        WITH f AS (
          SELECT f.*, f.expected_qty - COALESCE((SELECT sum(m.match_qty) FROM harvest_matches m
                 WHERE m.forecast_id = f.id AND m.status IN {_ACTIVE_SQL}), 0) AS free_qty
          FROM harvest_forecasts f WHERE f.id = %(fid)s AND f.farmer_id = %(uid)s AND f.status = 'open')
        SELECT r.id, r.product_name, r.variety, r.unit, r.needed_from, r.needed_to, r.district_code, r.upazila_code,
               r.note, u.full_name AS buyer_name,
               LEAST(r.quantity - COALESCE(used.q, 0), f.free_qty) AS possible_qty,
               r.quantity - COALESCE(used.q, 0) AS request_free_qty,
               CASE WHEN r.district_code = f.district_code THEN 2
                    WHEN left(r.district_code, 4) = left(f.district_code, 4) THEN 1 ELSE 0 END AS near
        FROM f
        JOIN buyer_demand_requests r ON r.status = 'open' AND r.buyer_id <> f.farmer_id AND r.unit = f.unit
             AND (r.crop_id = f.crop_id OR lower(r.product_name) = lower(f.product_name))
             AND r.needed_from <= f.harvest_to + 7 AND r.needed_to >= f.harvest_from - 7
             AND (r.variety IS NULL OR f.variety IS NULL OR lower(r.variety) = lower(f.variety))
        JOIN users u ON u.id = r.buyer_id AND u.status = 'active'
        LEFT JOIN LATERAL (SELECT sum(m.match_qty) AS q FROM harvest_matches m
                           WHERE m.request_id = r.id AND m.status IN {_ACTIVE_SQL}) used ON TRUE
        WHERE NOT EXISTS (SELECT 1 FROM harvest_matches x WHERE x.forecast_id = f.id AND x.request_id = r.id)
          AND LEAST(r.quantity - COALESCE(used.q, 0), f.free_qty) > 0
        ORDER BY near DESC, abs(r.needed_from - f.harvest_from), r.created_at
        LIMIT %(lim)s""", {"fid": forecast_id, "uid": farmer_id, "lim": limit})


def forecast_matches(farmer_id: int, forecast_id: int) -> list[dict]:
    """Match rows of one forecast. Buyer phone only after both sides agreed."""
    return fetch_all("""
        SELECT m.*, r.product_name AS request_product, r.needed_from, r.needed_to, r.district_code AS buyer_district,
               r.quantity AS request_qty, u.full_name AS buyer_name,
               CASE WHEN m.status IN ('agreed', 'qty_confirmed', 'converted') THEN u.phone END AS buyer_phone,
               o.order_number
        FROM harvest_matches m JOIN harvest_forecasts f ON f.id = m.forecast_id
        JOIN buyer_demand_requests r ON r.id = m.request_id JOIN users u ON u.id = r.buyer_id
        LEFT JOIN orders o ON o.id = m.order_id
        WHERE f.id = %s AND f.farmer_id = %s ORDER BY m.created_at""", (forecast_id, farmer_id))


def _free_qty(conn, forecast_id: int, request_id: int) -> tuple:
    f = conn.execute(f"SELECT expected_qty - COALESCE((SELECT sum(match_qty) FROM harvest_matches "
                     f"WHERE forecast_id = %s AND status IN {_ACTIVE_SQL}), 0) AS q FROM harvest_forecasts "
                     "WHERE id = %s", (forecast_id, forecast_id)).fetchone()
    r = conn.execute(f"SELECT quantity - COALESCE((SELECT sum(match_qty) FROM harvest_matches "
                     f"WHERE request_id = %s AND status IN {_ACTIVE_SQL}), 0) AS q FROM buyer_demand_requests "
                     "WHERE id = %s", (request_id, request_id)).fetchone()
    return (f["q"] if f else 0), (r["q"] if r else 0)


def _open_match(conn, forecast_id: int, request_id: int, qty, status: str) -> str:
    """Shared by farmer offer + buyer interest. Locks both rows, checks free quantity, never double-books."""
    f = conn.execute("SELECT id, status, unit FROM harvest_forecasts WHERE id = %s FOR UPDATE",
                     (forecast_id,)).fetchone()
    r = conn.execute("SELECT id, status, unit FROM buyer_demand_requests WHERE id = %s FOR UPDATE",
                     (request_id,)).fetchone()
    if not f or not r:
        return "not_found"
    if f["status"] != "open" or r["status"] != "open":
        return "closed"
    if f["unit"] != r["unit"]:
        return "unit_mismatch"
    if conn.execute("SELECT 1 FROM harvest_matches WHERE forecast_id = %s AND request_id = %s",
                    (forecast_id, request_id)).fetchone():
        return "exists"
    free_f, free_r = _free_qty(conn, forecast_id, request_id)
    if qty <= 0 or qty > free_f or qty > free_r:
        return "too_much"
    conn.execute("INSERT INTO harvest_matches (forecast_id, request_id, match_qty, status) VALUES (%s, %s, %s, %s)",
                 (forecast_id, request_id, qty, status))
    return "ok"


def farmer_offer(farmer_id: int, forecast_id: int, request_id: int, qty) -> str:
    with connect() as conn:
        own = conn.execute("SELECT 1 FROM harvest_forecasts WHERE id = %s AND farmer_id = %s",
                           (forecast_id, farmer_id)).fetchone()
        if not own:
            return "not_found"
        mine = conn.execute("SELECT 1 FROM buyer_demand_requests WHERE id = %s AND buyer_id = %s",
                            (request_id, farmer_id)).fetchone()
        if mine:
            return "not_found"
        return _open_match(conn, forecast_id, request_id, qty, "farmer_offered")


def farmer_respond(farmer_id: int, match_id: int, accept: bool) -> str:
    with connect() as conn:
        m = conn.execute("SELECT m.id, m.status FROM harvest_matches m JOIN harvest_forecasts f ON f.id = m.forecast_id "
                         "WHERE m.id = %s AND f.farmer_id = %s AND f.status = 'open' FOR UPDATE OF m",
                         (match_id, farmer_id)).fetchone()
        if not m:
            return "not_found"
        if m["status"] != "buyer_interested":
            return "bad_step"
        conn.execute("UPDATE harvest_matches SET status = %s WHERE id = %s",
                     ("agreed" if accept else "declined", match_id))
        return "ok"


def cancel_forecast(farmer_id: int, forecast_id: int) -> str:
    with connect() as conn:
        f = conn.execute("SELECT status FROM harvest_forecasts WHERE id = %s AND farmer_id = %s FOR UPDATE",
                         (forecast_id, farmer_id)).fetchone()
        if not f:
            return "not_found"
        if f["status"] != "open":
            return "closed"
        conn.execute("UPDATE harvest_forecasts SET status = 'cancelled', version = version + 1 WHERE id = %s",
                     (forecast_id,))
        conn.execute("UPDATE harvest_matches SET status = 'cancelled' WHERE forecast_id = %s "
                     "AND status IN ('buyer_interested', 'farmer_offered', 'agreed')", (forecast_id,))
        return "ok"


def confirm_harvest(farmer_id: int, forecast_id: int, actual_qty, harvest_date, listing: dict) -> dict:
    """One transaction: forecast -> harvest_confirmed, a real 'available' listing with the ACTUAL quantity,
    agreed matches get confirmed quantities in the order they were agreed (until the harvest runs out);
    agreed matches that do not fit are cancelled; unanswered interest/offers expire."""
    with connect() as conn:
        f = conn.execute("SELECT * FROM harvest_forecasts WHERE id = %s AND farmer_id = %s FOR UPDATE",
                         (forecast_id, farmer_id)).fetchone()
        if not f:
            return {"ok": False, "reason": "not_found"}
        if f["status"] != "open":
            return {"ok": False, "reason": "closed"}
        lst = None
        if actual_qty > 0:
            cols = ["farmer_id", "listing_type", "crop_id", "title", "category", "description", "unit",
                    "price_per_unit", "quantity", "min_order", "is_organic", "farming_method", "harvest_date",
                    "district_code", "upazila_code", "status"]
            vals = [farmer_id, "available", f["crop_id"], listing["title"], listing["category"],
                    listing.get("description") or f["description"], f["unit"], listing["price_per_unit"],
                    actual_qty, listing.get("min_order") or 1, listing["farming_method"] == "organic",
                    listing["farming_method"], harvest_date, f["district_code"], f["upazila_code"], "active"]
            lst = conn.execute(f"INSERT INTO listings ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))}) "
                               "RETURNING id", tuple(vals)).fetchone()
        conn.execute("UPDATE harvest_forecasts SET status = 'harvest_confirmed', actual_qty = %s, "
                     "actual_harvest_date = %s, listing_id = %s, version = version + 1 WHERE id = %s",
                     (actual_qty, harvest_date, lst["id"] if lst else None, forecast_id))
        left = actual_qty
        agreed = conn.execute("SELECT id, match_qty FROM harvest_matches WHERE forecast_id = %s AND status = 'agreed' "
                              "ORDER BY updated_at, id FOR UPDATE", (forecast_id,)).fetchall()
        confirmed = 0
        for m in agreed:
            give = min(m["match_qty"], left)
            if give > 0:
                conn.execute("UPDATE harvest_matches SET status = 'qty_confirmed', confirmed_qty = %s WHERE id = %s",
                             (give, m["id"]))
                left -= give
                confirmed += 1
            else:
                conn.execute("UPDATE harvest_matches SET status = 'cancelled', confirmed_qty = 0 WHERE id = %s",
                             (m["id"],))
        conn.execute("UPDATE harvest_matches SET status = 'expired' WHERE forecast_id = %s "
                     "AND status IN ('buyer_interested', 'farmer_offered')", (forecast_id,))
        return {"ok": True, "listing_id": lst["id"] if lst else None, "confirmed_matches": confirmed}


# ---------------------------------------------------------------- buyer requests (customer / admin)
def create_request(buyer_id: int, data: dict) -> int:
    cols = list(REQUEST_FIELDS) + ["buyer_id"]
    r = fetch_one(f"INSERT INTO buyer_demand_requests ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))}) "
                  "RETURNING id", tuple([data[k] for k in REQUEST_FIELDS] + [buyer_id]))
    return int(r["id"])


def list_requests(buyer_id: int) -> list[dict]:
    return fetch_all("SELECT * FROM buyer_demand_requests WHERE buyer_id = %s "
                     "ORDER BY status <> 'open', needed_from, id DESC", (buyer_id,))


def cancel_request(buyer_id: int, request_id: int) -> str:
    with connect() as conn:
        r = conn.execute("SELECT status FROM buyer_demand_requests WHERE id = %s AND buyer_id = %s FOR UPDATE",
                         (request_id, buyer_id)).fetchone()
        if not r:
            return "not_found"
        if r["status"] != "open":
            return "closed"
        conn.execute("UPDATE buyer_demand_requests SET status = 'cancelled' WHERE id = %s", (request_id,))
        conn.execute("UPDATE harvest_matches SET status = 'cancelled' WHERE request_id = %s "
                     "AND status IN ('buyer_interested', 'farmer_offered', 'agreed')", (request_id,))
        return "ok"


def potential_forecasts(buyer_id: int, request_id: int, limit: int = 30) -> list[dict]:
    """Open forecasts that fit an open request (same rules as potential_requests, mirrored)."""
    return fetch_all(f"""
        WITH r AS (
          SELECT r.*, r.quantity - COALESCE((SELECT sum(m.match_qty) FROM harvest_matches m
                 WHERE m.request_id = r.id AND m.status IN {_ACTIVE_SQL}), 0) AS free_qty
          FROM buyer_demand_requests r WHERE r.id = %(rid)s AND r.buyer_id = %(uid)s AND r.status = 'open')
        SELECT f.id, f.product_name, f.variety, f.unit, f.harvest_from, f.harvest_to, f.district_code,
               f.upazila_code, f.quality_grade, f.expected_qty, u.full_name AS farmer_name,
               LEAST(f.expected_qty - COALESCE(used.q, 0), r.free_qty) AS possible_qty,
               CASE WHEN f.district_code = r.district_code THEN 2
                    WHEN left(f.district_code, 4) = left(r.district_code, 4) THEN 1 ELSE 0 END AS near
        FROM r
        JOIN harvest_forecasts f ON f.status = 'open' AND f.farmer_id <> r.buyer_id AND f.unit = r.unit
             AND (f.crop_id = r.crop_id OR lower(f.product_name) = lower(r.product_name))
             AND r.needed_from <= f.harvest_to + 7 AND r.needed_to >= f.harvest_from - 7
             AND (r.variety IS NULL OR f.variety IS NULL OR lower(r.variety) = lower(f.variety))
        JOIN users u ON u.id = f.farmer_id AND u.status = 'active'
        LEFT JOIN LATERAL (SELECT sum(m.match_qty) AS q FROM harvest_matches m
                           WHERE m.forecast_id = f.id AND m.status IN {_ACTIVE_SQL}) used ON TRUE
        WHERE NOT EXISTS (SELECT 1 FROM harvest_matches x WHERE x.forecast_id = f.id AND x.request_id = r.id)
          AND LEAST(f.expected_qty - COALESCE(used.q, 0), r.free_qty) > 0
        ORDER BY near DESC, abs(r.needed_from - f.harvest_from), f.created_at
        LIMIT %(lim)s""", {"rid": request_id, "uid": buyer_id, "lim": limit})


def request_matches(buyer_id: int, request_id: int) -> list[dict]:
    """Match rows of one request. Farmer phone only after both sides agreed."""
    return fetch_all("""
        SELECT m.*, f.product_name AS forecast_product, f.harvest_from, f.harvest_to, f.district_code AS farmer_district,
               f.expected_qty, f.actual_qty, f.status AS forecast_status, f.listing_id, u.full_name AS farmer_name,
               CASE WHEN m.status IN ('agreed', 'qty_confirmed', 'converted') THEN u.phone END AS farmer_phone,
               o.order_number
        FROM harvest_matches m JOIN buyer_demand_requests r ON r.id = m.request_id
        JOIN harvest_forecasts f ON f.id = m.forecast_id JOIN users u ON u.id = f.farmer_id
        LEFT JOIN orders o ON o.id = m.order_id
        WHERE r.id = %s AND r.buyer_id = %s ORDER BY m.created_at""", (request_id, buyer_id))


def buyer_interest(buyer_id: int, request_id: int, forecast_id: int, qty) -> str:
    with connect() as conn:
        own = conn.execute("SELECT 1 FROM buyer_demand_requests WHERE id = %s AND buyer_id = %s",
                           (request_id, buyer_id)).fetchone()
        if not own:
            return "not_found"
        mine = conn.execute("SELECT 1 FROM harvest_forecasts WHERE id = %s AND farmer_id = %s",
                            (forecast_id, buyer_id)).fetchone()
        if mine:
            return "not_found"
        return _open_match(conn, forecast_id, request_id, qty, "buyer_interested")


def buyer_respond(buyer_id: int, match_id: int, accept: bool) -> str:
    with connect() as conn:
        m = conn.execute("SELECT m.id, m.status FROM harvest_matches m JOIN buyer_demand_requests r ON r.id = m.request_id "
                         "JOIN harvest_forecasts f ON f.id = m.forecast_id "
                         "WHERE m.id = %s AND r.buyer_id = %s AND f.status = 'open' FOR UPDATE OF m",
                         (match_id, buyer_id)).fetchone()
        if not m:
            return "not_found"
        if m["status"] != "farmer_offered":
            return "bad_step"
        conn.execute("UPDATE harvest_matches SET status = %s WHERE id = %s",
                     ("agreed" if accept else "declined", match_id))
        return "ok"


# ---------------------------------------------------------------- offline sync: products
def listing_by_client(farmer_id: int, client_id: str) -> dict | None:
    return fetch_one("SELECT id FROM listings WHERE farmer_id = %s AND client_id = %s", (farmer_id, client_id))


def create_listing_once(farmer_id: int, data: dict, image_path: str | None, district_code: str | None,
                        upazila_code: str | None, client_id: str) -> dict:
    """Idempotent product create for offline drafts (same client_id -> same product, never a duplicate)."""
    old = fetch_one("SELECT id FROM listings WHERE farmer_id = %s AND client_id = %s", (farmer_id, client_id))
    if old:
        return {"id": old["id"], "duplicate": True}
    cols = list(LISTING_FIELDS) + ["image_path", "district_code", "upazila_code", "farmer_id", "client_id"]
    vals = [data[k] for k in LISTING_FIELDS] + [image_path, district_code, upazila_code, farmer_id, client_id]
    r = fetch_one(f"INSERT INTO listings ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))}) "
                  "ON CONFLICT (farmer_id, client_id) WHERE client_id IS NOT NULL DO NOTHING RETURNING id", tuple(vals))
    if r is None:
        r = fetch_one("SELECT id FROM listings WHERE farmer_id = %s AND client_id = %s", (farmer_id, client_id))
        return {"id": r["id"], "duplicate": True}
    return {"id": r["id"], "duplicate": False}


# ================================================================ Marketplace + customer (Phase A)
EFFECTIVE_PRICE = "COALESCE(l.discount_price, l.price_per_unit)"
MARKET_COLS = ("l.id, l.title, l.crop_id, l.category, l.unit, l.price_per_unit, l.discount_price, "
               f"{EFFECTIVE_PRICE} AS price_now, l.quantity, l.min_order, l.listing_type, l.available_from, "
               "l.harvest_date, l.image_path, l.is_organic, l.farming_method, l.district_code, l.upazila_code, "
               "l.created_at, u.full_name AS farmer_name, u.id AS farmer_id")
MARKET_FROM = ("FROM listings l JOIN users u ON u.id = l.farmer_id "
               "WHERE l.status = 'active' AND u.status = 'active' AND u.role = 'farmer'")
PAGE_SIZE = 24


def _search_sql(q: str, known_crops: set[str]) -> tuple[str, list, str, list]:
    """(where_sql, params, rank_sql, rank_params) for a search text, see search.py."""
    from chashibondhu.web import search
    p = search.parse(q)
    if not p["text"]:
        return "", [], "0", []
    if p["groups"]:
        ors, params = [], []
        for key in p["groups"]:
            pats = search.alias_patterns(key)
            cids = search.group_crop_ids(key, known_crops)
            ors.append("(l.title ~* ANY(%s) OR coalesce(l.description, '') ~* ANY(%s)"
                       + (" OR l.crop_id = ANY(%s))" if cids else ")"))
            params += [pats, pats] + ([cids] if cids else [])
        where = " AND (" + " OR ".join(ors) + ")"
    else:
        ands, params = [], []
        for w in p["rest"]:
            like = "%" + w.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            ands.append("(l.title ILIKE %s OR coalesce(l.description, '') ILIKE %s "
                        "OR word_similarity(%s, lower(l.title)) >= 0.5)")
            params += [like, like, w]
        where = " AND " + " AND ".join(ands)
    rank_parts, rank_params = ["word_similarity(%s, lower(l.title))"], [p["text"]]
    for w in p["rest"]:
        rank_parts.append("(CASE WHEN l.title ILIKE %s THEN 1 ELSE 0 END)")
        rank_params.append("%" + w.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
    return where, params, " + ".join(rank_parts), rank_params


def market_search(f: dict, known_crops: set[str], page: int = 1) -> tuple[list[dict], int]:
    """Public market. f keys: q, section(fresh|tools), category, district, min, max, avail(now|preorder),
    organic(bool), sort(new|price_asc|price_desc|best). Returns (rows, total count)."""
    where, params = MARKET_FROM, []
    s_where, s_params, rank, rank_params = _search_sql(f.get("q") or "", known_crops)
    where += s_where
    params += s_params
    if f.get("section") == "tools":
        where += " AND l.category = 'tools_equipment'"
    elif f.get("section") == "fresh":
        where += " AND l.category <> 'tools_equipment'"
    if f.get("category"):
        where += " AND l.category = %s"
        params.append(f["category"])
    if f.get("district"):
        where += " AND l.district_code = %s"
        params.append(f["district"])
    if f.get("min") is not None:
        where += f" AND {EFFECTIVE_PRICE} >= %s"
        params.append(f["min"])
    if f.get("max") is not None:
        where += f" AND {EFFECTIVE_PRICE} <= %s"
        params.append(f["max"])
    if f.get("avail") == "now":
        where += " AND l.listing_type = 'available' AND l.quantity > 0"
    elif f.get("avail") == "preorder":
        where += " AND l.listing_type = 'expected'"
    if f.get("organic"):
        where += " AND l.farming_method = 'organic'"
    order = {"price_asc": f"{EFFECTIVE_PRICE} ASC, l.id DESC", "price_desc": f"{EFFECTIVE_PRICE} DESC, l.id DESC",
             "new": "l.created_at DESC"}.get(f.get("sort") or "", None)
    if order is None:
        order = f"({rank}) DESC, l.created_at DESC" if f.get("q") else "l.created_at DESC"
        order_params = rank_params if f.get("q") else []
    else:
        order_params = []
    total = fetch_one(f"SELECT count(*) AS n {where}", tuple(params))["n"]
    rows = fetch_all(f"SELECT {MARKET_COLS} {where} ORDER BY {order} LIMIT %s OFFSET %s",
                     tuple(params + order_params + [PAGE_SIZE, (max(page, 1) - 1) * PAGE_SIZE]))
    return rows, int(total)


def market_districts() -> list[str]:
    return [r["district_code"] for r in fetch_all(f"SELECT DISTINCT l.district_code {MARKET_FROM} "
                                                  "AND l.district_code IS NOT NULL ORDER BY 1")]


def suggest(prefix: str, known_crops: set[str], limit: int = 8) -> list[dict]:
    """Autocomplete: only words that match real active listings, with how many listings match."""
    from chashibondhu.web import search
    p = search.normalize(prefix)
    if not p:
        return []
    out = []
    for key in search.prefix_groups(p):
        where, params, _, _ = _search_sql(search.LEXICON[key][2][0], known_crops)
        n = fetch_one(f"SELECT count(*) AS n {MARKET_FROM}{where}", tuple(params))["n"]
        if n:
            bn, en = search.LEXICON[key][0], search.LEXICON[key][1]
            out.append({"kind": "product", "q": search.LEXICON[key][2][0], "bn": bn, "en": en, "count": int(n)})
    like = p.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    rows = fetch_all(f"SELECT l.title, count(*) AS n {MARKET_FROM} AND (lower(l.title) LIKE %s OR l.title ~* %s) "
                     "GROUP BY l.title ORDER BY n DESC, l.title LIMIT %s",
                     (like + "%", r"\m" + re.escape(p) if re.match(r"^[a-z]", p) else re.escape(p), limit))
    for r in rows:
        if not any(o.get("q", "").lower() == r["title"].lower() for o in out):
            out.append({"kind": "title", "q": r["title"], "bn": r["title"], "en": r["title"], "count": int(r["n"])})
    return out[:limit]


def get_market_listing(listing_id: int) -> dict | None:
    return fetch_one(f"SELECT {MARKET_COLS}, l.description, l.extra_info, l.status {MARKET_FROM} AND l.id = %s",
                     (listing_id,))


def related_listings(item: dict, limit: int = 6) -> list[dict]:
    return fetch_all(f"SELECT {MARKET_COLS} {MARKET_FROM} AND l.id <> %s AND "
                     "((l.crop_id IS NOT NULL AND l.crop_id = %s) OR l.category = %s) "
                     "ORDER BY (l.crop_id = %s) DESC NULLS LAST, l.created_at DESC LIMIT %s",
                     (item["id"], item.get("crop_id"), item["category"], item.get("crop_id"), limit))


# ---------------------------------------------------------------- customers
def create_customer(full_name: str, phone: str, password_hash: str, district_code: str | None,
                    upazila_code: str | None, address: str | None) -> int:
    r = fetch_one("INSERT INTO users (role, full_name, phone, password_hash, district_code, upazila_code, address) "
                  "VALUES ('customer', %s, %s, %s, %s, %s, %s) RETURNING id",
                  (full_name, phone, password_hash, district_code, upazila_code, address))
    return int(r["id"])


def get_customer(user_id: int) -> dict | None:
    return fetch_one("SELECT id, full_name, phone, district_code, upazila_code, address, avatar_path, created_at "
                     "FROM users WHERE id = %s AND role IN ('customer', 'admin')", (user_id,))


def update_customer(user_id: int, full_name: str, district_code: str | None, upazila_code: str | None,
                    address: str | None) -> int:
    return execute("UPDATE users SET full_name = %s, district_code = %s, upazila_code = %s, address = %s "
                   "WHERE id = %s", (full_name, district_code, upazila_code, address, user_id))


# ---------------------------------------------------------------- cart
def cart(customer_id: int) -> list[dict]:
    """Cart lines with the CURRENT price/stock (prices are never stored in the cart)."""
    return fetch_all(f"""
        SELECT c.id AS cart_id, c.quantity AS want, l.id, l.title, l.unit, l.price_per_unit, l.discount_price,
               {EFFECTIVE_PRICE} AS price_now, l.quantity AS stock, l.min_order, l.status, l.listing_type,
               l.image_path, l.farmer_id, u.full_name AS farmer_name, u.status AS farmer_status
        FROM cart_items c JOIN listings l ON l.id = c.listing_id JOIN users u ON u.id = l.farmer_id
        WHERE c.customer_id = %s ORDER BY u.full_name, c.added_at""", (customer_id,))


def cart_count(customer_id: int) -> int:
    return int(fetch_one("SELECT count(*) AS n FROM cart_items WHERE customer_id = %s", (customer_id,))["n"])


def line_problem(line: dict, qty) -> str | None:
    """Why this cart line cannot be bought now (None = OK)."""
    if line["status"] != "active" or line.get("farmer_status", "active") != "active":
        return "unavailable"
    if line["listing_type"] != "available":
        return "preorder"
    if qty < line["min_order"]:
        return "below_min"
    if qty > line["stock"]:
        return "no_stock"
    return None


def cart_set(customer_id: int, listing_id: int, qty, add: bool = False) -> str:
    """Add (add=True: increase) or set a cart quantity after checking the listing. Returns 'ok' or a reason."""
    with connect() as conn:
        line = conn.execute("SELECT l.id, l.status, l.listing_type, l.quantity AS stock, l.min_order, "
                            "u.status AS farmer_status, l.farmer_id FROM listings l JOIN users u ON u.id = l.farmer_id "
                            "WHERE l.id = %s", (listing_id,)).fetchone()
        if not line:
            return "unavailable"
        if line["farmer_id"] == customer_id:
            return "own"
        if add:
            cur = conn.execute("SELECT quantity FROM cart_items WHERE customer_id = %s AND listing_id = %s",
                               (customer_id, listing_id)).fetchone()
            qty = qty + (cur["quantity"] if cur else 0)
        why = line_problem(line, qty)
        if why:
            return why
        conn.execute("INSERT INTO cart_items (customer_id, listing_id, quantity) VALUES (%s, %s, %s) "
                     "ON CONFLICT (customer_id, listing_id) DO UPDATE SET quantity = EXCLUDED.quantity",
                     (customer_id, listing_id, qty))
        return "ok"


def cart_remove(customer_id: int, listing_id: int) -> int:
    return execute("DELETE FROM cart_items WHERE customer_id = %s AND listing_id = %s", (customer_id, listing_id))


def place_order(customer_id: int, delivery_address: str, phone: str, note: str | None,
                delivery_fee) -> dict:
    """Checkout in ONE transaction. Prices and stock are re-read from the database (never from the browser).
    Returns {"ok": True, "order_number"} or {"ok": False, "problems": [(title, reason)]}."""
    with connect() as conn:
        lines = conn.execute(f"""
            SELECT c.quantity AS want, l.id, l.title, l.unit, {EFFECTIVE_PRICE} AS price_now, l.quantity AS stock,
                   l.min_order, l.status, l.listing_type, l.farmer_id, u.status AS farmer_status
            FROM cart_items c JOIN listings l ON l.id = c.listing_id JOIN users u ON u.id = l.farmer_id
            WHERE c.customer_id = %s ORDER BY l.id FOR UPDATE OF c, l""", (customer_id,)).fetchall()
        if not lines:
            return {"ok": False, "problems": [("", "empty")]}
        problems = [(ln["title"], why) for ln in lines if (why := line_problem(ln, ln["want"]))]
        problems += [(ln["title"], "own") for ln in lines if ln["farmer_id"] == customer_id]
        if problems:
            return {"ok": False, "problems": problems}
        subtotal = sum((ln["price_now"] * ln["want"]).quantize(Decimal("0.01")) for ln in lines)
        total = subtotal + delivery_fee
        order = conn.execute("INSERT INTO orders (customer_id, payment_method, subtotal, delivery_fee, total, "
                             "delivery_address, phone, note) VALUES (%s, 'cod', %s, %s, %s, %s, %s, %s) "
                             "RETURNING id, order_number", (customer_id, subtotal, delivery_fee, total,
                                                            delivery_address, phone, note)).fetchone()
        farmers = set()
        for ln in lines:
            conn.execute("INSERT INTO order_items (order_id, listing_id, farmer_id, title, unit, unit_price, quantity, "
                         "line_total) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                         (order["id"], ln["id"], ln["farmer_id"], ln["title"], ln["unit"], ln["price_now"], ln["want"],
                          (ln["price_now"] * ln["want"]).quantize(Decimal("0.01"))))
            farmers.add(ln["farmer_id"])
        for fid in farmers:
            conn.execute("INSERT INTO notifications (user_id, kind, title, body, link, dedupe_key) VALUES "
                         "(%s, 'order', 'নতুন অর্ডার এসেছে / New order', %s, '/farmer/orders', %s) "
                         "ON CONFLICT (user_id, dedupe_key) WHERE dedupe_key IS NOT NULL DO NOTHING",
                         (fid, order["order_number"], f"neworder:{order['id']}"))
        conn.execute("DELETE FROM cart_items WHERE customer_id = %s", (customer_id,))
        return {"ok": True, "order_number": order["order_number"]}


# ---------------------------------------------------------------- customer orders
CUSTOMER_PERIODS = {"today": "1 day", "week": "7 days", "month": "30 days"}


def customer_orders(customer_id: int, period: str = "all") -> list[dict]:
    sql = ("SELECT o.*, (SELECT count(*) FROM order_items i WHERE i.order_id = o.id) AS item_count, "
           "(SELECT string_agg(i.title, ', ' ORDER BY i.id) FROM order_items i WHERE i.order_id = o.id) AS titles "
           "FROM orders o WHERE o.customer_id = %s")
    params: list = [customer_id]
    if period in CUSTOMER_PERIODS:
        sql += " AND o.created_at >= now() - %s::interval"
        params.append(CUSTOMER_PERIODS[period])
    return fetch_all(sql + " ORDER BY o.created_at DESC LIMIT 200", tuple(params))


def customer_order(customer_id: int, order_number: str) -> dict | None:
    """One order with its items. Farmer phone only after that farmer confirmed the item."""
    o = fetch_one("SELECT o.*, u.full_name AS customer_name FROM orders o JOIN users u ON u.id = o.customer_id "
                  "WHERE o.order_number = %s AND o.customer_id = %s", (order_number, customer_id))
    if not o:
        return None
    o["items"] = fetch_all("SELECT i.*, f.full_name AS farmer_name, f.district_code AS farmer_district, "
                           "CASE WHEN i.farmer_status IN ('accepted', 'packed', 'handed_over') THEN f.phone END "
                           "AS farmer_phone, l.status AS listing_status, l.image_path "
                           "FROM order_items i JOIN users f ON f.id = i.farmer_id "
                           "LEFT JOIN listings l ON l.id = i.listing_id WHERE i.order_id = %s ORDER BY i.id", (o["id"],))
    return o


def customer_stats(customer_id: int) -> dict:
    return fetch_one("""
        SELECT count(*) AS total_orders,
               count(*) FILTER (WHERE status IN ('pending', 'confirmed', 'shipped')) AS pending_orders,
               count(*) FILTER (WHERE status = 'delivered') AS completed_orders,
               COALESCE(sum(total) FILTER (WHERE status = 'delivered'), 0) AS spent
        FROM orders WHERE customer_id = %s""", (customer_id,)) or {}


def recent_purchases(customer_id: int, limit: int = 6) -> list[dict]:
    return fetch_all("SELECT i.title, i.quantity, i.unit, i.unit_price, i.listing_id, o.order_number, o.created_at "
                     "FROM order_items i JOIN orders o ON o.id = i.order_id WHERE o.customer_id = %s "
                     "AND o.status <> 'cancelled' ORDER BY o.created_at DESC, i.id LIMIT %s", (customer_id, limit))


def cancel_order(customer_id: int, order_number: str) -> str:
    """The customer may cancel only while no farmer has confirmed anything."""
    with connect() as conn:
        o = conn.execute("SELECT id, status FROM orders WHERE order_number = %s AND customer_id = %s FOR UPDATE",
                         (order_number, customer_id)).fetchone()
        if not o:
            return "not_found"
        if o["status"] != "pending":
            return "too_late"
        busy = conn.execute("SELECT 1 FROM order_items WHERE order_id = %s AND farmer_status IN "
                            "('accepted', 'packed', 'handed_over') LIMIT 1", (o["id"],)).fetchone()
        if busy:
            return "too_late"
        conn.execute("UPDATE orders SET status = 'cancelled' WHERE id = %s", (o["id"],))
        return "ok"


def reorder(customer_id: int, order_number: str) -> dict:
    """Put still-available items back in the cart at TODAY's price and stock. Returns added/skipped titles."""
    o = customer_order(customer_id, order_number)
    if not o:
        return {"added": [], "skipped": []}
    added, skipped = [], []
    for it in o["items"]:
        if not it["listing_id"]:
            skipped.append(it["title"])
            continue
        res = cart_set(customer_id, it["listing_id"], it["quantity"])
        if res == "no_stock":
            line = fetch_one("SELECT quantity, min_order FROM listings WHERE id = %s", (it["listing_id"],))
            if line and line["quantity"] >= line["min_order"]:
                res = cart_set(customer_id, it["listing_id"], line["quantity"])
        (added if res == "ok" else skipped).append(it["title"])
    return {"added": added, "skipped": skipped}


# ---------------------------------------------------------------- notifications
def list_notifications(user_id: int, limit: int = 100) -> list[dict]:
    return fetch_all("SELECT * FROM notifications WHERE user_id = %s ORDER BY created_at DESC LIMIT %s",
                     (user_id, limit))


def unread_count(user_id: int) -> int:
    return int(fetch_one("SELECT count(*) AS n FROM notifications WHERE user_id = %s AND read_at IS NULL",
                         (user_id,))["n"])


def mark_all_read(user_id: int) -> int:
    return execute("UPDATE notifications SET read_at = now() WHERE user_id = %s AND read_at IS NULL", (user_id,))
