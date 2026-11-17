"""Customer shopping assistant (Phase B3): real products only, numbers checked, never orders, customers only.
All offline (fake market + fake LLM); no database, no real AI call."""
from __future__ import annotations

import json
import re
import sys
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from chashibondhu.web import shop_assistant as sa  # noqa: E402


def row(i, title="Diamond Alu", unit="kg", price="40", qty="100", mn="1", method="conventional", disc=None,
        kind="available"):
    return {"id": i, "title": title, "unit": unit, "price_per_unit": Decimal(price),
            "discount_price": Decimal(disc) if disc else None, "price_now": Decimal(disc or price),
            "quantity": Decimal(qty), "min_order": Decimal(mn), "listing_type": kind, "farming_method": method,
            "farmer_name": "Rahim", "district_code": "BD2626", "image_path": None, "category": "vegetable"}


class FakeLLM:
    model = "fake-llm"

    def __init__(self, reply=None, error=None):
        self.reply, self.error, self.calls = reply, error, []

    def generate(self, system, user):
        self.calls.append((system, user))
        if self.error:
            raise self.error
        return self.reply if isinstance(self.reply, str) else json.dumps(self.reply, ensure_ascii=False)


# ================================================================ parsing
def test_parse_bangla_question():
    p = sa.parse("আমার ৫ কেজি আলু লাগবে কম দামে, জৈব হলে ভালো")
    assert p["qty"] == 5 and p["unit"] == "kg" and p["cheap"] and p["organic"] and not p["off_topic"]
    assert p["text"] == "আলু"


def test_parse_english_and_banglish():
    p = sa.parse("I need 2 dozen eggs, cheapest please")
    assert (p["qty"], p["unit"], p["cheap"], p["text"]) == (Decimal(2), "dozen", True, "eggs")
    p = sa.parse("10kg peyaj lagbe")
    assert (p["qty"], p["unit"], p["text"]) == (Decimal(10), "kg", "peyaj")
    assert sa.parse("আলুর পাতায় পোকা, কীটনাশক কোনটা?")["off_topic"]


# ================================================================ enrichment + fallback
def test_enrich_and_fallback_ranking():
    rows = sa.enrich([row(1, price="40"), row(2, unit="maund", price="1400"), row(3, qty="2"),
                      row(4, method="organic", price="45"), row(5, kind="expected")], Decimal("5"), "kg")
    by = {r["id"]: r for r in rows}
    assert by[1]["cart_qty"] == 5 and by[1]["enough"]
    assert by[3]["cart_qty"] == 2 and not by[3]["enough"]               # never above stock
    assert by[2]["base_price"] == Decimal("37.51") and by[2]["cart_qty"] == 1
    assert not by[5]["buyable"]
    assert sa.fallback_picks(rows, {"organic": False}) == [2, 1, 4]       # cheapest per kg first
    assert sa.fallback_picks(rows, {"organic": True})[0] == 4             # organic first when asked


# ================================================================ LLM answer safety
def test_llm_cannot_add_products_or_fake_numbers():
    rows = sa.enrich([row(1, price="40"), row(2, price="38", method="organic")], None, None)
    llm = FakeLLM({"intro": "দুটি আলু পাওয়া গেছে। ১০০ টাকায় ফ্রি ডেলিভারি!",
                   "picks": [{"id": 99, "why": "fake"}, {"id": 2, "why": "জৈব, ৩৮ টাকা কেজি।"},
                             {"id": 1, "why": "মাত্র ২৫ টাকা!"}, {"id": 2, "why": "duplicate"}]})
    out = sa.answer("আলু", rows, sa.parse("আলু"), llm=llm)
    assert out["mode"] == "ai" and [pk["row"]["id"] for pk in out["picks"]] == [2, 1]
    assert out["picks"][0]["why"] == "জৈব, ৩৮ টাকা কেজি।"                 # real price: kept
    assert out["picks"][1]["why"] == ""                                    # invented price 25: removed
    assert out["intro"] == "দুটি আলু পাওয়া গেছে।"                          # "free delivery" claim removed
    out = sa.answer("alu", rows, sa.parse("alu"), llm=FakeLLM({"intro": "Prices from 777 taka. I added it to your cart.",
                                                                 "picks": [{"id": 1, "why": "Fresh."}]}))
    assert out["intro"] == "" and out["picks"][0]["why"] == "Fresh."       # unknown number + fake action removed
    system, user = llm.calls[0]
    assert "Bangla" in system and '"id": 1' in user and "never" in system.lower()


def test_llm_failure_or_garbage_falls_back():
    rows = sa.enrich([row(1, price="40"), row(2, price="30")], None, None)
    p = sa.parse("alu")
    for llm in (FakeLLM(error=RuntimeError("rate limited")), FakeLLM("not json"), FakeLLM({"picks": [{"id": 7}]})):
        out = sa.answer("alu", rows, p, llm=llm)
        assert out["mode"] == "plain" and [pk["row"]["id"] for pk in out["picks"]] == [2, 1]
    assert sa.answer("alu", [], p, llm=FakeLLM({}))["mode"] == "none"


def test_llm_off_topic():
    rows = sa.enrich([row(1)], None, None)
    out = sa.answer("what is the weather", rows, sa.parse("what is the weather"),
                    llm=FakeLLM({"off_topic": True, "picks": [{"id": 1}]}))
    assert out["mode"] == "off_topic" and out["picks"] == []


# ================================================================ routes
@pytest.fixture
def client(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from chashibondhu.web import repo
    from chashibondhu.web.passwords import hash_password
    from fake_auth import install
    users = {"+8801733333333": {"id": 9, "role": "customer", "full_name": "Buyer", "status": "active",
                                "password_hash": hash_password("buyer12")},
             "+8801711111111": {"id": 7, "role": "farmer", "full_name": "Rahim", "status": "active",
                                "password_hash": hash_password("secret1")}}
    monkeypatch.setenv("WEB_SESSION_SECRET", "x" * 40)
    m = monkeypatch.setattr
    m(repo, "get_user_by_phone", lambda p: users.get(p))
    m(repo, "is_locked", lambda u: False)
    m(repo, "record_login", lambda uid, ok: None)
    install(monkeypatch)
    searches: list = []

    def market_search(f, known, page=1):
        searches.append(dict(f))
        if "alu" in f["q"] or "আলু" in f["q"]:
            rs = [row(1, price="40"), row(2, price="35", disc=None)]
            return ([r for r in rs if not f.get("organic")] or []), 2
        return [], 0
    m(repo, "market_search", market_search)
    from chashibondhu.web.app import mount_website
    app = FastAPI()
    mount_website(app)
    c = TestClient(app)
    c.searches = searches
    return c


def login(c, phone, pw, role):
    tok = re.search(r'name="csrf" value="([^"]+)"', c.get("/login").text).group(1)
    assert c.post("/login", data={"csrf": tok, "phone": phone, "password": pw, "as_role": role},
                  follow_redirects=False).status_code == 303


def tok(c):
    return re.search(r'name="csrf" value="([^"]+)"', c.get("/shop-assistant").text).group(1)


def test_customers_only(client):
    assert client.get("/shop-assistant", follow_redirects=False).headers["location"].startswith("/login")
    login(client, "+8801711111111", "secret1", "farmer")
    assert client.get("/shop-assistant", follow_redirects=False).status_code == 403
    assert client.post("/shop-assistant", data={"csrf": "x", "question": "alu"},
                       follow_redirects=False).status_code == 403


def test_ask_without_ai_shows_real_products_and_cart_buttons(client):
    login(client, "+8801733333333", "buyer12", "customer")
    page = client.get("/shop-assistant").text
    assert "/shop-assistant" in page and "Shopping helper" in page
    r = client.post("/shop-assistant", data={"csrf": tok(client), "question": "৫ কেজি alu kom dame, jaibo hole valo"})
    assert r.status_code == 200
    assert client.searches[0]["organic"] is True and client.searches[1]["organic"] is False   # organic retry
    assert "No organic product found" in r.text and "AI is not available" in r.text
    assert r.text.index("/market/2") < r.text.index("/market/1")                              # cheaper first
    assert 'action="/cart/add"' in r.text and 'value="5.0"' in r.text                          # prefilled, not added


def test_ask_nothing_found_and_validation(client):
    login(client, "+8801733333333", "buyer12", "customer")
    r = client.post("/shop-assistant", data={"csrf": tok(client), "question": "dragon fruit"})
    assert "No product in the market matches" in r.text and 'href="/requests"' in r.text
    assert client.post("/shop-assistant", data={"csrf": tok(client), "question": "x"}).status_code == 400
    assert client.post("/shop-assistant", data={"csrf": "bad", "question": "alu"}).status_code == 400


def test_rate_limit(client, monkeypatch):
    from chashibondhu.web import routes_shop_ai
    monkeypatch.setattr(routes_shop_ai, "LIMIT_PER_HOUR", 2)
    login(client, "+8801733333333", "buyer12", "customer")
    t = tok(client)
    codes = [client.post("/shop-assistant", data={"csrf": t, "question": "alu"}).status_code for _ in range(3)]
    assert codes == [200, 200, 429]
