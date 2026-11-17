"""Role-based identity + password reset tests.

Unit tests always run. Database tests write real (random, cleaned-up) users, so they run only when asked:
    $env:CB_AUTH_DB_TESTS="1"; python -m pytest tests/test_auth_identity.py -q
Needs migration 005 in the database.
"""
from __future__ import annotations

import os
import re
import secrets
import threading

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from chashibondhu.web import identity  # noqa: E402

DB = os.environ.get("CB_AUTH_DB_TESTS") == "1"
db_only = pytest.mark.skipif(not DB, reason="set CB_AUTH_DB_TESTS=1 to run database tests")
PW = "Shapla#2026"


# ================================================================ unit
def test_email_normalised_and_checked():
    assert identity.normalize_email("  Rahim@Gmail.COM ") == "rahim@gmail.com"
    for bad in ("", "rahim", "a@b", "a b@c.com", None):
        assert identity.normalize_email(bad) is None


def test_password_rules():
    assert identity.password_problem("Shapla#2026", 6) is None
    assert identity.password_problem("12345", 6)                     # too short
    assert identity.password_problem("123456", 6)                    # common
    assert identity.password_problem("aaaaaaa", 6)                   # one letter
    assert identity.password_problem("01712345678", 6, "+8801712345678")   # own phone
    assert identity.password_problem("x" * 129, 6)


def test_codes_hashed_with_nonce(monkeypatch):
    monkeypatch.setenv("WEB_SESSION_SECRET", "s" * 32)
    code = identity.new_code()
    assert re.fullmatch(r"\d{6}", code)
    h1, h2 = identity.code_hash(code), identity.code_hash(code)
    assert h1 != h2 and code not in h1                                # same code, different stored value
    assert identity.code_matches(code, h1) and not identity.code_matches("000000" if code != "000000" else "1", h1)
    assert identity.clean_code(" ১২৩ ৪৫৬ ") == "123456"
    t = identity.new_link_token()
    assert len(t) >= 40 and identity.token_hash(t) != t


def test_console_senders_refused_in_production(monkeypatch):
    from chashibondhu.web import notify
    monkeypatch.setenv("CB_SMS_PROVIDER", "console")
    monkeypatch.setenv("CB_MAIL_PROVIDER", "console")
    monkeypatch.setenv("CB_ENV", "production")
    assert not notify.sms_enabled() and not notify.mail_enabled()
    monkeypatch.setenv("CB_ENV", "dev")
    assert notify.sms_enabled() and notify.mail_enabled()


# ================================================================ database helpers
def phone() -> str:
    return "017" + f"{secrets.randbelow(10**8):08d}"


def norm(p: str) -> str:
    return "+88" + p


def email() -> str:
    return f"t{secrets.token_hex(5)}@test.example.com"


@pytest.fixture
def app_client(monkeypatch):
    from fastapi.testclient import TestClient
    from chashibondhu.api.main import app
    monkeypatch.setenv("CB_MAIL_PROVIDER", "console")
    monkeypatch.setenv("CB_SMS_PROVIDER", "")
    monkeypatch.delenv("CB_ENV", raising=False)
    made: list[str] = []
    from chashibondhu.web.db import execute
    test_ip_keys = [identity.rate_key(k, "testclient") for k in ("forgot_ip", "verify_ip", "link_ip")]
    execute("DELETE FROM auth_rate_events WHERE key_hash = ANY(%s)", (test_ip_keys,))   # TestClient's own IP only
    with TestClient(app) as c:
        c.made = made
        yield c
    execute("DELETE FROM auth_rate_events WHERE key_hash = ANY(%s)", (test_ip_keys,))
    for key in made:                                       # clean up every user this test created
        col = "email" if "@" in key else "phone"
        execute(f"DELETE FROM farmer_profiles WHERE user_id IN (SELECT id FROM users WHERE {col} = %s)", (key,))
        execute(f"DELETE FROM users WHERE {col} = %s", (key,))


def csrf(c, url: str) -> str:
    r = c.get(url)
    m = re.search(r'name="csrf" value="([^"]+)"', r.text)
    assert m, f"no csrf on {url}: {r.status_code}"
    return m.group(1)


def reg_farmer(c, p: str, pw: str = PW):
    c.made.append(norm(p))
    c.cookies.clear()
    return c.post("/register", data={"csrf": csrf(c, "/register"), "full_name": "Test Farmer", "phone": p,
                                     "password": pw, "password2": pw}, follow_redirects=False)


def reg_customer(c, mail: str | None, p: str | None, pw: str = PW):
    if mail:
        c.made.append(mail.strip().lower())
    c.cookies.clear()
    return c.post("/register/customer", data={"csrf": csrf(c, "/register/customer"), "full_name": "Test Buyer",
                                              "email": mail or "", "phone": p or "", "password": pw,
                                              "password2": pw}, follow_redirects=False)


def login(c, role: str, ident: str, pw: str = PW):
    c.cookies.clear()
    field = "email" if role == "customer" else "phone"
    return c.post("/login", data={"csrf": csrf(c, f"/login?as={role}"), field: ident, "password": pw,
                                  "as_role": role}, follow_redirects=False)


# ================================================================ registration rules (1-11)
@db_only
def test_registration_rules(app_client):
    c = app_client
    p, p2, m = phone(), phone(), email()
    assert reg_farmer(c, p).status_code == 303                                     # 1 new farmer phone
    r = reg_farmer(c, p)                                                           # 2 same farmer phone
    assert r.status_code == 400 and "already registered as a Farmer" in r.text
    assert reg_customer(c, m, p).status_code == 303                                # 7 phone used by a farmer
    m2 = email()
    assert reg_customer(c, m2, p).status_code == 303                               # 6 phone used by a customer
    p3 = phone()
    assert reg_customer(c, email(), p2).status_code == 303
    assert reg_farmer(c, p2).status_code == 303                                    # 3 phone used by a customer
    r = reg_customer(c, m, p3)                                                     # 5 duplicate email
    assert r.status_code == 400 and "already registered" in r.text
    r = reg_customer(c, "  " + m.upper() + " ", p3)                                # 11 case-insensitive
    assert r.status_code == 400 and "already registered" in r.text
    r = reg_customer(c, None, p3)                                                  # 8 no email
    assert r.status_code == 400 and "Email address is required" in r.text
    r = reg_customer(c, email(), None)                                             # 9 no phone
    assert r.status_code == 400 and "Phone number is required" in r.text
    c.cookies.clear()
    r = c.post("/register", data={"csrf": csrf(c, "/register"), "full_name": "X Y", "phone": "",
                                  "password": PW, "password2": PW})                # 10 farmer without phone
    assert r.status_code == 400 and "Phone number is required" in r.text


@db_only
def test_database_blocks_duplicates_even_without_the_app():
    from chashibondhu.web.db import execute
    p, m = norm(phone()), email()
    try:
        execute("INSERT INTO users (role, full_name, phone, password_hash) VALUES ('farmer','Test A',%s,'x')", (p,))
        with pytest.raises(Exception):
            execute("INSERT INTO users (role, full_name, phone, password_hash) VALUES ('farmer','Test B',%s,'x')", (p,))
        execute("INSERT INTO users (role, full_name, phone, email, password_hash) VALUES ('customer','Test C',%s,%s,'x')", (p, m))
        with pytest.raises(Exception):
            execute("INSERT INTO users (role, full_name, phone, email, password_hash) VALUES "
                    "('customer','Test D',%s,%s,'x')", (p, m.upper()))
        with pytest.raises(Exception):                                             # customer without email
            execute("INSERT INTO users (role, full_name, phone, password_hash) VALUES ('customer','Test E',%s,'x')", (p,))
    finally:
        execute("DELETE FROM users WHERE phone = %s", (p,))


# ================================================================ concurrency (12, 13)
def _race(fn, n: int = 6) -> list:
    out, barrier = [], threading.Barrier(n)

    def run():
        barrier.wait()
        out.append(fn())
    ts = [threading.Thread(target=run) for _ in range(n)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    return out


@db_only
def test_concurrent_farmer_same_phone_only_one_wins():
    from chashibondhu.web import repo_auth
    from chashibondhu.web.db import execute
    p = norm(phone())
    try:
        res = _race(lambda: repo_auth.create_farmer("Race Test", p, "x", None, None, None, None, []))
        assert sum(1 for r in res if r) == 1 and res.count(None) == len(res) - 1
    finally:
        execute("DELETE FROM farmer_profiles WHERE user_id IN (SELECT id FROM users WHERE phone = %s)", (p,))
        execute("DELETE FROM users WHERE phone = %s", (p,))


@db_only
def test_concurrent_customer_same_email_only_one_wins():
    from chashibondhu.web import repo_auth
    from chashibondhu.web.db import execute
    m = email()
    try:
        res = _race(lambda: repo_auth.create_customer("Race Test", m, norm(phone()), "x", None, None, None))
        assert sum(1 for r in res if r) == 1
    finally:
        execute("DELETE FROM users WHERE email = %s", (m,))


# ================================================================ login (14, 15, 16)
@db_only
def test_login_by_role(app_client):
    c = app_client
    p, m = phone(), email()
    reg_farmer(c, p)
    reg_customer(c, m, p)                                       # same phone, other role
    r = login(c, "farmer", p)
    assert r.status_code == 303 and r.headers["location"] == "/farmer"
    r = login(c, "customer", m.upper())
    assert r.status_code == 303 and r.headers["location"] != "/farmer"
    assert login(c, "customer", p).status_code == 400           # phone is not a customer login (has email)
    assert login(c, "farmer", m).status_code == 400
    assert login(c, "admin", p).status_code == 400              # never crosses roles
    assert login(c, "farmer", p, "wrong-pass").status_code == 400


@db_only
def test_old_customer_without_email_still_logs_in_and_adds_email(app_client):
    from chashibondhu.web.db import execute
    from chashibondhu.web.passwords import hash_password
    c, p, m = app_client, phone(), email()
    c.made += [norm(p), m]
    execute("ALTER TABLE users DISABLE TRIGGER trg_users_require_customer_email")   # make a pre-005 customer
    try:
        execute("INSERT INTO users (role, full_name, phone, password_hash) VALUES ('customer','Old Buyer',%s,%s)",
                (norm(p), hash_password(PW)))
    finally:
        execute("ALTER TABLE users ENABLE TRIGGER trg_users_require_customer_email")
    r = login(c, "customer", p)
    assert r.status_code == 303 and r.headers["location"] == "/account/email"
    r = c.post("/account/email", data={"csrf": csrf(c, "/account/email"), "email": m, "password": PW},
               follow_redirects=False)
    assert r.status_code == 303
    assert login(c, "customer", m).status_code == 303
    assert login(c, "customer", p).status_code == 400            # phone login closes once email exists


# ================================================================ customer reset by email link
@db_only
def test_customer_reset_link_flow(app_client, monkeypatch):
    from chashibondhu.web import notify
    sent = []
    monkeypatch.setattr(notify, "send_reset_email", lambda to, name, token, minutes: sent.append(token) or True)
    c, m = app_client, email()
    reg_customer(c, m, phone())
    login(c, "customer", m)
    old_cookie = dict(c.cookies)                                     # a login made BEFORE the reset
    assert c.get("/customer", follow_redirects=False).status_code == 200

    c.cookies.clear()
    r = c.post("/forgot/customer", data={"csrf": csrf(c, "/forgot/customer"), "email": m})
    r_none = c.post("/forgot/customer", data={"csrf": csrf(c, "/forgot/customer"), "email": email()})
    assert r.status_code == r_none.status_code == 200
    assert r.text.count("If this email has a customer account") == r_none.text.count("If this email has a customer account") == 1
    assert len(sent) == 1                                            # only the real account got a mail
    token = sent[0]

    r = c.get(f"/reset/{token}", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/reset/new"
    assert r.headers.get("referrer-policy") == "no-referrer"
    page = c.get("/reset/new")
    assert m in page.text and token not in page.text
    r = c.post("/reset/new", data={"csrf": csrf(c, "/reset/new"), "password": "123456", "password2": "123456"})
    assert r.status_code == 400 and "too easy" in r.text
    r = c.post("/reset/new", data={"csrf": csrf(c, "/reset/new"), "password": "NewPass#99",
                                   "password2": "NewPass#99"}, follow_redirects=False)
    assert r.status_code == 303 and "as=customer" in r.headers["location"]

    assert c.get(f"/reset/{token}", follow_redirects=False).status_code == 400        # used once only
    assert login(c, "customer", m).status_code == 400                                  # old password dead
    assert login(c, "customer", m, "NewPass#99").status_code == 303
    c.cookies.clear()
    c.cookies.update(old_cookie)                                                       # the old login...
    assert c.get("/customer", follow_redirects=False).status_code == 303               # ...is logged out


@db_only
def test_reset_link_expired_or_fake(app_client, monkeypatch):
    from chashibondhu.web import notify
    from chashibondhu.web.db import execute
    sent = []
    monkeypatch.setattr(notify, "send_reset_email", lambda to, name, token, minutes: sent.append(token) or True)
    c, m = app_client, email()
    reg_customer(c, m, phone())
    c.cookies.clear()
    c.post("/forgot/customer", data={"csrf": csrf(c, "/forgot/customer"), "email": m})
    execute("UPDATE password_resets SET expires_at = now() - interval '1 minute' WHERE secret_hash = %s",
            (identity.token_hash(sent[0]),))
    assert c.get(f"/reset/{sent[0]}", follow_redirects=False).status_code == 400
    assert c.get("/reset/" + "A" * 43, follow_redirects=False).status_code == 400
    assert c.get("/reset/new").status_code == 400


@db_only
def test_new_link_cancels_older_link(app_client, monkeypatch):
    from chashibondhu.web import notify
    sent = []
    monkeypatch.setattr(notify, "send_reset_email", lambda to, name, token, minutes: sent.append(token) or True)
    c, m = app_client, email()
    reg_customer(c, m, phone())
    c.cookies.clear()
    for _ in range(2):
        c.post("/forgot/customer", data={"csrf": csrf(c, "/forgot/customer"), "email": m})
    assert c.get(f"/reset/{sent[0]}", follow_redirects=False).status_code == 400
    assert c.get(f"/reset/{sent[1]}", follow_redirects=False).status_code == 303


# ================================================================ farmer reset by code
def _admin(c):
    from chashibondhu.web.db import fetch_one
    from chashibondhu.web.passwords import hash_password
    p = phone()
    c.made.append(norm(p))
    uid = fetch_one("INSERT INTO users (role, full_name, phone, password_hash) VALUES ('admin','Test Admin',%s,%s) "
                    "RETURNING id", (norm(p), hash_password(PW)))["id"]
    if fetch_one("SELECT to_regclass('public.admin_staff') AS t")["t"]:          # migration 007: give the permission
        fetch_one("INSERT INTO admin_staff (user_id, permissions) VALUES (%s, '{farmers}') RETURNING user_id", (uid,))
    assert login(c, "admin", p).status_code == 303


@db_only
def test_farmer_reset_with_admin_code(app_client):
    c, p = app_client, phone()
    reg_farmer(c, p)
    login(c, "farmer", p)
    farmer_cookie = dict(c.cookies)
    _admin(c)
    r = c.post("/admin/reset-code", data={"csrf": csrf(c, "/admin/reset-code"), "phone": p})
    code = re.search(r"letter-spacing:\.3em\">(\d{6})<", r.text).group(1)
    c.cookies.clear()
    page = c.get("/forgot/farmer")
    assert "Call the ChashiBondhu admin" in page.text                  # no SMS set -> honest message

    def try_code(cd, pw="Krishok#77"):
        return c.post("/forgot/farmer/code", data={"csrf": csrf(c, "/forgot/farmer/code"), "phone": p,
                                                   "code": cd, "password": pw, "password2": pw},
                      follow_redirects=False)
    wrong = "000000" if code != "000000" else "111111"
    r = try_code(wrong)
    assert r.status_code == 400 and "wrong or expired" in r.text
    r = try_code(code)
    assert r.status_code == 303 and "as=farmer" in r.headers["location"]
    assert try_code(code).status_code == 400                             # single use
    assert login(c, "farmer", p, "Krishok#77").status_code == 303
    c.cookies.clear()
    c.cookies.update(farmer_cookie)
    assert c.get("/farmer", follow_redirects=False).status_code == 303   # old session ended


@db_only
def test_farmer_code_dies_after_5_wrong_tries(app_client):
    c, p = app_client, phone()
    reg_farmer(c, p)
    _admin(c)
    r = c.post("/admin/reset-code", data={"csrf": csrf(c, "/admin/reset-code"), "phone": p})
    code = re.search(r"letter-spacing:\.3em\">(\d{6})<", r.text).group(1)
    c.cookies.clear()
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        c.post("/forgot/farmer/code", data={"csrf": csrf(c, "/forgot/farmer/code"), "phone": p, "code": wrong,
                                            "password": "Krishok#77", "password2": "Krishok#77"})
    r = c.post("/forgot/farmer/code", data={"csrf": csrf(c, "/forgot/farmer/code"), "phone": p, "code": code,
                                            "password": "Krishok#77", "password2": "Krishok#77"})
    assert r.status_code == 400                                          # even the right code is dead now


@db_only
def test_farmer_sms_flow_and_generic_answer(app_client, monkeypatch):
    from chashibondhu.web import notify
    texts = []
    monkeypatch.setenv("CB_SMS_PROVIDER", "console")
    monkeypatch.setattr(notify, "send_sms", lambda ph, text: texts.append((ph, text)) or True)
    c, p = app_client, phone()
    reg_farmer(c, p)
    c.cookies.clear()
    r1 = c.post("/forgot/farmer", data={"csrf": csrf(c, "/forgot/farmer"), "phone": p})
    r2 = c.post("/forgot/farmer", data={"csrf": csrf(c, "/forgot/farmer"), "phone": phone()})   # no account
    assert r1.status_code == r2.status_code == 200
    assert "If this number has a farmer account" in r1.text and "If this number has a farmer account" in r2.text
    assert len(texts) == 1 and texts[0][0] == norm(p)
    code = re.search(r"code: (\d{6})", texts[0][1]).group(1)
    r = c.post("/forgot/farmer/code", data={"csrf": csrf(c, "/forgot/farmer/code"), "phone": p, "code": code,
                                            "password": "Krishok#77", "password2": "Krishok#77"},
               follow_redirects=False)
    assert r.status_code == 303


@db_only
def test_rate_limit_on_forgot(app_client, monkeypatch):
    from chashibondhu.web import notify
    monkeypatch.setattr(notify, "send_reset_email", lambda *a: True)
    c, m = app_client, email()
    codes = [c.post("/forgot/customer", data={"csrf": csrf(c, "/forgot/customer"), "email": m}).status_code
             for _ in range(4)]
    assert codes[:3] == [200, 200, 200] and codes[3] == 429


@db_only
def test_admin_page_is_admin_only(app_client):
    c, p = app_client, phone()
    reg_farmer(c, p)
    login(c, "farmer", p)
    assert c.get("/admin/reset-code", follow_redirects=False).status_code == 403
