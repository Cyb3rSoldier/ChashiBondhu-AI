"""Test helper for the offline web tests (auth + marketplace B1/B2/B3 + admin).

The login/register routes use repo_auth (role-based identity, migration 005). The offline tests fake `repo`,
so this makes repo_auth read the SAME fake users, and it BLOCKS every real database call from repo_auth,
so an offline test can never write to Supabase again.
"""
from __future__ import annotations

from chashibondhu.web import repo, repo_auth


def _no_db(*_a, **_k):
    raise AssertionError("offline web test tried to use the real database through repo_auth")


def install(monkeypatch, users=lambda: ()):
    """users: optional function returning fake user dicts (only needed for email lookups)."""
    m = monkeypatch.setattr
    for name in ("fetch_one", "execute", "connect"):
        m(repo_auth, name, _no_db)

    def by_phone(phone, role):
        u = repo.get_user_by_phone(phone) if phone else None   # the test's own fake
        return u if u and u.get("role") == role else None

    def find_login_user(role, phone=None, email=None):
        if role in ("farmer", "admin"):
            return by_phone(phone, role)
        if role == "customer" and email:
            return next((u for u in users() if u.get("role") == "customer"
                         and (u.get("email") or "").lower() == email.lower()), None)
        return None

    def find_legacy_customer(phone):
        u = by_phone(phone, "customer")
        return u if u and not u.get("email") else None

    m(repo_auth, "find_login_user", find_login_user)
    m(repo_auth, "find_legacy_customer", find_legacy_customer)
    m(repo_auth, "farmer_phone_taken", lambda phone: by_phone(phone, "farmer") is not None)
    m(repo_auth, "customer_email_taken", lambda email, except_user_id=None: any(
        u.get("role") == "customer" and (u.get("email") or "").lower() == email.lower()
        and u.get("id") != except_user_id for u in users()))
    m(repo_auth, "session_version", lambda uid: 0)
    m(repo_auth, "rate_hit", lambda key, limit, minutes: True)
    m(repo_auth, "create_farmer", lambda *a: repo.create_farmer(*a))       # whatever the test faked
    m(repo_auth, "create_customer", lambda *a: repo.create_customer(*a))

    # Marketplace B1 (migration 006): same rule, no real database from offline tests
    from chashibondhu.web import repo_market_b1 as b1
    for name in ("fetch_one", "fetch_all", "execute", "connect"):
        m(b1, name, _no_db)
    m(b1, "product_extras", lambda cid, lid, fid: {"review_n": 0, "review_avg": None, "reviews": [], "saved": False,
                                                   "following": False, "alert": None, "can_review": False,
                                                   "my_review": None})
    m(b1, "is_following", lambda cid, fid: False)

    # Marketplace B2 (comparison, dashboard request summary)
    from chashibondhu.web import repo_market_b2 as b2
    for name in ("fetch_one", "fetch_all"):
        m(b2, name, _no_db)
    m(b2, "compare_rows", lambda ids: [])
    m(b2, "request_summary", lambda buyer_id: {"open_requests": 0, "need_answer": 0, "waiting_harvest": 0,
                                               "can_order": 0})

    # Shopping assistant (B3): never call a real LLM from offline tests
    from chashibondhu.web import shop_assistant
    m(shop_assistant, "get_client", lambda: None)

    # Admin (A1): no real database from offline tests (admin login audit is best-effort and swallows this)
    from chashibondhu.web import repo_admin
    for name in ("fetch_one", "fetch_all", "connect"):
        m(repo_admin, name, _no_db)


def role_of(users_by_phone: dict, phone: str) -> str:
    """Role of a fake user, for the login form's as_role."""
    tail = "".join(ch for ch in phone if ch.isdigit())[-10:]
    return next((u["role"] for k, u in users_by_phone.items() if k.endswith(tail)), "farmer")
