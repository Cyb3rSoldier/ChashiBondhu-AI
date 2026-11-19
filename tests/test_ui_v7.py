"""UI v7: admin hidden from public pages, /admin is the admin sign-in, split sign-in cards, real logo assets."""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
WEB = ROOT / "src" / "chashibondhu" / "web"


@pytest.fixture
def c(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from chashibondhu.web.app import mount_website
    monkeypatch.setenv("WEB_SESSION_SECRET", "x" * 40)
    app = FastAPI()
    mount_website(app)
    return TestClient(app)


def test_no_admin_link_on_public_pages(c):
    for url in ("/", "/login", "/login?as=customer", "/register", "/register/customer"):
        html = c.get(url).text
        assert "as=admin" not in html and "Admin login" not in html and 'href="/admin' not in html, url


def test_admin_login_lives_at_admin(c):
    r = c.get("/login?as=admin", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/admin"
    page = c.get("/admin").text
    assert 'name="as_role" value="admin"' in page and "Admin Sign In" in page and 'name="csrf"' in page
    r = c.get("/admin-products", follow_redirects=False)                 # any admin page -> admin sign-in
    assert r.status_code == 303 and r.headers["location"].startswith("/admin?next=")
    assert 'value="/admin-products"' in c.get("/admin?next=/admin-products").text
    assert 'value=""' in c.get("/admin?next=https://evil.example").text.split('name="next"')[1][:20]


def test_split_cards_keep_the_same_form_fields(c):
    f = c.get("/login?as=farmer").text
    assert 'action="/login"' in f and 'name="phone"' in f and 'name="password"' in f and 'value="farmer"' in f
    assert "cb-auth2" in f and "data-cb-eye" in f and "/static/img/logo-mark.png" in f
    cu = c.get("/login?as=customer").text
    assert 'name="email"' in cu and 'value="customer"' in cu and "form-first" in cu
    for url, fields in (("/register", ("full_name", "phone", "password", "password2", "land", "main_crops")),
                        ("/register/customer", ("full_name", "email", "phone", "address", "password", "password2"))):
        html = c.get(url).text
        for name in fields:
            assert f'name="{name}"' in html, (url, name)


def test_assets_exist_and_are_small():
    img = WEB / "static" / "img"
    for name, kb in (("logo-mark.png", 120), ("favicon.png", 20), ("hero.jpg", 400), ("hero-sm.jpg", 150), ("auth-farmer.jpg", 150)):
        assert (img / name).exists() and (img / name).stat().st_size < kb * 1024, name
    from PIL import Image
    assert Image.open(img / "logo-mark.png").getpixel((2, 2))[3] == 0          # real transparency, no baked checkerboard


def test_no_t_inside_attributes_in_new_templates():
    for p in [WEB / "templates" / x for x in ("login.html", "register.html", "customer/register.html", "admin/login.html",
                                              "auth/_brand.html", "auth/_pw.html", "farmer/dashboard.html", "customer/dashboard.html")]:
        s = p.read_text(encoding="utf-8")
        assert not re.search(r'="[^"]*\{\{\s*t\(', s), p.name
