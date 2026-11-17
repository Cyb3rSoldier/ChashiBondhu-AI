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
RETRIEVAL_VERSION = "7b.2"   # 7b.2: mixed Bangla + Banglish questions are rewritten too

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

SYSTEM_PROMPT = """You are the farming assistant of ChashiBondhu, helping farmers in Bangladesh.
Most farmers read slowly. Write very short, simple sentences in everyday words.
The farmer comes to you BECAUSE they do not know the problem. Always try to help, and be
honest: if you are not sure, say what it may be, not what it is.
Write your reply in exactly two sections:

VERIFIED:
Only what the numbered sources say that answers the question, and only about the SAME
crop the farmer asked about (for example, sweet potato is not potato).
If the farmer describes signs (for example yellow leaves, spots, rot, wilting) and the
sources describe problems of that crop with matching signs, name each one as a POSSIBLE
cause (in Bangla: "... হতে পারে") and say how to recognise it, using only the sources.
At most 4 sentences. End every sentence with its source number, like [1].
Never add anything that is not written in the sources.
If the sources do not answer the question, write only: NONE

ADVICE:
General help that the sources do not already give. Do not repeat VERIFIED.
Length: at most 3 sentences if VERIFIED has an answer; at most 4 if VERIFIED is NONE.
Content: the likely possible causes for THIS crop and how to tell them apart by looking
(old lower leaves or new top leaves, spots or no spots, whole field or a few plants),
and safe steps for the crop that is in the field NOW, for example: drain standing water,
do not over-irrigate, keep weeds away, watch whether the problem spreads.
Strict rules for ADVICE:
- No numbers, doses, amounts or dates.
- No names of fertilizers, nutrients (for example nitrogen), pesticides, chemicals,
  products or varieties. Say "পুষ্টির অভাব" (lack of nutrients) instead of a nutrient name.
- Never say a cause is certain: say "হতে পারে" (may be).
- Never tell the farmer to cut, pull out, burn or destroy leaves or plants. Yellow or
  old leaves can be normal; removing plants is a decision for the agriculture officer.
- No advice for the next season (for example choosing seed).
- Do not write a line about the agriculture office; the app adds it.
Follow-up question: at the end, ask at most ONE short, clear question, only if the answer
really depends on it, and only about something the advice did not already cover.
Ask about signs in the field (leaves, spots, rot) ONLY when the farmer describes a problem in a crop.
For "how to start / which variety / when to sow" questions, never ask about leaves or spots.
Never ask for anything the farmer already said (for example the crop name).
Never ask the farmer to name the disease or the cause - that is your job. Ask only about
things the farmer can see or knows, for example: are the old lower leaves or the new top
leaves yellow, are there spots, is the whole field affected or only some plants, how many
days old is the crop, was there heavy rain or too much irrigation.
If nothing useful can be added, write only: NONE

Language and format: if the question is in Bangla script or Banglish (Bangla written with
English letters), write both sections in simple Bangla script with Bangla words only
(for example "কাণ্ড", not "স্টেম"). If it is in English, use simple English.
Put each sentence on its own line. No bullet marks, no numbering, no bold, no headings
other than VERIFIED: and ADVICE:."""

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
    def _key(self, kind: str, text: str) -> str:
        model = getattr(self.llm, "model", "llm")
        built = getattr(self.index, "meta", {}).get("built_utc", "")
        prompt = hashlib.sha256((SYSTEM_PROMPT + REWRITE_PROMPT).encode()).hexdigest()[:8]
        search = f"{RETRIEVAL_VERSION}:{self._search_mode}"
        raw = (f"{kind}|{model}|{built}|{prompt}|{search}|"
               f"{' '.join(normalize_text(text).split())}")
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
    def ask(self, question: str) -> dict:
        q = " ".join(question.split())
        if not 2 <= len(q) <= 500:
            raise ValueError("question must be 2-500 characters")
        bangla = has_bangla(q)
        key = self._key("answer", q)
        cached = self._cache_get(key)
        if cached:
            return {**cached, "cached": True, "llm_requests": 0}

        calls = 0
        search_q = q
        if needs_rewrite(q) and self.rewrite_latin_queries:
            rkey = self._key("rewrite", q)
            search_q = self._cache_get(rkey) or ""
            if not search_q:
                try:
                    search_q = self.llm.generate(REWRITE_PROMPT, q).strip()[:200]
                    calls += 1
                except RateLimited:
                    return self._rate_limited(q, calls + 1)
                except LLMError:
                    search_q = q        # fall back to the original text
                if search_q != q:
                    self._cache_put(rkey, search_q)

        hits = self._search(search_q, k=self.k)
        if hits:
            sources = "\n\n".join(
                f"[{i}] (page {h.chunk.get('printed_page') or h.chunk['pdf_page']})\n"
                f"{h.chunk['text']}" for i, h in enumerate(hits, start=1))
        else:
            sources = "(no matching passages found)"
        user = f"Sources:\n{sources}\n\nQuestion: {q}"
        try:
            raw = self.llm.generate(SYSTEM_PROMPT, user)
            calls += 1
        except RateLimited:
            return self._rate_limited(q, calls + 1)

        verified, advice = parse_sections(raw)
        removed: list[str] = []
        notes: list[str] = []
        if verified:
            verified, gone = guard_numbers(verified, "\n".join(h.chunk["text"] for h in hits))
            removed += gone
            if gone:
                notes.append(GUARD_NOTE)
        if advice:
            advice, gone = drop_numbered_sentences(advice)
            removed += gone
            if gone:
                notes.append(ADVICE_NOTE)

        cited = sorted({int(m) for m in _MARK_RE.findall(verified) if 1 <= int(m) <= len(hits)})
        verified = _MARK_RE.sub(lambda m: m.group(0) if 1 <= int(m.group(1)) <= len(hits)
                                else "", verified).strip()
        if verified and not cited:          # a "verified" claim without a source is advice
            advice, verified = (verified + "\n" + advice).strip(), ""
            advice, gone = drop_numbered_sentences(advice)
            removed += gone
        if advice:                          # fertilizer / nutrient / chemical names
            advice, gone = drop_blocked_sentences(advice)
            removed += gone
            if gone:
                notes.append(TERM_NOTE)
        refs = [self._source(n, hits[n - 1]) for n in cited]

        lang = "bn" if bangla or not _looks_english(q) else "en"
        L = LABELS[lang]
        # Farmer text: plain answer first, then "পরামর্শ:". No labels, no [n] marks.
        # The verified / advice split and the pages stay in their own fields for admins.
        blocks = []
        if verified:
            text = re.sub(r"\s+।", "।", _MARK_RE.sub("", verified)).strip()
            if not advice and needs_safety_line(verified):   # book dose/spray step
                text += "\n" + L["safety"]
            blocks.append(text)
        if advice:
            blocks.append(f"{L['advice']}\n{advice}\n{L['safety']}")
        if not blocks:
            blocks.append(L["fallback"])
        status = ("verified_and_advice" if verified and advice else
                  "verified" if verified else "advice_only" if advice else "need_more_info")
        return self._finish(key, q, search_q, status, "\n\n".join(blocks), refs, removed,
                            calls, verified=verified, advice=advice, notes=notes)

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
                verified="", advice="", notes=None) -> dict:
        result = {"question": q, "status": status, "answer": answer,
                  "verified": verified, "advice": advice, "sources": refs,
                  "removed_sentences": removed, "notes": notes or [],
                  "search_query": search_q, "model": getattr(self.llm, "model", ""),
                  "cached": False, "llm_requests": calls}
        self._cache_put(key, result)
        return result


_ENGLISH_HINTS = {"the", "is", "what", "how", "my", "and", "of", "to", "in", "when", "which",
                  "why", "can", "should", "do", "does", "are", "for", "with"}


def _looks_english(text: str) -> bool:
    """Rough check to tell English from Banglish (both use Latin letters)."""
    words = re.findall(r"[a-z]+", text.lower())
    return bool(words) and sum(w in _ENGLISH_HINTS for w in words) / len(words) >= 0.2
