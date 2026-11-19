"""Dr. Krishi (AI-2): picks only the needed tool, real weather numbers in a card, climate history (not a forecast),
photo answers always "possible", no invented numbers / doses / chemical names, separate from Fosholi.
No real AI or weather call (fakes). Database tests: $env:CB_DB_TESTS="1" (needs migrations 010 + 011)."""
from __future__ import annotations

import io
import json
import os
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

DB = os.environ.get("CB_DB_TESTS") == "1"
db_only = pytest.mark.skipif(not DB, reason="set CB_DB_TESTS=1 to run database tests")

WEATHER = {"now": {"temp": 26.4, "rh": 71, "rain_mm": 0.0, "wind": 6.1, "time": "2026-11-15T22:00"},
           "days": [{"date": "2026-11-15", "t_max": 28.1, "t_min": 17.2, "rain_mm": 0.0, "rain_prob": 3, "wind_max": 9, "gust_max": 20},
                    {"date": "2026-11-16", "t_max": 27.9, "t_min": 17.8, "rain_mm": 6.2, "rain_prob": 70, "wind_max": 12, "gust_max": 55},
                    {"date": "2026-11-17", "t_max": 28.4, "t_min": 18.0, "rain_mm": 0.4, "rain_prob": 12, "wind_max": 8, "gust_max": 18}],
           "source": "Open-Meteo"}
AREA = {"code": "BD30260024", "lat": 23.5938, "lon": 90.1414, "name_bn": "দোহার", "name_en": "Dohar", "district_code": "BD3026"}


class FakeLLM:
    model, provider = "fake-text", "gemma"         # gemma provider = no streaming, whole text once

    def __init__(self, text):
        self.text, self.calls = text, []

    def generate(self, system, user):
        self.calls.append((system, user))
        return self.text


class FakeVision:
    model = "fake-vision"

    def __init__(self, obj):
        self.obj, self.calls = obj, []

    def analyze(self, system, text, jpeg):
        self.calls.append(text)
        return json.dumps(self.obj, ensure_ascii=False)


def run(q, **kw):
    from chashibondhu.assistant.drkrishi import answer
    from chashibondhu.web.drkrishi_tools import intents, numbers_of
    kw.setdefault("intents", intents(q, kw.get("image_jpeg") is not None))
    return list(answer(q, numbers_of=numbers_of, **kw))


def said(ev):
    return [e["text"] for e in ev if e["t"] == "s"]


# ================================================================ tools
@pytest.mark.parametrize("q,img,want", [
    ("আগামীকাল বৃষ্টি হবে কি?", False, ["weather"]), ("kal brishti hobe?", False, ["weather"]),
    ("এই মাসে সাধারণত কত বৃষ্টি হয়?", False, ["weather", "climate"]),
    ("আমার এলাকায় এখন কোন রোগ বেশি হচ্ছে?", False, ["risk"]),
    ("এই পাতায় কী রোগ হয়েছে?", True, ["image"]), ("আলু চাষ কিভাবে শুরু করব?", False, ["general"])])
def test_intents(q, img, want):
    from chashibondhu.web.drkrishi_tools import intents
    assert intents(q, img) == want


def test_farm_tips_from_real_numbers():
    from chashibondhu.web.drkrishi_tools import farm_tips
    tips = [b for b, _ in farm_tips(WEATHER)]
    assert any("বৃষ্টির সম্ভাবনা বেশি" in t for t in tips) and any("ঝোড়ো" in t for t in tips)
    dry = {"days": [{**d, "rain_prob": 5, "rain_mm": 0, "gust_max": 10} for d in WEATHER["days"]]}
    assert [b for b, _ in farm_tips(dry)][0].startswith("সামনের দিনগুলোতে বৃষ্টির সম্ভাবনা কম")


def test_weather_call_and_cache():
    from chashibondhu.web import drkrishi_tools as t
    t._cache.clear()

    class S:
        n = 0

        def get(self, url, params=None, timeout=None):
            S.n += 1
            assert params["latitude"] == 23.59 and params["timezone"] == "Asia/Dhaka"
            class R:
                def raise_for_status(self): pass
                def json(self):
                    return {"current": {"temperature_2m": 26.4, "relative_humidity_2m": 71, "precipitation": 0, "wind_speed_10m": 5},
                            "daily": {"time": ["a", "b", "c"], "temperature_2m_max": [1, 2, 3], "temperature_2m_min": [0, 1, 2],
                                      "precipitation_sum": [0, 0, 0], "precipitation_probability_max": [1, 2, 3],
                                      "wind_speed_10m_max": [1, 1, 1], "wind_gusts_10m_max": [2, 2, 2]}}
            return R()
    w = t.weather(23.5938, 90.1414, session=S())
    t.weather(23.5938, 90.1414, session=S())
    assert w["now"]["temp"] == 26.4 and len(w["days"]) == 3 and S.n == 1          # second call from cache
    t._cache.clear()

    class Down:
        def get(self, *a, **k):
            raise OSError("no internet")
    with pytest.raises(t.WeatherUnavailable):
        t.weather(23.5, 90.1, session=Down())


# ================================================================ answers + guards
def test_weather_answer_only_real_numbers():
    llm = FakeLLM("আগামীকাল বৃষ্টির সম্ভাবনা ৭০%।\nতাই কাল সেচ দেবেন না।\nবৃষ্টি হবে ৯৯ মিমি।\nইউরিয়া এখন দেবেন না।\n")
    ev = run("আগামীকাল বৃষ্টি হবে কি?", llm=llm, area=AREA, weather_fn=lambda la, lo: WEATHER)
    card = next(e for e in ev if e["t"] == "card")
    assert card["kind"] == "weather" and card["data"]["days"][1]["rain_prob"] == 70 and card["tips"]
    assert said(ev) == ["আগামীকাল বৃষ্টির সম্ভাবনা ৭০%।", "তাই কাল সেচ দেবেন না।"]     # 99 invented, urea named
    assert ev[-1]["removed"] == 2 and "FACTS" in llm.calls[0][1]


def test_weather_without_area_or_service():
    ev = run("আজ আবহাওয়া কেমন?", llm=FakeLLM("জেলা বেছে নিন।"), area=None, weather_fn=None)
    assert {"t": "card", "kind": "note", "code": "need_area"} in ev

    def down(la, lo):
        from chashibondhu.web.drkrishi_tools import WeatherUnavailable
        raise WeatherUnavailable("x")
    ev = run("আজ আবহাওয়া কেমন?", llm=FakeLLM("এখন তথ্য নেই।"), area=AREA, weather_fn=down)
    assert {"t": "card", "kind": "note", "code": "weather_down"} in ev
    assert not any("°" in t for t in said(ev))


def test_general_dose_question_is_refused_safely():
    ev = run("ধানে কত কেজি ইউরিয়া দেব প্রতি বিঘায়?", llm=FakeLLM("প্রতি বিঘায় ১০ কেজি দিন।\nইউরিয়া দুই ভাগে দিন।\n"))
    assert said(ev) == [] or "ফসলি" in said(ev)[0]
    assert "ফসলি" in " ".join(said(ev)) and ev[-1]["safety"]


def test_risk_says_no_live_reports():
    llm = FakeLLM("এই মৌসুমে ধানে ব্লাস্ট রোগ হতে পারে।\nজেলায় ৪০% জমিতে আক্রমণ হয়েছে।\n")
    ev = run("আমার এলাকায় এখন কোন রোগ বেশি হচ্ছে?", llm=llm, area=AREA)
    note = next(e for e in ev if e["t"] == "card")
    assert note["code"] == "no_local_reports" and "মাঠ-রিপোর্ট" in note["text"]
    assert said(ev) == ["এই মৌসুমে ধানে ব্লাস্ট রোগ হতে পারে।"]                          # invented outbreak % removed


GOOD = {"is_plant": True, "image_quality": "good", "crop": {"bn": "ধান", "en": "Rice", "sure": True},
        "diagnosis": {"bn": "ব্লাস্ট রোগ", "en": "Blast", "scientific_name": "Magnaporthe oryzae", "confidence": "high"},
        "observed_symptoms": ["পাতায় চোখের মতো দাগ"], "typical_symptoms": ["শিষের গোড়া পচে যায়"],
        "possible_causes": ["আর্দ্র আবহাওয়া"], "immediate_actions": ["আক্রান্ত জমি আলাদা করে দেখুন", "ট্রাইসাইক্লাজল ৭৫ গ্রাম দিন"],
        "prevention": ["রোগমুক্ত বীজ ব্যবহার করুন"], "risk_level": "moderate",
        "follow_up_questions": ["এই রোগ কীভাবে ছড়ায়"], "summary": "পাতায় ব্লাস্ট রোগ হতে পারে।"}


def test_photo_answer_is_one_checked_diagnosis():
    vis = FakeVision(GOOD)
    ev = run("এই পাতায় কী রোগ হয়েছে?", llm=FakeLLM("x"), image_jpeg=b"jpeg", vision=vis)
    dx = next(e for e in ev if e["t"] == "diagnosis")["data"]
    assert dx["status"] == "possible" and dx["crop"]["key"] == "rice" and dx["diagnosis"]["confidence"] == "high"
    assert dx["immediate_actions"] == ["আক্রান্ত জমি আলাদা করে দেখুন"]               # dose + chemical line removed
    assert dx["follow_up_questions"] == ["এই রোগ কীভাবে ছড়ায়?"] and dx["risk_level"] == "moderate"
    done = ev[-1]
    assert done["payload"] == dx and "ফসল: ধান" in done["answer"] and done["model"] == "fake-vision"
    assert not [e for e in ev if e["t"] == "s"]                                          # no loose paragraph


def test_photo_not_a_plant_and_followup_context():
    vis = FakeVision({"is_plant": False})
    hist = [{"role": "user", "content": "ছবি পাঠানো হয়েছে"}, {"role": "assistant", "content": "ফসল: ধান\nসম্ভাব্য সমস্যা: ব্লাস্ট রোগ"}]
    ev = run("এবার এই ছবিটা দেখুন", llm=FakeLLM("x"), image_jpeg=b"j", vision=vis, history=hist)
    dx = next(e for e in ev if e["t"] == "diagnosis")["data"]
    assert dx["status"] == "not_plant" and "ব্লাস্ট রোগ" in vis.calls[0]


def test_broken_json_is_retried_then_friendly_error():
    class Bad(FakeVision):
        def analyze(self, system, text, jpeg):
            self.calls.append(text)
            return "sorry, I cannot"
    vis = Bad({})
    ev = run("কী হয়েছে?", llm=FakeLLM("x"), image_jpeg=b"j", vision=vis)
    assert len(vis.calls) == 2 and ev[-1] == {"t": "error", "code": "ai_error"}


# ================================================================ climate (real table)
@db_only
def test_climate_from_real_nasa_csv(tmp_path, monkeypatch):
    csv_path = Path(os.environ.get("CB_NASA_CSV", ROOT / "data" / "raw" / "climate" /
                                   "Bangladesh_Climate_Master_Fixed_2001_2025.csv"))
    if not csv_path.exists():
        pytest.skip("put the NASA CSV at data/raw/climate/ (or set CB_NASA_CSV)")
    import runpy
    out = runpy.run_path(str(ROOT / "scripts" / "import_nasa_climate.py"), run_name="not_main")
    assert out["main"](["x", str(csv_path)]) == 0
    from chashibondhu.web import drkrishi_tools as t, geo_points
    monkeypatch.setattr(geo_points, "point", lambda code: AREA)
    c = t.climate("BD30260024", month=7)
    r = c["recent"]
    assert r["years"] == "2001-2025" and r["wettest"]["rain_mm"] >= r["rain_mm_avg"] >= r["driest"]["rain_mm"]
    assert r["last"]["year"] == 2025


# ================================================================ routes
@pytest.fixture
def client(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from chashibondhu.web import repo, routes_ai_hub, drkrishi_tools, geo_points
    from chashibondhu.web.passwords import hash_password
    from fake_auth import install
    users = {"+8801711111111": {"id": 7, "role": "farmer", "full_name": "Rahim", "status": "active",
                                "password_hash": hash_password("secret1")}}
    monkeypatch.setenv("WEB_SESSION_SECRET", "x" * 40)
    m = monkeypatch.setattr
    m(repo, "get_user_by_phone", lambda p: users.get(p))
    m(repo, "is_locked", lambda u: False)
    m(repo, "record_login", lambda uid, ok: None)
    install(monkeypatch)
    saved = []
    m(repo, "add_ai_message", lambda conv, role, content, **kw: saved.append((conv, role, content, kw)) or len(saved))
    m(routes_ai_hub.repo_ai2, "new_conversation", lambda uid, a: 900)
    m(routes_ai_hub.repo_ai2, "owns", lambda c, u, a: True)
    m(routes_ai_hub.repo_ai2, "messages", lambda c, u, a, limit=40: [])
    m(routes_ai_hub.repo_ai2, "user_area", lambda uid: "BD30260024")
    m(geo_points, "point", lambda code: AREA if code else None)
    m(geo_points, "_points", lambda: {"BD3026": {**AREA, "code": "BD3026", "name_en": "Dhaka", "name_bn": "ঢাকা"}})
    m(drkrishi_tools, "weather", lambda la, lo: WEATHER)
    m(routes_ai_hub, "load_text_llm", lambda: FakeLLM("আগামীকাল বৃষ্টির সম্ভাবনা ৭০%।\n"))
    m(routes_ai_hub, "load_vision", lambda: FakeVision(GOOD))
    m(routes_ai_hub, "load_catalogue", lambda: None)          # old free-text path (catalogue: test_ai_v4.py)
    m(routes_ai_hub, "load_book", lambda: None)
    m(routes_ai_hub.repo_ai2, "set_payload", lambda mid, p: saved.append(("payload", mid, p, {})))
    m(routes_ai_hub.repo_ai2, "retitle", lambda conv, old, new: saved.append(("title", conv, new, {})))
    from chashibondhu.web.app import mount_website
    app = FastAPI()
    mount_website(app)
    c = TestClient(app)
    c.saved = saved
    tok = re.search(r'name="csrf" value="([^"]+)"', c.get("/login").text).group(1)
    assert c.post("/login", data={"csrf": tok, "phone": "+8801711111111", "password": "secret1", "as_role": "farmer"},
                  follow_redirects=False).status_code == 303
    page = c.get("/assistant/drkrishi").text
    c.tok = re.search(r'name="csrf" value="([^"]+)"', page).group(1)
    c.page = page
    return c


def _png() -> bytes:
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (200, 150), (40, 140, 60)).save(b, "PNG")
    return b.getvalue()


def test_page_and_weather_route(client):
    assert 'data-assistant="drkrishi"' in client.page and 'data-ai-file' in client.page and "BD3026" in client.page
    assert 'id="aiHistory"' in client.page and "ফসলের রোগ শনাক্ত করুন" in client.page
    r = client.post("/app/drkrishi/ask", data={"question": "আগামীকাল বৃষ্টি হবে কি?"}, headers={"X-CSRF-Token": client.tok})
    ev = [json.loads(x) for x in r.text.strip().split("\n")]
    assert ev[0]["intents"] == ["weather"] and ev[1]["kind"] == "weather" and ev[-1]["t"] == "done"
    assert [s[1] for s in client.saved] == ["user", "assistant"] and client.saved[0][0] == 900


def test_photo_route(client):
    r = client.post("/app/drkrishi/ask", data={"question": "এটা কী?"}, files={"image": ("leaf.png", _png(), "image/png")},
                    headers={"X-CSRF-Token": client.tok})
    ev = [json.loads(x) for x in r.text.strip().split("\n")]
    assert ev[0]["intents"] == ["image"] and ev[1]["t"] == "diagnosis" and ev[-1]["conv_id"] == 900
    assert client.saved[0][3]["kind"] == "photo" and client.saved[2][0] == "payload"
    client.saved.clear()
    client.post("/app/drkrishi/ask", files={"image": ("leaf.png", _png(), "image/png")}, headers={"X-CSRF-Token": client.tok})
    assert client.saved[0][2] == "ছবি পাঠানো হয়েছে" and client.saved[-1] == ("title", 900, "ছবি: ধান — ব্লাস্ট রোগ", {})
    bad = client.post("/app/drkrishi/ask", data={"question": "x"}, files={"image": ("a.png", b"not an image", "image/png")},
                      headers={"X-CSRF-Token": client.tok})
    assert bad.status_code == 422 and bad.json()["detail"] == "not_image"
    assert client.post("/app/drkrishi/ask", data={"question": "x"}, headers={"X-CSRF-Token": client.tok}).status_code == 422


def test_no_t_inside_option_tags():
    """t() makes <span>s; browsers show both languages inside <option>, so options must be plain text."""
    for p in (ROOT / "src" / "chashibondhu" / "web" / "templates").rglob("*.html"):
        for opt in re.findall(r"<option[^>]*>(.*?)</option>", p.read_text(encoding="utf-8"), re.S):
            assert "t(" not in opt, f"{p.name}: t() inside <option>"
