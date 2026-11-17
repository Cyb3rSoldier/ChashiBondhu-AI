"""SQL for the admin side (A1). Every change goes through a function that also writes the audit log,
in the SAME transaction (no change without an audit record)."""
from __future__ import annotations

import json

from chashibondhu.web.db import connect, fetch_all, fetch_one

PAGE = 50
PERMISSIONS = ("dashboard", "farmers", "consumers", "products", "reviews", "orders", "complaints", "finance",
               "notifications", "content", "analytics", "audit", "staff")
SPANS = {"7d": ("7 days", "day"), "30d": ("30 days", "day"), "12m": ("12 months", "month")}


# ---------------------------------------------------------------- audit
def _audit(conn, actor_id, action, target_type=None, target_id=None, result="ok", reason=None, meta=None):
    conn.execute("INSERT INTO admin_audit_log (actor_id, actor_name, action, target_type, target_id, result, reason, "
                 "meta) VALUES (%s, (SELECT full_name FROM users WHERE id = %s), %s, %s, %s, %s, %s, %s)",
                 (actor_id, actor_id, action, target_type, target_id, result, (reason or None) and reason[:500],
                  json.dumps(meta or {}, ensure_ascii=False, default=str)))


def audit(actor_id, action, target_type=None, target_id=None, result="ok", reason=None, meta=None) -> None:
    with connect() as conn:
        _audit(conn, actor_id, action, target_type, target_id, result, reason, meta)


def audit_page(f: dict, page: int = 1) -> tuple[list[dict], int]:
    where, params = " WHERE true", []
    if f.get("action"):
        where += " AND a.action LIKE %s"
        params.append(f["action"].replace("%", "") + "%")
    if f.get("actor"):
        where += " AND a.actor_id = %s"
        params.append(f["actor"])
    if f.get("target_type"):
        where += " AND a.target_type = %s"
        params.append(f["target_type"])
    if f.get("target_id"):
        where += " AND a.target_id = %s"
        params.append(f["target_id"])
    n = fetch_one(f"SELECT count(*) AS n FROM admin_audit_log a{where}", tuple(params))["n"]
    rows = fetch_all(f"SELECT a.* FROM admin_audit_log a{where} ORDER BY a.id DESC LIMIT %s OFFSET %s",
                     tuple(params + [PAGE, (max(page, 1) - 1) * PAGE]))
    return rows, int(n)


# ---------------------------------------------------------------- staff
def staff_row(user_id: int) -> dict | None:
    return fetch_one("SELECT s.*, u.status, u.full_name FROM admin_staff s JOIN users u ON u.id = s.user_id "
                     "WHERE s.user_id = %s AND u.role = 'admin'", (user_id,))


def list_staff() -> list[dict]:
    return fetch_all("SELECT u.id, u.full_name, u.phone, u.status, u.created_at, u.last_login_at, "
                     "COALESCE(s.is_super, false) AS is_super, COALESCE(s.permissions, '{}') AS permissions, "
                     "(s.user_id IS NOT NULL) AS has_row FROM users u LEFT JOIN admin_staff s ON s.user_id = u.id "
                     "WHERE u.role = 'admin' ORDER BY s.is_super DESC NULLS LAST, u.full_name")


def create_staff(actor_id: int, full_name: str, phone: str, password_hash: str, perms: list[str]) -> int | None:
    """New admin account (not super). None if the phone is already an admin."""
    try:
        with connect() as conn:
            uid = conn.execute("INSERT INTO users (role, full_name, phone, password_hash) VALUES ('admin', %s, %s, %s) "
                               "RETURNING id", (full_name, phone, password_hash)).fetchone()["id"]
            conn.execute("INSERT INTO admin_staff (user_id, permissions, created_by) VALUES (%s, %s, %s)",
                         (uid, perms, actor_id))
            _audit(conn, actor_id, "staff.create", "user", uid, meta={"permissions": perms})
            return int(uid)
    except Exception as e:
        if getattr(e, "sqlstate", None) == "23505":
            return None
        raise


def set_permissions(actor_id: int, user_id: int, perms: list[str], is_super: bool) -> str:
    with connect() as conn:
        u = conn.execute("SELECT id FROM users WHERE id = %s AND role = 'admin' FOR UPDATE", (user_id,)).fetchone()
        if not u:
            return "not_found"
        old = conn.execute("SELECT is_super, permissions FROM admin_staff WHERE user_id = %s", (user_id,)).fetchone()
        if old and old["is_super"] and not is_super and _supers(conn) <= 1:
            return "last_super"
        conn.execute("INSERT INTO admin_staff (user_id, is_super, permissions, created_by) VALUES (%s, %s, %s, %s) "
                     "ON CONFLICT (user_id) DO UPDATE SET is_super = EXCLUDED.is_super, "
                     "permissions = EXCLUDED.permissions, updated_at = now()", (user_id, is_super, perms, actor_id))
        _audit(conn, actor_id, "staff.permissions", "user", user_id,
               meta={"before": dict(old) if old else None, "after": {"is_super": is_super, "permissions": perms}})
        return "ok"


def _supers(conn) -> int:
    return conn.execute("SELECT count(*) AS n FROM admin_staff s JOIN users u ON u.id = s.user_id "
                        "WHERE s.is_super AND u.role = 'admin' AND u.status = 'active'").fetchone()["n"]


# ---------------------------------------------------------------- users (farmers / consumers / staff status)
def set_user_status(actor_id: int, user_id: int, roles: tuple[str, ...], suspend: bool, reason: str | None) -> str:
    """Suspend or restore. Suspending ends every login of that user at once (session_version + 1)."""
    with connect() as conn:
        u = conn.execute("SELECT id, role, status FROM users WHERE id = %s FOR UPDATE", (user_id,)).fetchone()
        if not u or u["role"] not in roles:
            return "not_found"
        if user_id == actor_id:
            return "self"
        if suspend and u["role"] == "admin":
            s = conn.execute("SELECT is_super FROM admin_staff WHERE user_id = %s", (user_id,)).fetchone()
            if s and s["is_super"] and _supers(conn) <= 1:
                return "last_super"
        new = "suspended" if suspend else "active"
        if u["status"] == new:
            return "same"
        conn.execute("UPDATE users SET status = %s, suspended_reason = %s, session_version = session_version + 1 "
                     "WHERE id = %s", (new, reason if suspend else None, user_id))
        _audit(conn, actor_id, "user.suspend" if suspend else "user.restore", "user", user_id, reason=reason,
               meta={"role": u["role"], "before": u["status"], "after": new})
        return "ok"


def user_list(role: str, f: dict, page: int = 1) -> tuple[list[dict], int]:
    where, params = " WHERE u.role = %s", [role]
    if f.get("q"):
        where += " AND (u.full_name ILIKE %s OR u.phone LIKE %s OR COALESCE(u.email, '') ILIKE %s OR u.id::text = %s)"
        like = "%" + f["q"].replace("%", "").replace("_", "\\_") + "%"
        params += [like, like, like, f["q"]]
    if f.get("district"):
        where += " AND u.district_code = %s"
        params.append(f["district"])
    if f.get("status"):
        where += " AND u.status = %s"
        params.append(f["status"])
    n = fetch_one(f"SELECT count(*) AS n FROM users u{where}", tuple(params))["n"]
    extra = ("(SELECT count(*) FROM listings l WHERE l.farmer_id = u.id AND l.status = 'active') AS active_listings, "
             "(SELECT count(*) FROM order_items i WHERE i.farmer_id = u.id) AS order_items"
             if role == "farmer" else
             "(SELECT count(*) FROM orders o WHERE o.customer_id = u.id) AS orders, "
             "(SELECT COALESCE(sum(total), 0) FROM orders o WHERE o.customer_id = u.id AND o.status = 'delivered') AS spent")
    rows = fetch_all(f"SELECT u.id, u.full_name, u.phone, u.email, u.status, u.district_code, u.upazila_code, "
                     f"u.created_at, u.last_login_at, {extra} FROM users u{where} ORDER BY u.id DESC LIMIT %s OFFSET %s",
                     tuple(params + [PAGE, (max(page, 1) - 1) * PAGE]))
    return rows, int(n)


def user_detail(user_id: int, role: str) -> dict | None:
    u = fetch_one("SELECT id, role, full_name, phone, email, status, suspended_reason, district_code, upazila_code, "
                  "address, avatar_path, created_at, last_login_at, failed_logins, locked_until "
                  "FROM users WHERE id = %s AND role = %s", (user_id, role))
    if not u:
        return None
    if role == "farmer":
        u["listings"] = fetch_all("SELECT id, title, unit, price_per_unit, discount_price, quantity, status, "
                                  "moderated_at, created_at FROM listings WHERE farmer_id = %s "
                                  "ORDER BY created_at DESC LIMIT 100", (user_id,))
        u["order_items"] = fetch_all("SELECT i.id, i.title, i.quantity, i.unit, i.line_total, i.farmer_status, "
                               "o.order_number, o.status AS order_status, o.created_at FROM order_items i "
                               "JOIN orders o ON o.id = i.order_id WHERE i.farmer_id = %s "
                               "ORDER BY o.created_at DESC LIMIT 100", (user_id,))
    else:
        u["orders"] = fetch_all("SELECT order_number, status, payment_status, total, created_at FROM orders "
                                "WHERE customer_id = %s ORDER BY created_at DESC LIMIT 100", (user_id,))
    u["history"] = fetch_all("SELECT a.action, a.reason, a.created_at, a.actor_name FROM admin_audit_log a "
                             "WHERE a.target_type = 'user' AND a.target_id = %s "
                             "ORDER BY a.id DESC LIMIT 50", (user_id,))
    return u


# ---------------------------------------------------------------- listings
def listing_list(f: dict, page: int = 1) -> tuple[list[dict], int]:
    where, params = " WHERE true", []
    if f.get("q"):
        where += " AND (l.title ILIKE %s OR u.full_name ILIKE %s OR l.id::text = %s)"
        like = "%" + f["q"].replace("%", "").replace("_", "\\_") + "%"
        params += [like, like, f["q"]]
    for k, col in (("category", "l.category"), ("district", "l.district_code"), ("status", "l.status")):
        if f.get(k):
            where += f" AND {col} = %s"
            params.append(f[k])
    if f.get("farmer"):
        where += " AND l.farmer_id = %s"
        params.append(f["farmer"])
    if f.get("avail") == "out":
        where += " AND l.listing_type = 'available' AND l.quantity < l.min_order"
    elif f.get("avail") == "preorder":
        where += " AND l.listing_type = 'expected'"
    elif f.get("avail") == "moderated":
        where += " AND l.moderated_at IS NOT NULL"
    base = f"FROM listings l JOIN users u ON u.id = l.farmer_id{where}"
    n = fetch_one(f"SELECT count(*) AS n {base}", tuple(params))["n"]
    rows = fetch_all(f"SELECT l.id, l.title, l.category, l.unit, l.price_per_unit, l.discount_price, l.quantity, "
                     f"l.min_order, l.listing_type, l.status, l.district_code, l.created_at, l.moderated_at, "
                     f"l.moderation_reason, u.id AS farmer_id, u.full_name AS farmer_name {base} "
                     f"ORDER BY l.id DESC LIMIT %s OFFSET %s", tuple(params + [PAGE, (max(page, 1) - 1) * PAGE]))
    return rows, int(n)


def moderate_listing(actor_id: int, listing_id: int, remove: bool, reason: str | None) -> str:
    """remove=True: hide from the market (farmer cannot undo). remove=False: admin restores it."""
    with connect() as conn:
        l = conn.execute("SELECT id, farmer_id, title, status, moderated_at FROM listings WHERE id = %s FOR UPDATE",
                         (listing_id,)).fetchone()
        if not l:
            return "not_found"
        if remove:
            if l["moderated_at"]:
                return "same"
            conn.execute("UPDATE listings SET status = 'hidden', moderated_at = now(), moderated_by = %s, "
                         "moderation_reason = %s WHERE id = %s", (actor_id, reason, listing_id))
            conn.execute("INSERT INTO notifications (user_id, kind, title, body, link) VALUES (%s, 'admin', "
                         "'অ্যাডমিন একটি পণ্য সরিয়েছেন / A product was removed by the admin', %s, '/farmer/listings')",
                         (l["farmer_id"], f"{l['title']}: {reason}"))
        else:
            if not l["moderated_at"]:
                return "same"
            conn.execute("UPDATE listings SET moderated_at = NULL, moderated_by = NULL, moderation_reason = NULL, "
                         "status = 'active' WHERE id = %s", (listing_id,))
            conn.execute("INSERT INTO notifications (user_id, kind, title, body, link) VALUES (%s, 'admin', "
                         "'পণ্য আবার বাজারে / Product is back in the market', %s, '/farmer/listings')",
                         (l["farmer_id"], l["title"]))
        _audit(conn, actor_id, "listing.remove" if remove else "listing.restore", "listing", listing_id,
               reason=reason, meta={"before": l["status"], "farmer_id": l["farmer_id"]})
        return "ok"


# ---------------------------------------------------------------- reviews
def review_list(f: dict, page: int = 1) -> tuple[list[dict], int]:
    where, params = " WHERE true", []
    if f.get("status"):
        where += " AND r.status = %s"
        params.append(f["status"])
    if f.get("rating"):
        where += " AND r.rating = %s"
        params.append(f["rating"])
    if f.get("q"):
        where += " AND (l.title ILIKE %s OR COALESCE(r.comment, '') ILIKE %s)"
        like = "%" + f["q"].replace("%", "").replace("_", "\\_") + "%"
        params += [like, like]
    base = (f"FROM reviews r JOIN listings l ON l.id = r.listing_id JOIN users c ON c.id = r.customer_id "
            f"JOIN users fa ON fa.id = l.farmer_id{where}")
    n = fetch_one(f"SELECT count(*) AS n {base}", tuple(params))["n"]
    rows = fetch_all(f"SELECT r.id, r.rating, r.comment, r.status, r.moderation_reason, r.created_at, r.updated_at, "
                     f"(r.order_item_id IS NOT NULL) AS verified, l.id AS listing_id, l.title, "
                     f"c.id AS customer_id, c.full_name AS customer_name, fa.id AS farmer_id, fa.full_name AS farmer_name "
                     f"{base} ORDER BY r.id DESC LIMIT %s OFFSET %s",
                     tuple(params + [PAGE, (max(page, 1) - 1) * PAGE]))
    return rows, int(n)


def moderate_review(actor_id: int, review_id: int, hide: bool, reason: str | None) -> str:
    with connect() as conn:
        r = conn.execute("SELECT id, status FROM reviews WHERE id = %s FOR UPDATE", (review_id,)).fetchone()
        if not r:
            return "not_found"
        new = "hidden" if hide else "visible"
        if r["status"] == new:
            return "same"
        conn.execute("UPDATE reviews SET status = %s, moderation_reason = %s WHERE id = %s",
                     (new, reason if hide else None, review_id))
        _audit(conn, actor_id, "review.hide" if hide else "review.restore", "review", review_id, reason=reason)
        return "ok"


# ---------------------------------------------------------------- command center (real numbers only)
def dashboard_numbers() -> dict:
    return fetch_one("""
        SELECT (SELECT count(*) FROM users WHERE role = 'farmer') AS farmers,
               (SELECT count(*) FROM users WHERE role = 'farmer' AND status = 'active') AS farmers_active,
               (SELECT count(*) FROM users WHERE role = 'customer') AS customers,
               (SELECT count(*) FROM users WHERE role = 'customer' AND status = 'active') AS customers_active,
               (SELECT count(*) FROM listings WHERE status <> 'archived') AS listings,
               (SELECT count(*) FROM listings WHERE status = 'active') AS listings_active,
               (SELECT count(*) FROM listings WHERE status = 'active' AND listing_type = 'available'
                  AND quantity < min_order) AS out_of_stock,
               (SELECT count(*) FROM listings WHERE moderated_at IS NOT NULL) AS moderated,
               (SELECT count(*) FROM orders) AS orders,
               (SELECT count(*) FROM orders WHERE status IN ('pending', 'confirmed', 'shipped')) AS orders_open,
               (SELECT count(*) FROM orders WHERE status = 'delivered') AS orders_done,
               (SELECT count(*) FROM orders WHERE status = 'cancelled') AS orders_cancelled,
               (SELECT COALESCE(sum(total), 0) FROM orders WHERE status = 'delivered') AS sales_delivered,
               (SELECT COALESCE(sum(total), 0) FROM orders WHERE status = 'delivered' AND payment_status = 'paid')
                 AS sales_paid,
               (SELECT count(*) FROM reviews WHERE status = 'hidden') AS reviews_hidden,
               (SELECT count(*) FROM complaints WHERE status IN ('open', 'in_review', 'in_progress'))
                 AS complaints_open,
               (SELECT count(*) FROM orders WHERE status = 'delivered' AND payment_status = 'unpaid')
                 AS cod_to_collect""") or {}


def series(span: str) -> dict:
    """Orders, delivered sales and sign-ups per day (7d/30d) or per month (12m), Asia/Dhaka dates; zero-filled."""
    interval, unit = SPANS.get(span, SPANS["30d"])
    step = "1 day" if unit == "day" else "1 month"
    sql = f"""
        WITH b AS (SELECT generate_series(date_trunc('{unit}', (now() AT TIME ZONE 'Asia/Dhaka') - interval '{interval}')
                                          + interval '{step}', date_trunc('{unit}', now() AT TIME ZONE 'Asia/Dhaka'),
                                          interval '{step}') AS d)
        SELECT b.d,
          (SELECT count(*) FROM orders o WHERE date_trunc('{unit}', o.created_at AT TIME ZONE 'Asia/Dhaka') = b.d) AS orders,
          (SELECT COALESCE(sum(o.total), 0) FROM orders o WHERE o.status = 'delivered'
             AND date_trunc('{unit}', o.created_at AT TIME ZONE 'Asia/Dhaka') = b.d) AS sales,
          (SELECT count(*) FROM users u WHERE u.role = 'farmer'
             AND date_trunc('{unit}', u.created_at AT TIME ZONE 'Asia/Dhaka') = b.d) AS farmers,
          (SELECT count(*) FROM users u WHERE u.role = 'customer'
             AND date_trunc('{unit}', u.created_at AT TIME ZONE 'Asia/Dhaka') = b.d) AS customers
        FROM b ORDER BY b.d"""
    rows = fetch_all(sql)
    return {"unit": unit, "rows": rows}


def breakdowns() -> dict:
    return {
        "status": fetch_all("SELECT status AS k, count(*) AS n FROM orders GROUP BY status ORDER BY n DESC"),
        "category": fetch_all("SELECT category AS k, count(*) AS n FROM listings WHERE status = 'active' "
                              "GROUP BY category ORDER BY n DESC"),
        "district": fetch_all("SELECT COALESCE(l.district_code, '—') AS k, count(DISTINCT l.id) AS n, "
                              "count(DISTINCT l.farmer_id) AS farmers FROM listings l WHERE l.status = 'active' "
                              "GROUP BY 1 ORDER BY n DESC LIMIT 15"),
        "recent": fetch_all("SELECT a.action, a.target_type, a.target_id, a.created_at, a.actor_name "
                            "FROM admin_audit_log a ORDER BY a.id DESC LIMIT 10"),
    }
