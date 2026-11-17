"""Phase 7 assistant tests. No internet, no Gemini key, no torch needed:
a fake embedder and a fake LLM replace the real ones. Passage texts below are
invented test strings, not real agricultural advice."""
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from chashibondhu.api.assistant_routes import get_assistant  # noqa: E402
from chashibondhu.api.main import app  # noqa: E402
from chashibondhu.assistant.guard import guard_numbers, numbers_in  # noqa: E402
from chashibondhu.assistant.ingestion.chunking import chunk_pages  # noqa: E402
from chashibondhu.assistant.ingestion.pdf_bijoy import line_to_text  # noqa: E402
from chashibondhu.assistant.llm.gemini import (GeminiClient, LLMError,  # noqa: E402
                                               RateLimited)
from chashibondhu.assistant.retrieval.index import RagIndex, tokenize  # noqa: E402
from chashibondhu.assistant.service import (Assistant, drop_numbered_sentences,  # noqa: E402
                                            parse_sections)

CHUNKS = [
    {"chunk_id": "T:p30:0", "source_id": "T", "pdf_page": 30, "printed_page": 5,
     "text": "আলু চাষ: টেস্ট জাত রোপণ করুন। বীজ ১৫ সেমি দূরে লাগান।"},
    {"chunk_id": "T:p40:0", "source_id": "T", "pdf_page": 40, "printed_page": 15,
     "text": "সরিষা চাষ: টেস্ট জমি তৈরি করুন। সার ২০ কেজি দিন।"},
    {"chunk_id": "T:p50:0", "source_id": "T", "pdf_page": 50, "printed_page": 25,
     "text": "টমেটো চাষ: চারা টেস্ট পদ্ধতিতে লাগান।"},
]


class FakeEmbedder:
    """Hashed bag-of-words vectors: same words -> similar vectors."""
    name = "fake-embedder"

    def encode(self, texts):
        out = np.zeros((len(texts), 64), dtype=np.float32)
        for i, t in enumerate(texts):
            for tok in tokenize(t.split(": ", 1)[-1]):
                out[i, zlib.crc32(tok.encode()) % 64] += 1
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        return out / np.where(norms == 0, 1, norms)


class FakeLLM:
    model = "fake-llm"

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def generate(self, system, user):
        self.calls.append((system, user))
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def _assistant(replies, tmp_path=None):
    index = RagIndex.build(CHUNKS, FakeEmbedder())
    cache = (tmp_path / "cache.json") if tmp_path else None
    return Assistant(index, FakeLLM(replies), cache_path=cache, k=2)


# ------------------------------------------------------------------ ingestion
def test_bijoy_spans_joined_before_conversion():
    spans = [("‡", "SutonnyMJ"), ("mvbvi", "SutonnyMJ"), (" BARI-1", "TimesNewRoman")]
    assert line_to_text(spans) == "সোনার BARI-1"


def test_bijoy_vowel_sign_at_end_does_not_crash():
    # bijoy2unicode alone raises IndexError on "‡K" (vowel sign before the last letter)
    assert line_to_text([("Avjy ‡K", "SutonnyMJ"), (" BARI", "Arial")]) == "আলু কে BARI"


@pytest.mark.parametrize("bijoy,expected", [
    ("kK©iv", "শর্করা"), ("¸iæZ¡c~Y©", "গুরুত্বপূর্ণ"), ("evwl©K", "বার্ষিক"),
    ("me©vwaK", "সর্বাধিক"), ("Kv‡ev©nvB‡W«U", "কার্বোহাইড্রেট"), ("e‡Y©i", "বর্ণের"),
    ("chv©‡q", "পর্যায়ে"), ("Kg©", "কর্ম"),                       # reph (র্)
    ("Kv‡Ði", "কাণ্ডের"), ("`iæb", "দরুন"), ("iƒcvšÍwiZ", "রূপান্তরিত"),
    ("mg¯Í", "সমস্ত"), ("msiÿY", "সংরক্ষণ"),                    # font-layout fixes
    ("Avjy", "আলু"), ("†b`vij¨vÛ", "নেদারল্যান্ড"), ("D‡b¥vPb", "উন্মোচন")])  # unchanged
def test_book_font_patterns(bijoy, expected):
    """Real words from the BARI Hatboi raw text (SutonnyMJ)."""
    import unicodedata
    got = line_to_text([(bijoy, "SutonnyMJ-Regular")])
    assert unicodedata.normalize("NFC", got) == unicodedata.normalize("NFC", expected)


def test_chunking_keeps_pages_and_size():
    pages = [{"pdf_page": 30, "printed_page": 5, "text": "\n".join(["ক" * 300] * 5)},
             {"pdf_page": 31, "printed_page": 6, "text": "ছোট লাইন"}]
    chunks = chunk_pages(pages, max_chars=700, overlap_lines=1)
    assert all(len(c["text"]) <= 700 for c in chunks)
    assert {c["pdf_page"] for c in chunks} == {30, 31}
    assert len({c["chunk_id"] for c in chunks}) == len(chunks)


# ------------------------------------------------------------------ retrieval
def test_tokenize_bangla_digits_and_case():
    assert tokenize("আলু ১৫ BARI") == ["আলু", "15", "bari"]


def test_search_and_save_load(tmp_path):
    index = RagIndex.build(CHUNKS, FakeEmbedder())
    assert index.search("সরিষা সার", k=1)[0].chunk["pdf_page"] == 40
    index.save(tmp_path)
    again = RagIndex.load(tmp_path, FakeEmbedder())
    assert again.search("টমেটো চারা", k=1)[0].chunk["pdf_page"] == 50


def test_load_rejects_other_embedding_model(tmp_path):
    RagIndex.build(CHUNKS, FakeEmbedder()).save(tmp_path)
    other = FakeEmbedder()
    other.name = "another-model"
    with pytest.raises(ValueError):
        RagIndex.load(tmp_path, other)


# ------------------------------------------------------------------ guard
def test_numbers_bangla_equals_ascii():
    assert numbers_in("১৫ সেমি, 1,500 টাকা, 2.50") == {"15", "1500", "2.5"}


def test_guard_removes_unsupported_numbers_only():
    answer = "বীজ ১৫ সেমি দূরে লাগান [1]। সার ৯৯ কেজি দিন [2]। ১. ভালো করে সেচ দিন।"
    kept, removed = guard_numbers(answer, "বীজ 15 সেমি দূরে")
    assert "১৫" in kept and "ভালো করে সেচ" in kept
    assert removed == ["সার ৯৯ কেজি দিন [2]।"]


# ------------------------------------------------------------------ assistant
V = "VERIFIED:\nবীজ ১৫ সেমি দূরে লাগান [1]।\n\nADVICE:\nNONE"


def test_parse_sections():
    assert parse_sections(V) == ("বীজ ১৫ সেমি দূরে লাগান [1]।", "")
    assert parse_sections("**VERIFIED:** NONE\n**ADVICE:** পানি নিষ্কাশন করুন।") == \
        ("", "পানি নিষ্কাশন করুন।")
    assert parse_sections("no markers here") == ("", "no markers here")   # -> advice


def test_advice_never_keeps_numbers():
    kept, removed = drop_numbered_sentences("জমি পরিষ্কার রাখুন। প্রতি লিটারে ২ মিলি দিন।")
    assert kept == "জমি পরিষ্কার রাখুন।" and len(removed) == 1


def test_verified_answer_with_citation(tmp_path):
    a = _assistant([V], tmp_path)
    r = a.ask("আলু কত দূরে লাগাবো?")
    assert r["status"] == "verified" and r["llm_requests"] == 1
    assert r["answer"] == "বীজ ১৫ সেমি দূরে লাগান।"          # plain text, no labels or [1]
    assert r["verified"] == "বীজ ১৫ সেমি দূরে লাগান [1]।"     # admin field keeps the mark
    assert r["sources"][0]["printed_page"] == 5
    assert "Sources:" in a.llm.calls[0][1]


def test_not_in_book_still_gives_advice():
    r = _assistant(["VERIFIED: NONE\nADVICE:\nপাতা হলুদ হলে পানি জমে আছে কিনা দেখুন। "
                    "অসুস্থ গাছ তুলে ফেলুন।"]).ask("পাতা হলুদ হচ্ছে কেন?")
    assert r["status"] == "advice_only" and r["sources"] == []
    assert r["answer"].startswith("পরামর্শ:") and "কৃষি অফিসে নিশ্চিত" in r["answer"]
    assert "জানি না" not in r["answer"] and "পাইনি" not in r["answer"]


def test_both_parts():
    raw = "VERIFIED:\nবীজ ১৫ সেমি দূরে লাগান [1]।\nADVICE:\nমাটি ঝুরঝুরে করে নিন।"
    r = _assistant([raw]).ask("আলু কীভাবে লাগাবো?")
    assert r["status"] == "verified_and_advice"
    assert r["answer"] == ("বীজ ১৫ সেমি দূরে লাগান।\n\nপরামর্শ:\nমাটি ঝুরঝুরে করে নিন।\n"
                           "ওষুধ বা সার কেনা ও দেওয়ার আগে স্থানীয় কৃষি অফিসে নিশ্চিত হোন।")
    assert "যাচাই" not in r["answer"] and "AI" not in r["answer"]


def test_made_up_numbers_removed_everywhere():
    raw = "VERIFIED:\nসরিষায় সার ৫০ কেজি দিন [1]।\nADVICE:\nএকরে ৩ বস্তা দিন। আগাছা পরিষ্কার করুন।"
    r = _assistant([raw]).ask("সরিষায় কত সার?")
    assert "৫০" not in r["answer"] and "৩" not in r["answer"]
    assert "আগাছা পরিষ্কার করুন।" in r["answer"] and len(r["removed_sentences"]) == 2


def test_uncited_verified_becomes_advice():
    r = _assistant(["VERIFIED:\nজমিতে পানি জমতে দেবেন না।\nADVICE: NONE"]).ask("আলুর যত্ন?")
    assert r["status"] == "advice_only" and r["verified"] == ""


def test_nothing_useful_asks_for_more_info():
    r = _assistant(["VERIFIED: NONE\nADVICE: NONE"]).ask("এটা কী?")
    assert r["status"] == "need_more_info" and "কোন ফসল" in r["answer"]


def test_english_and_banglish():
    en = _assistant(["আলু রোপণ", V]).ask("When should I plant potato?")
    assert en["llm_requests"] == 2 and en["answer"] == "বীজ ১৫ সেমি দূরে লাগান।"
    bl = _assistant(["আলু রোপণ দূরত্ব", V]).ask("alu koto dure lagabo")
    assert bl["search_query"] == "আলু রোপণ দূরত্ব" and bl["status"] == "verified"
    assert _assistant([V]).ask("আলু কত দূরে?")["llm_requests"] == 1


def test_cache_avoids_second_call(tmp_path):
    a = _assistant([V], tmp_path)
    a.ask("আলু কত দূরে?")
    again = a.ask("  আলু   কত দূরে? ")
    assert again["cached"] is True and again["llm_requests"] == 0
    assert len(a.llm.calls) == 1
    fresh = Assistant(a.index, FakeLLM([]), cache_path=tmp_path / "cache.json")
    assert fresh.ask("আলু কত দূরে?")["cached"] is True      # cache survives restart


def test_rate_limited_not_cached(tmp_path):
    a = _assistant([RateLimited("limit"), V], tmp_path)
    assert a.ask("আলু কত দূরে?")["status"] == "rate_limited"
    assert a.ask("আলু কত দূরে?")["status"] == "verified"


def test_invalid_citation_marks_dropped():
    r = _assistant(["VERIFIED:\nবীজ ১৫ সেমি দূরে লাগান [1][7]।\nADVICE: NONE"]).ask("আলু কত দূরে?")
    assert "[7]" not in r["verified"] and [s["n"] for s in r["sources"]] == [1]


# ------------------------------------------------------------------ gemini client
class _Resp:
    def __init__(self, status, data):
        self.status_code, self._data = status, data

    def json(self):
        return self._data


class _Session:
    def __init__(self, resp):
        self.resp, self.sent = resp, None

    def post(self, url, json, headers, timeout):
        self.sent = (url, json, headers)
        return self.resp


def test_gemini_client_parses_and_hides_key():
    ok = _Session(_Resp(200, {"candidates": [{"content": {"parts": [
        {"text": "thinking", "thought": True}, {"text": "উত্তর"}]}}]}))
    c = GeminiClient("SECRET-KEY", "m1", session=ok)
    assert c.generate("sys", "hi") == "উত্তর"
    assert ok.sent[2]["x-goog-api-key"] == "SECRET-KEY" and "SECRET" not in ok.sent[0]
    with pytest.raises(RateLimited):
        GeminiClient("SECRET-KEY", session=_Session(_Resp(429, {}))).generate("s", "u")
    with pytest.raises(LLMError) as e:
        GeminiClient("SECRET-KEY", session=_Session(
            _Resp(400, {"error": {"message": "bad"}}))).generate("s", "u")
    assert "SECRET" not in str(e.value)
    with pytest.raises(LLMError):
        GeminiClient("")


def test_groq_client_parses_and_hides_key(monkeypatch):
    from chashibondhu.assistant.llm.openai_compat import OpenAICompatClient, llm_from_env
    ok = _Session(_Resp(200, {"choices": [{"message": {"content": "উত্তর"}}]}))
    c = OpenAICompatClient("https://x/v1", "SECRET-KEY", "m1", session=ok, provider="groq")
    assert c.generate("sys", "hi") == "উত্তর"
    assert ok.sent[0] == "https://x/v1/chat/completions"
    assert ok.sent[1]["messages"][0] == {"role": "system", "content": "sys"}
    with pytest.raises(RateLimited):
        OpenAICompatClient("https://x/v1", "SECRET-KEY", "m", session=_Session(_Resp(429, {}))
                           ).generate("s", "u")
    with pytest.raises(LLMError) as e:
        OpenAICompatClient("https://x/v1", "SECRET-KEY", "m", session=_Session(
            _Resp(401, {"error": {"message": "invalid key"}}))).generate("s", "u")
    assert "SECRET" not in str(e.value)
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "k")
    monkeypatch.delenv("GROQ_MODEL", raising=False)
    assert llm_from_env(Path("/nonexistent")).model == "openai/gpt-oss-120b"
    monkeypatch.setenv("LLM_PROVIDER", "nope")
    with pytest.raises(LLMError):
        llm_from_env(Path("/nonexistent"))


# ------------------------------------------------------------------ API
@pytest.fixture
def client():
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_api_ask(client):
    a = _assistant([V])
    app.dependency_overrides[get_assistant] = lambda: a
    r = client.post("/assistant/ask", json={"question": "আলু কত দূরে?"})
    assert r.status_code == 200 and r.json()["sources"][0]["pdf_page"] == 30
    assert client.post("/assistant/ask", json={"question": ""}).status_code == 422


def test_api_rate_limit_is_429(client):
    a = _assistant([RateLimited("limit")])
    app.dependency_overrides[get_assistant] = lambda: a
    assert client.post("/assistant/ask", json={"question": "আলু কত দূরে?"}).status_code == 429
