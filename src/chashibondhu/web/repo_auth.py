"""SQL for role-based identity and password reset (parameterised queries only).

Rules (also enforced by migration 005 in the database):
  farmer  -> phone unique among farmers      admin -> phone unique among admins
  customer-> email unique among customers (lower case); phone required but shared phones are fine
"""
from __future__ import annotations

from decimal import Decimal
from typing import Callable

from chashibondhu.web.db import connect, execute, fetch_one

CODE_MAX_ATTEMPTS = 5


def is_unique_violation(e: BaseException) -> bool:
    for x in (e, getattr(e, "__cause__", None), getattr(e, "__context__", None)):
        if x is not None and getattr(x, "sqlstate", None) == "23505":
            return True
    return False


# ---------------------------------------------------------------- lookups
def find_login_user(role: str, phone: str | None = None, email: str | None = None) -> dict | None:
    """Farmer/admin by phone, customer by email. Never crosses roles."""
    if role in ("farmer", "admin") and phone:
        return fetch_one("SELECT * FROM users WHERE role = %s AND phone = %s", (role, phone))
    if role == "customer" and email:
        return fetch_one("SELECT * FROM users WHERE role = 'customer' AND lower(email) = lower(%s)", (email,))
    return None


def find_legacy_customer(phone: str) -> dict | None:
    """Old customer accounts made before emails were required (log in once by phone, then add email)."""
    return fetch_one("SELECT * FROM users WHERE role = 'customer' AND phone = %s AND email IS NULL "
                     "ORDER BY id LIMIT 1", (phone,))


def farmer_phone_taken(phone: str) -> bool:
    return fetch_one("SELECT 1 AS x FROM users WHERE role = 'farmer' AND phone = %s", (phone,)) is not None


def customer_email_taken(email: str, except_user_id: int | None = None) -> bool:
    return fetch_one("SELECT 1 AS x FROM users WHERE role = 'customer' AND lower(email) = lower(%s) AND id <> %s",
                     (email, except_user_id or 0)) is not None


def session_version(user_id: int) -> int | None:
    r = fetch_one("SELECT session_version, status FROM users WHERE id = %s", (user_id,))
    if not r or r.get("status") != "active":
        return None
    return int(r["session_version"])


# ---------------------------------------------------------------- create (None = duplicate, lost the race)
def create_farmer(full_name: str, phone: str, password_hash: str, district_code: str | None,
                  upazila_code: str | None, land_decimal: Decimal | None, land_text: str | None,
                  main_crops: list[str]) -> int | None:
    try:
        with connect() as conn:
            row = conn.execute(
                "INSERT INTO users (role, full_name, phone, password_hash, district_code, upazila_code) "
                "VALUES ('farmer', %s, %s, %s, %s, %s) RETURNING id",
                (full_name, phone, password_hash, district_code, upazila_code)).fetchone()
            conn.execute("INSERT INTO farmer_profiles (user_id, land_decimal, land_text, main_crops) "
                         "VALUES (%s, %s, %s, %s)", (row["id"], land_decimal, land_text, main_crops))
            return int(row["id"])
    except Exception as e:
        if is_unique_violation(e):
            return None
        raise


def create_customer(full_name: str, email: str, phone: str, password_hash: str, district_code: str | None,
                    upazila_code: str | None, address: str | None) -> int | None:
    try:
        r = fetch_one("INSERT INTO users (role, full_name, email, phone, password_hash, district_code, "
                      "upazila_code, address) VALUES ('customer', %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                      (full_name, email, phone, password_hash, district_code, upazila_code, address))
        return int(r["id"])
    except Exception as e:
        if is_unique_violation(e):
            return None
        raise


def set_customer_email(user_id: int, email: str) -> bool:
    try:
        return execute("UPDATE users SET email = %s WHERE id = %s AND role = 'customer'", (email, user_id)) == 1
    except Exception as e:
        if is_unique_violation(e):
            return False
        raise


# ---------------------------------------------------------------- rate limiting
def rate_hit(key_hash: str, limit: int, window_minutes: int) -> bool:
    """Log one event; True if still under the limit for the window."""
    with connect() as conn:
        conn.execute("DELETE FROM auth_rate_events WHERE created_at < now() - interval '1 day'")
        n = conn.execute("SELECT count(*) AS n FROM auth_rate_events WHERE key_hash = %s "
                         "AND created_at > now() - make_interval(mins => %s)", (key_hash, window_minutes)).fetchone()
        conn.execute("INSERT INTO auth_rate_events (key_hash) VALUES (%s)", (key_hash,))
        return int(n["n"]) < limit


# ---------------------------------------------------------------- resets
def create_reset(user_id: int, channel: str, secret_hash: str, minutes: int, created_by: int | None = None) -> None:
    """New code/link; every older open one for this user stops working."""
    with connect() as conn:
        conn.execute("UPDATE password_resets SET revoked_at = now() WHERE user_id = %s "
                     "AND used_at IS NULL AND revoked_at IS NULL", (user_id,))
        conn.execute("INSERT INTO password_resets (user_id, channel, secret_hash, created_by, expires_at) "
                     "VALUES (%s, %s, %s, %s, now() + make_interval(mins => %s))",
                     (user_id, channel, secret_hash, created_by, minutes))


def email_reset_user(secret_hash: str) -> dict | None:
    """The customer behind a still-valid link, else None."""
    return fetch_one(
        "SELECT u.id, u.full_name, u.email FROM password_resets r JOIN users u ON u.id = r.user_id "
        "WHERE r.secret_hash = %s AND r.channel = 'email' AND r.used_at IS NULL AND r.revoked_at IS NULL "
        "AND r.expires_at > now() AND u.role = 'customer' AND u.status = 'active'", (secret_hash,))


def _finish(conn, user_id: int, reset_id: int, password_hash: str) -> None:
    conn.execute("UPDATE password_resets SET used_at = now() WHERE id = %s", (reset_id,))
    conn.execute("UPDATE password_resets SET revoked_at = now() WHERE user_id = %s AND id <> %s "
                 "AND used_at IS NULL AND revoked_at IS NULL", (user_id, reset_id))
    conn.execute("UPDATE users SET password_hash = %s, session_version = session_version + 1, "
                 "password_changed_at = now(), failed_logins = 0, locked_until = NULL WHERE id = %s",
                 (password_hash, user_id))


def complete_email_reset(secret_hash: str, password_hash: str) -> bool:
    """Single use: the row is locked, so two tabs cannot both use the same link."""
    with connect() as conn:
        r = conn.execute(
            "SELECT r.id, r.user_id FROM password_resets r JOIN users u ON u.id = r.user_id "
            "WHERE r.secret_hash = %s AND r.channel = 'email' AND r.used_at IS NULL AND r.revoked_at IS NULL "
            "AND r.expires_at > now() AND u.status = 'active' FOR UPDATE OF r", (secret_hash,)).fetchone()
        if not r:
            return False
        _finish(conn, int(r["user_id"]), int(r["id"]), password_hash)
        return True


def complete_code_reset(phone: str, matches: Callable[[str], bool], password_hash: str) -> str:
    """Farmer code (SMS or admin). 'ok' | 'bad'. Every wrong try counts against all open codes."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT r.id, r.user_id, r.secret_hash FROM password_resets r JOIN users u ON u.id = r.user_id "
            "WHERE u.role = 'farmer' AND u.phone = %s AND u.status = 'active' AND r.channel IN ('sms', 'admin') "
            "AND r.used_at IS NULL AND r.revoked_at IS NULL AND r.expires_at > now() AND r.attempts < %s "
            "FOR UPDATE OF r", (phone, CODE_MAX_ATTEMPTS)).fetchall()
        for r in rows:
            if matches(r["secret_hash"]):
                _finish(conn, int(r["user_id"]), int(r["id"]), password_hash)
                return "ok"
        if rows:
            conn.execute("UPDATE password_resets SET attempts = attempts + 1 WHERE id = ANY(%s)",
                         ([int(r["id"]) for r in rows],))
        return "bad"
