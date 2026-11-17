"""SQL for Admin A2: orders + disputes, finance (COD paid / refunded -> existing ledger trigger), complaints.

Rules kept from the existing system:
- Order flow: pending -> confirmed -> shipped -> delivered; cancel only before delivery. No new statuses.
- Admin never edits prices, quantities or stock directly. Cancelling restores stock only for items the farmer
  had confirmed but not yet handed over (stock_deducted = true), so nothing is oversold.
- Money: the farmer ledger is written ONLY by the existing database trigger (delivered AND paid -> credit,
  refunded/cancelled -> reversal, unique per item, so never twice).
Every change writes the audit log in the same transaction.
"""
from __future__ import annotations

import csv
import io

from chashibondhu.web.db import connect, fetch_all, fetch_one
from chashibondhu.web.repo_admin import PAGE, _audit

LIVE = ("accepted", "packed", "handed_over")
COMPLAINT_STATUSES = ("open", "in_review", "in_progress", "resolved", "rejected", "closed")


def _like(q: str) -> str:
    return "%" + q.replace("\\", "").replace("%", "").replace("_", "\\_") + "%"


# ================================================================ orders
def order_list(f: dict, page: int = 1) -> tuple[list[dict], int]:
    where, params = " WHERE true", []
    if f.get("q"):
        where += " AND (o.order_number ILIKE %s OR c.full_name ILIKE %s OR o.phone LIKE %s)"
        params += [_like(f["q"])] * 3
    for k, col in (("status", "o.status"), ("payment", "o.payment_status")):
        if f.get(k):
            where += f" AND {col} = %s"
            params.append(f[k])
    if f.get("customer"):
        where += " AND o.customer_id = %s"
        params.append(f["customer"])
    if f.get("farmer"):
        where += " AND EXISTS (SELECT 1 FROM order_items i WHERE i.order_id = o.id AND i.farmer_id = %s)"
        params.append(f["farmer"])
    if f.get("from"):
        where += " AND (o.created_at AT TIME ZONE 'Asia/Dhaka')::date >= %s"
        params.append(f["from"])
    if f.get("to"):
        where += " AND (o.created_at AT TIME ZONE 'Asia/Dhaka')::date <= %s"
        params.append(f["to"])
    base = f"FROM orders o JOIN users c ON c.id = o.customer_id{where}"
    n = fetch_one(f"SELECT count(*) AS n {base}", tuple(params))["n"]
    rows = fetch_all(f"SELECT o.id, o.order_number, o.status, o.payment_status, o.payment_method, o.total, o.created_at, "
                     f"c.id AS customer_id, c.full_name AS customer_name, "
                     f"(SELECT count(DISTINCT i.farmer_id) FROM order_items i WHERE i.order_id = o.id) AS farmers, "
                     f"(SELECT count(*) FROM order_items i WHERE i.order_id = o.id) AS items {base} "
                     f"ORDER BY o.id DESC LIMIT %s OFFSET %s", tuple(params + [PAGE, (max(page, 1) - 1) * PAGE]))
    return rows, int(n)


def order_detail(order_number: str) -> dict | None:
    o = fetch_one("SELECT o.*, c.full_name AS customer_name, c.email AS customer_email, c.phone AS customer_account_phone "
                  "FROM orders o JOIN users c ON c.id = o.customer_id WHERE o.order_number = %s", (order_number,))
    if not o:
        return None
    o["order_items"] = fetch_all(
        "SELECT i.*, u.full_name AS farmer_name, u.phone AS farmer_phone, "
        "(SELECT COALESCE(sum(l.amount), 0) FROM farmer_ledger l WHERE l.order_item_id = i.id) AS ledger_net "
        "FROM order_items i JOIN users u ON u.id = i.farmer_id WHERE i.order_id = %s ORDER BY u.full_name, i.id",
        (o["id"],))
    o["history"] = fetch_all("SELECT action, reason, meta, actor_name, created_at FROM admin_audit_log "
                             "WHERE target_type = 'order' AND target_id = %s ORDER BY id DESC", (o["id"],))
    o["complaints"] = fetch_all("SELECT id, complaint_number, subject, status, created_at FROM complaints "
                                "WHERE subject ILIKE %s OR description ILIKE %s ORDER BY id DESC LIMIT 20",
                                (_like(order_number), _like(order_number)))
    o["next"] = allowed_steps(o)
    return o


def allowed_steps(o: dict) -> list[str]:
    """What an admin may do now, from the real item states (never skips the farmers' own steps)."""
    items = o.get("order_items") or []
    live = [i for i in items if i["farmer_status"] != "rejected"]
    steps = []
    if o["status"] == "pending" and live and all(i["farmer_status"] in LIVE for i in live):
        steps.append("confirm")
    if o["status"] == "confirmed" and live and all(i["farmer_status"] == "handed_over" for i in live):
        steps.append("ship")
    if o["status"] == "shipped":
        steps.append("deliver")
    if o["status"] in ("pending", "confirmed", "shipped"):
        steps.append("cancel")
    if o["status"] == "delivered" and o["payment_status"] == "unpaid":
        steps.append("paid")
    if o["payment_status"] == "paid":
        steps.append("refund")
    return steps


STEP_TO = {"confirm": ("pending", "confirmed"), "ship": ("confirmed", "shipped"), "deliver": ("shipped", "delivered")}


def order_step(actor_id: int, order_id: int, step: str, reason: str | None) -> str:
    """confirm / ship / deliver / cancel (orders permission). Re-checks everything inside the transaction."""
    with connect() as conn:
        o = conn.execute("SELECT * FROM orders WHERE id = %s FOR UPDATE", (order_id,)).fetchone()
        if not o:
            return "not_found"
        o["order_items"] = conn.execute("SELECT * FROM order_items WHERE order_id = %s FOR UPDATE",
                                        (order_id,)).fetchall()
        if step not in allowed_steps(o) or step in ("paid", "refund"):
            return "not_allowed"
        if step == "cancel":
            restored = []
            for i in o["order_items"]:
                if i["stock_deducted"] and i["farmer_status"] in ("accepted", "packed") and i["listing_id"]:
                    conn.execute("UPDATE listings SET quantity = quantity + %s WHERE id = %s", (i["quantity"], i["listing_id"]))
                    conn.execute("UPDATE order_items SET stock_deducted = false WHERE id = %s", (i["id"],))
                    restored.append({"item": i["id"], "listing": i["listing_id"], "qty": str(i["quantity"])})
            conn.execute("UPDATE orders SET status = 'cancelled', cancel_reason = %s WHERE id = %s", (reason, order_id))
            _audit(conn, actor_id, "order.cancel", "order", order_id, reason=reason,
                   meta={"before": o["status"], "stock_restored": restored})
            return "ok"
        before, after = STEP_TO[step]
        conn.execute("UPDATE orders SET status = %s WHERE id = %s AND status = %s", (after, order_id, before))
        _audit(conn, actor_id, f"order.{step}", "order", order_id, reason=reason, meta={"before": before, "after": after})
        return "ok"


def payment_step(actor_id: int, order_id: int, step: str, reason: str | None) -> str:
    """paid (COD cash received after delivery) / refund (finance permission). The ledger trigger does the money."""
    with connect() as conn:
        o = conn.execute("SELECT * FROM orders WHERE id = %s FOR UPDATE", (order_id,)).fetchone()
        if not o:
            return "not_found"
        if step == "paid" and o["status"] == "delivered" and o["payment_status"] == "unpaid":
            new = "paid"
        elif step == "refund" and o["payment_status"] == "paid":
            new = "refunded"
        else:
            return "not_allowed"
        conn.execute("UPDATE orders SET payment_status = %s WHERE id = %s", (new, order_id))
        ledger = conn.execute("SELECT entry_type, count(*) AS n, COALESCE(sum(l.amount), 0) AS total FROM farmer_ledger l "
                              "JOIN order_items i ON i.id = l.order_item_id WHERE i.order_id = %s GROUP BY entry_type",
                              (order_id,)).fetchall()
        _audit(conn, actor_id, "payment.paid" if new == "paid" else "payment.refund", "order", order_id, reason=reason,
               meta={"method": o["payment_method"], "amount": str(o["total"]), "before": o["payment_status"],
                     "ledger_after": [dict(r) for r in ledger]})
        return "ok"


# ================================================================ finance
def finance_summary() -> dict:
    s = fetch_one("""
        SELECT COALESCE(sum(total) FILTER (WHERE status <> 'cancelled'), 0)                         AS order_value,
               count(*) FILTER (WHERE payment_status = 'paid')                                     AS paid_n,
               COALESCE(sum(total) FILTER (WHERE payment_status = 'paid'), 0)                      AS paid_sum,
               count(*) FILTER (WHERE status = 'delivered' AND payment_status = 'unpaid')          AS to_collect_n,
               COALESCE(sum(total) FILTER (WHERE status = 'delivered' AND payment_status = 'unpaid'), 0) AS to_collect_sum,
               count(*) FILTER (WHERE status IN ('pending', 'confirmed', 'shipped'))                AS open_n,
               COALESCE(sum(total) FILTER (WHERE status IN ('pending', 'confirmed', 'shipped')), 0) AS open_sum,
               count(*) FILTER (WHERE payment_status = 'refunded')                                 AS refunded_n,
               COALESCE(sum(total) FILTER (WHERE payment_status = 'refunded'), 0)                  AS refunded_sum
        FROM orders""") or {}
    s.update(fetch_one("""
        SELECT COALESCE(sum(amount) FILTER (WHERE entry_type = 'sale_credit'), 0)     AS credited,
               COALESCE(sum(amount) FILTER (WHERE entry_type = 'refund_reversal'), 0) AS reversed,
               COALESCE(sum(amount), 0)                                               AS farmer_balance
        FROM farmer_ledger""") or {})
    s["pending_earnings"] = fetch_one(
        "SELECT COALESCE(sum(i.line_total), 0) AS v FROM order_items i JOIN orders o ON o.id = i.order_id "
        "WHERE i.farmer_status <> 'rejected' AND o.status <> 'cancelled' AND o.payment_status = 'unpaid'")["v"]
    return s


def farmer_earnings(limit: int = 100) -> list[dict]:
    return fetch_all("""
        SELECT u.id, u.full_name, u.phone,
               COALESCE((SELECT sum(amount) FROM farmer_ledger l WHERE l.farmer_id = u.id), 0) AS balance,
               COALESCE((SELECT sum(i.line_total) FROM order_items i JOIN orders o ON o.id = i.order_id
                         WHERE i.farmer_id = u.id AND i.farmer_status <> 'rejected' AND o.status <> 'cancelled'
                           AND o.payment_status = 'unpaid'), 0) AS pending
        FROM users u WHERE u.role = 'farmer'
          AND (EXISTS (SELECT 1 FROM farmer_ledger l WHERE l.farmer_id = u.id)
               OR EXISTS (SELECT 1 FROM order_items i WHERE i.farmer_id = u.id))
        ORDER BY balance DESC, pending DESC LIMIT %s""", (limit,))


def ledger_rows(farmer_id: int | None, page: int = 1) -> tuple[list[dict], int]:
    where, params = "", []
    if farmer_id:
        where, params = " WHERE l.farmer_id = %s", [farmer_id]
    n = fetch_one(f"SELECT count(*) AS n FROM farmer_ledger l{where}", tuple(params))["n"]
    rows = fetch_all(f"SELECT l.id, l.entry_type, l.amount, l.created_at, u.id AS farmer_id, u.full_name AS farmer_name, "
                     f"i.title, i.quantity, i.unit, o.order_number FROM farmer_ledger l "
                     f"JOIN users u ON u.id = l.farmer_id JOIN order_items i ON i.id = l.order_item_id "
                     f"JOIN orders o ON o.id = i.order_id{where} ORDER BY l.id DESC LIMIT %s OFFSET %s",
                     tuple(params + [PAGE, (max(page, 1) - 1) * PAGE]))
    return rows, int(n)


def _safe_cell(v) -> str:
    """CSV/Excel formula injection guard."""
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") and not s.lstrip("-").replace(".", "", 1).isdigit() else s


def export_csv(kind: str) -> tuple[str, int]:
    if kind == "payments":
        head = ["order_number", "created_at", "customer", "status", "payment_method", "payment_status", "subtotal",
                "delivery_fee", "total"]
        rows = fetch_all("SELECT o.order_number, o.created_at, c.full_name AS customer, o.status, o.payment_method, "
                         "o.payment_status, o.subtotal, o.delivery_fee, o.total FROM orders o "
                         "JOIN users c ON c.id = o.customer_id ORDER BY o.id")
    elif kind == "ledger":
        head = ["id", "created_at", "farmer_id", "farmer", "order_number", "item", "entry_type", "amount"]
        rows = fetch_all("SELECT l.id, l.created_at, u.id AS farmer_id, u.full_name AS farmer, o.order_number, "
                         "i.title AS item, l.entry_type, l.amount FROM farmer_ledger l JOIN users u ON u.id = l.farmer_id "
                         "JOIN order_items i ON i.id = l.order_item_id JOIN orders o ON o.id = i.order_id ORDER BY l.id")
    else:
        raise ValueError(kind)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(head)
    for r in rows:
        w.writerow([_safe_cell(r[h]) for h in head])
    return "﻿" + buf.getvalue(), len(rows)        # BOM so Excel shows Bangla names correctly


# ================================================================ complaints
def complaint_list(f: dict, page: int = 1) -> tuple[list[dict], int]:
    where, params = " WHERE true", []
    if f.get("status") == "active":
        where += " AND c.status IN ('open', 'in_review', 'in_progress')"
    elif f.get("status"):
        where += " AND c.status = %s"
        params.append(f["status"])
    if f.get("category"):
        where += " AND c.category = %s"
        params.append(f["category"])
    if f.get("role"):
        where += " AND u.role = %s"
        params.append(f["role"])
    if f.get("mine"):
        where += " AND c.assigned_to = %s"
        params.append(f["mine"])
    if f.get("q"):
        where += " AND (c.complaint_number ILIKE %s OR c.subject ILIKE %s OR c.description ILIKE %s OR u.full_name ILIKE %s)"
        params += [_like(f["q"])] * 4
    base = f"FROM complaints c JOIN users u ON u.id = c.user_id LEFT JOIN users a ON a.id = c.assigned_to{where}"
    n = fetch_one(f"SELECT count(*) AS n {base}", tuple(params))["n"]
    rows = fetch_all(f"SELECT c.id, c.complaint_number, c.category, c.subject, c.status, c.created_at, c.updated_at, "
                     f"(c.image_path IS NOT NULL) AS has_photo, u.id AS user_id, u.full_name AS user_name, "
                     f"u.role AS user_role, a.full_name AS assigned_name {base} "
                     f"ORDER BY (c.status IN ('open', 'in_review', 'in_progress')) DESC, c.id DESC LIMIT %s OFFSET %s",
                     tuple(params + [PAGE, (max(page, 1) - 1) * PAGE]))
    return rows, int(n)


def complaint_detail(complaint_id: int) -> dict | None:
    c = fetch_one("SELECT c.*, u.full_name AS user_name, u.role AS user_role, u.phone AS user_phone, u.email AS user_email, "
                  "a.full_name AS assigned_name, r.full_name AS responder_name FROM complaints c "
                  "JOIN users u ON u.id = c.user_id LEFT JOIN users a ON a.id = c.assigned_to "
                  "LEFT JOIN users r ON r.id = c.responded_by WHERE c.id = %s", (complaint_id,))
    if not c:
        return None
    c["notes"] = fetch_all("SELECT n.note, n.created_at, u.full_name AS author FROM complaint_notes n "
                           "LEFT JOIN users u ON u.id = n.author_id WHERE n.complaint_id = %s ORDER BY n.id", (complaint_id,))
    c["history"] = fetch_all("SELECT action, reason, meta, actor_name, created_at FROM admin_audit_log "
                             "WHERE target_type = 'complaint' AND target_id = %s ORDER BY id DESC", (complaint_id,))
    c["orders"] = fetch_all("SELECT order_number, status, payment_status, total, created_at FROM orders "
                            "WHERE customer_id = %s ORDER BY id DESC LIMIT 10", (c["user_id"],)) \
        if c["user_role"] == "customer" else []
    return c


def complaint_staff() -> list[dict]:
    return fetch_all("SELECT u.id, u.full_name FROM users u JOIN admin_staff s ON s.user_id = u.id "
                     "WHERE u.role = 'admin' AND u.status = 'active' AND (s.is_super OR 'complaints' = ANY(s.permissions)) "
                     "ORDER BY u.full_name")


def complaint_update(actor_id: int, complaint_id: int, *, status: str | None = None, assign: int | None = None,
                     unassign: bool = False, reply: str | None = None, note: str | None = None) -> str:
    with connect() as conn:
        c = conn.execute("SELECT * FROM complaints WHERE id = %s FOR UPDATE", (complaint_id,)).fetchone()
        if not c:
            return "not_found"
        changes = {}
        if status and status != c["status"]:
            if status not in COMPLAINT_STATUSES:
                return "not_allowed"
            conn.execute("UPDATE complaints SET status = %s, updated_at = now() WHERE id = %s", (status, complaint_id))
            changes["status"] = [c["status"], status]
        if assign is not None:
            ok = conn.execute("SELECT 1 FROM users u JOIN admin_staff s ON s.user_id = u.id WHERE u.id = %s "
                              "AND u.role = 'admin' AND u.status = 'active' AND (s.is_super OR 'complaints' = ANY(s.permissions))",
                              (assign,)).fetchone()
            if not ok:
                return "not_allowed"
            conn.execute("UPDATE complaints SET assigned_to = %s, updated_at = now() WHERE id = %s", (assign, complaint_id))
            changes["assigned_to"] = [c["assigned_to"], assign]
        elif unassign and c["assigned_to"]:
            conn.execute("UPDATE complaints SET assigned_to = NULL, updated_at = now() WHERE id = %s", (complaint_id,))
            changes["assigned_to"] = [c["assigned_to"], None]
        if reply:
            conn.execute("UPDATE complaints SET admin_response = %s, responded_by = %s, responded_at = now(), "
                         "updated_at = now() WHERE id = %s", (reply, actor_id, complaint_id))
            link = "/customer/complaints" if conn.execute("SELECT role FROM users WHERE id = %s", (c["user_id"],)) \
                .fetchone()["role"] == "customer" else "/farmer/complaints"
            conn.execute("INSERT INTO notifications (user_id, kind, title, body, link, dedupe_key) VALUES "
                         "(%s, 'complaint', 'অভিযোগের উত্তর এসেছে / Reply to your complaint', %s, %s, NULL)",
                         (c["user_id"], c["complaint_number"], link))
            changes["reply"] = True
        if note:
            conn.execute("INSERT INTO complaint_notes (complaint_id, author_id, note) VALUES (%s, %s, %s)",
                         (complaint_id, actor_id, note))
            changes["note"] = True
        if not changes:
            return "same"
        _audit(conn, actor_id, "complaint.update", "complaint", complaint_id, meta=changes)
        return "ok"


def open_complaints() -> int:
    return int(fetch_one("SELECT count(*) AS n FROM complaints WHERE status IN ('open', 'in_review', 'in_progress')")["n"])
