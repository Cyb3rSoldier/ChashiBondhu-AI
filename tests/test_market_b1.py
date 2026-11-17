"""Marketplace Phase B1: saved items, favourite farmers, alerts, verified reviews.

Database tests run only when asked (they create and delete their own rows):
    $env:CB_DB_TESTS="1"; python -m pytest -q tests/test_market_b1.py
Needs migration 006.
"""
from __future__ import annotations

import os
import re
import secrets
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

DB = os.environ.get("CB_DB_TESTS") == "1"
db_only = pytest.mark.skipif(not DB, reason="set CB_DB_TESTS=1 to run database tests")


def test_migration_file_has_the_rules():
    sql = (ROOT / "supabase" / "migrations" / "006_marketplace_b1.sql").read_text(encoding="utf-8")
    for must in ("saved_items", "favourite_farmers", "product_alerts", "reviews_require_purchase",
                 "listings_notify_watchers", "o.status = 'delivered'", "ON CONFLICT (user_id, dedupe_key)"):
        assert must in sql


# ================================================================ database
@pytest.fixture
def world():
    """One farmer, two customers, one listing; everything deleted afterwards."""
    from chashibondhu.web.db import execute, fetch_one
    tag = secrets.token_hex(4)
    ph = lambda: "+88017" + f"{secrets.randbelow(10**8):08d}"  # noqa: E731
    ids: dict = {}
    ids["farmer"] = fetch_one("INSERT INTO users (role, full_name, phone, password_hash) VALUES "
                              "('farmer', 'Test Farmer', %s, 'x') RETURNING id", (ph(),))["id"]
    for k in ("c1", "c2"):
        ids[k] = fetch_one("INSERT INTO users (role, full_name, phone, email, password_hash) VALUES "
                           "('customer', 'Test Buyer', %s, %s, 'x') RETURNING id",
                           (ph(), f"{k}{tag}@test.example.com"))["id"]
    ids["listing"] = fetch_one("INSERT INTO listings (farmer_id, title, unit, price_per_unit, quantity, min_order) "
                               "VALUES (%s, 'Test Alu', 'kg', 40, 0, 1) RETURNING id", (ids["farmer"],))["id"]
    yield ids
    users = [ids["farmer"], ids["c1"], ids["c2"]]
    execute("DELETE FROM orders WHERE customer_id = ANY(%s)", (users,))
    execute("DELETE FROM listings WHERE farmer_id = %s", (ids["farmer"],))
    execute("DELETE FROM farmer_profiles WHERE user_id = ANY(%s)", (users,))
    execute("DELETE FROM users WHERE id = ANY(%s)", (users,))


def notes(uid: int, prefix: str) -> list[dict]:
    from chashibondhu.web.db import fetch_all
    return fetch_all("SELECT * FROM notifications WHERE user_id = %s AND dedupe_key LIKE %s", (uid, prefix + "%"))


def deliver(customer: int, listing: int, status: str = "delivered") -> None:
    from chashibondhu.web.db import fetch_one, execute
    o = fetch_one("INSERT INTO orders (customer_id, subtotal, total, delivery_address, phone, status) "
                  "VALUES (%s, 40, 40, 'Dhaka', '+8801700000000', %s) RETURNING id", (customer, status))
    farmer = fetch_one("SELECT farmer_id FROM listings WHERE id = %s", (listing,))["farmer_id"]
    execute("INSERT INTO order_items (order_id, listing_id, farmer_id, title, unit, unit_price, quantity, line_total, "
            "farmer_status) VALUES (%s, %s, %s, 'Test Alu', 'kg', 40, 1, 40, 'handed_over')", (o["id"], listing, farmer))


@db_only
def test_review_needs_delivered_purchase(world):
    from chashibondhu.web import repo_market_b1 as b1
    from chashibondhu.web.db import execute
    c, lid = world["c1"], world["listing"]
    assert b1.save_review(c, lid, 5, "great") == "not_verified"
    with pytest.raises(Exception):                       # the database refuses too, not only the app
        execute("INSERT INTO reviews (listing_id, customer_id, rating) VALUES (%s, %s, 4)", (lid, c))
    deliver(c, lid, status="shipped")
    assert b1.save_review(c, lid, 5, None) == "not_verified"
    deliver(c, lid)
    assert b1.save_review(c, lid, 5, "great") == "ok"
    assert b1.save_review(c, lid, 3, "ok now") == "ok"   # edit, still one review
    x = b1.product_extras(c, lid, world["farmer"])
    assert x["review_n"] == 1 and float(x["review_avg"]) == 3.0 and x["can_review"] and x["my_review"]["rating"] == 3
    assert x["reviews"][0]["name"] == "Test"             # first name only
    execute("UPDATE reviews SET status = 'hidden' WHERE listing_id = %s", (lid,))   # admin hides (trigger allows)
    assert b1.product_extras(None, lid, world["farmer"])["review_n"] == 0
    assert b1.delete_review(c, lid) == 1


@db_only
def test_restock_alert_once_per_day(world):
    from chashibondhu.web import repo_market_b1 as b1
    from chashibondhu.web.db import execute
    lid = world["listing"]
    assert b1.set_alert(world["c1"], lid, True, False)
    execute("UPDATE listings SET quantity = 20 WHERE id = %s", (lid,))           # back in stock
    execute("UPDATE listings SET quantity = 0 WHERE id = %s", (lid,))
    execute("UPDATE listings SET quantity = 15 WHERE id = %s", (lid,))           # again the same day
    assert len(notes(world["c1"], "restock:")) == 1
    assert notes(world["c2"], "restock:") == []                                  # c2 never asked
    execute("UPDATE listings SET quantity = 30 WHERE id = %s", (lid,))           # just more stock: no alert
    assert len(notes(world["c1"], "restock:")) == 1


@db_only
def test_price_drop_alert(world):
    from chashibondhu.web import repo_market_b1 as b1
    from chashibondhu.web.db import execute
    lid = world["listing"]
    b1.set_alert(world["c1"], lid, False, True)
    execute("UPDATE listings SET quantity = 10 WHERE id = %s", (lid,))
    execute("UPDATE listings SET price_per_unit = 50 WHERE id = %s", (lid,))     # up: nothing
    assert notes(world["c1"], "price:") == []
    execute("UPDATE listings SET discount_price = 35 WHERE id = %s", (lid,))     # 50 -> 35
    n = notes(world["c1"], "price:")
    assert len(n) == 1 and "৳50" in n[0]["body"] and "৳35" in n[0]["body"]
    assert notes(world["c1"], "restock:") == []                                  # restock was not chosen
    b1.set_alert(world["c1"], lid, False, False)                                 # turn off
    execute("UPDATE listings SET discount_price = 30 WHERE id = %s", (lid,))
    assert len(notes(world["c1"], "price:")) == 1


@db_only
def test_follow_farmer_gets_new_product_note(world):
    from chashibondhu.web import repo_market_b1 as b1
    from chashibondhu.web.db import fetch_one
    assert b1.toggle_follow(world["c1"], world["farmer"]) is True
    assert b1.toggle_follow(world["c1"], world["c1"]) is None                    # not a farmer
    new = fetch_one("INSERT INTO listings (farmer_id, title, unit, price_per_unit, quantity) "
                    "VALUES (%s, 'Test Begun', 'kg', 30, 5) RETURNING id", (world["farmer"],))["id"]
    assert [x["link"] for x in notes(world["c1"], "newlisting:")] == [f"/market/{new}"]
    assert notes(world["c2"], "newlisting:") == []
    assert b1.saved_page(world["c1"])["farmers"][0]["active_listings"] == 2
    assert b1.toggle_follow(world["c1"], world["farmer"]) is False


@db_only
def test_saved_and_save_for_later(world):
    from chashibondhu.web import repo_market_b1 as b1
    from chashibondhu.web.db import execute, fetch_one
    c, lid = world["c1"], world["listing"]
    assert b1.toggle_saved(c, lid) is True
    assert b1.product_extras(c, lid, world["farmer"])["saved"] is True
    assert b1.toggle_saved(c, lid) is False
    assert b1.toggle_saved(c, 0) is None
    execute("UPDATE listings SET quantity = 5 WHERE id = %s", (lid,))
    execute("INSERT INTO cart_items (customer_id, listing_id, quantity) VALUES (%s, %s, 1)", (c, lid))
    assert b1.save_for_later(c, lid) is True
    assert fetch_one("SELECT 1 AS x FROM cart_items WHERE customer_id = %s", (c,)) is None
    assert [i["id"] for i in b1.saved_page(c)["items"]] == [lid]
    execute("UPDATE listings SET status = 'hidden' WHERE id = %s", (lid,))
    assert b1.saved_page(c)["items"][0]["on_sale"] is False                     # still listed, marked
    assert b1.toggle_saved(c, lid) is False                                      # can remove a hidden one


# ================================================================ routes (offline, fake data)
@pytest.fixture
def client(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from chashibondhu.web import repo, repo_market_b1 as b1
    from chashibondhu.web.passwords import hash_password
    from fake_auth import install
    users = {"+8801733333333": {"id": 9, "role": "customer", "full_name": "Buyer", "status": "active",
                                "password_hash": hash_password("buyer12")},
             "+8801711111111": {"id": 7, "role": "farmer", "full_name": "Rahim", "status": "active",
                                "password_hash": hash_password("secret1")}}
    monkeypatch.setenv("WEB_SESSION_SECRET", "x" * 40)
    monkeypatch.setattr(repo, "get_user_by_phone", lambda p: users.get(p))
    monkeypatch.setattr(repo, "is_locked", lambda u: False)
    monkeypatch.setattr(repo, "record_login", lambda uid, ok: None)
    install(monkeypatch)
    from decimal import Decimal
    row = {"id": 1, "title": "Diamond Alu", "crop_id": "potato", "category": "vegetable", "unit": "kg",
           "price_per_unit": Decimal("40"), "discount_price": None, "price_now": Decimal("40"),
           "quantity": Decimal("100"), "min_order": Decimal("1"), "listing_type": "available", "available_from": None,
           "harvest_date": None, "image_path": None, "is_organic": False, "farming_method": "conventional",
           "district_code": None, "upazila_code": None, "created_at": None, "farmer_name": "Rahim", "farmer_id": 7,
           "description": None, "extra_info": None, "status": "active"}
    monkeypatch.setattr(repo, "get_market_listing", lambda lid: row if lid == 1 else None)
    monkeypatch.setattr(repo, "related_listings", lambda item, limit=6: [])
    calls: list = []
    monkeypatch.setattr(b1, "toggle_saved", lambda c, l: calls.append(("save", c, l)) or True)
    monkeypatch.setattr(b1, "set_alert", lambda c, l, r, p: calls.append(("alert", c, l, r, p)) or True)
    monkeypatch.setattr(b1, "save_review", lambda c, l, r, t: calls.append(("review", c, l, r, t)) or "not_verified")
    monkeypatch.setattr(b1, "saved_page", lambda c: {"items": [], "farmers": [], "alerts": []})
    from chashibondhu.web.app import mount_website
    app = FastAPI()
    mount_website(app)
    c = TestClient(app)
    c.calls = calls
    return c


def _login(c, phone, pw, role):
    tok = re.search(r'name="csrf" value="([^"]+)"', c.get("/login").text).group(1)
    assert c.post("/login", data={"csrf": tok, "phone": phone, "password": pw, "as_role": role},
                  follow_redirects=False).status_code == 303
    return tok


def _csrf(c, url="/market/1"):
    return re.search(r'name="csrf" value="([^"]+)"', c.get(url).text).group(1)


def test_product_page_by_role(client):
    guest = client.get("/market/1").text
    assert "/market/1/save" not in guest and "No reviews yet" in guest
    _login(client, "+8801733333333", "buyer12", "customer")
    page = client.get("/market/1").text
    assert "/market/1/save" in page and "/farmers/7/follow" in page and "/market/1/alert" in page
    assert "/market/1/review" not in page                       # no delivered purchase -> no form


def test_actions_need_a_customer(client):
    r = client.post("/market/1/save", data={"csrf": _csrf(client, "/login")}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/login")       # guest -> login
    _login(client, "+8801711111111", "secret1", "farmer")
    # role is checked before CSRF, so any token gives 403 for a farmer
    assert client.post("/market/1/save", data={"csrf": "x"}, follow_redirects=False).status_code == 403
    assert client.get("/customer/saved", follow_redirects=False).status_code == 403
    assert client.calls == []


def test_customer_actions(client):
    _login(client, "+8801733333333", "buyer12", "customer")
    tok = _csrf(client, "/customer/saved")
    assert client.post("/market/1/save", data={"csrf": tok}, follow_redirects=False).status_code == 303
    client.post("/market/1/alert", data={"csrf": tok, "restock": "1"})
    client.post("/market/1/review", data={"csrf": tok, "rating": "9"})               # bad stars: not saved
    r = client.post("/market/1/review", data={"csrf": tok, "rating": "4", "comment": "  very   good "},
                    follow_redirects=False)
    assert r.headers["location"] == "/market/1#reviews"
    assert client.calls == [("save", 9, 1), ("alert", 9, 1, True, False), ("review", 9, 1, 4, "very good")]
    assert client.post("/market/1/save", data={"csrf": "wrong"}).status_code == 400   # CSRF


def test_saved_and_farmer_pages_render(client, monkeypatch):
    from decimal import Decimal
    from chashibondhu.web import repo_market_b1 as b1
    item = {"id": 1, "title": "Diamond Alu", "unit": "kg", "image_path": None, "listing_type": "available",
            "quantity": Decimal("0"), "min_order": Decimal("1"), "price_now": Decimal("35"),
            "price_per_unit": Decimal("40"), "discount_price": Decimal("35"), "on_sale": True, "farmer_name": "Rahim"}
    monkeypatch.setattr(b1, "saved_page", lambda c: {
        "items": [item, {**item, "id": 2, "title": "Old Begun", "on_sale": False}],
        "farmers": [{"id": 7, "full_name": "Rahim", "district_code": "BD2626", "upazila_code": None,
                     "avatar_path": None, "active_listings": 3}],
        "alerts": [{"listing_id": 1, "on_restock": True, "on_price_drop": True, "title": "Diamond Alu"}]})
    monkeypatch.setattr(b1, "farmer_listings", lambda fid: (
        ({"id": 7, "full_name": "Rahim", "district_code": None, "upazila_code": None, "avatar_path": None},
         [{"id": 1, "title": "Diamond Alu", "category": "vegetable", "unit": "kg", "price_now": Decimal("35"),
           "price_per_unit": Decimal("40"), "discount_price": Decimal("35"), "quantity": Decimal("5"),
           "listing_type": "available", "image_path": None, "farming_method": "organic", "district_code": None,
           "farmer_name": "Rahim", "available_from": None}]) if fid == 7 else (None, [])))
    guest = client.get("/market/farmer/7")
    assert guest.status_code == 200 and "Diamond Alu" in guest.text and "Log in to follow" in guest.text
    assert client.get("/market/farmer/99").status_code == 404
    _login(client, "+8801733333333", "buyer12", "customer")
    page = client.get("/customer/saved").text
    assert "Out of stock" in page and "Not for sale now" in page and "/farmers/7/follow" in page
    assert "Back in stock" in page and "Price drop" in page
    assert "/farmers/7/follow" in client.get("/market/farmer/7").text


def test_review_form_for_verified_buyer(client, monkeypatch):
    from datetime import datetime
    from decimal import Decimal
    from chashibondhu.web import repo_market_b1 as b1
    monkeypatch.setattr(b1, "product_extras", lambda cid, lid, fid: {
        "review_n": 1, "review_avg": Decimal("4.0"), "saved": True, "following": True,
        "alert": {"restock": True, "price_drop": False}, "can_review": bool(cid),
        "my_review": {"rating": 4, "comment": "good", "status": "visible"} if cid else None,
        "reviews": [{"rating": 4, "comment": "good", "name": "Karim", "created_at": datetime.now(),
                     "updated_at": datetime.now()}]})
    guest = client.get("/market/1").text
    assert "Karim" in guest and "Verified buyer" in guest and "/market/1/review" not in guest
    _login(client, "+8801733333333", "buyer12", "customer")
    page = client.get("/market/1").text
    assert "/market/1/review" in page and "Update review" in page and 'value="4" required checked' in page
    assert "fa-solid fa-heart" in page and "user-check" in page
