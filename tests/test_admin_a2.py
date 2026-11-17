"""Admin A2: orders (real flow, no skipping farmer steps), COD paid/refund -> existing ledger trigger (never twice),
cancel returns stock only when safe, complaints workflow, CSV export, permissions.

Database tests run only when asked:   $env:CB_DB_TESTS="1"; python -m pytest -q tests/test_admin_a2.py
Needs migrations 005-008. Test rows are deleted afterwards (audit rows stay, by design).
"""
from __future__ import annotations

import os
import re
import secrets
import sys
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

DB = os.environ.get("CB_DB_TESTS") == "1"
db_only = pytest.mark.skipif(not DB, reason="set CB_DB_TESTS=1 to run database tests")
PW = "Shapla#2026x"


def test_allowed_steps_follow_farmer_steps():
    from chashibondhu.web.repo_admin_a2 import allowed_steps
    it = lambda s: {"farmer_status": s}  # noqa: E731
    o = {"status": "pending", "payment_status": "unpaid", "order_items": [it("accepted"), it("pending")]}
    assert allowed_steps(o) == ["cancel"]                                      # one farmer has not confirmed
    o["order_items"] = [it("accepted"), it("rejected")]
    assert allowed_steps(o) == ["confirm", "cancel"]
    o.update(status="confirmed", order_items=[it("packed")])
    assert "ship" not in allowed_steps(o)                                      # not handed over yet
    o["order_items"] = [it("handed_over")]
    assert allowed_steps(o) == ["ship", "cancel"]
    assert allowed_steps({"status": "shipped", "payment_status": "unpaid", "order_items": []}) == ["deliver", "cancel"]
    assert allowed_steps({"status": "delivered", "payment_status": "unpaid", "order_items": []}) == ["paid"]
    assert allowed_steps({"status": "delivered", "payment_status": "paid", "order_items": []}) == ["refund"]
    assert allowed_steps({"status": "cancelled", "payment_status": "unpaid", "order_items": []}) == []


def test_csv_formula_guard():
    from chashibondhu.web.repo_admin_a2 import _safe_cell
    assert _safe_cell("=HYPERLINK(1)") == "'=HYPERLINK(1)" and _safe_cell("-40") == "-40" and _safe_cell(None) == ""


# ================================================================ database
def _phone():
    return "+88017" + f"{secrets.randbelow(10**8):08d}"


@pytest.fixture
def world():
    from chashibondhu.web.db import execute, fetch_one
    from chashibondhu.web.passwords import hash_password
    tag = secrets.token_hex(3)
    ids: dict = {"phones": {}}
    for key, role in (("boss", "admin"), ("clerk", "admin"), ("cash", "admin"), ("f1", "farmer"), ("f2", "farmer"),
                      ("buyer", "customer")):
        ph = _phone()
        ids["phones"][key] = ph
        ids[key] = fetch_one("INSERT INTO users (role, full_name, phone, email, password_hash) VALUES (%s, %s, %s, %s, %s) "
                             "RETURNING id", (role, f"Test {key}", ph,
                                              f"{key}{tag}@test.example.com" if role == "customer" else None,
                                              hash_password(PW)))["id"]
    execute("INSERT INTO admin_staff (user_id, is_super) VALUES (%s, true)", (ids["boss"],))
    execute("INSERT INTO admin_staff (user_id, permissions) VALUES (%s, '{orders,complaints}')", (ids["clerk"],))
    execute("INSERT INTO admin_staff (user_id, permissions) VALUES (%s, '{finance}')", (ids["cash"],))
    ids["l1"] = fetch_one("INSERT INTO listings (farmer_id, title, unit, price_per_unit, quantity) VALUES "
                          "(%s, 'Test Alu', 'kg', 40, 100) RETURNING id", (ids["f1"],))["id"]
    ids["l2"] = fetch_one("INSERT INTO listings (farmer_id, title, unit, price_per_unit, quantity) VALUES "
                          "(%s, 'Test Begun', 'kg', 30, 50) RETURNING id", (ids["f2"],))["id"]
    yield ids
    users = [ids[k] for k in ("boss", "clerk", "cash", "f1", "f2", "buyer")]
    execute("DELETE FROM farmer_ledger WHERE farmer_id = ANY(%s)", (users,))
    execute("DELETE FROM complaints WHERE user_id = ANY(%s)", (users,))
    execute("DELETE FROM orders WHERE customer_id = ANY(%s)", (users,))
    execute("DELETE FROM listings WHERE farmer_id = ANY(%s)", (users,))
    execute("DELETE FROM users WHERE id = ANY(%s)", (users,))


def make_order(w, s1="accepted", s2="accepted", deducted=True):
    """Order of 10 kg alu (farmer 1) + 5 kg begun (farmer 2); farmer steps as given, stock taken like the real app."""
    from chashibondhu.web.db import execute, fetch_one
    o = fetch_one("INSERT INTO orders (customer_id, subtotal, total, delivery_address, phone) "
                  "VALUES (%s, 550, 550, 'Dhaka', '+8801700000000') RETURNING id, order_number", (w["buyer"],))
    for fid, lid, title, qty, price, st in ((w["f1"], w["l1"], "Test Alu", 10, 40, s1),
                                            (w["f2"], w["l2"], "Test Begun", 5, 30, s2)):
        execute("INSERT INTO order_items (order_id, listing_id, farmer_id, title, unit, unit_price, quantity, line_total, "
                "farmer_status, stock_deducted) VALUES (%s, %s, %s, %s, 'kg', %s, %s, %s, %s, %s)",
                (o["id"], lid, fid, title, price, qty, price * qty, st, deducted and st in ("accepted", "packed", "handed_over")))
        if deducted and st in ("accepted", "packed", "handed_over"):
            execute("UPDATE listings SET quantity = quantity - %s WHERE id = %s", (qty, lid))
    return o


def qty(lid):
    from chashibondhu.web.db import fetch_one
    return fetch_one("SELECT quantity FROM listings WHERE id = %s", (lid,))["quantity"]


def ledger(w):
    from chashibondhu.web.db import fetch_all
    return fetch_all("SELECT farmer_id, entry_type, amount FROM farmer_ledger WHERE farmer_id = ANY(%s) ORDER BY id",
                     ([w["f1"], w["f2"]],))


@db_only
def test_full_order_flow_and_ledger_once(world):
    from chashibondhu.web import repo_admin_a2 as r2
    from chashibondhu.web.db import execute
    o = make_order(world, "accepted", "pending")
    assert r2.order_step(world["boss"], o["id"], "confirm", None) == "not_allowed"     # farmer 2 not confirmed
    execute("UPDATE order_items SET farmer_status = 'accepted' WHERE order_id = %s", (o["id"],))
    assert r2.order_step(world["boss"], o["id"], "confirm", None) == "ok"
    assert r2.order_step(world["boss"], o["id"], "ship", None) == "not_allowed"         # not handed over
    execute("UPDATE order_items SET farmer_status = 'handed_over' WHERE order_id = %s", (o["id"],))
    assert r2.order_step(world["boss"], o["id"], "ship", None) == "ok"
    assert r2.payment_step(world["boss"], o["id"], "paid", None) == "not_allowed"       # COD: only after delivery
    assert r2.order_step(world["boss"], o["id"], "deliver", None) == "ok"
    assert ledger(world) == []                                                          # delivered but not paid
    assert r2.payment_step(world["boss"], o["id"], "paid", None) == "ok"
    assert r2.payment_step(world["boss"], o["id"], "paid", None) == "not_allowed"       # never twice
    assert [(x["entry_type"], x["amount"]) for x in ledger(world)] == [("sale_credit", 400), ("sale_credit", 150)]
    assert r2.order_step(world["boss"], o["id"], "cancel", "too late") == "not_allowed"  # delivered: refund instead
    assert r2.payment_step(world["boss"], o["id"], "refund", "rotten") == "ok"
    assert sum(x["amount"] for x in ledger(world)) == 0 and len(ledger(world)) == 4
    d = r2.order_detail(o["order_number"])
    assert [h["action"] for h in d["history"]] == ["payment.refund", "payment.paid", "order.deliver", "order.ship",
                                                    "order.confirm"]


@db_only
def test_cancel_returns_only_safe_stock(world):
    from chashibondhu.web import repo_admin_a2 as r2
    o = make_order(world, "packed", "handed_over")
    assert (qty(world["l1"]), qty(world["l2"])) == (90, 45)
    assert r2.order_step(world["boss"], o["id"], "cancel", "customer unreachable") == "ok"
    assert (qty(world["l1"]), qty(world["l2"])) == (100, 45)                 # handed-over goods are gone: no restore
    assert r2.order_step(world["boss"], o["id"], "cancel", "again") == "not_allowed"
    d = r2.order_detail(o["order_number"])
    assert d["status"] == "cancelled" and d["cancel_reason"] == "customer unreachable"


@db_only
def test_finance_numbers(world):
    from chashibondhu.web import repo_admin_a2 as r2
    from chashibondhu.web.db import execute
    before = r2.finance_summary()
    o = make_order(world, "handed_over", "handed_over")
    execute("UPDATE orders SET status = 'delivered' WHERE id = %s", (o["id"],))
    s = r2.finance_summary()
    assert s["to_collect_sum"] - before["to_collect_sum"] == 550
    assert s["pending_earnings"] - before["pending_earnings"] == 550
    body, n = r2.export_csv("payments")
    assert body.startswith("﻿order_number") and o["order_number"] in body and n >= 1


@db_only
def test_complaint_workflow(world):
    from chashibondhu.web import repo_admin_a2 as r2
    from chashibondhu.web.db import fetch_one
    c = fetch_one("INSERT INTO complaints (user_id, category, subject, description) VALUES "
                  "(%s, 'order', 'Late order', 'My order came very late, please check.') RETURNING id", (world["buyer"],))
    cid = c["id"]
    assert r2.complaint_update(world["boss"], cid, assign=world["f1"]) == "not_allowed"     # not staff
    assert r2.complaint_update(world["boss"], cid, assign=world["clerk"], status="in_progress",
                               note="called the farmer") == "ok"
    assert r2.complaint_update(world["boss"], cid, status="bogus") == "not_allowed"
    assert r2.complaint_update(world["clerk"], cid, reply="We spoke to the farmer. Sorry!", status="resolved") == "ok"
    d = r2.complaint_detail(cid)
    assert (d["status"], d["assigned_name"], d["admin_response"]) == ("resolved", "Test clerk", "We spoke to the farmer. Sorry!")
    assert [n["note"] for n in d["notes"]] == ["called the farmer"] and len(d["history"]) == 2
    note = fetch_one("SELECT link FROM notifications WHERE user_id = %s AND kind = 'complaint' ORDER BY id DESC LIMIT 1",
                     (world["buyer"],))
    assert note["link"] == "/customer/complaints"
    assert r2.complaint_update(world["boss"], cid) == "same"


# ---------------------------------------------------------------- pages + permissions on the real database
@pytest.fixture
def web():
    from fastapi.testclient import TestClient
    from chashibondhu.api.main import app
    with TestClient(app) as c:
        yield c


def _login(c, phone):
    c.cookies.clear()
    tok = re.search(r'name="csrf" value="([^"]+)"', c.get("/login?as=admin").text).group(1)
    assert c.post("/login", data={"csrf": tok, "phone": phone, "password": PW, "as_role": "admin"},
                  follow_redirects=False).status_code == 303


def _tok(c, url):
    return re.search(r'name="csrf" value="([^"]+)"', c.get(url).text).group(1)


@db_only
def test_pages_and_permissions(world, web):
    c = web
    o = make_order(world, "handed_over", "handed_over")
    from chashibondhu.web.db import execute, fetch_one
    execute("UPDATE orders SET status = 'delivered' WHERE id = %s", (o["id"],))
    cid = fetch_one("INSERT INTO complaints (user_id, category, subject, description) VALUES (%s, 'order', %s, "
                    "'Something is wrong with this order.') RETURNING id", (world["buyer"], o["order_number"]))["id"]
    _login(c, world["phones"]["boss"])
    for url in ("/admin", "/admin-orders", f"/admin-orders?farmer={world['f1']}", f"/admin-orders/{o['order_number']}",
                "/admin-finance", f"/admin-finance?farmer={world['f1']}", "/admin-complaints",
                "/admin-complaints?status=", f"/admin-complaints/{cid}"):
        assert c.get(url).status_code == 200, url
    assert o["order_number"] in c.get(f"/admin-complaints/{cid}").text
    assert "COD cash received" in c.get(f"/admin-orders/{o['order_number']}").text
    r = c.get("/admin-finance/export/ledger.csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")

    _login(c, world["phones"]["clerk"])                                            # orders + complaints, no finance
    page = c.get(f"/admin-orders/{o['order_number']}").text
    assert "COD cash received" not in page
    tok = _tok(c, "/admin-orders")
    assert c.post(f"/admin-orders/{o['order_number']}/step", data={"csrf": tok, "step": "paid"},
                  follow_redirects=False).status_code == 403
    for url in ("/admin-finance", "/admin-finance/export/payments.csv"):
        assert c.get(url, follow_redirects=False).status_code == 403
    assert c.get(f"/admin-complaints/{cid}").status_code == 200

    _login(c, world["phones"]["cash"])                                             # finance only
    assert c.get("/admin-orders", follow_redirects=False).status_code == 403
    tok = _tok(c, "/admin-finance")
    r = c.post(f"/admin-orders/{o['order_number']}/step", data={"csrf": tok, "step": "paid"}, follow_redirects=False)
    assert r.status_code == 303
    assert fetch_one("SELECT payment_status FROM orders WHERE id = %s", (o["id"],))["payment_status"] == "paid"
    assert len(ledger(world)) == 2
