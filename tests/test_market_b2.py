"""Marketplace Phase B2: buyer matching stages in the customer dashboard + product comparison.

Database tests run only when asked (they create and delete their own rows):
    $env:CB_DB_TESTS="1"; python -m pytest -q tests/test_market_b2.py
"""
from __future__ import annotations

import os
import re
import secrets
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from chashibondhu.web import compare, matching_stages as ms  # noqa: E402

DB = os.environ.get("CB_DB_TESTS") == "1"
db_only = pytest.mark.skipif(not DB, reason="set CB_DB_TESTS=1 to run database tests")
TODAY = date(2026, 11, 14)


# ================================================================ stages (pure)
@pytest.mark.parametrize("status,start,stage", [
    ("buyer_interested", None, "buyer_interested"), ("farmer_offered", None, "farmer_interested"),
    ("agreed", TODAY + timedelta(days=5), "awaiting_harvest"), ("agreed", TODAY, "awaiting_qty"),
    ("qty_confirmed", None, "available"), ("converted", None, "converted"), ("declined", None, "cancelled"),
    ("cancelled", None, "cancelled"), ("expired", None, "expired")])
def test_match_stage(status, start, stage):
    assert ms.match_stage({"status": status, "harvest_from": start}, TODAY) == stage


def test_request_stage():
    assert ms.request_stage({"status": "open", "matches": [], "potential": []}, TODAY) == "created"
    assert ms.request_stage({"status": "open", "matches": [], "potential": [{"id": 1}]}, TODAY) == "potential"
    r = {"status": "open", "potential": [], "matches": [{"status": "declined"}, {"status": "qty_confirmed"},
                                                         {"status": "buyer_interested"}]}
    assert ms.request_stage(r, TODAY) == "available"                       # the furthest live match wins
    assert ms.request_stage({"status": "cancelled", "matches": [{"status": "agreed"}]}, TODAY) == "cancelled"
    assert ms.request_stage({"status": "expired", "matches": []}, TODAY) == "expired"
    assert ms.request_stage({"status": "open", "matches": [{"status": "declined"}], "potential": []}, TODAY) == "cancelled"
    items = ms.decorate([{"status": "open", "potential": [1], "matches": [{"status": "farmer_offered"}]}], TODAY)
    assert items[0]["stage"] == "farmer_interested" and items[0]["step"] == 2
    assert items[0]["matches"][0]["stage"] == "farmer_interested"
    assert {s for s, _, _ in ms.STEPS} == set(ms.STAGE_STEP.values())       # every step is reachable
    assert set(ms.STAGE_STEP) <= set(ms.LABELS)


# ================================================================ comparison (pure)
def test_per_base_units():
    assert compare.per_base("kg", Decimal("40")) == ("kg", Decimal("40.00"))
    assert compare.per_base("gram", Decimal("50")) == ("kg", Decimal("50000.00"))
    assert compare.per_base("maund", Decimal("1400")) == ("kg", Decimal("37.51"))
    assert compare.per_base("dozen", Decimal("120")) == ("piece", Decimal("10.00"))
    assert compare.per_base("packet", Decimal("50")) == (None, None)


def test_groups_only_compatible_units():
    rows = [{"id": 1, "unit": "kg", "price_now": Decimal("40")}, {"id": 2, "unit": "maund", "price_now": Decimal("1400")},
            {"id": 3, "unit": "dozen", "price_now": Decimal("120")}, {"id": 4, "unit": "packet", "price_now": Decimal("50")}]
    groups, alone = compare.groups(rows)
    kg = next(g for g in groups if g["base"] == "kg")
    assert [r["id"] for r in kg["rows"]] == [2, 1] and kg["rows"][0]["cheapest"] and not kg["rows"][1]["cheapest"]
    piece = next(g for g in groups if g["base"] == "piece")
    assert "cheapest" not in piece["rows"][0]                              # alone in its group: no "lowest" badge
    assert [r["id"] for r in alone] == [4]


def test_clean_ids():
    assert compare.clean_ids(["3", 3, "x", -1, 5, 6, 7, 8]) == [3, 5, 6, 7]


# ================================================================ database
@pytest.fixture
def world():
    from chashibondhu.web.db import execute, fetch_one
    tag = secrets.token_hex(4)
    ph = lambda: "+88017" + f"{secrets.randbelow(10**8):08d}"  # noqa: E731
    ids = {"farmer": fetch_one("INSERT INTO users (role, full_name, phone, password_hash) VALUES "
                               "('farmer', 'Test Farmer', %s, 'x') RETURNING id", (ph(),))["id"],
           "buyer": fetch_one("INSERT INTO users (role, full_name, phone, email, password_hash) VALUES "
                              "('customer', 'Test Buyer', %s, %s, 'x') RETURNING id",
                              (ph(), f"b{tag}@test.example.com"))["id"]}
    yield ids
    execute("DELETE FROM orders WHERE customer_id = %s", (ids["buyer"],))
    execute("DELETE FROM listings WHERE farmer_id = %s", (ids["farmer"],))
    execute("DELETE FROM users WHERE id = ANY(%s)", ([ids["farmer"], ids["buyer"]],))


@db_only
def test_compare_rows_only_active(world):
    from chashibondhu.web import repo_market_b2 as b2
    from chashibondhu.web.db import fetch_one
    mk = lambda title, status: fetch_one(  # noqa: E731
        "INSERT INTO listings (farmer_id, title, unit, price_per_unit, quantity, status) VALUES (%s, %s, 'kg', 40, 5, %s) "
        "RETURNING id", (world["farmer"], title, status))["id"]
    a, h = mk("Test Alu", "active"), mk("Test Hidden", "hidden")
    rows = b2.compare_rows([a, h, 999999999])
    assert [r["id"] for r in rows] == [a] and rows[0]["review_n"] == 0 and rows[0]["price_now"] == 40


@db_only
def test_request_summary_counts(world):
    from chashibondhu.web import repo_market_b2 as b2
    from chashibondhu.web.db import fetch_one
    d = date.today()
    f = fetch_one("INSERT INTO harvest_forecasts (farmer_id, product_name, expected_qty, unit, harvest_from, harvest_to) "
                  "VALUES (%s, 'Test Alu', 500, 'kg', %s, %s) RETURNING id", (world["farmer"], d + timedelta(10),
                                                                           d + timedelta(20)))["id"]
    reqs = [fetch_one("INSERT INTO buyer_demand_requests (buyer_id, product_name, quantity, unit, needed_from, needed_to) "
                      "VALUES (%s, %s, 50, 'kg', %s, %s) RETURNING id",
                      (world["buyer"], f"Test Alu {i}", d + timedelta(10), d + timedelta(20)))["id"] for i in range(3)]
    for r, st in zip(reqs, ("farmer_offered", "agreed", "qty_confirmed")):
        fetch_one("INSERT INTO harvest_matches (forecast_id, request_id, match_qty, status) VALUES (%s, %s, 10, %s) "
                  "RETURNING id", (f, r, st))
    s = b2.request_summary(world["buyer"])
    assert (s["open_requests"], s["need_answer"], s["waiting_harvest"], s["can_order"]) == (3, 1, 1, 1)
    assert b2.request_summary(world["farmer"])["open_requests"] == 0


# ================================================================ routes (offline, fake data)
ROW = {"id": 1, "title": "Diamond Alu", "crop_id": "potato", "category": "vegetable", "unit": "kg",
       "price_per_unit": Decimal("40"), "discount_price": None, "price_now": Decimal("40"), "quantity": Decimal("100"),
       "min_order": Decimal("1"), "listing_type": "available", "available_from": None, "harvest_date": None,
       "image_path": None, "is_organic": False, "farming_method": "conventional", "district_code": None,
       "upazila_code": None, "created_at": None, "farmer_name": "Rahim", "farmer_id": 7, "description": None,
       "extra_info": None, "status": "active", "review_avg": None, "review_n": 0}


@pytest.fixture
def client(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from chashibondhu.web import repo, repo_market_b2 as b2
    from chashibondhu.web.passwords import hash_password
    from fake_auth import install
    users = {"+8801733333333": {"id": 9, "role": "customer", "full_name": "Buyer", "status": "active",
                                "password_hash": hash_password("buyer12")}}
    monkeypatch.setenv("WEB_SESSION_SECRET", "x" * 40)
    m = monkeypatch.setattr
    m(repo, "get_user_by_phone", lambda p: users.get(p))
    m(repo, "is_locked", lambda u: False)
    m(repo, "record_login", lambda uid, ok: None)
    install(monkeypatch)
    rows = {i: {**ROW, "id": i, "title": f"Item {i}"} for i in range(1, 7)}
    rows[2].update(unit="maund", price_now=Decimal("1400"), price_per_unit=Decimal("1400"))
    rows[3].update(unit="packet", price_now=Decimal("50"))
    m(repo, "get_market_listing", lambda lid: rows.get(lid))
    m(repo, "related_listings", lambda item, limit=6: [])
    m(b2, "compare_rows", lambda ids: [dict(rows[i]) for i in ids if i in rows])
    today = date.today()
    m(repo, "expire_stale", lambda: None)
    m(repo, "list_requests", lambda uid: [{"id": 5, "product_name": "Alu", "variety": None, "quantity": Decimal("50"),
                                           "unit": "kg", "status": "open", "needed_from": today, "needed_to": today,
                                           "district_code": None}])
    m(repo, "potential_forecasts", lambda uid, rid: [])
    m(repo, "get_customer", lambda uid: {"id": uid, "full_name": "Buyer", "district_code": None, "upazila_code": None,
                                         "avatar_path": None})
    m(repo, "customer_stats", lambda uid: {})
    m(repo, "recent_purchases", lambda uid: [])
    m(repo, "unread_count", lambda uid: 0)
    m(repo, "cart_count", lambda uid: 0)
    m(repo, "request_matches", lambda uid, rid: [
        {"id": 8, "status": "qty_confirmed", "match_qty": Decimal("20"), "confirmed_qty": Decimal("18"),
         "farmer_name": "Rahim", "harvest_from": today, "harvest_to": today, "farmer_district": None,
         "farmer_phone": "+8801711111111", "order_number": None, "listing_id": 1}])
    from chashibondhu.web.app import mount_website
    app = FastAPI()
    mount_website(app)
    return TestClient(app)


def _tok(c, url):
    return re.search(r'name="csrf" value="([^"]+)"', c.get(url).text).group(1)


def test_compare_flow(client):
    tok = _tok(client, "/market/1")
    assert "Add to compare" in client.get("/market/1").text
    for i in (1, 2, 3, 4, 5):
        client.post("/compare/toggle", data={"csrf": tok, "listing_id": i})
    page = client.get("/compare").text
    assert "Item 5" not in page                                                      # max 4
    assert "Item 1" in page and "Item 2" in page and "Lowest price" in page          # maund 37.51/kg < 40/kg
    assert "Cannot be compared" in page and "Item 3" in page
    assert "৳37.51" in page or "37.51" in page
    assert "Remove from compare" in client.get("/market/1").text
    client.post("/compare/toggle", data={"csrf": tok, "listing_id": 1, "go": "1"})
    assert "Item 1" not in client.get("/compare").text
    client.post("/compare/clear", data={"csrf": tok})
    assert "Nothing to compare yet" in client.get("/compare").text
    assert client.post("/compare/toggle", data={"csrf": "bad", "listing_id": 1}).status_code == 400


def test_requests_page_in_customer_dashboard(client):
    tok = _tok(client, "/login")
    assert client.post("/login", data={"csrf": tok, "phone": "+8801733333333", "password": "buyer12",
                                       "as_role": "customer"}, follow_redirects=False).status_code == 303
    page = client.get("/requests").text
    assert "Demand requests" in page or "requests" in page
    assert 'aria-current="step"' in page and "Available for order" in page
    assert 'href="/market/1"' in page and "Open the product and order" in page
    assert "/customer/saved" in page                                                 # customer sidebar layout
    dash = client.get("/customer").text
    assert "Demand requests &amp; matches" in dash or "Demand requests & matches" in dash
