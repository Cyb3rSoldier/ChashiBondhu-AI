"""Phase 7b tests: Bangla query helpers, smart search, advice term guard, service wiring.
All offline: a tiny fake embedder and a fake LLM. No network, no model download."""
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from chashibondhu.assistant import service  # noqa: E402
from chashibondhu.assistant.advice_terms import (  # noqa: E402
    drop_blocked_sentences, find_blocked, needs_safety_line)
from chashibondhu.assistant.retrieval.index import RagIndex, normalize_text, tokenize  # noqa: E402
from chashibondhu.assistant.retrieval.query_bn import (  # noqa: E402
    bm25_tokens, detect_intent, plan_query, stem, tag_passage)
from chashibondhu.assistant.retrieval.smart import SmartSearch  # noqa: E402

N = normalize_text


class BowEmbedder:
    """Bag-of-words hashed into 64 dims; deterministic (crc32, not Python hash)."""
    name = "fake-bow"

    def encode(self, texts):
        out = np.zeros((len(texts), 64), np.float32)
        for r, t in enumerate(texts):
            t = t.replace("query:", " ").replace("passage:", " ")
            for tok in tokenize(t):
                out[r, zlib.crc32(tok.encode("utf-8")) % 64] += 1.0
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return out / norms


TEXTS = [
    # 0 variety page: colour words, no disease
    "বারি আলুর জাত। আলুর চামড়ার রং হলুদ, শাঁসের রং হালকা হলুদ। ফলন বেশি টন/হেক্টর। "
    "পরিপক্কতা লাভ করে।",
    # 1 potato disease page
    "আলুর ভাইরাস রোগ। লক্ষণ: আক্রান্ত গাছের পাতা কোঁকড়ানো ও হলুদ হয়। জাব পোকা দমন করতে হবে।",
    # 2 general cultivation page
    "আলু রোপণের সময় ও জমি তৈরি। আলু লাগানোর জন্য বেলে দোআঁশ মাটি ভালো।",
    # 3 another crop's disease page
    "টমেটোর ঢলে পড়া রোগ। লক্ষণ: গাছ হঠাৎ ঢলে পড়ে। আক্রান্ত গাছ তুলে ফেলুন।",
    # 4 second variety page
    "আলুর জাত বর্ণনা: আলু ডিম্বাকার, রং হলুদ, শাঁস হলুদ। ফলন বেশি।",
    # 5 disease control step with a spray instruction (no numbers)
    "আলুর রোগ দমন: রোগের আক্রমণ বেশি হলে গাছের গোড়ায় স্প্রে করতে হবে।",
]


def make_index():
    chunks = [{"chunk_id": f"T:p{i}:0", "source_id": "T", "pdf_page": 100 + i,
               "printed_page": 75 + i, "text": t} for i, t in enumerate(TEXTS)]
    return RagIndex.build(chunks, BowEmbedder())


class FakeLLM:
    model = "fake-llm"

    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def generate(self, system, user):
        self.calls.append((system, user))
        return self.reply


# ---------------------------------------------------------------- query_bn
def test_stem_strips_one_common_ending():
    assert stem(N("আলুর")) == N("আলু")
    assert stem(N("পাতায়")) == N("পাতা")
    assert stem(N("রোগের")) == N("রোগ")
    assert stem(N("মাটিতে")) == N("মাটি")
    assert stem("urea") == "urea"


def test_bm25_tokens_keep_raw_word_and_stem():
    assert N("সার") in bm25_tokens("সারের") and N("সার") in bm25_tokens("সার")
    toks = bm25_tokens("আলুর")
    assert N("আলুর") in toks and N("আলু") in toks


def test_question_words_are_removed():
    toks = bm25_tokens("আলুর পাতা হলুদ হয়ে যাচ্ছে কেন?")
    for w in ("কেন", "হয়ে", "যাচ্ছে"):
        assert N(w) not in toks
    assert N("হলুদ") in toks


@pytest.mark.parametrize("q", ["আলুর পাতা হলুদ হয়ে যাচ্ছে কেন?", "টমেটো গাছে পোকা ধরেছে",
                               "ধানের পাতায় বাদামি দাগ", "মরিচ গাছ ঢলে পড়ছে"])
def test_problem_questions_detected(q):
    assert detect_intent(q) == "problem"


@pytest.mark.parametrize("q", ["আলু কখন লাগাতে হয়", "আলুর রং হলুদ কোন জাত",
                               "সরিষার ভালো জাত কোনটি"])
def test_general_questions_not_detected_as_problem(q):
    assert detect_intent(q) == "general"


def test_plan_adds_book_words_only_for_problem_questions():
    assert N("লক্ষণ") in plan_query("আলুর পাতা হলুদ কেন").search_text
    assert plan_query("আলু কখন লাগাতে হয়").search_text == "আলু কখন লাগাতে হয়"


def test_tag_passage():
    assert tag_passage(TEXTS[0]) == "variety"
    assert tag_passage(TEXTS[1]) == "problem"
    assert tag_passage(TEXTS[2]) == "general"


# ---------------------------------------------------------------- smart search
def test_smart_search_puts_disease_page_above_variety_pages():
    hits = SmartSearch(make_index()).search("আলুর পাতা হলুদ হয়ে যাচ্ছে কেন?", k=3)
    assert hits[0].chunk["pdf_page"] == 101
    assert hits[0].tag == "problem"
    top3 = [h.chunk["pdf_page"] for h in hits]
    assert 100 not in top3[:1] and 104 not in top3[:1]


def test_smart_search_does_not_boost_general_questions():
    s = SmartSearch(make_index())
    for h in s.search("আলু কখন লাগাতে হয়", k=6):
        assert h.score <= 2.0 / 61 + 1e-9      # pure RRF, no section boost


def test_smart_search_empty_question():
    assert SmartSearch(make_index()).search("   ") == []


# ---------------------------------------------------------------- advice terms
def test_blocked_bangla_sentences_removed():
    text = ("পানি জমে থাকলে পাতা হলুদ হতে পারে।\n"
            "নাইট্রোজেনের অভাব হতে পারে, জৈব সার দিন।\n"
            "নিচের পাতা না উপরের পাতা হলুদ?")
    kept, removed = drop_blocked_sentences(text)
    assert "নাইট্রোজেন" not in kept and len(removed) == 1
    assert "পানি জমে" in kept and "উপরের পাতা" in kept


def test_blocked_english_terms():
    assert find_blocked("Apply urea now.")
    assert find_blocked("Use a fungicide.")
    assert find_blocked("Spray in the evening.")
    assert not find_blocked("Check if water is standing in the field.")
    assert not find_blocked("Decide after looking at the lower leaves.")


def test_safety_line_needed_for_book_dose_steps():
    assert needs_safety_line("প্রতি লিটার পানিতে মিশিয়ে বীজ শোধন করতে হবে")
    assert not needs_safety_line("কার্তিক মাসে আলু লাগানো ভালো")


# ---------------------------------------------------------------- service wiring
def test_assistant_removes_nutrient_advice_and_sends_disease_page_first():
    llm = FakeLLM("VERIFIED:\nNONE\nADVICE:\n"
                  "পানি জমে থাকলে পাতা হলুদ হতে পারে।\n"
                  "নাইট্রোজেনের অভাব হতে পারে, জৈব সার দিন।\n"
                  "নিচের পাতা না উপরের পাতা বেশি হলুদ?")
    a = service.Assistant(make_index(), llm)
    assert a._search_mode == "smart"
    r = a.ask("আলুর পাতা হলুদ হয়ে যাচ্ছে কেন?")
    assert r["status"] == "advice_only"
    assert "নাইট্রোজেন" not in r["answer"] and "পানি জমে" in r["answer"]
    assert service.TERM_NOTE in r["notes"]
    first_source = llm.calls[-1][1].split("[2]")[0]
    assert "ভাইরাস" in first_source


def test_verified_spray_step_gets_safety_line():
    llm = FakeLLM("VERIFIED:\nরোগ বেশি হলে গাছের গোড়ায় স্প্রে করতে হবে [1]।\nADVICE:\nNONE")
    r = service.Assistant(make_index(), llm).ask("আলুর রোগ দমন কিভাবে করবো")
    assert r["status"] == "verified"
    assert service.LABELS["bn"]["safety"] in r["answer"]


def test_cache_key_changes_with_retrieval_version(monkeypatch):
    a = service.Assistant(make_index(), FakeLLM("ADVICE:\nNONE"))
    old = a._key("answer", "আলু")
    monkeypatch.setattr(service, "RETRIEVAL_VERSION", "test-next")
    assert a._key("answer", "আলু") != old


def test_simple_index_falls_back_to_plain_search():
    class SimpleIndex:
        meta = {}

        def search(self, q, k=5):
            return []

    a = service.Assistant(SimpleIndex(), FakeLLM("VERIFIED:\nNONE\nADVICE:\nNONE"))
    assert a._search_mode == "plain"
    assert a.ask("আলুর পাতা হলুদ")["status"] == "need_more_info"


def test_cache_survives_restart_with_different_k(tmp_path):
    llm = FakeLLM("VERIFIED:\nNONE\nADVICE:\nপানি জমে থাকলে পাতা হলুদ হতে পারে।")
    a = service.Assistant(make_index(), llm, cache_path=tmp_path / "c.json", k=3)
    a.ask("আলুর পাতা হলুদ")
    fresh = service.Assistant(make_index(), FakeLLM("SHOULD NOT BE USED"),
                              cache_path=tmp_path / "c.json")
    assert fresh.ask("আলুর পাতা হলুদ")["cached"] is True


def test_no_space_before_dari():
    llm = FakeLLM("VERIFIED:\nভাইরাস রোগ হতে পারে [1] ।\nADVICE:\nNONE")
    r = service.Assistant(make_index(), llm).ask("আলুর পাতা হলুদ কেন")
    assert "পারে।" in r["answer"] and " ।" not in r["answer"]
