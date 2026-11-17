"""Fosholi (AI-1): real sentence streaming WITH the same safety guards as the old answer, fallback, routes,
separate conversations per assistant. No real AI call and no book index needed (fakes).

Database tests:  $env:CB_DB_TESTS="1"; python -m pytest -q tests/test_fosholi.py   (needs migration 010)"""
from __future__ import annotations

import json
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

BOOK = ("আলু গাছের নিচের পাতা হলুদ হলে নাবি ধসা রোগ হতে পারে। রোগ দেখা দিলে প্রতি লিটার পানিতে ২ গ্রাম ঔষধ "
        "মিশিয়ে স্প্রে করতে হয়।")
LLM_TEXT = ("VERIFIED:\n"
            "আলুর নিচের পাতা হলুদ হলে নাবি ধসা রোগ হতে পারে [1]।\n"
            "এ রোগে প্রতি লিটার পানিতে ২ গ্রাম ঔষধ দিতে হয় [1]।\n"
            "এ রোগে ফলন ৫০ ভাগ কমে যায় [1]।\n"
            "পাতায় কালো দাগ থাকে।\n"
            "ADVICE:\n"
            "জমিতে পানি জমতে দেবেন না।\n"
            "৩ দিন পর আবার দেখুন।\n"
            "একটু ইউরিয়া সার দিন।\n"
            "দাগগুলো কি পুরো জমিতে, নাকি কয়েকটি গাছে?\n")


class Hit:
    def __init__(self, text, page):
        self.chunk = {"text": text, "pdf_page": page, "printed_page": page - 10, "source_id": "kph10"}


class FakeIndex:
    meta = {"built_utc": "test"}

    def search(self, q, k=6):
        return [Hit(BOOK, 120)]


class FakeResp:
    def __init__(self, status, lines, log):
        self.status_code, self._lines, self._log = status, lines, log

    def iter_lines(self):
        for ln in self._lines:
            self._log.append(("sent", ln))
            yield ln.encode("utf-8") if isinstance(ln, str) else ln

    def close(self):
        pass


class FakeSession:
    def __init__(self, status=200, text=LLM_TEXT, chunk=7, fail_after=None):
        self.status, self.text, self.chunk, self.fail_after, self.log, self.bodies = status, text, chunk, fail_after, [], []

    def post(self, url, json=None, **kw):
        self.bodies.append(json)
        assert kw.get("stream") is True and json["stream"] is True
        pieces = [self.text[i:i + self.chunk] for i in range(0, len(self.text), self.chunk)]
        lines = [": keep-alive", ""]
        for n, p in enumerate(pieces):
            if self.fail_after is not None and n == self.fail_after:
                lines.append('data: {"error": {"message": "boom"}}')
                break
            lines.append("data: " + __import__("json").dumps({"choices": [{"delta": {"content": p}}]}, ensure_ascii=False))
        lines.append("data: [DONE]")
        return FakeResp(self.status, lines, self.log)


def groq(session, model="groq-test"):
    from chashibondhu.assistant.llm.openai_compat import OpenAICompatClient
    return OpenAICompatClient("https://example.invalid/v1", "key", model, session=session, provider="groq")


class TextOnly:
    """A client that cannot stream (like Gemma)."""
    provider, model = "gemma", "gemma-test"

    def __init__(self, text=LLM_TEXT):
        self.text, self.calls = text, 0

    def generate(self, system, user):
        self.calls += 1
        return self.text


def make_assistant(llm, tmp_path=None):
    from chashibondhu.assistant.service import Assistant
    return Assistant(FakeIndex(), llm, cache_path=(tmp_path / "cache.json") if tmp_path else None, smart_search=False)


def events(assistant, q="আলুর পাতা হলুদ কেন?"):
    from chashibondhu.assistant.fosholi import ask_stream
    return list(ask_stream(assistant, q))


# ================================================================ guards while streaming
def test_stream_shows_only_guarded_sentences(tmp_path):
    session = FakeSession()
    a = make_assistant(groq(session), tmp_path)
    ev = events(a)
    assert ev[0] == {"t": "start"} and ev[-1]["t"] == "done"
    said = [(e["part"], e["text"]) for e in ev if e["t"] == "s"]
    assert said == [
        ("verified", "আলুর নিচের পাতা হলুদ হলে নাবি ধসা রোগ হতে পারে।"),
        ("verified", "এ রোগে প্রতি লিটার পানিতে ২ গ্রাম ঔষধ দিতে হয়।"),     # "2" is in the book: kept
        ("advice", "পাতায় কালো দাগ থাকে।"),                              # no citation -> advice rules
        ("advice", "জমিতে পানি জমতে দেবেন না।"),
        ("advice", "দাগগুলো কি পুরো জমিতে, নাকি কয়েকটি গাছে?"),
    ]
    text = " ".join(t for _, t in said)
    assert "৫০" not in text and "৩ দিন" not in text and "ইউরিয়া" not in text      # invented number, dose, fertilizer
    done = ev[-1]
    assert done["status"] == "verified_and_advice" and done["safety"] and done["sources"][0]["printed_page"] == 110
    assert done["removed"] == 3 and done["model"] == "groq-test"
    assert session.bodies[0]["stream"] is True


def test_sentences_arrive_before_the_model_finishes(tmp_path):
    from chashibondhu.assistant.fosholi import ask_stream
    session = FakeSession()
    gen = ask_stream(make_assistant(groq(session), tmp_path), "আলুর পাতা হলুদ কেন?")
    first = None
    for e in gen:
        if e["t"] == "s":
            first = e
            break
    sent = [x for x in session.log if x[0] == "sent"]
    total = len(FakeSession().text) // 7 + 4
    assert first and len(sent) < total                     # the first sentence came out mid-stream (real streaming)


def test_same_cache_as_the_old_answer(tmp_path):
    session = FakeSession()
    a = make_assistant(groq(session), tmp_path)
    first = [e for e in events(a) if e["t"] == "s"]
    n_calls = len(session.bodies)
    again = events(a)
    assert [e for e in again if e["t"] == "s"] == first and again[-1]["cached"] is True
    assert len(session.bodies) == n_calls                  # no new AI call
    old = a.ask("আলুর পাতা হলুদ কেন?")                     # the old (non-stream) path reads the same cache
    assert old["cached"] is True and "ইউরিয়া" not in old["answer"]


def test_fallback_when_groq_is_rate_limited(tmp_path):
    from chashibondhu.assistant.llm.fallback import FallbackChain
    gemma = TextOnly()
    a = make_assistant(FallbackChain([groq(FakeSession(status=429)), gemma]), tmp_path)
    ev = events(a)
    assert gemma.calls == 1 and ev[-1]["model"] == "gemma-test"
    assert [e["text"] for e in ev if e["t"] == "s"][0].startswith("আলুর নিচের পাতা")


def test_all_busy_and_mid_stream_failure(tmp_path):
    from chashibondhu.assistant.llm.fallback import FallbackChain
    a = make_assistant(FallbackChain([groq(FakeSession(status=429))]), tmp_path)
    assert events(a)[-1] == {"t": "error", "code": "ai_busy"}
    b = make_assistant(groq(FakeSession(fail_after=12)), tmp_path)
    ev = events(b)
    assert ev[-1] == {"t": "error", "code": "ai_error"} and not (tmp_path / "cache.json").exists()   # nothing cached


def test_no_markers_means_advice_rules(tmp_path):
    a = make_assistant(TextOnly("পাতা হলুদ হলে নাবি ধসা হতে পারে [1]। ২ গ্রাম ঔষধ দিন।"), tmp_path)
    ev = events(a)                                  # without VERIFIED: everything is advice, like the old answer:
    assert [e for e in ev if e["t"] == "s"] == []   # "[1]" and "২" are numbers -> removed
    assert ev[-1]["fallback"] and ev[-1]["status"] == "need_more_info"


# ================================================================ routes (no database)
@pytest.fixture
def client(monkeypatch, tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from chashibondhu.web import repo, routes_ai, routes_ai_hub
    from chashibondhu.web.passwords import hash_password
    from fake_auth import install
    users = {"+8801711111111": {"id": 7, "role": "farmer", "full_name": "Rahim", "status": "active",
                                "password_hash": hash_password("secret1")},
             "+8801733333333": {"id": 9, "role": "customer", "full_name": "Buyer", "status": "active",
                                "password_hash": hash_password("buyer12")}}
    monkeypatch.setenv("WEB_SESSION_SECRET", "x" * 40)
    m = monkeypatch.setattr
    m(repo, "get_user_by_phone", lambda p: users.get(p))
    m(repo, "is_locked", lambda u: False)
    m(repo, "record_login", lambda uid, ok: None)
    install(monkeypatch)
    saved = []
    m(repo, "add_ai_message", lambda conv, role, content, **kw: saved.append((conv, role, content, kw)) or len(saved))
    m(routes_ai_hub.repo_ai2, "new_conversation", lambda uid, a: 500 + len(saved))
    m(routes_ai_hub.repo_ai2, "owns", lambda c, u, a: True)
    m(routes_ai_hub.repo_ai2, "messages", lambda c, u, a: [])
    m(routes_ai, "load_assistant", lambda: make_assistant(groq(FakeSession()), tmp_path))
    from chashibondhu.web.app import mount_website
    app = FastAPI()
    mount_website(app)
    c = TestClient(app)
    c.saved = saved
    return c


def login(c, phone, pw, role):
    tok = re.search(r'name="csrf" value="([^"]+)"', c.get("/login").text).group(1)
    assert c.post("/login", data={"csrf": tok, "phone": phone, "password": pw, "as_role": role},
                  follow_redirects=False).status_code == 303


def test_hub_and_access(client):
    assert client.get("/assistant", follow_redirects=False).headers["location"].startswith("/login")
    login(client, "+8801733333333", "buyer12", "customer")
    assert client.get("/assistant", follow_redirects=False).status_code == 403          # customers: shopping helper
    client.cookies.clear()
    login(client, "+8801711111111", "secret1", "farmer")
    hub = client.get("/assistant").text
    assert "ফসলি" in hub and "ড. কৃষি" in hub and "/assistant/fosholi" in hub
    assert client.get("/assistant?photo=1", follow_redirects=False).headers["location"] == "/assistant/drkrishi"
    assert client.get("/assistant?q=alu", follow_redirects=False).headers["location"] == "/assistant/fosholi?q=alu"
    page = client.get("/assistant/fosholi").text
    assert 'data-assistant="fosholi"' in page and "ai_chat.js" in page
    assert "বই থেকে উত্তর খুঁজছে" not in page and "Searching the handbook" not in page


def test_stream_route(client):
    login(client, "+8801711111111", "secret1", "farmer")
    page = client.get("/assistant/fosholi").text
    tok = re.search(r'name="csrf" value="([^"]+)"', page).group(1)
    r = client.post("/app/fosholi/ask", json={"question": "আলুর পাতা হলুদ কেন?"}, headers={"X-CSRF-Token": tok})
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/x-ndjson")
    ev = [json.loads(x) for x in r.text.strip().split("\n")]
    assert ev[0]["t"] == "start" and ev[-1]["t"] == "done" and ev[-1]["message_id"] == 2
    assert [s[1] for s in client.saved] == ["user", "assistant"] and client.saved[1][3]["sources"]
    assert client.post("/app/fosholi/ask", json={"question": "x"}, headers={"X-CSRF-Token": tok}).status_code == 422
    assert client.post("/app/fosholi/ask", json={"question": "আলু"}, headers={"X-CSRF-Token": "bad"}).status_code == 400


# ================================================================ database: conversations stay with their assistant
@db_only
def test_conversations_are_separate_per_assistant():
    from chashibondhu.web import repo, repo_ai2
    from chashibondhu.web.db import execute, fetch_one
    uid = fetch_one("INSERT INTO users (role, full_name, phone, password_hash) VALUES ('farmer', 'Test AI', %s, 'x') "
                    "RETURNING id", ("+88017" + f"{secrets.randbelow(10**8):08d}",))["id"]
    try:
        f = repo_ai2.new_conversation(uid, "fosholi")
        d = repo_ai2.new_conversation(uid, "drkrishi")
        repo.add_ai_message(f, "user", "আলু?")
        repo.add_ai_message(d, "user", "আবহাওয়া?")
        assert [m["content"] for m in repo_ai2.messages(f, uid, "fosholi")] == ["আলু?"]
        assert repo_ai2.messages(f, uid, "drkrishi") == [] and not repo_ai2.owns(f, uid, "drkrishi")
        assert not repo_ai2.owns(f, uid + 1, "fosholi")
        with pytest.raises(Exception):
            repo_ai2.new_conversation(uid, "other")
    finally:
        execute("DELETE FROM users WHERE id = %s", (uid,))


def test_low_reasoning_effort_for_gpt_oss(monkeypatch):
    from chashibondhu.assistant.llm.streaming import reasoning_effort, stream_chat
    assert reasoning_effort("openai/gpt-oss-120b") == "low" and reasoning_effort("llama-3.3-70b") is None
    monkeypatch.setenv("FOSHOLI_REASONING", "medium")
    assert reasoning_effort("openai/gpt-oss-120b") == "medium"
    s = FakeSession()
    list(stream_chat(groq(s, model="openai/gpt-oss-120b"), "sys", "user"))
    assert s.bodies[0]["reasoning_effort"] == "medium"
    s2 = FakeSession()
    list(stream_chat(groq(s2, model="llama-test"), "sys", "user"))
    assert "reasoning_effort" not in s2.bodies[0]
