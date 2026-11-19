"""Home page and bazar must show the same product data (price after discount, district, stock).
Needs the database: $env:CB_DB_TESTS="1"."""
from __future__ import annotations

import os
import re
import secrets
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
pytestmark = pytest.mark.skipif(os.environ.get("CB_DB_TESTS") != "1", reason="set CB_DB_TESTS=1")


@pytest.fixture
def listing():
    from chashibondhu.web.db import execute, fetch_one
    phone = "+88017" + f"{secrets.randbelow(10**8):08d}"
    uid = fetch_one("INSERT INTO users (role, full_name, phone, password_hash, district_code) "
                    "VALUES ('farmer', 'Test Farmer', %s, 'x', 'BD3026') RETURNING id", (phone,))["id"]
    lid = fetch_one("INSERT INTO listings (farmer_id, title, crop_id, category, unit, price_per_unit, discount_price, "
                    "quantity, listing_type, status, district_code, farming_method) VALUES "
                    "(%s, 'Zz Home Test Tomato', NULL, 'vegetables', 'kg', 25, 22, 50, 'available', 'active', 'BD3026', 'organic') "
                    "RETURNING id", (uid,))["id"]
    yield lid
    execute("DELETE FROM listings WHERE id = %s", (lid,))
    execute("DELETE FROM users WHERE id = %s", (uid,))


def _card(html: str, lid: int) -> str:
    m = re.search(rf'<a class="cb-card[^"]*" href="/market/{lid}">(.*?)</a>', html, re.S)
    assert m, "card not found"
    return re.sub(r"\s+", " ", m.group(1))


def _text(card: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", card))


def test_home_and_bazar_cards_match(listing):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from chashibondhu.web.app import mount_website
    os.environ.setdefault("WEB_SESSION_SECRET", "x" * 40)
    app = FastAPI()
    mount_website(app)
    c = TestClient(app)
    home = _card(c.get("/").text, listing)
    bazar = _card(c.get("/market").text, listing)
    print(_text(home)); print(_text(bazar))
    assert re.search(r"৳ ?(২২|22)", _text(home)) and "<s>" in home and "সাশ্রয়" in home   # discount price + saving
    strip_area = lambda x: re.sub(r" · .*?</div>", "</div>", x, count=1)  # noqa: E731
    assert strip_area(home) == strip_area(bazar)                  # same card, same data
    assert "BD3026" not in _text(home)                            # district name, not the code
    searched = _card(c.get("/?q=Zz+Home").text, listing)
    assert searched == home
