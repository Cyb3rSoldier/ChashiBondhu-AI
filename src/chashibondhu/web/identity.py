"""Identity helpers: email normalising, password rules, reset tokens/codes and HMAC hashing.

Nothing secret is stored in clear: link tokens -> sha256, OTP/admin codes -> nonce + HMAC(secret),
rate-limit keys -> HMAC(secret). The secret is WEB_SESSION_SECRET from the environment / .env.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
from functools import lru_cache

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_PASSWORD = 128
COMMON = {"123456", "1234567", "12345678", "123456789", "1234567890", "111111", "000000", "654321",
          "password", "password1", "qwerty", "abc123", "abcdef", "112233", "121212", "123123",
          "chashibondhu", "bangladesh", "iloveyou"}


# ---------------------------------------------------------------- settings
@lru_cache(maxsize=1)
def _dotenv() -> dict:
    """Values from the repo .env (only used when a variable is not in the real environment)."""
    try:
        from chashibondhu.web.db import _root
        path = _root() / ".env"
    except Exception:  # noqa: BLE001
        return {}
    out = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return out


def setting(name: str, default: str = "") -> str:
    v = os.environ.get(name)
    return v if v is not None else _dotenv().get(name, default)


def _secret() -> bytes:
    s = setting("WEB_SESSION_SECRET")
    if len(s) < 16:
        raise RuntimeError("WEB_SESSION_SECRET is missing or too short")
    return s.encode("utf-8")


# ---------------------------------------------------------------- email + password
def normalize_email(raw: str | None) -> str | None:
    """Trim + lower case. None if it does not look like an email."""
    s = (raw or "").strip().lower()
    return s if s and len(s) <= 254 and EMAIL_RE.match(s) else None


def password_problem(password: str, min_length: int, phone: str | None = None) -> tuple[str, str] | None:
    """(bn, en) message if the new password is too weak, else None."""
    if len(password) < min_length:
        return (f"পাসওয়ার্ড অন্তত {min_length} অক্ষরের হতে হবে।", f"Password must have at least {min_length} characters.")
    if len(password) > MAX_PASSWORD:
        return ("পাসওয়ার্ড অনেক লম্বা।", "Password is too long.")
    digits = re.sub(r"\D", "", phone or "")
    if (password.lower() in COMMON or len(set(password)) == 1
            or (digits and password in (digits, digits[-11:], digits[-10:]))):
        return ("এই পাসওয়ার্ড সহজে অনুমান করা যায়। অন্য পাসওয়ার্ড দিন।",
                "This password is too easy to guess. Choose another one.")
    return None


# ---------------------------------------------------------------- tokens and codes
def new_link_token() -> str:
    return secrets.token_urlsafe(32)                      # 256 bits, URL-safe


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def code_hash(code: str) -> str:
    nonce = secrets.token_hex(8)
    return nonce + "$" + hmac.new(_secret(), (nonce + ":" + code).encode(), hashlib.sha256).hexdigest()


def code_matches(code: str, stored: str) -> bool:
    try:
        nonce, digest = stored.split("$", 1)
    except ValueError:
        return False
    calc = hmac.new(_secret(), (nonce + ":" + code).encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(calc, digest)


def clean_code(raw: str | None) -> str:
    return re.sub(r"\D", "", (raw or "").translate(str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")))[:6]


def rate_key(kind: str, value: str) -> str:
    return hmac.new(_secret(), f"{kind}:{value}".encode(), hashlib.sha256).hexdigest()
