"""SQL for Admin A3: announcements, articles/news, pre-harvest monitoring, offline sync log, analytics reports.
Every admin change writes the audit log in the same transaction."""
from __future__ import annotations

import csv
import io
from datetime import date, timedelta

from chashibondhu.web.db import connect, execute, fetch_all, fetch_one
from chashibondhu.web.repo_admin import PAGE, _audit
from chashibondhu.web.repo_admin_a2 import _like, _safe_cell

AUDIENCE_ROLES = {"all": ("farmer", "customer"), "farmer": ("farmer",), "customer": ("customer",)}


# ================================================================ announcements
def announcements(limit: int = 100) -> list[dict]:
    return fetch_all("SELECT a.*, u.full_name AS creator FROM announcements a LEFT JOIN users u ON u.id = a.created_by "
                     "ORDER BY a.id DESC LIMIT %s", (limit,))


def create_announcement(actor_id: int, title: str, body: str, audience: str, publish: bool, notify: bool) -> int:
    with connect() as conn:
        aid = conn.execute("INSERT INTO announcements (title, body, audience, created_by, status, published_at) "
                           "VALUES (%s, %s, %s, %s, %s, CASE WHEN %s THEN now() END) RETURNING id",
                           (title, body, audience, actor_id, "published" if publish else "draft", publish)).fetchone()["id"]
        n = _notify(conn, aid) if publish and notify else None
        _audit(conn, actor_id, "announcement.create", "announcement", aid,
               meta={"audience": audience, "status": "published" if publish else "draft", "in_app_sent": n})
        return int(aid)


def _notify(conn, aid: int) -> int:
    """In-app notification to every active user of the audience, once (dedupe key per announcement)."""
    a = conn.execute("SELECT * FROM announcements WHERE id = %s FOR UPDATE", (aid,)).fetchone()
    if a["notified_at"] or a["status"] != "published":
        return 0
    cur = conn.execute("INSERT INTO notifications (user_id, kind, title, body, link, dedupe_key) "
                       "SELECT u.id, 'announcement', %s, left(%s, 300), %s, %s FROM users u "
                       "WHERE u.role = ANY(%s) AND u.status = 'active' "
                       "ON CONFLICT (user_id, dedupe_key) WHERE dedupe_key IS NOT NULL DO NOTHING",
                       (a["title"], a["body"], "/farmer/tips" if a["audience"] == "farmer" else None, f"ann:{aid}",
                        list(AUDIENCE_ROLES[a["audience"]])))
    conn.execute("UPDATE announcements SET notified_at = now(), notified_count = %s WHERE id = %s", (cur.rowcount, aid))
    return cur.rowcount


def announcement_action(actor_id: int, aid: int, action: str) -> str:
    """publish / notify / archive / restore (archived -> draft)."""
    with connect() as conn:
        a = conn.execute("SELECT * FROM announcements WHERE id = %s FOR UPDATE", (aid,)).fetchone()
        if not a:
            return "not_found"
        meta = {"before": a["status"]}
        if action == "publish" and a["status"] == "draft":
            conn.execute("UPDATE announcements SET status = 'published', published_at = now(), updated_at = now() "
                         "WHERE id = %s", (aid,))
        elif action == "notify" and a["status"] == "published" and not a["notified_at"]:
            meta["in_app_sent"] = _notify(conn, aid)
        elif action == "archive" and a["status"] != "archived":
            conn.execute("UPDATE announcements SET status = 'archived', updated_at = now() WHERE id = %s", (aid,))
        elif action == "restore" and a["status"] == "archived":
            conn.execute("UPDATE announcements SET status = 'draft', updated_at = now() WHERE id = %s", (aid,))
        else:
            return "not_allowed"
        _audit(conn, actor_id, f"announcement.{action}", "announcement", aid, meta=meta)
        return "ok"


# ================================================================ content (articles / news / videos)
CONTENT_FIELDS = ("kind", "title", "summary", "body", "media_url", "source_name", "source_url")


def content_list(f: dict, page: int = 1) -> tuple[list[dict], int]:
    where, params = " WHERE true", []
    if f.get("status"):
        where += " AND status = %s"
        params.append(f["status"])
    if f.get("kind"):
        where += " AND kind = %s"
        params.append(f["kind"])
    n = fetch_one(f"SELECT count(*) AS n FROM content_posts{where}", tuple(params))["n"]
    rows = fetch_all(f"SELECT id, kind, title, status, published_at, updated_at, source_name FROM content_posts{where} "
                     f"ORDER BY id DESC LIMIT %s OFFSET %s", tuple(params + [PAGE, (max(page, 1) - 1) * PAGE]))
    return rows, int(n)


def content_get(cid: int) -> dict | None:
    return fetch_one("SELECT * FROM content_posts WHERE id = %s", (cid,))


def content_save(actor_id: int, cid: int | None, data: dict) -> int:
    with connect() as conn:
        if cid:
            conn.execute(f"UPDATE content_posts SET {', '.join(f'{k} = %s' for k in CONTENT_FIELDS)}, updated_at = now() "
                         f"WHERE id = %s", tuple(data[k] for k in CONTENT_FIELDS) + (cid,))
            _audit(conn, actor_id, "content.update", "content", cid, meta={"title": data["title"]})
            return cid
        new = conn.execute(f"INSERT INTO content_posts ({', '.join(CONTENT_FIELDS)}, created_by) VALUES "
                           f"({', '.join(['%s'] * len(CONTENT_FIELDS))}, %s) RETURNING id",
                           tuple(data[k] for k in CONTENT_FIELDS) + (actor_id,)).fetchone()["id"]
        _audit(conn, actor_id, "content.create", "content", new, meta={"title": data["title"], "kind": data["kind"]})
        return int(new)


def content_status(actor_id: int, cid: int, status: str, published_at: date | None = None) -> str:
    with connect() as conn:
        c = conn.execute("SELECT status, published_at FROM content_posts WHERE id = %s FOR UPDATE", (cid,)).fetchone()
        if not c:
            return "not_found"
        if c["status"] == status:
            return "same"
        if status == "published":
            conn.execute("UPDATE content_posts SET status = 'published', updated_at = now(), "
                         "published_at = COALESCE(%s::date::timestamptz, published_at, now()) WHERE id = %s",
                         (published_at, cid))
        else:
            conn.execute("UPDATE content_posts SET status = %s, updated_at = now() WHERE id = %s", (status, cid))
        _audit(conn, actor_id, f"content.{status}", "content", cid, meta={"before": c["status"]})
        return "ok"


def public_posts(limit: int = 30) -> list[dict]:
    return fetch_all("SELECT id, kind, title, summary, published_at, source_name FROM content_posts "
                     "WHERE status = 'published' AND published_at <= now() ORDER BY published_at DESC LIMIT %s", (limit,))


def public_post(cid: int) -> dict | None:
    return fetch_one("SELECT * FROM content_posts WHERE id = %s AND status = 'published' AND published_at <= now()",
                     (cid,))


# ================================================================ pre-harvest monitoring (view + cancel with a reason)
def forecasts(f: dict, page: int = 1) -> tuple[list[dict], int]:
    where, params = " WHERE true", []
    if f.get("status"):
        where += " AND h.status = %s"
        params.append(f["status"])
    if f.get("q"):
        where += " AND (h.product_name ILIKE %s OR u.full_name ILIKE %s OR h.id::text = %s)"
        params += [_like(f["q"]), _like(f["q"]), f["q"]]
    base = f"FROM harvest_forecasts h JOIN users u ON u.id = h.farmer_id{where}"
    n = fetch_one(f"SELECT count(*) AS n {base}", tuple(params))["n"]
    rows = fetch_all(f"SELECT h.id, h.product_name, h.variety, h.expected_qty, h.unit, h.harvest_from, h.harvest_to, "
                     f"h.district_code, h.status, h.actual_qty, h.actual_harvest_date, h.listing_id, h.created_at, "
                     f"u.id AS farmer_id, u.full_name AS farmer_name, "
                     f"(SELECT count(*) FROM harvest_matches m WHERE m.forecast_id = h.id) AS matches {base} "
                     f"ORDER BY h.id DESC LIMIT %s OFFSET %s", tuple(params + [PAGE, (max(page, 1) - 1) * PAGE]))
    return rows, int(n)


def demand_requests(f: dict, page: int = 1) -> tuple[list[dict], int]:
    where, params = " WHERE true", []
    if f.get("status"):
        where += " AND r.status = %s"
        params.append(f["status"])
    if f.get("q"):
        where += " AND (r.product_name ILIKE %s OR u.full_name ILIKE %s OR r.id::text = %s)"
        params += [_like(f["q"]), _like(f["q"]), f["q"]]
    base = f"FROM buyer_demand_requests r JOIN users u ON u.id = r.buyer_id{where}"
    n = fetch_one(f"SELECT count(*) AS n {base}", tuple(params))["n"]
    rows = fetch_all(f"SELECT r.id, r.product_name, r.quantity, r.unit, r.needed_from, r.needed_to, r.district_code, "
                     f"r.status, r.created_at, u.id AS buyer_id, u.full_name AS buyer_name, u.role AS buyer_role, "
                     f"(SELECT count(*) FROM harvest_matches m WHERE m.request_id = r.id) AS matches {base} "
                     f"ORDER BY r.id DESC LIMIT %s OFFSET %s", tuple(params + [PAGE, (max(page, 1) - 1) * PAGE]))
    return rows, int(n)


def matches(f: dict, page: int = 1) -> tuple[list[dict], int]:
    where, params = " WHERE true", []
    if f.get("status"):
        where += " AND m.status = %s"
        params.append(f["status"])
    base = ("FROM harvest_matches m JOIN harvest_forecasts h ON h.id = m.forecast_id JOIN buyer_demand_requests r "
            "ON r.id = m.request_id JOIN users fa ON fa.id = h.farmer_id JOIN users b ON b.id = r.buyer_id "
            f"LEFT JOIN orders o ON o.id = m.order_id{where}")
    n = fetch_one(f"SELECT count(*) AS n {base}", tuple(params))["n"]
    rows = fetch_all(f"SELECT m.id, m.status, m.match_qty, m.confirmed_qty, m.updated_at, h.id AS forecast_id, "
                     f"h.product_name, h.unit, fa.id AS farmer_id, fa.full_name AS farmer_name, r.id AS request_id, "
                     f"b.id AS buyer_id, b.full_name AS buyer_name, o.order_number {base} "
                     f"ORDER BY m.id DESC LIMIT %s OFFSET %s",
                     tuple(params + [PAGE, (max(page, 1) - 1) * PAGE]))
    return rows, int(n)


def harvest_counts() -> dict:
    return fetch_one("""
        SELECT (SELECT count(*) FROM harvest_forecasts WHERE status = 'open') AS forecasts_open,
               (SELECT count(*) FROM harvest_forecasts WHERE actual_qty IS NOT NULL) AS forecasts_confirmed,
               (SELECT count(*) FROM buyer_demand_requests WHERE status = 'open') AS requests_open,
               (SELECT count(*) FROM harvest_matches WHERE status IN ('buyer_interested', 'farmer_offered', 'agreed')) AS matches_live,
               (SELECT count(*) FROM harvest_matches WHERE status = 'qty_confirmed') AS matches_orderable,
               (SELECT count(*) FROM harvest_matches WHERE status = 'converted') AS matches_converted""") or {}


def admin_cancel(actor_id: int, kind: str, rec_id: int, reason: str) -> str:
    """Cancel a misleading forecast or demand request (only while 'open'). Live matches are cancelled too.
    Never creates stock and never touches listings or orders."""
    table, owner, col, link = (("harvest_forecasts", "farmer_id", "forecast_id", "/farmer/forecasts") if kind == "forecast"
                               else ("buyer_demand_requests", "buyer_id", "request_id", "/requests"))
    with connect() as conn:
        r = conn.execute(f"SELECT id, status, {owner} AS owner, product_name FROM {table} WHERE id = %s FOR UPDATE",
                         (rec_id,)).fetchone()
        if not r:
            return "not_found"
        if r["status"] != "open":
            return "not_allowed"
        conn.execute(f"UPDATE {table} SET status = 'cancelled' WHERE id = %s", (rec_id,))
        m = conn.execute(f"UPDATE harvest_matches SET status = 'cancelled' WHERE {col} = %s "
                         "AND status IN ('buyer_interested', 'farmer_offered', 'agreed')", (rec_id,)).rowcount
        conn.execute("INSERT INTO notifications (user_id, kind, title, body, link) VALUES (%s, 'admin', "
                     "'অ্যাডমিন একটি তথ্য বাতিল করেছেন / An admin cancelled a record', %s, %s)",
                     (r["owner"], f"{r['product_name']}: {reason}", link))
        _audit(conn, actor_id, f"{kind}.cancel", kind, rec_id, reason=reason, meta={"matches_cancelled": m})
        return "ok"


# ================================================================ offline sync log
def log_sync(farmer_id: int | None, record_type: str, client_id: str | None, result: str, http_status: int,
             detail: str | None, server_id: int | None) -> None:
    execute("INSERT INTO offline_sync_events (farmer_id, record_type, client_id, result, http_status, detail, server_id) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (farmer_id, record_type, client_id, result, http_status, (detail or None) and str(detail)[:120], server_id))


def sync_events(f: dict, page: int = 1) -> tuple[list[dict], int, list[dict]]:
    where, params = " WHERE true", []
    if f.get("result") == "problems":
        where += " AND e.result IN ('conflict', 'rejected', 'error')"
    elif f.get("result"):
        where += " AND e.result = %s"
        params.append(f["result"])
    if f.get("farmer"):
        where += " AND e.farmer_id = %s"
        params.append(f["farmer"])
    n = fetch_one(f"SELECT count(*) AS n FROM offline_sync_events e{where}", tuple(params))["n"]
    rows = fetch_all(f"SELECT e.*, u.full_name AS farmer_name FROM offline_sync_events e "
                     f"LEFT JOIN users u ON u.id = e.farmer_id{where} ORDER BY e.id DESC LIMIT %s OFFSET %s",
                     tuple(params + [PAGE, (max(page, 1) - 1) * PAGE]))
    summary = fetch_all("SELECT result, count(*) AS n FROM offline_sync_events WHERE created_at > now() - interval '7 days' "
                        "GROUP BY result ORDER BY n DESC")
    return rows, int(n), summary


# ================================================================ analytics (aggregates only, no personal data)
REPORTS = {
    "registrations": ("নিবন্ধন", "Registrations"), "orders": ("অর্ডার ও বিক্রি", "Orders & sales"),
    "categories": ("পণ্যের ধরন", "Product categories"), "districts": ("জেলা অনুযায়ী", "By district"),
    "complaints": ("অভিযোগ", "Complaints"), "reviews": ("রিভিউ", "Reviews"),
    "harvest": ("আগাম ফসল", "Harvest forecasts"), "demand": ("আগাম চাহিদা ও মিল", "Demand & matches"),
    "ai": ("AI প্রশ্ন ও মতামত", "AI questions & feedback"),
}
DAY = "(%s AT TIME ZONE 'Asia/Dhaka')::date"


def report(kind: str, d_from: date, d_to: date) -> tuple[list[str], list[dict]]:
    p = {"a": d_from, "b": d_to}
    rng = lambda col: f"{DAY % col} BETWEEN %(a)s AND %(b)s"  # noqa: E731
    if kind == "registrations":
        return ["day", "farmers", "customers"], fetch_all(
            f"SELECT d::date AS day, (SELECT count(*) FROM users u WHERE u.role = 'farmer' AND {DAY % 'u.created_at'} = d::date) AS farmers, "
            f"(SELECT count(*) FROM users u WHERE u.role = 'customer' AND {DAY % 'u.created_at'} = d::date) AS customers "
            f"FROM generate_series(%(a)s::date, %(b)s::date, interval '1 day') d ORDER BY d", p)
    if kind == "orders":
        return ["day", "orders", "delivered", "delivered_value", "cancelled"], fetch_all(
            f"SELECT d::date AS day, count(o.id) AS orders, count(o.id) FILTER (WHERE o.status = 'delivered') AS delivered, "
            f"COALESCE(sum(o.total) FILTER (WHERE o.status = 'delivered'), 0) AS delivered_value, "
            f"count(o.id) FILTER (WHERE o.status = 'cancelled') AS cancelled "
            f"FROM generate_series(%(a)s::date, %(b)s::date, interval '1 day') d "
            f"LEFT JOIN orders o ON {DAY % 'o.created_at'} = d::date GROUP BY d ORDER BY d", p)
    if kind == "categories":
        return ["category", "active_listings", "new_in_period"], fetch_all(
            f"SELECT category, count(*) FILTER (WHERE status = 'active') AS active_listings, "
            f"count(*) FILTER (WHERE {rng('created_at')}) AS new_in_period FROM listings GROUP BY category ORDER BY 2 DESC", p)
    if kind == "districts":
        return ["district_code", "farmers", "customers", "active_listings"], fetch_all(
            "SELECT COALESCE(district_code, '-') AS district_code, count(*) FILTER (WHERE role = 'farmer') AS farmers, "
            "count(*) FILTER (WHERE role = 'customer') AS customers, "
            "(SELECT count(*) FROM listings l WHERE l.status = 'active' AND l.district_code IS NOT DISTINCT FROM u.district_code) "
            "AS active_listings FROM users u WHERE role IN ('farmer', 'customer') GROUP BY district_code ORDER BY 2 DESC", p)
    if kind == "complaints":
        return ["category", "status", "complaints"], fetch_all(
            f"SELECT category, status, count(*) AS complaints FROM complaints WHERE {rng('created_at')} "
            f"GROUP BY category, status ORDER BY category, status", p)
    if kind == "reviews":
        return ["rating", "visible", "hidden"], fetch_all(
            f"SELECT g AS rating, count(r.id) FILTER (WHERE r.status = 'visible') AS visible, "
            f"count(r.id) FILTER (WHERE r.status = 'hidden') AS hidden FROM generate_series(1, 5) g "
            f"LEFT JOIN reviews r ON r.rating = g AND {rng('r.created_at')} GROUP BY g ORDER BY g", p)
    if kind == "harvest":
        return ["product", "unit", "forecasts", "expected_qty", "confirmed_forecasts", "actual_qty"], fetch_all(
            f"SELECT product_name AS product, unit, count(*) AS forecasts, sum(expected_qty) AS expected_qty, "
            f"count(actual_qty) AS confirmed_forecasts, COALESCE(sum(actual_qty), 0) AS actual_qty "
            f"FROM harvest_forecasts WHERE {rng('created_at')} GROUP BY product_name, unit ORDER BY 3 DESC", p)
    if kind == "demand":
        return ["product", "unit", "requests", "requested_qty", "matches", "agreed", "orderable", "converted"], fetch_all(
            f"SELECT r.product_name AS product, r.unit, count(DISTINCT r.id) AS requests, "
            f"(SELECT sum(x.quantity) FROM buyer_demand_requests x WHERE x.product_name = r.product_name AND x.unit = r.unit "
            f" AND {rng('x.created_at')}) AS requested_qty, count(m.id) AS matches, "
            f"count(m.id) FILTER (WHERE m.status = 'agreed') AS agreed, count(m.id) FILTER (WHERE m.status = 'qty_confirmed') "
            f"AS orderable, count(m.id) FILTER (WHERE m.status = 'converted') AS converted "
            f"FROM buyer_demand_requests r LEFT JOIN harvest_matches m ON m.request_id = r.id "
            f"WHERE {rng('r.created_at')} GROUP BY r.product_name, r.unit ORDER BY 3 DESC", p)
    if kind == "ai":
        return ["day", "questions", "helpful", "not_helpful"], fetch_all(
            f"SELECT d::date AS day, (SELECT count(*) FROM ai_messages m WHERE m.role = 'user' AND {DAY % 'm.created_at'} = d::date) "
            f"AS questions, (SELECT count(*) FROM ai_feedback f WHERE f.helpful AND {DAY % 'f.created_at'} = d::date) AS helpful, "
            f"(SELECT count(*) FROM ai_feedback f WHERE NOT f.helpful AND {DAY % 'f.created_at'} = d::date) AS not_helpful "
            f"FROM generate_series(%(a)s::date, %(b)s::date, interval '1 day') d ORDER BY d", p)
    raise ValueError(kind)


def ai_negative_feedback(limit: int = 30) -> list[dict]:
    """Answers people marked as not helpful (question + answer + model), to improve the assistant."""
    return fetch_all("""
        SELECT f.created_at, f.comment, a.content AS answer, a.model, a.status,
               (SELECT q.content FROM ai_messages q WHERE q.conversation_id = a.conversation_id AND q.role = 'user'
                  AND q.id < a.id ORDER BY q.id DESC LIMIT 1) AS question
        FROM ai_feedback f JOIN ai_messages a ON a.id = f.message_id
        WHERE NOT f.helpful ORDER BY f.id DESC LIMIT %s""", (limit,))


def to_csv(headers: list[str], rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(headers)
    for r in rows:
        w.writerow([_safe_cell(r[h]) for h in headers])
    return "﻿" + buf.getvalue()


def clamp_range(a: date | None, b: date | None) -> tuple[date, date]:
    b = b or date.today()
    a = a or (b - timedelta(days=29))
    if a > b:
        a, b = b, a
    return max(a, b - timedelta(days=365)), b
