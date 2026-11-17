"""Fosholi (ফসলি): the handbook assistant, streamed sentence by sentence (AI-1).

Same knowledge, prompt, search, guards and cache as service.Assistant.ask (nothing weaker):
  * VERIFIED sentences are shown only if they cite a real passage [n] AND every number is in the passages.
  * ADVICE sentences are shown only if they have no number and no fertilizer / nutrient / chemical name.
  * A VERIFIED sentence without a valid citation is treated as ADVICE (same as ask()).
A sentence is checked as soon as it is complete, then sent to the browser - so the farmer sees the answer
grow, and never sees a sentence that a guard would remove. The final result is cached in the SAME cache
as ask(), so both paths stay consistent.

Events (dicts, the route sends one JSON per line):
  {"t": "start"}
  {"t": "s", "part": "verified"|"advice", "text": "...", "cites": [1, 3]}
  {"t": "done", "status", "safety", "fallback", "sources", "model", "cached", ...}
  {"t": "error", "code": "ai_busy"|"ai_error"}
"""
from __future__ import annotations

import re
from typing import Iterator

from chashibondhu.assistant.advice_terms import find_blocked, needs_safety_line
from chashibondhu.assistant.guard import guard_numbers, numbers_in, split_sentences
from chashibondhu.assistant.llm.gemini import LLMError, RateLimited
from chashibondhu.assistant.llm.streaming import stream_text
from chashibondhu.assistant.service import (ADVICE_NOTE, GUARD_NOTE, LABELS, REWRITE_PROMPT, SYSTEM_PROMPT,
                                            TERM_NOTE, _looks_english, has_bangla, needs_rewrite)

_MARKER = re.compile(r"^\s*[#*]*\s*(VERIFIED|ADVICE)\s*\**\s*:?\s*\**\s*", re.I)
_MARK = re.compile(r"\[\s*(\d+)\s*\]")
_LIST = re.compile(r"^\s*(?:[\d০-৯]{1,2}[.)]|[-•*])\s+")
_BOUNDARY = re.compile(r"[।!?]\s+")


def _clean(sentence: str) -> str:
    return re.sub(r"\s+([।,])", r"\1", _MARK.sub("", sentence)).strip(" *")


class _Guarded:
    """Checks sentences one by one, exactly like the guards in ask()."""

    def __init__(self, hits):
        self.hits = hits
        self.src = "\n".join(h.chunk["text"] for h in hits)
        self.section = "ADVICE"             # text before any marker = advice (safe side, like parse_sections)
        self.verified, self.advice, self.removed, self.notes, self.cited = [], [], [], [], set()

    def _note(self, n):
        if n not in self.notes:
            self.notes.append(n)

    def line(self, line: str) -> Iterator[dict]:
        m = _MARKER.match(line)
        if m:
            self.section = m.group(1).upper()
            line = line[m.end():]
        for s in split_sentences(line):
            ev = self.sentence(s)
            if ev:
                yield ev

    def sentence(self, s: str) -> dict | None:
        s = s.strip()
        if not s or s.strip(" .*").upper() == "NONE":
            return None
        if self.section == "VERIFIED":
            marks = sorted({int(x) for x in _MARK.findall(s) if 1 <= int(x) <= len(self.hits)})
            if marks:
                _, gone = guard_numbers(s, self.src)
                if gone:
                    self.removed += gone
                    self._note(GUARD_NOTE)
                    return None
                self.cited.update(marks)
                self.verified.append(s)
                return {"t": "s", "part": "verified", "text": _clean(s), "cites": marks}
        body = _LIST.sub("", s)
        if numbers_in(body):
            self.removed.append(s)
            self._note(ADVICE_NOTE)
            return None
        if find_blocked(s):
            self.removed.append(s)
            self._note(TERM_NOTE)
            return None
        text = _clean(body)
        if not text:
            return None
        self.advice.append(text)
        return {"t": "s", "part": "advice", "text": text, "cites": []}


def _lang(q: str) -> str:
    return "bn" if has_bangla(q) or not _looks_english(q) else "en"


def _finish_events(result: dict, lang: str) -> dict:
    L = LABELS[lang]
    verified, advice = result.get("verified") or "", result.get("advice") or ""
    safety = L["safety"] if advice or (verified and needs_safety_line(verified)) else ""
    return {"t": "done", "status": result.get("status"), "safety": safety,
            "fallback": L["fallback"] if not verified and not advice else "",
            "advice_label": L["advice"].rstrip(":"), "sources": result.get("sources") or [],
            "model": result.get("model"), "cached": bool(result.get("cached")), "answer": result.get("answer", ""),
            "removed": len(result.get("removed_sentences") or [])}


def ask_stream(assistant, question: str) -> Iterator[dict]:
    q = " ".join(question.split())
    if not 2 <= len(q) <= 500:
        raise ValueError("question must be 2-500 characters")
    lang = _lang(q)
    yield {"t": "start"}
    key = assistant._key("answer", q)
    cached = assistant._cache_get(key)
    if cached:                                  # real stored answer: sent in the same sentence form
        for s in split_sentences(cached.get("verified") or ""):
            yield {"t": "s", "part": "verified", "text": _clean(s),
                   "cites": sorted({int(x) for x in _MARK.findall(s)})}
        for s in split_sentences(cached.get("advice") or ""):
            yield {"t": "s", "part": "advice", "text": _clean(s), "cites": []}
        yield _finish_events({**cached, "cached": True}, lang)
        return

    calls, search_q = 0, q
    if needs_rewrite(q) and assistant.rewrite_latin_queries:
        rkey = assistant._key("rewrite", q)
        search_q = assistant._cache_get(rkey) or ""
        if not search_q:
            try:
                search_q = assistant.llm.generate(REWRITE_PROMPT, q).strip()[:200]
                calls += 1
            except RateLimited:
                yield {"t": "error", "code": "ai_busy"}
                return
            except LLMError:
                search_q = q
            if search_q != q:
                assistant._cache_put(rkey, search_q)

    hits = assistant._search(search_q, k=assistant.k)
    sources = ("\n\n".join(f"[{i}] (page {h.chunk.get('printed_page') or h.chunk['pdf_page']})\n{h.chunk['text']}"
                           for i, h in enumerate(hits, start=1)) if hits else "(no matching passages found)")
    user = f"Sources:\n{sources}\n\nQuestion: {q}"
    g, info, buf = _Guarded(hits), {}, ""
    try:
        for piece in stream_text(assistant.llm, SYSTEM_PROMPT, user, info):
            buf += piece
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                yield from g.line(line)
            # long line with finished sentences (no newline yet): check those now
            last = None
            for m in _BOUNDARY.finditer(buf):
                last = m
            if last and len(buf) > last.end():
                done, buf = buf[:last.end()], buf[last.end():]
                yield from g.line(done)
        yield from g.line(buf)
        calls += 1
    except RateLimited:
        yield {"t": "error", "code": "ai_busy"}
        return
    except LLMError:
        yield {"t": "error", "code": "ai_error"}
        return

    L = LABELS[lang]
    verified, advice = "\n".join(g.verified), "\n".join(g.advice)
    blocks = []
    if verified:
        text = re.sub(r"\s+।", "।", _MARK.sub("", verified)).strip()
        if not advice and needs_safety_line(verified):
            text += "\n" + L["safety"]
        blocks.append(text)
    if advice:
        blocks.append(f"{L['advice']}\n{advice}\n{L['safety']}")
    if not blocks:
        blocks.append(L["fallback"])
    status = ("verified_and_advice" if verified and advice else "verified" if verified
              else "advice_only" if advice else "need_more_info")
    refs = [assistant._source(n, hits[n - 1]) for n in sorted(g.cited)]
    if info.get("model") and hasattr(assistant.llm, "last_model"):
        assistant.llm.last_model = info["model"]
    result = assistant._finish(key, q, search_q, status, "\n\n".join(blocks), refs, g.removed, calls,
                               verified=verified, advice=advice, notes=g.notes)
    result["model"] = info.get("model") or result.get("model")
    yield _finish_events(result, lang)
