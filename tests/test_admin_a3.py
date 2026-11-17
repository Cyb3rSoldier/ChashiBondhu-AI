"""Admin A3: announcements (in-app once), articles/news (only published is public), pre-harvest monitoring
(cancel never makes stock), offline sync log, analytics + CSV, permissions.

Database tests run only when asked:   $env:CB_DB_TESTS="1"; python -m pytest -q tests/test_admin_a3.py
Needs migrations 005-009."""
from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

DB = os.environ.get("CB_DB_TESTS") == "1"
db_only = pytest.mark.skipif(not DB, reason="set CB_DB_TESTS=1 to run database tests")
PW = "Shapla#2026x"


def test_sync_result_mapping():
    from fastapi.responses import JSONResponse
    from chashibondhu.web.routes_harvest import _sync_result
    assert _sync_result({"ok": True, "id": 5, "version": 1, "duplicate": False}) == ("created", 200, None, 5)
    assert _sync_result({"ok": True, "id": 5, "duplicate": True}) == ("duplicate", 200, None, 5)
    assert _sync_result({"ok": True, "id": 5, "version": 3})[0] == "updated"
    assert _sync_result(JSONResponse({"detail": "conflict"}, status_code=409))[:3] == ("conflict", 409, "conflict")
    assert _sync_result(JSONResponse({"detail": "invalid"}, status_code=422))[:3] == ("rejected", 422, "invalid")


def test_clamp_range():
    from chashibondhu.web.repo_admin_a3 import clamp_range
    a, b = clamp_range(None, date(2026, 11, 15))
    assert (b - a).days == 29
    a, b = clamp_range(date(2020, 1, 1), date(2026, 11, 15))
    assert (b - a).days == 365
    assert clamp_range(date(2026, 11, 15), date(2026, 11, 1)) == (date(2026, 11, 1), date(2026, 11, 15))


def test_tips_patch_script(tmp_path, monkeypatch):
    src = tmp_path / "src/chashibondhu/web"
    src.mkdir(parents=True)
    (src / "repo.py").write_text('def farmer_tips(limit: int = 30) -> list[dict]:\n'
                                 '    return fetch_all("SELECT id, title, body, created_at FROM announcements WHERE audience IN (\'all\', \'farmer\') "\n'
                                 '                     "ORDER BY created_at DESC LIMIT %s", (limit,))\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    import runpy
    runpy.run_path(str(ROOT / "scripts" / "patch_tips_009.py"))
    assert "AND status = 'published'" in (src / "repo.py").read_text(encoding="utf-8")
    runpy.run_path(str(ROOT / "scripts" / "patch_tips_009.py"))              # twice is fine


# ================================================================ database
def _phone():
    return "+88017" + f"{secrets.randbelow(10**8):08d}"


@pytest.fixture
def world():
    from chashibondhu.web.db import execute, fetch_one
    from chashibondhu.web.passwords import hash_password
    tag = secrets.token_hex(3)
    ids: dict = {"phones": {}}
    for key, role in (("boss", "admin"), ("writer", "admin"), ("f1", "farmer"), ("buyer", "customer")):
        ph = _phone()
        ids["phones"][key] = ph
        ids[key] = fetch_one("INSERT INTO users (role, full_name, phone, email, password_hash) VALUES (%s, %s, %s, %s, %s) "
                             "RETURNING id", (role, f"Test {key}", ph, f"{key}{tag}@test.example.com" if role == "customer"
                                              else None, hash_password(PW)))["id"]
    execute("INSERT INTO admin_staff (user_id, is_super) VALUES (%s, true)", (ids["boss"],))
    execute("INSERT INTO admin_staff (user_id, permissions) VALUES (%s, '{content}')", (ids["writer"],))
    ids["ann"], ids["posts"] = [], []
    yield ids
    users = [ids[k] for k in ("boss", "writer", "f1", "buyer")]
    execute("DELETE FROM announcements WHERE id = ANY(%s)", (ids["ann"],))
    execute("DELETE FROM content_posts WHERE id = ANY(%s) OR created_by = ANY(%s)", (ids["posts"], users))
    execute("DELETE FROM listings WHERE farmer_id = ANY(%s)", (users,))
    execute("DELETE FROM users WHERE id = ANY(%s)", (users,))


@db_only
def test_announcement_in_app_once(world):
    from chashibondhu.web import repo_admin_a3 as r3
    from chashibondhu.web.db import fetch_one
    aid = r3.create_announcement(world["boss"], "Test rain alert", "Heavy rain expected, protect your seedlings.",
                                 "farmer", publish=False, notify=True)
    world["ann"].append(aid)
    n = lambda uid: fetch_one("SELECT count(*) AS n FROM notifications WHERE user_id = %s AND dedupe_key = %s",  # noqa: E731
                              (uid, f"ann:{aid}"))["n"]
    assert n(world["f1"]) == 0                                       # draft: nothing sent
    assert r3.announcement_action(world["boss"], aid, "notify") == "not_allowed"
    assert r3.announcement_action(world["boss"], aid, "publish") == "ok"
    assert r3.announcement_action(world["boss"], aid, "notify") == "ok"
    assert r3.announcement_action(world["boss"], aid, "notify") == "not_allowed"   # only once
    assert n(world["f1"]) == 1 and n(world["buyer"]) == 0           # farmers only
    a = fetch_one("SELECT status, notified_count FROM announcements WHERE id = %s", (aid,))
    assert a["status"] == "published" and a["notified_count"] >= 1
    assert r3.announcement_action(world["boss"], aid, "archive") == "ok"
    assert r3.announcement_action(world["boss"], aid, "restore") == "ok"


@db_only
def test_content_only_published_is_public(world):
    from chashibondhu.web import repo_admin_a3 as r3
    data = {"kind": "news", "title": "Test potato price news", "summary": None, "body": "A real news text for testing.",
            "media_url": None, "source_name": "DAM", "source_url": "https://dam.gov.bd"}
    cid = r3.content_save(world["writer"], None, data)
    world["posts"].append(cid)
    assert r3.public_post(cid) is None
    assert r3.content_status(world["writer"], cid, "published", date.today() + timedelta(days=3)) == "ok"
    assert r3.public_post(cid) is None                               # scheduled for the future
    r3.content_status(world["writer"], cid, "draft")
    assert r3.content_status(world["writer"], cid, "published", date.today() - timedelta(days=1)) == "ok"
    assert r3.public_post(cid)["source_name"] == "DAM" and any(p["id"] == cid for p in r3.public_posts())
    assert r3.content_status(world["writer"], cid, "archived") == "ok" and r3.public_post(cid) is None


@db_only
def test_admin_cancel_forecast_never_makes_stock(world):
    from chashibondhu.web import repo_admin_a3 as r3
    from chashibondhu.web.db import execute, fetch_one
    d = date.today()
    f = fetch_one("INSERT INTO harvest_forecasts (farmer_id, product_name, expected_qty, unit, harvest_from, harvest_to) "
                  "VALUES (%s, 'Test Alu', 500, 'kg', %s, %s) RETURNING id", (world["f1"], d + timedelta(5), d + timedelta(9)))["id"]
    r = fetch_one("INSERT INTO buyer_demand_requests (buyer_id, product_name, quantity, unit, needed_from, needed_to) "
                  "VALUES (%s, 'Test Alu', 50, 'kg', %s, %s) RETURNING id", (world["buyer"], d + timedelta(5), d + timedelta(9)))["id"]
    m = fetch_one("INSERT INTO harvest_matches (forecast_id, request_id, match_qty, status) VALUES (%s, %s, 50, 'agreed') "
                  "RETURNING id", (f, r))["id"]
    listings_before = fetch_one("SELECT count(*) AS n FROM listings")["n"]
    assert r3.admin_cancel(world["boss"], "forecast", f, "fake photo, not his field") == "ok"
    assert r3.admin_cancel(world["boss"], "forecast", f, "again") == "not_allowed"
    assert fetch_one("SELECT status FROM harvest_matches WHERE id = %s", (m,))["status"] == "cancelled"
    assert fetch_one("SELECT count(*) AS n FROM listings")["n"] == listings_before
    rows, n = r3.forecasts({"q": "Test Alu"})
    assert any(x["id"] == f and x["status"] == "cancelled" for x in rows)
    assert r3.matches({"status": "cancelled"})[1] >= 1
    assert r3.admin_cancel(world["boss"], "request", r, "duplicate request") == "ok"
    execute("DELETE FROM buyer_demand_requests WHERE id = %s", (r,))
    execute("DELETE FROM harvest_forecasts WHERE id = %s", (f,))


@db_only
def test_sync_log_written_by_wrapper(world):
    from fastapi.responses import JSONResponse
    from chashibondhu.web import repo_admin_a3 as r3, routes_harvest as rh

    class Req:                                                   # minimal stand-in for a logged-in farmer request
        def __init__(self):
            self.session = {"user": {"id": world["f1"], "role": "farmer", "name": "Test f1"}}
            self._json = {"client_id": "0b9a3c0e-7d0b-4a8e-9a55-0d4f6f0f9a01"}

    async def ok(_):
        return {"ok": True, "id": 77, "version": 1, "duplicate": False}

    async def bad(_):
        return JSONResponse({"detail": "conflict"}, status_code=409)

    import chashibondhu.web.deps as deps
    orig = deps.current_user
    deps.current_user = lambda request: request.session.get("user")
    try:
        asyncio.run(rh._logged(Req(), "forecast", ok))
        asyncio.run(rh._logged(Req(), "forecast", bad))
    finally:
        deps.current_user = orig
    rows, n, summary = r3.sync_events({"farmer": world["f1"]})
    assert [(r["result"], r["server_id"]) for r in rows] == [("conflict", None), ("created", 77)]
    assert str(rows[1]["client_id"]) == "0b9a3c0e-7d0b-4a8e-9a55-0d4f6f0f9a01"
    assert r3.sync_events({"result": "problems", "farmer": world["f1"]})[1] == 1


@db_only
def test_every_report_runs(world):
    from chashibondhu.web import repo_admin_a3 as r3
    a, b = r3.clamp_range(None, None)
    for k in r3.REPORTS:
        headers, rows = r3.report(k, a, b)
        assert headers and isinstance(rows, list), k
        assert r3.to_csv(headers, rows).startswith("﻿" + headers[0])
    assert len(r3.report("registrations", a, b)[1]) == 30


# ---------------------------------------------------------------- pages on the real database
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


@db_only
def test_pages_and_permissions(world, web):
    c = web
    _login(c, world["phones"]["boss"])
    for url in ("/admin-announcements", "/admin-content", "/admin-content/new", "/admin-harvest",
                "/admin-harvest?tab=requests", "/admin-harvest?tab=matches", "/admin-sync", "/admin-sync?result=problems",
                "/admin-analytics", "/admin-analytics?report=ai", "/admin-analytics?report=demand&from=2026-01-01&to=2026-12-31",
                "/articles"):
        assert c.get(url).status_code == 200, url
    r = c.get("/admin-analytics/orders.csv")
    assert r.status_code == 200 and r.text.startswith("﻿day")
    tok = re.search(r'name="csrf" value="([^"]+)"', c.get("/admin-announcements").text).group(1)
    c.post("/admin-announcements/new", data={"csrf": tok, "title": "Test notice", "body": "Market closed on Friday.",
                                             "audience": "customer", "publish": "1"})
    from chashibondhu.web.db import fetch_one
    world["ann"].append(fetch_one("SELECT id FROM announcements WHERE created_by = %s ORDER BY id DESC LIMIT 1",
                                  (world["boss"],))["id"])

    _login(c, world["phones"]["writer"])                                  # content only
    assert c.get("/admin-content").status_code == 200
    for url in ("/admin-announcements", "/admin-harvest", "/admin-sync", "/admin-analytics", "/admin-analytics/orders.csv"):
        assert c.get(url, follow_redirects=False).status_code == 403, url
    tok = re.search(r'name="csrf" value="([^"]+)"', c.get("/admin-content/new").text).group(1)
    r = c.post("/admin-content/new", data={"csrf": tok, "kind": "news", "title": "No source news", "body": "Text without a source."})
    assert r.status_code == 400 and "News needs a source" in r.text
    r = c.post("/admin-content/new", data={"csrf": tok, "kind": "article", "title": "Test seedbed tips",
                                           "body": "Keep the seedbed moist but not wet.", "source_name": "BARI"},
               follow_redirects=False)
    cid = int(r.headers["location"].rsplit("/", 1)[1])
    world["posts"].append(cid)
    assert c.get(f"/articles/{cid}").status_code == 404                   # still a draft
    c.post(f"/admin-content/{cid}", data={"csrf": tok, "action": "published"})
    assert "Test seedbed tips" in c.get(f"/articles/{cid}").text
