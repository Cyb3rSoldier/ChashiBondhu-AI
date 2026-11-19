"""AI v4: Dr. Krishi names the crop FIRST from the crop list (potato is never accepted as maize when unsure),
problem names come from crop_problems.csv, treatment comes from the handbook (Fosholi), expert-help flag;
Fosholi answers in sections, farmer context, safety line only when relevant, faster rewrite call.
No real AI call (fakes). Uses data/reference/crop_catalogue.csv + crop_problems.csv from the repo."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from chashibondhu.assistant import diagnosis as dx  # noqa: E402


@pytest.fixture(scope="module")
def cat():
    from chashibondhu.assistant.vision.problems import ProblemCatalogue
    ref = ROOT / "data" / "reference"
    if not (ref / "crop_problems.csv").exists():
        pytest.skip("data/reference/crop_problems.csv missing")
    return ProblemCatalogue.load(ref)


def potato(**kw):
    base = {"is_plant": True, "image_quality": "good", "leaf_features": "compound leaf, oval leaflets",
            "crop": {"id": "potato", "sure": True},
            "problem": {"id": "late_blight", "kind": "fungal", "confidence": "medium", "scientific_name": "Phytophthora infestans"},
            "other_possibilities": [{"id": "bacterial_wilt"}, {"id": "made_up"}],
            "about_bn": "এটি পাতা ও কাণ্ডের একটি দ্রুত ছড়ানো রোগ হতে পারে।",
            "observed_symptoms": ["পাতার কিনারায় কালচে ভেজা দাগ", "ভুট্টার পাতায় লম্বা দাগ"],
            "typical_symptoms": ["সকালে পাতার নিচে সাদা আস্তরণ"],
            "possible_causes": ["ঠান্ডা ও কুয়াশাভেজা আবহাওয়া"],
            "immediate_actions": ["আক্রান্ত গাছ আলাদা করে দেখুন", "মেনকোজেব ২ গ্রাম দিন"],
            "prevention": ["রোগমুক্ত বীজ আলু ব্যবহার করুন"], "risk_level": "high",
            "follow_up_questions": ["এই রোগ কীভাবে ছড়ায়"], "summary": "আলুর নাবি ধসা হতে পারে।"}
    base.update(kw)
    return base


# ================================================================ crop first
def test_prompt_lists_catalogue_crops_with_leaf_shapes_and_potato_problems(cat):
    p = dx.build_prompt(cat)
    assert '"potato" = Potato (আলু)' in p and "COMPOUND leaf of several oval leaflets" in p
    assert '"maize" = Maize' in p and "WIDE strap-shaped" in p and '"late_blight" = late blight' in p
    assert "FARMER SAYS" not in p and 'FARMER SAYS this is "potato"' in dx.build_prompt(cat, "potato")


def test_potato_from_list_names_come_from_the_file(cat):
    p = dx.check(potato(), "", cat)
    assert p["status"] == "possible" and p["crop"]["id"] == "potato" and p["crop_from"] == "photo"
    d = p["diagnosis"]
    assert (d["bn"], d["problem_id"], d["kind"], d["from_list"]) == ("নাবি ধ্বসা", "late_blight", "fungal", True)
    assert p["other_possibilities"] == [{"bn": "ব্যাকটেরিয়া জনিত ঢলে পড়া", "en": "bacterial wilt"}]   # made_up dropped
    assert p["observed_symptoms"] == ["পাতার কিনারায় কালচে ভেজা দাগ"]       # the maize line is removed
    assert p["immediate_actions"] == ["আক্রান্ত গাছ আলাদা করে দেখুন"]          # product + dose removed
    assert d["search_bn"] == "নাবি ধ্বসা রোগ লক্ষণ দমন" and p["risk_level"] == "high" and p["support"] is True


def test_unsure_crop_asks_the_farmer_instead_of_guessing(cat):
    p = dx.check(potato(crop={"id": "maize", "sure": False}), "", cat)
    assert p["status"] == "pick_crop" and {c["id"] for c in p["pick_crop"]} >= {"potato", "maize"}
    assert "diagnosis" not in p
    assert dx.check(potato(crop={"id": "jackfruit", "sure": True}), "", cat)["status"] == "pick_crop"


def test_farmer_crop_wins_and_mismatch_is_reported(cat):
    p = dx.check(potato(crop={"id": "maize", "sure": True, "matches_farmer": True}), "", cat, "potato")
    assert p["crop"]["id"] == "potato" and p["crop_from"] == "farmer" and p["diagnosis"]["bn"] == "নাবি ধ্বসা"
    m = dx.check(potato(crop={"id": "maize", "matches_farmer": False}), "", cat, "potato")
    assert m["status"] == "crop_mismatch" and "আলু" in m["message"] and m["pick_crop"]


def test_problem_outside_the_list_is_uncertain_and_healthy_is_healthy(cat):
    u = dx.check(potato(problem={"id": "rust", "bn": "মরিচা", "confidence": "high"}), "", cat)
    assert u["status"] == "uncertain" and u["diagnosis"] is None and u["follow_up_questions"] == [] and u["support"]
    h = dx.check(potato(problem={"id": "healthy", "confidence": "high"}), "", cat)
    assert h["status"] == "healthy" and h["immediate_actions"] == [] and h["risk_level"] is None


def test_crop_without_a_problem_list_uses_checked_free_names(cat):
    p = dx.check(potato(crop={"id": "tomato", "sure": True},
                        problem={"id": "free", "bn": "পাতা কোঁকড়ানো রোগ", "en": "leaf curl", "kind": "viral", "confidence": "medium"},
                        observed_symptoms=["পাতা কুঁকড়ে গেছে"], other_possibilities=[]), "", cat)
    assert p["status"] == "possible" and p["diagnosis"]["bn"] == "পাতা কোঁকড়ানো রোগ" and p["diagnosis"]["kind"] == "viral"
    assert p["diagnosis"]["search_bn"] == "টমেটো পাতা কোঁকড়ানো রোগ দমন"
    bad = dx.check(potato(crop={"id": "tomato", "sure": True}, problem={"id": "free", "bn": "আলুর ধসা", "confidence": "high"}), "", cat)
    assert bad["status"] == "uncertain"                                   # problem names another crop


def test_crop_from_the_farmers_words(cat):
    from chashibondhu.assistant.drkrishi import crop_from_text
    assert crop_from_text("আলুর পাতায় দাগ কেন?", cat) == "potato"
    assert crop_from_text("ধানের পাতা হলুদ", cat) is None                 # Aman or Boro: not guessed
    assert crop_from_text("আলু আর টমেটো", cat) is None


# ================================================================ treatment from the handbook
class FakeVision:
    model = "fake-vision"

    def __init__(self, obj):
        self.obj, self.systems = obj, []

    def analyze(self, system, text, jpeg):
        self.systems.append(system)
        return json.dumps(self.obj, ensure_ascii=False)


def test_diagnosis_then_handbook_treatment(cat, monkeypatch):
    from chashibondhu.assistant import drkrishi, fosholi
    asked = []

    def fake_stream(book, q, context=""):
        asked.append(q)
        yield {"t": "start"}
        yield {"t": "s", "part": "verified", "sec": "fix", "text": "রোগ দেখা দিলে হাতবইয়ের মাত্রায় ছত্রাকনাশক স্প্রে করতে হয়।", "cites": [1]}
        yield {"t": "done", "sources": [{"printed_page": 29, "pdf_page": 39}]}
    monkeypatch.setattr(fosholi, "ask_stream", fake_stream)
    vis = FakeVision(potato())
    ev = list(drkrishi.answer("কী হয়েছে?", llm=None, intents=["image"], image_jpeg=b"j", vision=vis,
                              catalogue=cat, book=object(), numbers_of=lambda x: set()))
    kinds = [e["t"] for e in ev]
    assert kinds[:3] == ["start", "diagnosis", "treat_start"] and "treat" in kinds and kinds[-2:] == ["treat_done", "done"]
    assert asked == ["আলু নাবি ধ্বসা রোগ লক্ষণ দমন"] and "FARMER SAYS" not in vis.systems[0]
    done = ev[-1]
    assert done["payload"]["treatment"]["sources"][0]["printed_page"] == 29 and "চিকিৎসা (হাতবই থেকে)" in done["answer"]
    assert done["safety"]


def test_no_page_backed_treatment_says_so(cat, monkeypatch):
    from chashibondhu.assistant import drkrishi, fosholi
    monkeypatch.setattr(fosholi, "ask_stream", lambda b, q, c="": iter([{"t": "s", "part": "advice", "text": "জমি পরিষ্কার রাখুন।"},
                                                                       {"t": "done", "sources": []}]))
    ev = list(drkrishi.answer("আলুর পাতায় দাগ", llm=None, intents=["image"], image_jpeg=b"j",
                              vision=FakeVision(potato()), catalogue=cat, book=object(), numbers_of=lambda x: set()))
    assert any(e["t"] == "treat" and e["part"] == "note" for e in ev) and ev[-1]["support"] is True


def test_crop_from_words_is_sent_as_the_farmer_crop(cat):
    from chashibondhu.assistant import drkrishi
    vis = FakeVision(potato(crop={"id": "maize", "sure": True, "matches_farmer": True}))
    ev = list(drkrishi.answer("আলুর পাতায় দাগ", llm=None, intents=["image"], image_jpeg=b"j", vision=vis,
                              catalogue=cat, numbers_of=lambda x: set()))
    assert 'FARMER SAYS this is "potato"' in vis.systems[0] and ev[1]["data"]["crop"]["id"] == "potato"


def test_weather_and_climate_are_fetched_together():
    from chashibondhu.assistant.drkrishi import _prefetch
    area = {"lat": 23.7, "lon": 90.4, "code": "BD3026"}
    t0 = time.perf_counter()
    pre = _prefetch(["weather", "climate"], area, lambda a, b: time.sleep(.4) or "w", lambda c: time.sleep(.4) or "c")
    assert (pre["weather"](), pre["climate"]()) == ("w", "c") and time.perf_counter() - t0 < .7


# ================================================================ Fosholi
class Hit:
    def __init__(self, text, page):
        self.chunk = {"text": text, "pdf_page": page, "printed_page": page - 10, "source_id": "kph10"}


class FakeIndex:
    meta = {"built_utc": "t"}

    def search(self, q, k=6):
        return [Hit("আলুর জমিতে পানি জমতে দেওয়া যাবে না। নাবি ধসা রোগে পাতায় কালো দাগ হয়।", 40)]


class FakeLLM:
    model, provider = "fake", "gemma"

    def __init__(self, text):
        self.text, self.users = text, []

    def generate(self, system, user):
        self.users.append(user)
        return self.text


NATURAL = ("আলুর জমিতে পানি জমতে দেওয়া যাবে না [1]। নাবি ধসা রোগে পাতায় কালো দাগ হয় [1]।\n"
           "\n"
           "কুয়াশার সময় জমি বেশি করে দেখুন।\n"
           "- আক্রান্ত গাছ আলাদা করে দেখুন।\n"
           "- ৩ দিন পর ইউরিয়া দিন।\n")


def _assistant(text=NATURAL):
    from chashibondhu.assistant.service import Assistant
    return Assistant(FakeIndex(), FakeLLM(text), smart_search=False)


def test_fosholi_answers_naturally_with_layout_and_checks():
    from chashibondhu.assistant.fosholi import ask_stream
    a = _assistant()
    ev = list(ask_stream(a, "আলুর পাতায় কালো দাগ, কী করব?", "district Rangpur; month November"))
    said = [(e["part"], e["blk"], e["new"], e["text"]) for e in ev if e["t"] == "s"]
    assert said == [("verified", "p", True, "আলুর জমিতে পানি জমতে দেওয়া যাবে না।"),
                    ("verified", "p", False, "নাবি ধসা রোগে পাতায় কালো দাগ হয়।"),
                    ("advice", "p", True, "কুয়াশার সময় জমি বেশি করে দেখুন।"),
                    ("advice", "ul", True, "আক্রান্ত গাছ আলাদা করে দেখুন।")]      # number + fertilizer line removed
    assert "Farmer: district Rangpur; month November" in a.llm.users[0] and "Conversation so far" not in a.llm.users[0]
    done = ev[-1]
    assert done["support"] is True and done["general"] is True and not done["safety"]
    assert done["answer"].startswith("আলুর জমিতে পানি জমতে দেওয়া যাবে না। নাবি ধসা") and "\n- আক্রান্ত" in done["answer"]
    again = list(ask_stream(a, "আলুর পাতায় কালো দাগ, কী করব?", "district Rangpur; month November"))
    assert [e for e in again if e["t"] == "s"] == [e for e in ev if e["t"] == "s"] and again[-1]["cached"]
    list(ask_stream(a, "আলুর পাতায় কালো দাগ, কী করব?", "district Bogura; month November"))
    assert len(a.llm.users) == 2                                          # other district = other cache key


def test_follow_up_question_uses_the_chat():
    from chashibondhu.assistant.fosholi import ask_stream
    from chashibondhu.assistant.service import FOLLOWUP_PROMPT
    a = _assistant("আস্ত আলুর জন্য সারি থেকে সারি দূরত্ব রাখতে হয় [1]।\n")
    calls = []
    real = a.llm.generate

    def gen(system, user):
        calls.append((system, user))
        return "আলু রোপণের দূরত্ব" if system == FOLLOWUP_PROMPT else real(system, user)
    a.llm.generate = gen
    hist = [{"role": "user", "content": "আলু চাষের জন্য কোন মাটি ভালো?"},
            {"role": "assistant", "content": "বেলে দোআঁশ মাটি ভালো।"}]
    ev = list(ask_stream(a, "রোপণের দূরত্ব কত রাখব?", "", hist))
    assert calls[0][0] == FOLLOWUP_PROMPT and "আলু চাষের জন্য কোন মাটি ভালো?" in calls[0][1]
    assert "Conversation so far:\nFarmer: আলু চাষের জন্য" in calls[1][1]
    assert ev[-1]["result"]["search_query"] == "আলু রোপণের দূরত্ব"
    # the same words after another question are a different answer (not served from the cache)
    list(ask_stream(a, "রোপণের দূরত্ব কত রাখব?", "", [{"role": "user", "content": "টমেটো চাষ?"}]))
    assert sum(1 for s, _ in calls if s != FOLLOWUP_PROMPT) == 2


def test_headings_and_numbered_steps_are_kept_but_checked():
    from chashibondhu.assistant.fosholi import ask_stream
    a = _assistant("### জমি তৈরি\n1. জমিতে পানি জমতে দেওয়া যাবে না [1]।\n2. আগাছা পরিষ্কার রাখুন।\n### ৫ দিনের কাজ\n")
    ev = [e for e in ask_stream(a, "আলুর জমি কীভাবে তৈরি করব?") if e["t"] == "s"]
    assert [(e["part"], e["blk"]) for e in ev] == [("head", "h"), ("verified", "ol"), ("advice", "ol")]


def test_old_page_ask_uses_the_same_pipeline():
    a = _assistant()
    r = a.ask("আলুর পাতায় কালো দাগ, কী করব?")
    assert r["status"] == "verified_and_advice" and r["sources"] and "ইউরিয়া" not in r["answer"]
    assert a.ask("আলুর পাতায় কালো দাগ, কী করব?")["cached"] is True


def test_safety_line_only_for_medicine_or_fertilizer_questions():
    from chashibondhu.assistant.fosholi import ask_stream
    a = _assistant("ADVICE:\n{fix} জমি তৈরি করে সারি করে লাগান।\n")
    assert not list(ask_stream(a, "আলু কীভাবে লাগাব?"))[-1]["safety"]
    a2 = _assistant("ADVICE:\n{fix} জমির অবস্থা দেখে সময় ঠিক করুন।\n")
    assert list(ask_stream(a2, "আলুতে সার কখন দেব?"))[-1]["safety"]


def test_rewrite_call_uses_low_reasoning(monkeypatch):
    from chashibondhu.assistant.llm.openai_compat import OpenAICompatClient
    sent = []

    class Resp:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": "আলুর পাতা পচা"}}]}

    class S:
        def post(self, url, json=None, timeout=None, headers=None):
            sent.append(json)
            return Resp()
    c = OpenAICompatClient("https://x", "k", "openai/gpt-oss-120b", session=S(), provider="groq")
    monkeypatch.delenv("LLM_FAST_GENERATE", raising=False)
    c.generate("s", "u")
    monkeypatch.setenv("LLM_FAST_GENERATE", "0")
    c.generate("s", "u")
    assert sent[0]["reasoning_effort"] == "low" and "reasoning_effort" not in sent[1]
