"""AI chat redesign (Fosholi + Dr. Krishi): checked photo diagnosis (one crop, no mixing, honest sure-ness),
chat history (list / search / rename / delete / open, owner + assistant checked), shared page.
Database tests: $env:CB_DB_TESTS="1" (needs migrations 010 + 012)."""
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

from chashibondhu.assistant import diagnosis as dx  # noqa: E402

JUTE = {"is_plant": True, "image_quality": "good", "crop": {"bn": "পাট", "en": "Jute", "sure": True},
        "diagnosis": {"bn": "কাণ্ড পচা রোগ", "en": "Stem Rot", "scientific_name": "Macrophomina phaseolina", "confidence": "medium"},
        "observed_symptoms": ["কাণ্ডে কালচে বাদামি দাগ", "টমেটো পাতায় হলুদ দাগ"],
        "typical_symptoms": ["গাছ ঢলে পড়ে", "বেগুনের ফল পচে যায়"],
        "possible_causes": ["জমিতে পানি জমে থাকা", "Tomato leaf curl virus"],
        "immediate_actions": ["আক্রান্ত গাছ তুলে ফেলুন", "জমিতে পানি জমতে দেবেন না", "কার্বেন্ডাজিম ২ গ্রাম দিন"],
        "prevention": ["রোগমুক্ত বীজ ব্যবহার করুন", "৮০% জমিতে আক্রমণ হলে…"], "risk_level": "high",
        "follow_up_questions": ["এই রোগ কীভাবে ছড়ায়?", "টমেটোতেও কি হয়?"], "summary": "পাটের কাণ্ড পচা রোগ হতে পারে।"}


# ================================================================ diagnosis consistency
def test_one_crop_only_no_mixing():
    p = dx.check(JUTE)
    text = " ".join(str(v) for v in p.values())
    assert p["crop"]["key"] == "jute" and p["diagnosis"]["bn"] == "কাণ্ড পচা রোগ"
    assert "টমেটো" not in text and "Tomato" not in text and "বেগুন" not in text
    assert p["observed_symptoms"] == ["কাণ্ডে কালচে বাদামি দাগ"] and p["typical_symptoms"] == ["গাছ ঢলে পড়ে"]
    assert p["immediate_actions"] == ["আক্রান্ত গাছ তুলে ফেলুন", "জমিতে পানি জমতে দেবেন না"]   # chemical + dose gone
    assert p["prevention"] == ["রোগমুক্ত বীজ ব্যবহার করুন"]                                        # invented % gone
    assert p["follow_up_questions"] == ["এই রোগ কীভাবে ছড়ায়?"] and p["risk_level"] == "high"
    assert p["diagnosis"]["scientific_name"] == "Macrophomina phaseolina" and p["removed"] >= 6


def test_problem_naming_another_crop_becomes_uncertain():
    p = dx.check({**JUTE, "diagnosis": {"bn": "টমেটোর পাতা কোঁকড়ানো", "en": "Tomato leaf curl", "confidence": "high"}})
    assert p["status"] == "uncertain" and p["diagnosis"] is None and p["risk_level"] is None
    assert p["follow_up_questions"] == [] and p["next_step"]


def test_unknown_crop_low_and_no_crop_names_anywhere():
    p = dx.check({**JUTE, "crop": {"bn": "", "en": "", "sure": False}})
    assert p["crop"]["bn"] == "ফসল নিশ্চিতভাবে শনাক্ত করা যায়নি" and p["crop"]["key"] is None
    assert p["diagnosis"]["confidence"] == "low" and p["diagnosis"]["scientific_name"] == "" and p["risk_level"] is None
    assert p["next_step"] and not any(dx.crops_in(x) for x in p["observed_symptoms"] + p["immediate_actions"])
    p2 = dx.check({**JUTE, "crop": {"bn": "পাট", "en": "Jute", "sure": False}})
    assert p2["crop"]["key"] is None and p2["diagnosis"]["confidence"] == "low"


def test_not_plant_and_poor_photo():
    assert dx.check({"is_plant": False})["status"] == "not_plant"
    p = dx.check({**JUTE, "image_quality": "poor"})
    assert p["status"] == "poor_image" and "diagnosis" not in p and "immediate_actions" not in p and p["next_step"]


def test_odd_model_output_never_crashes():
    for raw in ({}, {"crop": "x", "diagnosis": [], "observed_symptoms": "abc", "confidence": 5},
                {"crop": {"bn": None}, "diagnosis": {"bn": 7}, "follow_up_questions": [None, {}, "কেন"]}):
        p = dx.check(raw)
        assert p["status"] in ("possible", "uncertain") and p["limitations"]
    with pytest.raises(dx.BadJSON):
        dx.parse("no json here")
    assert dx.parse('```json\n{"is_plant": true}\n```') == {"is_plant": True}


def test_crop_word_matching_is_careful():
    assert dx.crops_in("ধানের পাতা") == {"rice"} and dx.crops_in("প্রধান সমস্যা") == set()
    assert dx.crops_in("আমার জমি") == set() and dx.crops_in("Mung bean") == {"mungbean"}
    assert dx.crops_in("গমন") == set() and dx.crops_in("আলুর গাছ") == {"potato"}
    assert dx.crops_in("টমেটোতেও") == {"tomato"} and dx.crops_in("ধানেও") == {"rice"} and dx.crops_in("পাটের") == {"jute"}


def test_as_text_keeps_crop_and_problem_for_followups():
    t = dx.as_text(dx.check(JUTE))
    assert t.startswith("ফসল: পাট\nসম্ভাব্য সমস্যা: কাণ্ড পচা রোগ") and "টমেটো" not in t


# ================================================================ history (real database)
@db_only
def test_history_list_search_rename_hide_and_ownership():
    from chashibondhu.web import repo, repo_ai2
    from chashibondhu.web.db import execute, fetch_one
    ph = lambda: "+88017" + f"{secrets.randbelow(10**8):08d}"  # noqa: E731
    uid = fetch_one("INSERT INTO users (role, full_name, phone, password_hash) VALUES ('farmer','Test H',%s,'x') RETURNING id", (ph(),))["id"]
    other = fetch_one("INSERT INTO users (role, full_name, phone, password_hash) VALUES ('farmer','Test O',%s,'x') RETURNING id", (ph(),))["id"]
    try:
        a = repo_ai2.new_conversation(uid, "drkrishi")
        b = repo_ai2.new_conversation(uid, "drkrishi")
        empty = repo_ai2.new_conversation(uid, "drkrishi")
        f = repo_ai2.new_conversation(uid, "fosholi")
        repo.add_ai_message(a, "user", "আলুর পাতায় দাগ")
        mid = repo.add_ai_message(a, "assistant", "ফসল: আলু")
        repo_ai2.set_payload(mid, {"status": "possible", "crop": {"bn": "আলু"}})
        repo.add_ai_message(b, "user", "ছবি পাঠানো হয়েছে")
        repo_ai2.retitle(b, "ছবি পাঠানো হয়েছে", "ছবি: ধান — ব্লাস্ট রোগ")
        repo.add_ai_message(f, "user", "সরিষার জাত")
        ids = [c["id"] for c in repo_ai2.conversations(uid, "drkrishi")]
        assert set(ids) == {a, b} and empty not in ids                                   # no empty chats, no Fosholi
        assert [c["title"] for c in repo_ai2.conversations(uid, "drkrishi", "ব্লাস্ট")] == ["ছবি: ধান — ব্লাস্ট রোগ"]
        assert repo_ai2.conversations(uid, "drkrishi", "100%_") == []                      # LIKE wildcards are escaped
        assert repo_ai2.messages(a, uid, "drkrishi")[-1]["payload"]["crop"]["bn"] == "আলু"
        assert not repo_ai2.rename(a, other, "drkrishi", "x") and not repo_ai2.hide(a, other, "drkrishi")
        assert not repo_ai2.rename(a, uid, "fosholi", "x") and not repo_ai2.rename(a, uid, "drkrishi", "   ")
        assert repo_ai2.rename(a, uid, "drkrishi", "  আলুর   দাগ  ") and repo_ai2.conversations(uid, "drkrishi", "আলুর দাগ")
        repo_ai2.retitle(a, "ছবি পাঠানো হয়েছে", "should not change")
        assert repo_ai2.conversations(uid, "drkrishi", "আলুর")[0]["title"] == "আলুর দাগ"
        assert repo_ai2.hide(a, uid, "drkrishi") and not repo_ai2.owns(a, uid, "drkrishi")
        assert repo_ai2.messages(a, uid, "drkrishi") == [] and [c["id"] for c in repo_ai2.conversations(uid, "drkrishi")] == [b]
        assert fetch_one("SELECT count(*) AS n FROM ai_messages WHERE conversation_id = %s", (a,))["n"] == 2  # kept for admin
    finally:
        execute("DELETE FROM users WHERE id IN (%s, %s)", (uid, other))


# ================================================================ routes
@pytest.fixture
def client(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from chashibondhu.web import repo, routes_ai_hub, geo_points
    from chashibondhu.web.passwords import hash_password
    from fake_auth import install
    users = {"+8801711111111": {"id": 7, "role": "farmer", "full_name": "Rahim", "status": "active", "password_hash": hash_password("secret1")}}
    monkeypatch.setenv("WEB_SESSION_SECRET", "x" * 40)
    m = monkeypatch.setattr
    m(repo, "get_user_by_phone", lambda p: users.get(p))
    m(repo, "is_locked", lambda u: False)
    m(repo, "record_login", lambda uid, ok: None)
    install(monkeypatch)
    calls = []
    r2 = routes_ai_hub.repo_ai2
    m(r2, "owns", lambda c, u, a: (c, u, a) in {(5, 7, "drkrishi"), (6, 7, "fosholi")})
    m(r2, "messages", lambda c, u, a, limit=40: [{"id": 1, "role": "user", "kind": "photo", "content": "ছবি পাঠানো হয়েছে", "created_at": None},
                                                {"id": 2, "role": "assistant", "kind": "photo", "content": "ফসল: ধান",
                                                 "payload": {"status": "possible"}, "created_at": None}] if c == 5 else [])
    m(r2, "conversations", lambda u, a, q="": calls.append(("list", u, a, q)) or [{"id": 5, "title": "ধান", "updated_at": "2026-11-15T10:00:00+06:00"}])
    m(r2, "rename", lambda c, u, a, t: calls.append(("rename", c, u, a, t)) or c == 5)
    m(r2, "hide", lambda c, u, a: calls.append(("hide", c, u, a)) or c == 5)
    m(r2, "user_area", lambda u: None)
    m(geo_points, "_points", lambda: {})
    from chashibondhu.web.app import mount_website
    app = FastAPI()
    mount_website(app)
    c = TestClient(app)
    c.calls = calls
    tok = re.search(r'name="csrf" value="([^"]+)"', c.get("/login").text).group(1)
    c.post("/login", data={"csrf": tok, "phone": "+8801711111111", "password": "secret1", "as_role": "farmer"})
    return c


def _tok(page):
    return re.search(r'name="csrf" value="([^"]+)"', page).group(1)


def test_open_chat_only_own_and_same_assistant(client):
    page = client.get("/assistant/drkrishi?c=5").text
    assert 'data-conv="5"' in page and '"payload": {"status": "possible"}' in page
    assert 'data-conv="6"' not in client.get("/assistant/drkrishi?c=6").text              # a Fosholi chat
    assert 'data-conv="5"' not in client.get("/assistant/fosholi?c=5").text
    fos = client.get("/assistant/fosholi").text
    assert "ফসলি" in fos and "data-ai-file" not in fos and "ধানের জন্য কোন সার কখন ব্যবহার করব?" in fos


def test_sidebar_api(client):
    tok = _tok(client.get("/assistant/drkrishi").text)
    j = client.get("/app/drkrishi/conversations?q=ধান").json()
    assert j["items"][0]["title"] == "ধান" and client.calls[-1] == ("list", 7, "drkrishi", "ধান")
    assert client.get("/app/other/conversations").status_code == 404
    h = {"X-CSRF-Token": tok}
    assert client.post("/app/drkrishi/conversations/5/rename", json={"title": "নতুন নাম"}, headers=h).json() == {"ok": True}
    assert client.post("/app/drkrishi/conversations/5/rename", json={"title": "  "}, headers=h).status_code == 422
    assert client.post("/app/drkrishi/conversations/9/delete", headers=h).status_code == 404
    assert client.post("/app/drkrishi/conversations/5/delete", headers=h).json() == {"ok": True}
    assert client.post("/app/drkrishi/conversations/5/delete").status_code in (400, 403)   # CSRF needed
    client.cookies.clear()
    assert client.get("/app/drkrishi/conversations").status_code in (401, 403)


def test_templates_have_no_t_in_attributes_or_options():
    for name in ("chat.html", "hub.html"):
        s = (ROOT / "src/chashibondhu/web/templates/ai" / name).read_text(encoding="utf-8")
        assert not re.search(r'="[^"]*\{\{\s*t\(', s), name
        for opt in re.findall(r"<option[^>]*>(.*?)</option>", s, re.S):
            assert "t(" not in opt
