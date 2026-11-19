"""Fosholi answer-quality fixes (7c.1): mixed Bangla + Banglish questions are rewritten before searching,
advice may not contain month names (dates), follow-up questions not about leaves for 'how to start' questions."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_fosholi as tf  # noqa: E402


def test_needs_rewrite_mixed_script():
    from chashibondhu.assistant.service import needs_rewrite
    assert needs_rewrite("ekhon kon বীজ bopon korbo dhaner jonno")
    assert needs_rewrite("dhaner বীজ ki ki ache") and needs_rewrite("moricher chas kivabe suru korbo")
    assert not needs_rewrite("ধানের কোন জাত এখন লাগাব?") and not needs_rewrite("আলুর পাতা হলুদ কেন ২০২৬?")


class Recorder(tf.TextOnly):
    """Answers the rewrite call with a Bangla query, then the real answer; records the search query."""
    def __init__(self):
        super().__init__()
        self.prompts = []

    def generate(self, system, user):
        self.prompts.append(system[:30])
        if system.startswith("Rewrite"):
            return "ধানের জাত বপনের সময়"
        return super().generate(system, user)


class SpyIndex(tf.FakeIndex):
    def __init__(self):
        self.queries = []

    def search(self, q, k=6):
        self.queries.append(q)
        return super().search(q, k)


def test_mixed_question_is_searched_in_bangla(tmp_path):
    from chashibondhu.assistant.fosholi import ask_stream
    from chashibondhu.assistant.service import Assistant
    llm, idx = Recorder(), SpyIndex()
    a = Assistant(idx, llm, cache_path=tmp_path / "c.json", smart_search=False)
    list(ask_stream(a, "ekhon kon বীজ bopon korbo dhaner jonno"))
    assert idx.queries == ["ধানের জাত বপনের সময়"] and llm.prompts[0].startswith("Rewrite")
    idx2, llm2 = SpyIndex(), Recorder()
    b = Assistant(idx2, llm2, cache_path=tmp_path / "d.json", smart_search=False)
    b.ask("ekhon kon বীজ bopon korbo dhaner jonno")                       # the old path does the same
    assert idx2.queries == ["ধানের জাত বপনের সময়"]


def test_month_names_are_blocked_in_advice_only():
    from chashibondhu.assistant.advice_terms import find_blocked, needs_safety_line
    assert find_blocked("মাস্টার বীজ শীতকালীন (আগস্ট‑অক্টোবর) সময়ে বপন করা যেতে পারে।")
    assert find_blocked("কার্তিকের শেষে লাগান।") and find_blocked("মে মাসে দিন।") and find_blocked("Sow in August.")
    assert not find_blocked("মেঘলা দিনে পানি কম দিন।") and not find_blocked("This may be a nutrient problem.")
    assert not needs_safety_line("আলু কার্তিক মাসে লাগাতে হয়।")             # a book sowing date is not a dose


def test_advice_with_month_is_not_shown(tmp_path):
    text = "VERIFIED:\nNONE\nADVICE:\nআগস্ট‑অক্টোবর সময়ে বপন করুন।\nভালো বীজ বেছে নিন।\n"
    a = tf.make_assistant(tf.TextOnly(text), tmp_path)
    said = [e["text"] for e in tf.events(a, "ধানের বীজ কখন বুনব?") if e["t"] == "s"]
    assert said == ["ভালো বীজ বেছে নিন।"]


def test_prompt_rules():
    from chashibondhu.assistant.service import REWRITE_PROMPT, RETRIEVAL_VERSION, SYSTEM_PROMPT
    assert "Answer exactly what the farmer asked" in SYSTEM_PROMPT and "Most answers\n  need no question" in SYSTEM_PROMPT
    assert "জাত" in REWRITE_PROMPT and RETRIEVAL_VERSION == "8.0"
