"""Phase 14b: Groq -> Gemma fallback for text and vision."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from chashibondhu.assistant.llm.fallback import FallbackChain  # noqa: E402
from chashibondhu.assistant.llm.gemini import LLMError, RateLimited  # noqa: E402
from chashibondhu.assistant.llm.gemma import GemmaTextClient, extract_answer  # noqa: E402
from chashibondhu.assistant.vision.gemma_client import GemmaVisionClient, trim_to_json  # noqa: E402


class Fake:
    def __init__(self, model, result=None, exc=None):
        self.model, self.result, self.exc, self.calls = model, result, exc, 0

    def generate(self, system, user):
        self.calls += 1
        if self.exc:
            raise self.exc
        return self.result

    analyze = lambda self, system, text, jpeg: self.generate(system, text)  # noqa: E731


class Resp:
    def __init__(self, code, data):
        self.status_code, self._data, self.text = code, data, json.dumps(data)

    def json(self):
        return self._data


class Session:
    def __init__(self, *resps):
        self.resps, self.bodies = list(resps), []

    def post(self, url, json=None, timeout=None, headers=None):
        assert "key=" not in url and headers["x-goog-api-key"] == "k"
        self.bodies.append(json)
        return self.resps.pop(0)


def parts(*ps):
    return Resp(200, {"candidates": [{"content": {"parts": list(ps)}}]})


def test_primary_answers_secondary_not_called():
    a, b = Fake("groq", "A"), Fake("gemma", "B")
    chain = FallbackChain([a, b])
    assert chain.generate("s", "u") == "A" and b.calls == 0 and chain.model == "groq"


def test_rate_limit_falls_back_and_records_model():
    a, b = Fake("groq", exc=RateLimited("x")), Fake("gemma", "B")
    chain = FallbackChain([a, b])
    assert chain.analyze("s", "t", b"j") == "B"
    assert chain.last_model == "gemma" and chain.models == ["groq", "gemma"]


def test_all_rate_limited_raises_rate_limited():
    chain = FallbackChain([Fake("a", exc=RateLimited("x")), Fake("b", exc=RateLimited("y"))])
    with pytest.raises(RateLimited):
        chain.generate("s", "u")


def test_other_error_raises_last_error():
    chain = FallbackChain([Fake("a", exc=RateLimited("x")), Fake("b", exc=LLMError("boom"))])
    with pytest.raises(LLMError) as e:
        chain.generate("s", "u")
    assert not isinstance(e.value, RateLimited)


def test_extract_answer_drops_thinking():
    raw = "Thinking Process: blah <answer>draft</answer> more <answer>উত্তর</answer>"
    assert extract_answer(raw) == "উত্তর"
    assert extract_answer("plain text") == "plain text"


def test_gemma_text_client_skips_thought_parts():
    s = Session(parts({"text": "secret", "thought": True}, {"text": "x <answer>ঠিক</answer>"}))
    out = GemmaTextClient("k", session=s).generate("SYS", "USER")
    assert out == "ঠিক"
    sent = s.bodies[0]["contents"][0]["parts"][0]["text"]
    assert "SYS" in sent and "USER" in sent and "<answer>" in sent


def test_gemma_429_is_rate_limited():
    s = Session(Resp(429, {"error": {"message": "quota"}}))
    with pytest.raises(RateLimited):
        GemmaTextClient("k", session=s).generate("s", "u")


def test_trim_to_json_and_vision_retry_without_json_mode():
    js = '{"is_plant_photo": true, "image_quality": "ok", "candidates": []}'
    assert trim_to_json("1. Analyze {the} request... " + js) == js
    s = Session(Resp(400, {"error": {"message": "responseMimeType not supported"}}),
                parts({"text": "Thinking: look at {leaf}\n" + js}))
    out = GemmaVisionClient("k", session=s).analyze("SYS", "note", b"\xff\xd8")
    assert json.loads(out)["image_quality"] == "ok"
    assert "responseMimeType" not in s.bodies[1]["generationConfig"]


def test_factories_use_fallback_only_when_enabled(monkeypatch, tmp_path):
    from chashibondhu.assistant.llm.openai_compat import OpenAICompatClient, llm_from_env
    from chashibondhu.assistant.vision.client import VisionClient
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "g")
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.delenv("LLM_FALLBACK", raising=False)
    assert isinstance(llm_from_env(tmp_path), FallbackChain)
    assert isinstance(VisionClient.from_env(tmp_path), FallbackChain)
    monkeypatch.setenv("LLM_FALLBACK", "off")
    assert isinstance(llm_from_env(tmp_path), OpenAICompatClient)
    assert isinstance(VisionClient.from_env(tmp_path), VisionClient)
