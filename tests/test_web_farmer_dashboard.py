"""Farmer dashboard Phase 1: pages, ownership-safe flows and AI access (no database: fake repo).

The SQL itself (stock, ledger trigger, migration 002) was tested against a real PostgreSQL 16;
see docs in the delivery message. Run: python -m pytest -q tests/test_web_farmer_dashboard.py
"""
from __future__ import annotations

import re
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))   # tests/fake_auth.py

pytest.importorskip("fastapi.testclient")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from chashibondhu.web import repo  # noqa: E402
from chashibondhu.web import routes_farmer  # noqa: E402
from chashibondhu.web.passwords import hash_password  # noqa: E402

NOW = datetime(2026, 11, 13, 10, 0)
USERS = {
    "+8801711111111": {"id": 7, "role": "farmer", "full_name": "Rahim", "status": "active",
                       "password_hash": hash_password("secret1")},
    "+8801733333333": {"id": 9, "role": "customer", "full_name": "Buyer", "status": "active",
                       "password_hash": hash_password("buyer12")},
}


@pytest.fixture()
def fake(monkeypatch):
    calls: dict = {}
    m = monkeypatch.setattr
    m(repo, "get_user_by_phone", lambda phone: USERS.get(phone))
    from fake_auth import install
    install(monkeypatch)
    m(repo, "get_user", lambda uid: next((u for u in USERS.values() if u["id"] == uid), None))
    m(repo, "is_locked", lambda u: False)
    m(repo, "record_login", lambda uid, ok: None)
    m(repo, "get_farmer_profile", lambda uid: {"id": uid, "full_name": "Rahim", "phone": "+8801711111111",
                                               "district_code": "BD2019", "upazila_code": "BD20190009",
                                               "main_crops": ["potato"], "avatar_path": None, "address": None})
    m(repo, "farmer_stats", lambda uid: {"total_products": 3, "active_listings": 2, "out_of_stock": 1,
                                         "total_orders": 4, "pending_orders": 1, "completed_orders": 2,
                                         "earned": Decimal("1200"), "pending_earnings": Decimal("300")})
    m(repo, "list_plantings", lambda uid: [])
    m(repo, "recent_questions", lambda uid, n=5: [])
    m(repo, "list_my_listings", lambda uid: [{"id": 1, "title": "Potato", "category": "vegetable", "unit": "kg",
                                              "price_per_unit": Decimal("30"), "quantity": Decimal("0"),
                                              "listing_type": "available", "status": "active", "image_path": None,
                                              "farming_method": "organic", "created_at": NOW}])
    m(repo, "farmer_order_items", lambda uid, period="all": calls.setdefault("orders", []).append(period) or [])

    def set_item(uid, item_id, status):
        calls["item"] = (uid, item_id, status)
        return "no_stock"
    m(repo, "set_item_farmer_status", set_item)
    m(repo, "archive_listing", lambda uid, lid: calls.setdefault("archived", (uid, lid)) and 1)
    m(repo, "earnings_summary", lambda uid: {"lifetime_sales": Decimal("1200"), "balance": Decimal("1200"),
                                             "reversals": 0, "completed_count": 1})
    m(repo, "earnings_series", lambda uid, span: [{"label": "11-13", "amount": Decimal("1200")}])
    m(repo, "earnings_history", lambda uid, limit=50: [])
    m(repo, "top_products", lambda uid, limit=5: [])
    m(repo, "price_products", lambda: [])
    m(repo, "farmer_tips", lambda limit=30: [])
    m(repo, "list_complaints", lambda uid: [])

    def create_listing(uid, data, path, d, u):
        calls["listing"] = data
        return 5
    m(repo, "create_listing", create_listing)
    from chashibondhu.web.app import mount_website
    app = FastAPI()
    mount_website(app)
    return app, calls


def login(app, phone, password):
    c = TestClient(app)
    tok = re.search(r'name="csrf" value="([^"]+)"', c.get("/login").text).group(1)
    from fake_auth import role_of
    r = c.post("/login", data={"csrf": tok, "phone": phone, "password": password,
                               "as_role": role_of(USERS, phone)}, follow_redirects=False)
    assert r.status_code == 303
    return c


def csrf(c, url="/farmer"):
    return re.search(r'name="csrf" value="([^"]+)"', c.get(url).text).group(1)


@pytest.mark.parametrize("url", ["/farmer", "/farmer/listings/new", "/farmer/listings", "/farmer/orders",
                                 "/farmer/earnings", "/farmer/earnings?span=12m", "/farmer/prices",
                                 "/farmer/tips", "/farmer/complaints", "/farmer/profile"])
def test_farmer_pages_render_with_sidebar(fake, url):
    app, _ = fake
    r = login(app, "01711111111", "secret1").get(url)
    assert r.status_code == 200
    assert 'class="cb-side"' in r.text


def test_overview_shows_real_numbers_and_id(fake):
    app, _ = fake
    html = login(app, "01711111111", "secret1").get("/farmer").text
    assert "CBF-000007" in html and "data-weather" in html and "Open-Meteo" in html


def test_out_of_stock_badge_when_quantity_zero(fake):
    app, _ = fake
    html = login(app, "01711111111", "secret1").get("/farmer/listings").text
    assert "Out of stock" in html


def test_add_product_farming_method_sets_badge(fake):
    app, calls = fake
    c = login(app, "01711111111", "secret1")
    r = c.post("/farmer/listings/new", data={"csrf": csrf(c), "title": "Potato", "category": "eggs",
                                             "price_per_unit": "30", "unit": "packet", "quantity": "10",
                                             "min_order": "1", "farming_method": "organic"},
               follow_redirects=False)
    assert r.status_code == 303
    d = calls["listing"]
    assert d["farming_method"] == "organic" and d["is_organic"] is True
    assert d["category"] == "eggs" and d["unit"] == "packet"


def test_old_form_without_method_still_works(fake):
    app, calls = fake
    c = login(app, "01711111111", "secret1")
    c.post("/farmer/listings/new", data={"csrf": csrf(c), "title": "Rice", "category": "grain",
                                         "price_per_unit": "50", "unit": "kg", "quantity": "10", "min_order": "1"})
    assert calls["listing"]["farming_method"] == "conventional" and calls["listing"]["is_organic"] is False


def test_order_step_error_is_shown(fake):
    app, calls = fake
    c = login(app, "01711111111", "secret1")
    r = c.post("/farmer/orders/items/3", data={"csrf": csrf(c), "status": "accepted"})
    assert calls["item"] == (7, 3, "accepted")
    assert "Not enough stock" in r.text


def test_order_period_filter(fake):
    app, calls = fake
    c = login(app, "01711111111", "secret1")
    c.get("/farmer/orders?period=week")
    c.get("/farmer/orders?period=hack")
    assert calls["orders"] == ["week", "all"]   # unknown period falls back to "all"


def test_delete_is_soft_and_own_only(fake):
    app, calls = fake
    c = login(app, "01711111111", "secret1")
    c.post("/farmer/listings/1/delete", data={"csrf": csrf(c)})
    assert calls["archived"] == (7, 1)


def test_customer_cannot_use_farmer_area_or_ai(fake):
    app, _ = fake
    c = login(app, "01733333333", "buyer12")
    assert c.get("/farmer").status_code == 403
    assert c.get("/assistant").status_code == 403
    tok = csrf(c, "/")
    r = c.post("/app/ai/ask", json={"question": "hello there"}, headers={"x-csrf-token": tok})
    assert r.status_code == 403 and r.json()["detail"] == "not_allowed"
    assert "/assistant" not in c.get("/").text


def test_guest_ai_goes_to_login_and_keeps_question(fake):
    app, _ = fake
    r = TestClient(app).get("/assistant?q=hello", follow_redirects=False)
    assert r.status_code == 303 and "next=/assistant%3Fq%3Dhello" in r.headers["location"]
    c = TestClient(app)
    tok = csrf(c, "/login")
    r = c.post("/app/ai/ask", json={"question": "hello there"}, headers={"x-csrf-token": tok})
    assert r.status_code == 401 and r.json()["detail"] == "login_required"


def test_farming_methods_match_database():
    assert routes_farmer.FARMING_METHODS == ("organic", "conventional", "other")
    sql = "".join(p.read_text(encoding="utf-8") for p in sorted((ROOT / "supabase" / "migrations").glob("00*.sql")))
    for unit in routes_farmer.UNITS:
        assert f"'{unit}'" in sql
    for cat in routes_farmer.CATEGORIES:
        assert f"'{cat}'" in sql
