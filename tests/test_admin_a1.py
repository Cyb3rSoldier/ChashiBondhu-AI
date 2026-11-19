"""Admin A1: permissions on the server, append-only audit log, suspension, product + review moderation.

Database tests run only when asked (they create their own users and delete them afterwards;
the few audit rows they write stay — the audit log cannot be deleted, by design):
    $env:CB_DB_TESTS="1"; python -m pytest -q tests/test_admin_a1.py
Needs migrations 005, 006 and 007.
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
PW = "Shapla#2026x"


def test_migration_file():
    sql = (ROOT / "supabase" / "migrations" / "007_admin_a1.sql").read_text(encoding="utf-8")
    for must in ("admin_audit_log is append-only", "BEFORE TRUNCATE", "listings_keep_moderated_hidden",
                 "INSERT INTO admin_staff (user_id, is_super)", "'suspended'"):
        assert must in sql


# ================================================================ database
def _phone():
    return "+88017" + f"{secrets.randbelow(10**8):08d}"


@pytest.fixture
def world():
    from chashibondhu.web.db import execute, fetch_one
    from chashibondhu.web.passwords import hash_password
    tag = secrets.token_hex(3)
    ids: dict = {"phones": {}}

    def mk(key, role, extra_sql="", extra=()):
        ph = _phone()
        ids["phones"][key] = ph
        ids[key] = fetch_one(f"INSERT INTO users (role, full_name, phone, password_hash{', email' if role == 'customer' else ''}) "
                             f"VALUES (%s, %s, %s, %s{', %s' if role == 'customer' else ''}) RETURNING id",
                             (role, f"Test {key}", ph, hash_password(PW))
                             + ((f"{key}{tag}@test.example.com",) if role == "customer" else ()))["id"]
    mk("boss", "admin"), mk("staff", "admin"), mk("farmer", "farmer"), mk("buyer", "customer")
    execute("INSERT INTO admin_staff (user_id, is_super) VALUES (%s, true)", (ids["boss"],))
    execute("INSERT INTO admin_staff (user_id, permissions) VALUES (%s, '{products}')", (ids["staff"],))
    ids["listing"] = fetch_one("INSERT INTO listings (farmer_id, title, unit, price_per_unit, quantity) "
                               "VALUES (%s, 'Test Alu', 'kg', 40, 10) RETURNING id", (ids["farmer"],))["id"]
    yield ids
    users = [ids[k] for k in ("boss", "staff", "farmer", "buyer")]
    execute("DELETE FROM orders WHERE customer_id = ANY(%s)", (users,))
    execute("DELETE FROM listings WHERE farmer_id = %s", (ids["farmer"],))
    execute("DELETE FROM users WHERE id = ANY(%s)", (users,))


@db_only
def test_audit_log_is_append_only(world):
    from chashibondhu.web import repo_admin as ra
    from chashibondhu.web.db import execute, fetch_one
    ra.audit(world["boss"], "test.ping", "user", world["boss"], meta={"x": 1})
    row = fetch_one("SELECT id, actor_name FROM admin_audit_log WHERE actor_id = %s ORDER BY id DESC LIMIT 1",
                    (world["boss"],))
    assert row["actor_name"] == "Test boss"
    for sql in ("UPDATE admin_audit_log SET action = 'x' WHERE id = %s", "DELETE FROM admin_audit_log WHERE id = %s"):
        with pytest.raises(Exception):
            execute(sql, (row["id"],))
    with pytest.raises(Exception):
        execute("TRUNCATE admin_audit_log")


@db_only
def test_suspend_ends_sessions_and_blocks_login(world):
    from chashibondhu.web import repo_admin as ra, repo_auth
    from chashibondhu.web.db import fetch_one
    before = repo_auth.session_version(world["farmer"])
    assert ra.set_user_status(world["boss"], world["farmer"], ("customer",), True, "spam") == "not_found"  # wrong page
    assert ra.set_user_status(world["boss"], world["farmer"], ("farmer",), True, "fake products") == "ok"
    assert repo_auth.session_version(world["farmer"]) is None                   # every old login is now invalid
    assert ra.set_user_status(world["boss"], world["farmer"], ("farmer",), True, "again") == "same"
    assert ra.set_user_status(world["boss"], world["boss"], ("admin",), True, "me") == "self"
    assert ra.set_user_status(world["boss"], world["farmer"], ("farmer",), False, None) == "ok"
    assert repo_auth.session_version(world["farmer"]) == before + 2
    log = fetch_one("SELECT count(*) AS n FROM admin_audit_log WHERE target_type = 'user' AND target_id = %s "
                    "AND action IN ('user.suspend', 'user.restore')", (world["farmer"],))
    assert log["n"] == 2


@db_only
def test_last_super_admin_is_protected(world):
    from chashibondhu.web import repo_admin as ra
    from chashibondhu.web.db import fetch_one
    supers = fetch_one("SELECT count(*) AS n FROM admin_staff s JOIN users u ON u.id = s.user_id "
                       "WHERE s.is_super AND u.status = 'active'")["n"]
    if supers == 1:                                     # only our test boss is super in this database
        assert ra.set_permissions(world["staff"], world["boss"], [], False) == "last_super"
    assert ra.set_permissions(world["boss"], world["staff"], ["products", "reviews"], False) == "ok"
    assert ra.staff_row(world["staff"])["permissions"] == ["products", "reviews"]


@db_only
def test_moderated_listing_stays_hidden(world):
    from chashibondhu.web import repo_admin as ra
    from chashibondhu.web.db import execute, fetch_one
    lid = world["listing"]
    assert ra.moderate_listing(world["boss"], lid, True, "wrong photo") == "ok"
    execute("UPDATE listings SET status = 'active' WHERE id = %s", (lid,))       # farmer tries to bring it back
    assert fetch_one("SELECT status FROM listings WHERE id = %s", (lid,))["status"] == "hidden"
    execute("UPDATE listings SET price_per_unit = 45 WHERE id = %s", (lid,))      # other edits still work
    note = fetch_one("SELECT body FROM notifications WHERE user_id = %s ORDER BY id DESC LIMIT 1", (world["farmer"],))
    assert "wrong photo" in note["body"]
    assert ra.moderate_listing(world["boss"], lid, False, "fixed") == "ok"
    l = fetch_one("SELECT status, moderated_at, price_per_unit, quantity FROM listings WHERE id = %s", (lid,))
    assert (l["status"], l["moderated_at"], l["price_per_unit"], l["quantity"]) == ("active", None, 45, 10)


@db_only
def test_review_moderation(world):
    from chashibondhu.web import repo_admin as ra
    from chashibondhu.web.db import execute, fetch_one
    o = fetch_one("INSERT INTO orders (customer_id, subtotal, total, delivery_address, phone, status) "
                  "VALUES (%s, 40, 40, 'Dhaka', '+8801700000000', 'delivered') RETURNING id", (world["buyer"],))["id"]
    execute("INSERT INTO order_items (order_id, listing_id, farmer_id, title, unit, unit_price, quantity, line_total, "
            "farmer_status) VALUES (%s, %s, %s, 'Test Alu', 'kg', 40, 1, 40, 'handed_over')",
            (o, world["listing"], world["farmer"]))
    rid = fetch_one("INSERT INTO reviews (listing_id, customer_id, rating, comment) VALUES (%s, %s, 1, 'bad words') "
                    "RETURNING id", (world["listing"], world["buyer"]))["id"]
    assert ra.moderate_review(world["boss"], rid, True, "abusive language") == "ok"
    r = fetch_one("SELECT status, moderation_reason FROM reviews WHERE id = %s", (rid,))
    assert (r["status"], r["moderation_reason"]) == ("hidden", "abusive language")
    rows, n = ra.review_list({"status": "hidden", "q": "Test Alu"})
    assert any(x["id"] == rid and x["verified"] for x in rows)
    assert ra.moderate_review(world["boss"], rid, False, None) == "ok"


@db_only
def test_dashboard_numbers_are_real(world):
    from chashibondhu.web import repo_admin as ra
    n = ra.dashboard_numbers()
    assert n["farmers"] >= 1 and n["customers"] >= 1 and n["listings_active"] >= 1
    s = ra.series("7d")
    assert s["unit"] == "day" and len(s["rows"]) == 7 and all(r["farmers"] >= 0 for r in s["rows"])
    assert len(ra.series("12m")["rows"]) == 12
    b = ra.breakdowns()
    assert {"status", "category", "district", "recent"} <= set(b)


# ---------------------------------------------------------------- full pages on the real database
@pytest.fixture
def web(monkeypatch):
    from fastapi.testclient import TestClient
    from chashibondhu.api.main import app
    monkeypatch.delenv("CB_ENV", raising=False)
    with TestClient(app) as c:
        yield c


def _login(c, phone, role="admin"):
    c.cookies.clear()
    tok = re.search(r'name="csrf" value="([^"]+)"', c.get(f"/login?as={role}").text).group(1)
    r = c.post("/login", data={"csrf": tok, "phone": phone, "password": PW, "as_role": role}, follow_redirects=False)
    assert r.status_code == 303
    return r


def _tok(c, url):
    return re.search(r'name="csrf" value="([^"]+)"', c.get(url).text).group(1)


@db_only
def test_pages_by_permission(world, web):
    c = web
    r = _login(c, world["phones"]["boss"])
    assert r.headers["location"] == "/admin"
    for url in ("/admin", "/admin?span=12m", "/admin/farmers", f"/admin/farmers/{world['farmer']}", "/admin/consumers",
                f"/admin/consumers/{world['buyer']}", "/admin-products", "/admin-products?avail=out", "/admin-reviews",
                "/admin-staff", "/admin-audit", "/admin/reset-code"):
        assert c.get(url).status_code == 200, url
    assert c.get(f"/admin/farmers/{world['buyer']}").status_code == 404           # a customer is not a farmer
    _login(c, world["phones"]["staff"])                                              # products only
    assert c.get("/admin-products").status_code == 200
    for url in ("/admin", "/admin/farmers", "/admin-staff", "/admin-audit", "/admin-reviews", "/admin/reset-code"):
        assert c.get(url, follow_redirects=False).status_code == 403, url
    tok = _tok(c, "/admin-products")
    assert c.post(f"/admin/farmers/{world['farmer']}/status", data={"csrf": tok, "action": "suspend",
                                                                    "reason": "test"}).status_code == 403
    _login(c, world["phones"]["farmer"], "farmer")
    assert c.get("/admin", follow_redirects=False).status_code == 403


@db_only
def test_suspended_staff_is_logged_out(world, web):
    from chashibondhu.web import repo_admin as ra
    c = web
    _login(c, world["phones"]["staff"])
    assert c.get("/admin-products").status_code == 200
    ra.set_user_status(world["boss"], world["staff"], ("admin",), True, "left the team")
    r = c.get("/admin-products", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/admin?next=")   # admin sign-in lives at /admin
    c.cookies.clear()
    tok = _tok(c, "/login?as=admin")
    r = c.post("/login", data={"csrf": tok, "phone": world["phones"]["staff"], "password": PW, "as_role": "admin"})
    assert r.status_code == 400


@db_only
def test_staff_manager_cannot_make_super(world, web):
    from chashibondhu.web import repo_admin as ra
    c = web
    ra.set_permissions(world["boss"], world["staff"], ["staff"], False)
    _login(c, world["phones"]["staff"])
    tok = _tok(c, "/admin-staff")
    r = c.post(f"/admin-staff/{world['staff']}/permissions", data={"csrf": tok, "perms": ["staff"]},
               follow_redirects=False)
    assert r.status_code == 303 and "own account" in c.get("/admin-staff").text           # self change refused
    assert c.post(f"/admin-staff/{world['boss']}/permissions", data={"csrf": tok, "is_super": "1"},
                  follow_redirects=False).status_code == 403
    r = c.post("/admin-staff/new", data={"csrf": tok, "full_name": "Test New", "phone": "01999999999",
                                         "password": "short", "perms": ["products"]}, follow_redirects=False)
    assert r.status_code == 303 and not any(x["full_name"] == "Test New" for x in ra.list_staff())   # weak password
