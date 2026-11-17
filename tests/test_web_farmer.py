"""Website step 2 (farmer side): register, login, pages, listings, farm, AI ask.

Uses an in-memory fake instead of Supabase, so the tests run offline.
"""
import re
import sys
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))   # tests/fake_auth.py

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from chashibondhu.web import repo, routes_ai  # noqa: E402
from chashibondhu.web.app import mount_website  # noqa: E402


class FakeDB:
    def __init__(self):
        self.users, self.profiles, self.listings, self.plots, self.plantings = {}, {}, {}, {}, {}
        self.messages, self.feedback = {}, []
        self.next = 1

    def nid(self):
        self.next += 1
        return self.next


@pytest.fixture()
def client(monkeypatch, tmp_path):
    db = FakeDB()
    monkeypatch.setenv("WEB_SESSION_SECRET", "x" * 40)
    monkeypatch.setattr("chashibondhu.web.images.uploads_dir", lambda: tmp_path)

    def get_user_by_phone(phone):
        return next((u for u in db.users.values() if u["phone"] == phone), None)

    def create_farmer(name, phone, pw_hash, district, upazila, land, land_text, crops):
        uid = db.nid()
        db.users[uid] = {"id": uid, "role": "farmer", "full_name": name, "phone": phone, "password_hash": pw_hash,
                         "status": "active", "district_code": district, "upazila_code": upazila}
        db.profiles[uid] = {"land_decimal": land, "land_text": land_text, "main_crops": crops, "has_irrigation": None}
        return uid

    def get_farmer_profile(uid):
        return {**db.users[uid], **db.profiles.get(uid, {})}

    def update_farmer_profile(uid, name, district, upazila, land, land_text, crops, irrigation):
        db.users[uid].update(full_name=name, district_code=district, upazila_code=upazila)
        db.profiles[uid].update(land_decimal=land, land_text=land_text, main_crops=crops, has_irrigation=irrigation)

    def create_listing(fid, data, image, district, upazila):
        lid = db.nid()
        db.listings[lid] = {**data, "id": lid, "farmer_id": fid, "image_path": image, "farmer_name": "x"}
        return lid

    def update_listing(fid, lid, data, image):
        if lid not in db.listings or db.listings[lid]["farmer_id"] != fid:
            return 0
        db.listings[lid].update(data)
        if image:
            db.listings[lid]["image_path"] = image
        return 1

    def add_plot(fid, name, area, land_type, irrigation, upazila):
        pid = db.nid()
        db.plots[pid] = {"id": pid, "farmer_id": fid, "name": name, "area_decimal": area, "land_type": land_type,
                         "irrigation": irrigation}
        return pid

    def add_planting(fid, plot_id, crop_id, variety, season, p_on, h_on, status):
        if plot_id not in db.plots or db.plots[plot_id]["farmer_id"] != fid:
            return None
        pid = db.nid()
        db.plantings[pid] = {"id": pid, "farmer_id": fid, "plot_id": plot_id, "plot_name": db.plots[plot_id]["name"],
                             "crop_id": crop_id, "variety": variety, "season": season, "planted_on": p_on,
                             "expected_harvest_on": h_on, "status": status}
        return pid

    def add_ai_message(conv, role, content, **kw):
        mid = db.nid()
        db.messages[mid] = {"conv": conv, "role": role, "content": content, **kw}
        return mid

    fakes = {
        "get_user_by_phone": get_user_by_phone, "get_user": lambda uid: db.users.get(uid),
        "create_farmer": create_farmer, "is_locked": lambda u: False, "record_login": lambda uid, ok: None,
        "get_farmer_profile": get_farmer_profile, "update_farmer_profile": update_farmer_profile,
        "farmer_stats": lambda fid: {"active_listings": sum(1 for l in db.listings.values() if l["farmer_id"] == fid),
                                     "growing": 0, "new_orders": 0, "earned": 0},
        "list_plots": lambda fid: [p for p in db.plots.values() if p["farmer_id"] == fid],
        "add_plot": add_plot, "delete_plot": lambda fid, pid: int(bool(db.plots.pop(pid, None))),
        "list_plantings": lambda fid: [p for p in db.plantings.values() if p["farmer_id"] == fid],
        "add_planting": add_planting, "set_planting_status": lambda fid, pid, st: 1,
        "list_my_listings": lambda fid: [l for l in db.listings.values() if l["farmer_id"] == fid],
        "get_my_listing": lambda fid, lid: (db.listings.get(lid) if db.listings.get(lid, {}).get("farmer_id") == fid else None),
        "create_listing": create_listing, "update_listing": update_listing,
        "set_listing_status": lambda fid, lid, st: 1,
        "public_listings": lambda limit=8: list(db.listings.values())[:limit],
        "public_counts": lambda: {"farmers": len(db.users), "listings": len(db.listings), "districts": 1},
        "farmer_order_items": lambda fid: [], "set_item_farmer_status": lambda fid, iid, st: 1,
        "new_conversation": lambda uid: db.nid(), "add_ai_message": add_ai_message,
        "add_feedback": lambda mid, uid, helpful, comment: db.feedback.append((mid, uid, helpful)),
        "message_in_conversation": lambda mid, conv: db.messages.get(mid, {}).get("conv") == conv,
        "recent_questions": lambda uid, limit=5: [],
    }
    for name, fn in fakes.items():
        monkeypatch.setattr(repo, name, fn)
    from fake_auth import install
    install(monkeypatch, lambda: db.users.values())

    class FakeAssistant:
        def ask(self, q):
            return {"question": q, "status": "verified", "answer": "✅ বই থেকে উত্তর", "verified": "", "advice": "",
                    "sources": [{"n": 1, "source": "BARI", "source_id": "b", "printed_page": 35, "pdf_page": 60,
                                 "excerpt": "..."}], "removed_sentences": [], "notes": [], "search_query": q,
                    "model": "fake-model", "cached": False, "llm_requests": 1}

    monkeypatch.setattr(routes_ai, "load_assistant", lambda: FakeAssistant())
    app = FastAPI()
    mount_website(app)
    c = TestClient(app)
    c.db = db
    return c


def csrf_of(html: str) -> str:
    m = re.search(r'name="csrf" value="([^"]+)"', html) or re.search(r'name="csrf-token" content="([^"]+)"', html)
    assert m, "csrf token missing"
    return m.group(1)


def register(c, phone="01712345678"):
    tok = csrf_of(c.get("/register").text)
    return c.post("/register", data={"csrf": tok, "full_name": "রহিম মিয়া", "phone": phone, "password": "secret12",
                                     "password2": "secret12", "upazila_code": "BD55850001", "land": "2",
                                     "land_unit": "bigha", "main_crops": ["potato", "not_a_crop"]},
                  follow_redirects=False)


def test_home_and_public_pages(client):
    for path in ("/", "/login", "/register"):
        r = client.get(path)
        assert r.status_code == 200, path
        assert "চাষীবন্ধু" in r.text
    # the farm assistant is for farmers + admins only: a guest is sent to login (question kept)
    r = client.get("/assistant?q=x", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/login?next=/assistant")


def test_farmer_pages_need_login(client):
    r = client.get("/farmer", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/login?next=/farmer")


def test_register_creates_farmer_and_logs_in(client):
    r = register(client)
    assert r.status_code == 303 and r.headers["location"] == "/farmer"
    (uid, user), = client.db.users.items()
    assert user["phone"] == "+8801712345678" and user["district_code"] == "BD5585"
    assert user["password_hash"].startswith("scrypt$") and "secret12" not in user["password_hash"]
    prof = client.db.profiles[uid]
    assert prof["land_decimal"] == Decimal("66.00") and prof["main_crops"] == ["potato"]
    page = client.get("/farmer")
    assert page.status_code == 200 and "রহিম মিয়া" in page.text


def test_register_validation_and_duplicate(client):
    tok = csrf_of(client.get("/register").text)
    bad = client.post("/register", data={"csrf": tok, "full_name": "X", "phone": "123", "password": "1",
                                         "password2": "2"})
    assert bad.status_code == 400 and "মোবাইল" in bad.text
    register(client)
    client.post("/logout", data={"csrf": csrf_of(client.get("/farmer").text)})
    again = register(client)
    assert again.status_code == 400 and "আগেই একটি কৃষক অ্যাকাউন্ট" in again.text


def test_csrf_required(client):
    client.get("/register")
    r = client.post("/register", data={"csrf": "wrong", "full_name": "A B", "phone": "01712345678",
                                       "password": "secret12", "password2": "secret12"})
    assert r.status_code == 400 and not client.db.users


def test_login_logout(client):
    register(client)
    client.post("/logout", data={"csrf": csrf_of(client.get("/farmer").text)})
    assert client.get("/farmer", follow_redirects=False).status_code == 303
    tok = csrf_of(client.get("/login").text)
    wrong = client.post("/login", data={"csrf": tok, "phone": "01712345678", "password": "nope-nope"})
    assert wrong.status_code == 400
    ok = client.post("/login", data={"csrf": tok, "phone": "০১৭১২৩৪৫৬৭৮", "password": "secret12"},
                     follow_redirects=False)
    assert ok.status_code == 303 and ok.headers["location"] == "/farmer"


def test_listing_create_with_photo_and_expected_rules(client):
    from io import BytesIO
    from PIL import Image
    register(client)
    tok = csrf_of(client.get("/farmer/listings/new").text)
    buf = BytesIO(); Image.new("RGB", (300, 200), (50, 150, 50)).save(buf, "JPEG")
    base = {"csrf": tok, "listing_type": "available", "crop_id": "potato", "title": "ডায়মন্ড আলু",
            "category": "vegetable", "unit": "kg", "price_per_unit": "৩৫", "quantity": "500", "min_order": "5"}
    r = client.post("/farmer/listings/new", data=base, files={"image": ("a.jpg", buf.getvalue(), "image/jpeg")},
                    follow_redirects=False)
    assert r.status_code == 303
    (lid, item), = client.db.listings.items()
    assert item["price_per_unit"] == Decimal("35.00") and item["image_path"].startswith("/media/listings/")
    assert client.get(item["image_path"]).status_code == 200
    exp = client.post("/farmer/listings/new", data={**base, "listing_type": "expected"})
    assert exp.status_code == 400 and "তারিখ" in exp.text
    zero = client.post("/farmer/listings/new", data={**base, "price_per_unit": "0"})
    assert zero.status_code == 400
    assert client.get("/farmer/listings").status_code == 200
    assert "ডায়মন্ড আলু" in client.get("/").text


def test_farm_plot_and_planting(client):
    register(client)
    tok = csrf_of(client.get("/farmer/farm").text)
    client.post("/farmer/farm/plots", data={"csrf": tok, "name": "বাড়ির পাশের জমি", "area_decimal": "33",
                                            "land_type": "medium_high", "irrigation": "yes"})
    (pid, plot), = client.db.plots.items()
    r = client.post("/farmer/farm/plantings", data={"csrf": tok, "plot_id": pid, "crop_id": "potato",
                                                    "planted_on": "2026-11-01", "expected_harvest_on": "2027-02-10"},
                    follow_redirects=False)
    assert r.status_code == 303 and len(client.db.plantings) == 1
    bad = client.post("/farmer/farm/plantings", data={"csrf": tok, "plot_id": pid, "crop_id": "potato",
                                                      "planted_on": "2026-11-01", "expected_harvest_on": "2026-10-01"})
    assert bad.status_code == 200 and len(client.db.plantings) == 1
    page = client.get("/farmer/farm")
    assert "আগাম বিক্রি" in page.text


def test_ai_ask_saves_history_and_feedback(client):
    register(client)
    tok = csrf_of(client.get("/assistant").text)
    no_csrf = client.post("/app/ai/ask", json={"question": "আলু কখন লাগাব?"})
    assert no_csrf.status_code == 400
    r = client.post("/app/ai/ask", json={"question": "আলু কখন লাগাব?"}, headers={"X-CSRF-Token": tok})
    assert r.status_code == 200 and r.json()["status"] == "verified"
    mid = r.json()["message_id"]
    roles = [m["role"] for m in client.db.messages.values()]
    assert roles == ["user", "assistant"]
    fb = client.post("/app/ai/feedback", json={"message_id": mid, "helpful": True}, headers={"X-CSRF-Token": tok})
    assert fb.status_code == 200 and client.db.feedback[0][2] is True
    short = client.post("/app/ai/ask", json={"question": "a"}, headers={"X-CSRF-Token": tok})
    assert short.status_code == 422


def test_guest_cannot_use_ai(client):
    tok = csrf_of(client.get("/login").text)
    r = client.post("/app/ai/ask", json={"question": "আলুর রোগ?"}, headers={"X-CSRF-Token": tok})
    assert r.status_code == 401 and r.json()["detail"] == "login_required"
    assert not client.db.messages


def test_farmer_rate_limit(client):
    register(client)
    tok = csrf_of(client.get("/assistant").text)
    codes = [client.post("/app/ai/ask", json={"question": "আলুর রোগ?"}, headers={"X-CSRF-Token": tok}).status_code
             for _ in range(routes_ai.LIMIT_USER + 1)]
    assert codes[0] == 200 and codes[-1] == 429
