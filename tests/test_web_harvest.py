"""Phase 2: pre-harvest buyer matching + offline sync (no database: fake repo).

The SQL (matching, harvest confirmation, conversion trigger, idempotent inserts) was tested against
PostgreSQL 16 with migrations 001-003. Run: python -m pytest -q tests/test_web_harvest.py
"""
from __future__ import annotations

import re
import sys
import uuid
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))   # tests/fake_auth.py

pytest.importorskip("fastapi.testclient")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from chashibondhu.web import repo, routes_harvest  # noqa: E402
from chashibondhu.web.passwords import hash_password  # noqa: E402

D = lambda n: (date.today() + timedelta(days=n)).isoformat()  # noqa: E731
USERS = {"+8801711111111": {"id": 7, "role": "farmer", "full_name": "Rahim", "status": "active",
                            "password_hash": hash_password("secret1")},
         "+8801733333333": {"id": 9, "role": "customer", "full_name": "Buyer", "status": "active",
                            "password_hash": hash_password("buyer12")}}


@pytest.fixture()
def app(monkeypatch):
    calls: dict = {}
    m = monkeypatch.setattr
    m(repo, "get_user_by_phone", lambda p: USERS.get(p))
    from fake_auth import install
    install(monkeypatch)
    m(repo, "is_locked", lambda u: False)
    m(repo, "record_login", lambda uid, ok: None)
    m(repo, "get_farmer_profile", lambda uid: {"district_code": "BD2626", "upazila_code": "BD26260001"})
    m(repo, "expire_stale", lambda: None)
    m(repo, "list_forecasts", lambda uid: [])
    m(repo, "list_requests", lambda uid: [])

    def create_forecast(uid, data, client_id=None):
        calls.setdefault("created", []).append((uid, data, client_id))
        return {"id": 11, "version": 1, "duplicate": len(calls["created"]) > 1}
    m(repo, "create_forecast", create_forecast)
    m(repo, "update_forecast", lambda uid, fid, data, base: (
        {"ok": True, "version": 2} if base in (None, 1) else
        {"ok": False, "reason": "conflict", "server": {**data, "expected_qty": 310, "version": 2}}))
    m(repo, "farmer_offer", lambda uid, fid, rid, q: calls.setdefault("offer", (uid, fid, rid, q)) and "ok")
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
    return c


def head_token(c):
    return {"X-CSRF-Token": re.search(r'name="csrf-token" content="([^"]+)"', c.get("/farmer/drafts").text).group(1)}


def body(**extra):
    b = {"client_id": str(uuid.uuid4()), "owner": 7,
         "data": {"product_name": "Tomato", "expected_qty": "500", "unit": "kg", "harvest_from": D(10)}}
    b.update(extra)
    return b


def test_plan_validation_rules():
    ok, err = routes_harvest._plan_data({"product_name": "Tomato", "expected_qty": "৫০০", "unit": "kg",
                                         "harvest_from": D(3)}, "forecast")
    assert not err and ok["expected_qty"] == 500 and ok["harvest_to"] == ok["harvest_from"]
    for bad in ({"expected_qty": "0"}, {"harvest_from": D(-3)}, {"unit": "ton"}, {"harvest_from": D(400)},
                {"harvest_from": D(5), "harvest_to": D(2)}):
        form = {"product_name": "Tomato", "expected_qty": "5", "unit": "kg", "harvest_from": D(3), **bad}
        assert routes_harvest._plan_data(form, "forecast")[1], bad


def test_sync_forecast_idempotent_and_owner(app):
    c = login(app, "01711111111", "secret1")
    h = head_token(c)
    b = body()
    first, second = c.post("/farmer/sync/forecast", json=b, headers=h), c.post("/farmer/sync/forecast", json=b, headers=h)
    assert first.json()["ok"] and second.json()["duplicate"] is True
    assert app.calls["created"][0][2] == b["client_id"]                 # client id reaches the database layer
    assert c.post("/farmer/sync/forecast", json={**b, "owner": 8}, headers=h).status_code == 403
    assert c.post("/farmer/sync/forecast", json=b).json()["detail"] == "csrf"
    assert c.post("/farmer/sync/forecast", json={**b, "client_id": "nope"}, headers=h).status_code == 422


def test_sync_conflict_returns_server_copy(app):
    c = login(app, "01711111111", "secret1")
    r = c.post("/farmer/sync/forecast", json=body(server_id=11, base_version=0), headers=head_token(c))
    assert r.status_code == 409 and r.json()["detail"] == "conflict" and r.json()["server"]["expected_qty"] == "310"
    r = c.post("/farmer/sync/forecast", json=body(server_id=11, force=True), headers=head_token(c))
    assert r.json()["ok"]


def test_sync_needs_login_and_farmer(app):
    assert TestClient(app).post("/farmer/sync/forecast", json=body()).json()["detail"] == "login_required"
    c = login(app, "01733333333", "buyer12")
    assert c.post("/farmer/sync/forecast", json=body(), headers={"X-CSRF-Token": "x"}).status_code == 403


def test_pages_and_access(app):
    f = login(app, "01711111111", "secret1")
    for url in ("/farmer/forecasts", "/farmer/forecasts/new", "/farmer/drafts"):
        assert f.get(url).status_code == 200, url
    assert "offline.js" in f.get("/farmer/drafts").text
    assert f.get("/requests").status_code == 403
    cu = login(app, "01733333333", "buyer12")
    assert cu.get("/requests").status_code == 200 and "offline.js" not in cu.get("/").text
    r = cu.get("/farmer/forecasts", headers={"accept": "text/html"})
    assert r.status_code == 403 and "not for your account" in r.text


def test_offer_quantity_must_be_positive(app):
    c = login(app, "01711111111", "secret1")
    tok = re.search(r'name="csrf" value="([^"]+)"', c.get("/farmer/forecasts").text).group(1)
    c.post("/farmer/forecasts/11/offer", data={"csrf": tok, "request_id": 3, "qty": "0"}, follow_redirects=False)
    assert "offer" not in app.calls
    c.post("/farmer/forecasts/11/offer", data={"csrf": tok, "request_id": 3, "qty": "২০০"}, follow_redirects=False)
    assert app.calls["offer"][1:3] == (11, 3) and app.calls["offer"][3] == 200


def test_service_worker_served_at_root(app):
    r = TestClient(app).get("/sw.js")
    assert r.status_code == 200 and r.headers["service-worker-allowed"] == "/"
    sw = r.text
    assert "/farmer/orders" not in sw and "cb-pages-" in sw        # private order pages are never cached


def test_migration_statuses_match_code():
    sql = (ROOT / "supabase" / "migrations" / "003_harvest_matching_offline.sql").read_text(encoding="utf-8")
    for s in repo.ACTIVE_MATCH + ("declined", "cancelled", "expired"):
        assert f"'{s}'" in sql
    assert "UNIQUE (farmer_id, client_id)" in sql and "uq_listings_farmer_client" in sql
