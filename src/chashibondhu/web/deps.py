"""Shared helpers for the website: templates, Bangla/English text, logged-in user, CSRF, flash."""
from __future__ import annotations

import csv
import hmac
import secrets
from functools import lru_cache
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape

WEB_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))

_BN_DIGITS = str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")


def t(bn: str, en: str) -> Markup:
    """Both languages in the page; CSS shows the one the visitor chose (no reload)."""
    return Markup(f'<span class="lang-bn">{escape(bn)}</span><span class="lang-en">{escape(en)}</span>')


def num(value, decimals: int = 0) -> Markup:
    """Number in both languages: ১,২৫০ / 1,250."""
    try:
        s = f"{float(value):,.{decimals}f}"
    except (TypeError, ValueError):
        s = str(value or "")
    return Markup(f'<span class="lang-bn">{escape(s.translate(_BN_DIGITS))}</span>'
                  f'<span class="lang-en">{escape(s)}</span>')


def bn_digits(s) -> str:
    return str(s).translate(_BN_DIGITS)


templates.env.globals.update(t=t, num=num)
templates.env.filters["bn_digits"] = bn_digits


# ---------------------------------------------------------------- crops (from data/reference)
def _root() -> Path:
    from chashibondhu.web.db import _root as db_root
    return db_root()


@lru_cache(maxsize=1)
def crops() -> list[dict]:
    """Crop catalogue rows: crop_id, name_bn, name_en (data/reference/crop_catalogue.csv)."""
    path = _root() / "data" / "reference" / "crop_catalogue.csv"
    out = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            cid = (row.get("crop_id") or "").strip()
            if cid:
                out.append({"crop_id": cid, "name_bn": (row.get("name_bn") or cid).strip(),
                            "name_en": (row.get("name_en") or cid).strip()})
    return out


def crop_ids() -> set[str]:
    return {c["crop_id"] for c in crops()}


def crop_name(crop_id: str | None) -> Markup:
    for c in crops():
        if c["crop_id"] == crop_id:
            return t(c["name_bn"], c["name_en"])
    return Markup(escape(crop_id or ""))


templates.env.globals["crop_name"] = crop_name


# ---------------------------------------------------------------- session user
def current_user(request: Request) -> dict | None:
    u = request.session.get("user")
    return u if isinstance(u, dict) and u.get("id") else None


class LoginRequired(Exception):
    """Raised when a page needs a logged-in user (handled -> redirect to /login)."""

    def __init__(self, next_url: str = "/"):
        self.next_url = next_url


def _session_still_valid(request: Request, user: dict) -> bool:
    """After a password reset (or account suspension) old logins stop working.
    Sessions made before migration 005 have no "sv" and are left alone."""
    sv = request.session.get("sv")
    if sv is None:
        return True
    from chashibondhu.web import repo_auth
    return repo_auth.session_version(int(user["id"])) == sv


def _need_login(request: Request) -> LoginRequired:
    return LoginRequired(request.url.path + (f"?{request.url.query}" if request.url.query else ""))


def require_role(request: Request, role: str) -> dict:
    user = current_user(request)
    if not user:
        raise _need_login(request)
    if not _session_still_valid(request, user):
        request.session.clear()
        raise _need_login(request)
    if user.get("role") != role:
        raise HTTPException(status_code=403, detail="not allowed for this account")
    return user


def login_session(request: Request, user: dict) -> None:
    request.session.clear()          # new session on login (prevents session fixation)
    request.session["user"] = {"id": int(user["id"]), "role": user["role"], "name": user["full_name"]}
    request.session["csrf"] = secrets.token_urlsafe(24)
    if user.get("session_version") is not None:   # rows from the database (migration 005)
        request.session["sv"] = int(user["session_version"])


def require_any_role(request: Request, roles: tuple[str, ...]) -> dict:
    """Like require_role, for pages open to several roles (e.g. the farm assistant: farmer + admin)."""
    user = current_user(request)
    if not user:
        raise _need_login(request)
    if not _session_still_valid(request, user):
        request.session.clear()
        raise _need_login(request)
    if user.get("role") not in roles:
        raise HTTPException(status_code=403, detail="not allowed for this account")
    return user


# ---------------------------------------------------------------- CSRF
def csrf_token(request: Request) -> str:
    tok = request.session.get("csrf")
    if not tok:
        tok = secrets.token_urlsafe(24)
        request.session["csrf"] = tok
    return tok


def check_csrf(request: Request, token: str | None) -> None:
    expected = request.session.get("csrf", "")
    if not expected or not token or not hmac.compare_digest(str(token), expected):
        raise HTTPException(status_code=400, detail="form expired, please reload the page")


# ---------------------------------------------------------------- flash messages
def flash(request: Request, kind: str, bn: str, en: str) -> None:
    msgs = request.session.get("flash", [])
    msgs.append([kind, bn, en])
    request.session["flash"] = msgs[-3:]


def pop_flash(request: Request) -> list:
    return request.session.pop("flash", [])


def render(request: Request, name: str, ctx: dict | None = None, status_code: int = 200):
    base = {"request": request, "user": current_user(request), "csrf": csrf_token(request),
            "flashes": pop_flash(request), "crops": crops()}
    base.update(ctx or {})
    return templates.TemplateResponse(request, name, base, status_code=status_code)
