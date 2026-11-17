"""Marketplace + customer Phase A (no database: fakes). The SQL (search, checkout transaction, stock,
notification triggers) was tested on PostgreSQL 16 with migrations 001-004.
Run: python -m pytest -q tests/test_web_market.py
"""
from __future__ import annotations

import re
import sys
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))   # tests/fake_auth.py
pytest.importorskip("fastapi.testclient")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from chashibondhu.web import repo, routes_market, search  # noqa: E402
from chashibondhu.web.passwords import hash_password  # noqa: E402

USERS = {"+8801733333333": {"id": 9, "role": "customer", "full_name": "Buyer", "status": "active",
                            "password_hash": hash_password("buyer12")},
         "+8801711111111": {"id": 7, "role": "farmer", "full_name": "Rahim", "status": "active",
                            "password_hash": hash_password("secret1")}}
ROW = {"id": 1, "title": "Diamond Alu", "crop_id": "potato", "category": "vegetable", "unit": "kg",
       "price_per_unit": Decimal("40"), "discount_price": Decimal("35"), "price_now": Decimal("35"),
       "quantity": Decimal("100"), "min_order": Decimal("1"), "listing_type": "available", "available_from": None,
       "harvest_date": None, "image_path": None, "is_organic": True, "farming_method": "organic",
       "district_code": "BD2626", "upazila_code": None, "created_at": "2026-11-13", "farmer_name": "Rahim",
       "farmer_id": 7, "description": None, "extra_info": None, "status": "active"}


@pytest.mark.parametrize("q", ["Potato", "alo", "alu", "aloo", "আলু", "potata", "Alu", "আলুর"])
def test_potato_spellings(q):
    assert search.parse(q)["groups"] == ["potato"]


def test_extra_words_rank_only():
    assert search.parse("diamond alu") == {"groups": ["potato"], "rest": ["diamond"], "text": "diamond alu"}
    assert search.parse("big alu")["rest"] == ["big"] and search.parse("lal alu")["rest"] == ["lal"]


def test_latin_alias_must_start_a_word():
    assert all(p.startswith(r"\m") for p in search.alias_patterns("potato") if p[2:3].isascii() and p[2:3].isalpha())


def test_filters_are_cleaned():
    f = routes_market.market_filters({"q": "  alu  ", "section": "hack", "category": "x", "district": "BD9999",
                                      "min": "৫০", "max": "10", "avail": "now", "organic": "1", "sort": "zzz"},
                                     ["BD2626"])
    assert f["q"] == "alu" and f["section"] == "" and f["category"] == "" and f["district"] == ""
    assert (f["min"], f["max"]) == (Decimal("10"), Decimal("50"))      # swapped when reversed
    assert f["avail"] == "now" and f["organic"] is True and f["sort"] == "best"


def test_delivery_fee_from_env(monkeypatch):
    monkeypatch.setenv("CB_DELIVERY_FEE", "60")
    assert routes_market.delivery_fee() == Decimal("60")
    monkeypatch.setenv("CB_DELIVERY_FEE", "-5")
    assert routes_market.delivery_fee() == Decimal("0")
    monkeypatch.setenv("CB_DELIVERY_FEE", "abc")
    assert routes_market.delivery_fee() == Decimal("0")


@pytest.fixture()
def app(monkeypatch):
    calls: dict = {}
    m = monkeypatch.setattr
    m(repo, "get_user_by_phone", lambda p: USERS.get(p))
    from fake_auth import install
    install(monkeypatch)
    m(repo, "is_locked", lambda u: False)
    m(repo, "record_login", lambda uid, ok: None)
    m(repo, "market_districts", lambda: ["BD2626"])
    m(repo, "market_search", lambda f, known, page=1: calls.setdefault("search", f) and ([ROW], 1))
    m(repo, "suggest", lambda q, known: [{"kind": "product", "q": "potato", "bn": "আলু", "en": "Potato", "count": 2}])
    m(repo, "get_market_listing", lambda lid: ROW if lid == 1 else None)
    m(repo, "related_listings", lambda item, limit=6: [])
    m(repo, "cart", lambda uid: [])
    m(repo, "get_customer", lambda uid: {"full_name": "Buyer", "phone": "+8801733333333", "address": "Dhaka"})

    def place(uid, addr, phone, note, fee):
        calls.setdefault("orders", []).append((uid, addr, phone, fee))
        return {"ok": True, "order_number": "CB261113-00001"}
    m(repo, "place_order", place)
    a = FastAPI()
    from chashibondhu.web.app import mount_website
    mount_website(a)
    a.calls = calls
    return a


def login(app, phone, pw):
    c = TestClient(app)
    tok = re.search(r'name="csrf" value="([^"]+)"', c.get("/login").text).group(1)
    from fake_auth import role_of
    assert c.post("/login", data={"csrf": tok, "phone": phone, "password": pw, "as_role": role_of(USERS, phone)},
                  follow_redirects=False).status_code == 303
    return c, tok


def test_public_market_and_product(app):
    g = TestClient(app)
    r = g.get("/market?q=alu&organic=1")
    assert r.status_code == 200 and "Diamond Alu" in r.text and app.calls["search"]["organic"] is True
    p = g.get("/market/1")
    assert p.status_code == 200 and "/login?as=customer&next=/market/1" in p.text
    assert g.get("/market/2", headers={"accept": "text/html"}).status_code == 404
    assert g.get("/market/suggest?q=p").json()["items"][0]["count"] == 2


def test_cart_and_checkout_customers_only(app):
    f, tok = login(app, "01711111111", "secret1")
    assert f.get("/cart").status_code == 403 and f.get("/checkout").status_code == 403
    assert TestClient(app).get("/cart", follow_redirects=False).status_code == 303


def test_checkout_token_blocks_double_order(app, monkeypatch):
    monkeypatch.setattr(repo, "cart", lambda uid: [{"id": 1, "title": "Diamond Alu", "want": Decimal("2"),
                                                     "price_now": Decimal("35"), "price_per_unit": Decimal("40"),
                                                     "discount_price": Decimal("35"), "stock": Decimal("100"),
                                                     "min_order": Decimal("1"), "status": "active",
                                                     "listing_type": "available", "farmer_status": "active",
                                                     "farmer_id": 7, "farmer_name": "Rahim", "unit": "kg",
                                                     "image_path": None}])
    c, tok = login(app, "01733333333", "buyer12")
    page = c.get("/checkout").text
    tok = re.search(r'name="csrf" value="([^"]+)"', page).group(1)
    token = re.search(r'name="token" value="([^"]+)"', page).group(1)
    form = {"csrf": tok, "token": token, "full_name": "Buyer", "phone": "01733333333",
            "delivery_address": "Lotakhole, Dohar, Dhaka"}
    r1 = c.post("/checkout", data=form, follow_redirects=False)
    assert r1.status_code == 303, r1.text[:300]
    r2 = c.post("/checkout", data=form, follow_redirects=False)
    assert r1.headers["location"] == "/customer/orders/CB261113-00001"
    assert r2.headers["location"] == "/customer/orders" and len(app.calls["orders"]) == 1
    assert app.calls["orders"][0][2] == "+8801733333333"


def test_online_payment_not_offered_or_accepted(app, monkeypatch):
    monkeypatch.setattr(repo, "cart", lambda uid: [{"id": 1, "title": "x", "want": Decimal("1"), "price_now": Decimal("1"),
                                                     "price_per_unit": Decimal("1"), "discount_price": None,
                                                     "stock": Decimal("5"), "min_order": Decimal("1"), "status": "active",
                                                     "listing_type": "available", "farmer_status": "active",
                                                     "farmer_id": 7, "farmer_name": "R", "unit": "kg", "image_path": None}])
    c, tok = login(app, "01733333333", "buyer12")
    page = c.get("/checkout").text
    assert 'value="bkash"' not in page and 'value="cod"' in page
    tok = re.search(r'name="csrf" value="([^"]+)"', page).group(1)
    token = re.search(r'name="token" value="([^"]+)"', page).group(1)
    c.post("/checkout", data={"csrf": tok, "token": token, "phone": "01733333333", "delivery_address": "Dhaka city",
                              "payment": "bkash"})
    assert "orders" not in app.calls


def test_customer_signup_validation(app, monkeypatch):
    created = {}
    monkeypatch.setattr(repo, "create_customer", lambda *a: created.setdefault("a", a) and 21)
    c = TestClient(app)
    tok = re.search(r'name="csrf" value="([^"]+)"', c.get("/register/customer").text).group(1)
    bad = c.post("/register/customer", data={"csrf": tok, "full_name": "A", "phone": "1", "password": "1", "password2": "2"})
    assert bad.status_code == 400 and "a" not in created
    no_email = c.post("/register/customer", data={"csrf": tok, "full_name": "New Buyer", "phone": "01755555555",
                                                  "password": "Shapla#26", "password2": "Shapla#26"})
    assert no_email.status_code == 400 and "Email address is required" in no_email.text and "a" not in created
    ok = c.post("/register/customer", data={"csrf": tok, "full_name": "New Buyer", "email": " New@Mail.com ",
                                            "phone": "০১৭৫৫৫৫৫৫৫৫", "password": "Shapla#26", "password2": "Shapla#26"},
                follow_redirects=False)
    # create_customer(name, email, phone, password_hash, district, upazila, address)
    assert ok.headers["location"] == "/market" and created["a"][1] == "new@mail.com"
    assert created["a"][2] == "+8801755555555" and created["a"][3].startswith("scrypt$")


def test_migration_matches_code():
    sql = (ROOT / "supabase" / "migrations" / "004_marketplace.sql").read_text(encoding="utf-8")
    assert "'tools_equipment'" in sql and "pg_trgm" in sql and "uq_notifications_dedupe" in sql
