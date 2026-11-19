"""ChashiBondhu assistant v1.3: verified book answer + safe AI advice (Phase 7b).

Goal (user decision): never leave a farmer with only "I don't know".
Every reply has up to two parts:
  VERIFIED - only what the retrieved BARI book passages say, with [n] page marks.
             The number guard removes any sentence whose number is not in them.
             If the book text gives a dose / spray / chemical step, the safety line is added.
  ADVICE   - general advice when the book does not fully answer: possible causes,
             what to check, safe steps, at most one follow-up question.
             Guards remove any advice sentence with a number, or with a fertilizer /
             nutrient / chemical name (advice_terms.py).
Flow: (Banglish/English -> 1 call rewrites to a Bangla search query) -> smart hybrid search
on the PC (stems, symptom intent, section boost; free) -> ONE LLM call writes both parts
-> guards -> cache. Cache key = model + index build + prompts + retrieval version.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from pathlib import Path

from chashibondhu.assistant.advice_terms import drop_blocked_sentences, needs_safety_line
from chashibondhu.assistant.guard import guard_numbers, numbers_in, split_sentences
from chashibondhu.assistant.llm.gemini import LLMError, RateLimited
from chashibondhu.assistant.retrieval.index import RagIndex, normalize_text

# Bump when search behaviour changes, so old cached answers are not reused.
RETRIEVAL_VERSION = "8.0"    # 8.0: natural answers (no fixed sections), follow-up questions use the chat

LABELS = {
    "bn": {"advice": "পরামর্শ:",
           "safety": "ওষুধ বা সার কেনা ও দেওয়ার আগে স্থানীয় কৃষি অফিসে নিশ্চিত হোন।",
           "fallback": "প্রশ্নটা আরেকটু খুলে বলবেন? কোন ফসল, কত দিন বয়স, কী সমস্যা দেখছেন — "
                       "তাহলে ভালো পরামর্শ দিতে পারবো। জরুরি হলে স্থানীয় কৃষি অফিসে যোগাযোগ করুন।"},
    "en": {"advice": "Advice:",
           "safety": "Before buying or using any medicine or fertilizer, confirm with your "
                     "local agriculture office.",
           "fallback": "Could you tell me a bit more: which crop, how old, and what problem "
                       "you see? If urgent, please contact your local agriculture office."},
}
RATE_LIMIT_BN = "এখন অনেক প্রশ্ন এসেছে। এক মিনিট পরে আবার চেষ্টা করুন।"
GUARD_NOTE = "Some sentences were removed because their numbers were not in the source."
ADVICE_NOTE = "Advice sentences with numbers were removed (numbers must come from a source)."
TERM_NOTE = ("Advice sentences naming fertilizers, nutrients or chemicals were removed "
             "(these must come from a source).")
SOURCE_LABEL = "BARI Krishi Projukti Hatboi, 10th ed."

SYSTEM_PROMPT = """You are Fosholi (ফসলি), the farming knowledge assistant of ChashiBondhu for farmers in Bangladesh.
Answer like a knowledgeable agricultural expert talking to a farmer: natural, simple, everyday Bangla
(Bangla script and Bangla words, for example "কাণ্ড", not "স্টেম"), short clear sentences.
The numbered handbook passages (Sources) are your main knowledge.

How to answer:
- Answer exactly what the farmer asked, directly, in normal paragraphs (usually one to three short ones).
  No introduction, no closing summary, no repeated points.
- Use only the parts of the sources that answer THIS question. Do not add other topics just because they
  are in the sources. Do not copy whole passages: explain in simple words.
- Keep the handbook's facts exactly: numbers, distances, amounts, dates, months, varieties and terms as written.
  End every sentence that uses a source with its source number, like [1].
- Use a short list (lines starting with "- ") only when naming several items, and numbered steps ("1. ")
  only for work done in order. Use a heading (a line starting with "### ") only in a long answer.
- If the farmer describes signs (yellow leaves, spots, rot, wilting) and the sources describe problems of that
  crop with matching signs, say what it MAY be ("... হতে পারে") and how to recognise it, from the sources.
- If the sources do not contain what was asked, say that in one plain sentence (for example
  "হাতবইয়ে এ বিষয়ে নির্দিষ্ট তথ্য পাওয়া যায়নি।"), then you may add a little general, safe guidance.
- General guidance that is not from the sources: no [n], no numbers, doses, amounts, dates or month names,
  and no fertilizer, nutrient, pesticide, chemical, product or variety names. Never say a cause is certain.
- Same crop only: answer about the crop the farmer asked about (sweet potato is not potato).
- Never tell the farmer to cut, pull out, burn or destroy plants. Do not write a line about the agriculture
  office or a hotline: the app shows that help itself.
- Ask the farmer a question only when the answer really depends on something they did not say. Most answers
  need no question.
- "Conversation so far" (if given) is the earlier chat. The new question may continue it (for example
  "how much distance?" after a potato question is about potato). Do not repeat what was already said.
- A "Farmer:" line gives the district and month. Use it only to fit general guidance to the season and place;
  never invent local facts, prices or weather.
- If the question is in English, answer in simple English with the same rules."""

FOLLOWUP_PROMPT = """The farmer's new message may continue the earlier conversation. Write ONE short standalone
Bangla search query in Bangla script (crop name + topic) for the new message, using the conversation to fill in
what the new message leaves out (for example the crop). Keep signs the farmer describes. If the farmer asks
which seed or variety, use the word জাত. Output only the query, nothing else."""

SECTIONS = ("cause", "now", "fix", "care", "extra")
TAG_RE = re.compile(r"^\s*[{\[(]\s*(cause|now|fix|care|extra)\s*[}\])]\s*:?\s*", re.I)
_ANY_TAG_RE = re.compile(r"[{\[(]\s*(?:cause|now|fix|care|extra)\s*[}\])]\s*:?\s*", re.I)


def split_tag(sentence: str) -> tuple[str, str]:
    """'{now} পানি সরান।' -> ('now', 'পানি সরান।'). No tag -> ('', sentence)."""
    m = TAG_RE.match(sentence)
    return (m.group(1).lower(), sentence[m.end():]) if m else ("", sentence)


def strip_tags(text: str) -> str:
    return _ANY_TAG_RE.sub("", text)


def needs_safety(question: str, verified: str) -> bool:
    """The 'confirm before buying medicine / fertilizer' line only when the topic is medicine or fertilizer
    (asked by the farmer, or a dose / spray step in the book text) - not under every answer."""
    return bool(_MEDICINE_TOPIC.search(question)) or needs_safety_line(question) or needs_safety_line(verified)


_MEDICINE_TOPIC = re.compile(r"সার|ওষুধ|ঔষধ|কীটনাশক|ছত্রাকনাশক|বালাইনাশক|স্প্রে|\b(?:sar|osudh|oshudh|aushadh|spray|"
                             r"fertili[sz]er|pesticide|fungicide|insecticide|urea|tsp|mop)\b", re.I)

REWRITE_PROMPT = """Rewrite the farmer's question as a short Bangla search query in Bangla
script: crop name + the problem or topic. Keep the signs the farmer describes (for example
yellow leaves, spots, rot, wilting) in simple Bangla words. The question may mix Bangla script
and Bangla written in English letters: understand both. If the farmer asks which seed or variety
to grow, use the word জাত (variety) in the query. Output only the query, nothing else."""

_SECTION_RE = re.compile(r"^\s*[#*]*\s*(VERIFIED|ADVICE)\s*\**\s*:?\s*\**\s*", re.I | re.M)


def parse_sections(raw: str) -> tuple[str, str]:
    """-> (verified, advice). Text without section markers is treated as ADVICE (safe side)."""
    parts = _SECTION_RE.split(raw)
    if len(parts) < 3:
        return "", raw.strip()
    found = {"VERIFIED": "", "ADVICE": ""}
    for i in range(1, len(parts) - 1, 2):
        found[parts[i].upper()] = parts[i + 1].strip()
    clean = {k: ("" if v.strip(" .*").upper() == "NONE" else v) for k, v in found.items()}
    return clean["VERIFIED"], clean["ADVICE"]


def drop_numbered_sentences(text: str) -> tuple[str, list[str]]:
    kept, removed = [], []
    for sentence in split_sentences(text):
        (removed if numbers_in(re.sub(r"^\s*[\d০-৯]{1,2}[.)]\s+", "", sentence))
         else kept).append(sentence)
    return "\n".join(kept), removed


_BANGLA_RE = re.compile(r"[\u0980-\u09FF]")
_MARK_RE = re.compile(r"\[\s*(\d+)\s*\]")


def has_bangla(text: str) -> bool:
    return bool(_BANGLA_RE.search(text))


_LATIN_WORD_RE = re.compile(r"[A-Za-z]{2,}")


def needs_rewrite(text: str) -> bool:
    """Any Banglish / English word -> rewrite to a Bangla search query first.
    (Before 7b.2 only questions WITHOUT any Bangla letter were rewritten, so mixed questions like
    'ekhon kon বীজ bopon korbo' were searched as they were and found the wrong pages.)"""
    return bool(_LATIN_WORD_RE.search(text))


def _pick_search(index, smart: bool):
    """Smart search needs a full RagIndex (chunks + embeddings + embedder).
    Anything simpler (for example a test fake with only .search) uses plain search."""
    if smart and all(hasattr(index, a) for a in ("chunks", "embeddings", "embedder")):
        from chashibondhu.assistant.retrieval.smart import SmartSearch
        return SmartSearch(index).search, "smart"
    return index.search, "plain"


class Assistant:
    def __init__(self, index: RagIndex, llm, cache_path: Path | None = None, k: int = 6,
                 rewrite_latin_queries: bool = True, smart_search: bool = True):
        self.index = index
        self.llm = llm
        self.k = k
        self.rewrite_latin_queries = rewrite_latin_queries
        self._search, self._search_mode = _pick_search(index, smart_search)
        self.cache_path = Path(cache_path) if cache_path else None
        self._lock = threading.Lock()
        self._cache: dict[str, dict] = {}
        if self.cache_path and self.cache_path.exists():
            try:
                self._cache = json.loads(self.cache_path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                self._cache = {}

    # ------------------------------------------------------------ factory
    @classmethod
    def from_env(cls, root: Path) -> "Assistant":
        from chashibondhu.assistant.retrieval.index import E5Embedder
        index_dir = Path(os.environ.get("RAG_INDEX_DIR",
                                        root / "data" / "processed" / "rag" / "kph10"))
        from chashibondhu.assistant.llm.openai_compat import llm_from_env
        llm = llm_from_env(root)
        index = RagIndex.load(index_dir, E5Embedder())
        return cls(index, llm, cache_path=index_dir / "answer_cache.json")

    # ------------------------------------------------------------ cache
    # The key includes prompts and retrieval version: changing either never returns old answers.
    def _key(self, kind: str, text: str, context: str = "") -> str:
        model = getattr(self.llm, "model", "llm")
        built = getattr(self.index, "meta", {}).get("built_utc", "")
        prompt = hashlib.sha256((SYSTEM_PROMPT + REWRITE_PROMPT + FOLLOWUP_PROMPT).encode()).hexdigest()[:8]
        search = f"{RETRIEVAL_VERSION}:{self._search_mode}"
        raw = (f"{kind}|{model}|{built}|{prompt}|{search}|"
               f"{' '.join(normalize_text(text).split())}|{context}")
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _cache_get(self, key: str):
        with self._lock:
            return self._cache.get(key)

    def _cache_put(self, key: str, value) -> None:
        with self._lock:
            self._cache[key] = value
            if self.cache_path:
                tmp = self.cache_path.with_suffix(".tmp")
                tmp.write_text(json.dumps(self._cache, ensure_ascii=False), encoding="utf-8")
                tmp.replace(self.cache_path)

    # ------------------------------------------------------------ main
    def ask(self, question: str, context: str = "", history: list | None = None) -> dict:
        """Whole answer at once (old /assistant page, scripts). Same pipeline and guards as fosholi.ask_stream."""
        from chashibondhu.assistant.fosholi import ask_stream
        q = " ".join(question.split())
        if not 2 <= len(q) <= 500:
            raise ValueError("question must be 2-500 characters")
        done, calls = None, 0
        for ev in ask_stream(self, q, context, history):
            if ev["t"] == "error":
                return self._rate_limited(q, 1) if ev["code"] == "ai_busy" else \
                    {**self._rate_limited(q, 1), "status": "error", "answer": LABELS["bn"]["fallback"]}
            if ev["t"] == "done":
                done = ev
        result = dict(done.get("result") or {})
        if done.get("cached"):
            result.update(cached=True, llm_requests=calls)
        return result

    # ------------------------------------------------------------ helpers
    @staticmethod
    def _source(n: int, hit) -> dict:
        c = hit.chunk
        return {"n": n, "source": SOURCE_LABEL, "source_id": c.get("source_id", ""),
                "printed_page": c.get("printed_page"), "pdf_page": c["pdf_page"],
                "excerpt": c["text"][:200]}

    def _rate_limited(self, q: str, calls: int) -> dict:
        return {"question": q, "status": "rate_limited", "answer": RATE_LIMIT_BN,
                "verified": "", "advice": "", "sources": [], "removed_sentences": [],
                "notes": [], "search_query": "", "model": getattr(self.llm, "model", ""),
                "cached": False, "llm_requests": calls}

    def _finish(self, key, q, search_q, status, answer, refs, removed, calls,
                verified="", advice="", notes=None, lines=None) -> dict:
        result = {"question": q, "status": status, "answer": answer,
                  "verified": verified, "advice": advice, "sources": refs,
                  "removed_sentences": removed, "notes": notes or [],
                  "search_query": search_q, "model": getattr(self.llm, "model", ""),
                  "cached": False, "llm_requests": calls, "lines": lines or []}
        self._cache_put(key, result)
        return result


_ENGLISH_HINTS = {"the", "is", "what", "how", "my", "and", "of", "to", "in", "when", "which",
                  "why", "can", "should", "do", "does", "are", "for", "with"}


def _looks_english(text: str) -> bool:
    """Rough check to tell English from Banglish (both use Latin letters)."""
    words = re.findall(r"[a-z]+", text.lower())
    return bool(words) and sum(w in _ENGLISH_HINTS for w in words) / len(words) >= 0.2
