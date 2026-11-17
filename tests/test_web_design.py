"""Tests for the 11 Nov design update: green header, photo hero, market search, login roles.

No database needed: repo functions are replaced with fakes.
Run: python -m pytest -q tests/test_web_design.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

pytest.importorskip("fastapi.testclient")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from chashibondhu.web import repo  # noqa: E402
from chashibondhu.web.deps import crop_ids  # noqa: E402

LISTINGS = [
    {"id": 1, "title": "Test potato", "crop_id": "potato", "unit": "kg", "price_per_unit": 30, "quantity": 100,
     "listing_type": "available", "available_from": None, "image_path": None, "is_organic": False,
     "district_code": "BD2019", "farmer_name": "Farmer A"},
    {"id": 2, "title": "Test tomato", "crop_id": "tomato", "unit": "kg", "price_per_unit": 60, "quantity": 50,
     "listing_type": "expected", "available_from": "2026-12-20", "image_path": None, "is_organic": True,
     "district_code": "BD2085", "farmer_name": "Farmer B"},
]


@pytest.fixture()
def client(monkeypatch):
    calls: dict = {}

    def fake_public(limit=8):
        calls["public"] = limit
        return LISTINGS

    def fake_market(q, crop_id, listing_type, limit=24):
        calls["market"] = (q, crop_id, listing_type, limit)
        return [x for x in LISTINGS if (not crop_id or x["crop_id"] == crop_id)
                and (not listing_type or x["listing_type"] == listing_type)]

    monkeypatch.setattr(repo, "public_listings", fake_public)
    monkeypatch.setattr(repo, "market_listings", fake_market)
    monkeypatch.setattr(repo, "public_counts", lambda: {"farmers": 5, "listings": 2, "districts": 2})
    monkeypatch.setattr(repo, "get_user_by_phone", lambda phone: None)
    from chashibondhu.web.app import mount_website
    app = FastAPI()
    mount_website(app)
    c = TestClient(app)
    c.calls = calls
    return c


def test_home_has_new_design_and_real_listings(client):
    r = client.get("/")
    assert r.status_code == 200
    html = r.text
    for part in ("cb-hero2", 'id="market"', "/login?as=customer", "/login?as=farmer",
                 "/login?as=admin", "/register", 'id="contact"', "/assistant?photo=1"):
        assert part in html, part
    assert html.count('class="cb-card"') == 2
    assert client.calls["public"] == 12
    assert "market" not in client.calls


def test_home_filters_use_market_search(client):
    crop = "tomato" if "tomato" in crop_ids() else ""
    r = client.get(f"/?q=test&crop={crop}&type=expected")
    assert r.status_code == 200
    q, crop_id, listing_type, limit = client.calls["market"]
    assert (q, listing_type, limit) == ("test", "expected", 24)
    assert crop_id == (crop or None)


def test_unknown_filters_are_ignored(client):
    r = client.get("/?crop=not_a_crop&type=zzz")
    assert r.status_code == 200
    assert "market" not in client.calls


def test_home_opens_when_database_is_down(client, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(repo, "public_listings", boom)
    r = client.get("/")
    assert r.status_code == 200
    assert "cb-hero2-facts" not in r.text      # no numbers shown when we cannot count


@pytest.mark.parametrize("asked,shown", [("admin", "admin"), ("customer", "customer"),
                                         ("farmer", "farmer"), ("hacker", "farmer")])
def test_login_role_picker(client, asked, shown):
    r = client.get(f"/login?as={asked}")
    assert r.status_code == 200
    assert re.search(r'name="as_role" value="(\w+)"', r.text).group(1) == shown


def test_failed_login_keeps_role(client):
    page = client.get("/login?as=admin").text
    token = re.search(r'name="csrf" value="([^"]+)"', page).group(1)
    r = client.post("/login", data={"phone": "01712345678", "password": "wrong-pass",
                                    "csrf": token, "as_role": "admin"})
    assert r.status_code == 400
    assert 'name="as_role" value="admin"' in r.text


def test_market_sql_escapes_wildcards(monkeypatch):
    seen = {}
    monkeypatch.setattr(repo, "fetch_all", lambda sql, params: seen.update(sql=sql, params=params) or [])
    repo.market_listings("50%_off", "potato", "expected", 24)
    assert "ILIKE %s" in seen["sql"]
    assert seen["params"] == ("%50\\%\\_off%", "potato", "expected", 24)
