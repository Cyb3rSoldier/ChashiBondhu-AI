"""Fosholi (ফসলি): the handbook assistant. Natural, conversational answers, streamed sentence by sentence.

How an answer is made (v8):
  1. The question (and, for a follow-up, the last turns of the chat) -> a Bangla search query
     (Banglish / follow-ups only; one fast call, cached).
  2. Hybrid search in the BARI handbook -> numbered passages.
  3. ONE model call writes a natural answer: paragraphs, a list only when it helps, no fixed sections.
     Every sentence that uses the handbook ends with its source number [n].
  4. Each finished sentence is checked BEFORE the farmer sees it:
       with a valid [n]  -> every number must be in the cited passages (else removed)          = "verified"
       without [n]       -> general guidance: no numbers, no fertilizer / chemical / product
                            names, no month names (else removed)                                = "advice"
  5. The final answer (ordered lines with their layout) is cached; the old /assistant page uses the same path.
No fact, number, dose or date reaches the farmer unless it is in the handbook text that was retrieved.

Events (one JSON per line in the route):
  {"t": "start"}
  {"t": "s", "part": "verified"|"advice"|"head", "blk": "p"|"ul"|"ol"|"h", "new": bool, "text": "...", "cites": [..]}
  {"t": "done", "status", "safety", "fallback", "sources", "support", "general", "answer", "result", ...}
  {"t": "error", "code": "ai_busy"|"ai_error"}
"""
from __future__ import annotations

import re
from typing import Iterator

from chashibondhu.assistant.advice_terms import _find_terms, find_blocked
from chashibondhu.assistant.guard import guard_numbers, numbers_in, split_sentences
from chashibondhu.assistant.llm.gemini import LLMError, RateLimited
from chashibondhu.assistant.llm.streaming import stream_text
from chashibondhu.assistant.service import (ADVICE_NOTE, FOLLOWUP_PROMPT, GUARD_NOTE, LABELS, REWRITE_PROMPT,
                                            SYSTEM_PROMPT, TERM_NOTE, _looks_english, has_bangla, needs_rewrite,
                                            needs_safety, strip_tags)

_MARKER = re.compile(r"^\s*[#*]*\s*(VERIFIED|ADVICE)\s*\**\s*:?\s*\**\s*", re.I)   # old two-part format
_MARK = re.compile(r"\[\s*(\d+)\s*\]")
_UL = re.compile(r"^\s*[-•*]\s+")
_OL = re.compile(r"^\s*(?:[\d০-৯]{1,2})[.)]\s+")
_HEAD = re.compile(r"^\s*#{1,4}\s+")
_BOUNDARY = re.compile(r"[।!?]\s+")


def _clean(sentence: str) -> str:
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", strip_tags(sentence))
    return re.sub(r"\s+([।,])", r"\1", _MARK.sub("", s)).strip(" *")


class _Guarded:
    """Checks each sentence before it is shown; keeps the layout (paragraph / list / heading)."""

    def __init__(self, hits):
        self.hits = hits
        self.src = "\n".join(h.chunk["text"] for h in hits)
        self.verified, self.advice, self.removed, self.notes, self.cited = [], [], [], [], set()
        self.lines: list[dict] = []
        self._shown_in_line = False

    def _note(self, n):
        if n not in self.notes:
            self.notes.append(n)

    def line(self, line: str, finished: bool = True) -> Iterator[dict]:
        """A whole output line (finished=True) or the finished sentences of a long line still being written."""
        if not getattr(self, "_open", False):
            line = _MARKER.sub("", line)
            blk = "p"
            if _HEAD.match(line):
                blk, line = "h", _HEAD.sub("", line)
            elif _UL.match(line):
                blk, line = "ul", _UL.sub("", line)
            elif _OL.match(line):
                blk, line = "ol", _OL.sub("", line)
            self._blk, self._shown_in_line = blk, False
        self._open = not finished
        if self._blk == "h":
            ev = self.heading(line)
            if ev:
                yield ev
            return
        for s in split_sentences(line):
            ev = self.sentence(s)
            if ev:
                ev["blk"], ev["new"] = self._blk, not self._shown_in_line
                self._shown_in_line = True
                self.lines.append({k: ev[k] for k in ("part", "blk", "new", "text", "cites")})
                yield ev

    def heading(self, text: str) -> dict | None:
        text = _clean(text).rstrip(":：")
        if not text or len(text) > 60 or numbers_in(text) or _find_terms(text):
            return None
        ev = {"t": "s", "part": "head", "blk": "h", "new": True, "text": text, "cites": []}
        self.lines.append({k: ev[k] for k in ("part", "blk", "new", "text", "cites")})
        return ev

    def sentence(self, s: str) -> dict | None:
        s = s.strip()
        if not s or s.strip(" .*").upper() == "NONE":
            return None
        marks = sorted({int(x) for x in _MARK.findall(s) if 1 <= int(x) <= len(self.hits)})
        if marks:                                         # book sentence: its numbers must be in the passages
            _, gone = guard_numbers(s, self.src)
            if gone:
                self.removed += gone
                self._note(GUARD_NOTE)
                return None
            self.cited.update(marks)
            self.verified.append(s)
            return {"t": "s", "part": "verified", "text": _clean(s), "cites": marks}
        if numbers_in(s):                                 # general guidance: no numbers, names or dates
            self.removed.append(s)
            self._note(ADVICE_NOTE)
            return None
        if find_blocked(s):
            self.removed.append(s)
            self._note(TERM_NOTE)
            return None
        text = _clean(s)
        if not text:
            return None
        self.advice.append(text)
        return {"t": "s", "part": "advice", "text": text, "cites": []}


def _lang(q: str) -> str:
    return "bn" if has_bangla(q) or not _looks_english(q) else "en"


def lines_to_text(lines: list[dict]) -> str:
    """Plain text of the answer with its layout (saved message, read aloud, old page)."""
    out, cur = [], ""
    for ln in lines:
        start = ln["new"] or ln["blk"] == "h"
        if start and cur:
            out.append(cur)
            cur = ""
        if ln["blk"] == "h":
            out.append(ln["text"])
            continue
        prefix = ("- " if ln["blk"] == "ul" else "• " if ln["blk"] == "ol" else "") if start else ""
        cur = (cur + " " + ln["text"]).strip() if cur else prefix + ln["text"]
    if cur:
        out.append(cur)
    return "\n".join(out)


def _finish_events(result: dict, lang: str) -> dict:
    L = LABELS[lang]
    verified, advice = result.get("verified") or "", result.get("advice") or ""
    q = result.get("question") or ""
    safety = L["safety"] if (verified or advice) and needs_safety(q, verified) else ""
    try:
        from chashibondhu.assistant.retrieval.query_bn import detect_intent
        problem = detect_intent(q) == "problem"
    except Exception:  # noqa: BLE001
        problem = False
    return {"t": "done", "status": result.get("status"), "safety": safety,
            "fallback": L["fallback"] if not verified and not advice else "",
            "sources": result.get("sources") or [], "model": result.get("model"),
            "cached": bool(result.get("cached")), "answer": result.get("answer", ""),
            "removed": len(result.get("removed_sentences") or []),
            "general": bool(advice),                      # part of the answer is general guidance (no book page)
            "support": problem or not verified,           # help line: crop problems, or the book had no answer
            "result": result}


def _history_text(history: list | None, turns: int = 2) -> tuple[str, str]:
    """-> (conversation text for the prompt, last farmer question). history = saved messages, oldest first."""
    msgs = [m for m in (history or []) if m.get("role") in ("user", "assistant") and (m.get("content") or "").strip()]
    msgs = msgs[-2 * turns:]
    if not msgs:
        return "", ""
    lines = [("Farmer: " if m["role"] == "user" else "Fosholi: ") + " ".join(str(m["content"]).split())[:350]
             for m in msgs]
    last_q = next((" ".join(str(m["content"]).split()) for m in reversed(msgs) if m["role"] == "user"), "")
    return "\n".join(lines), last_q


def ask_stream(assistant, question: str, context: str = "", history: list | None = None) -> Iterator[dict]:
    """context: "district Rangpur; month November". history: earlier messages of THIS chat (for follow-ups)."""
    q = " ".join(question.split())
    if not 2 <= len(q) <= 500:
        raise ValueError("question must be 2-500 characters")
    lang = _lang(q)
    yield {"t": "start"}
    context = " ".join((context or "").split())[:160]
    convo, last_q = _history_text(history)
    key = assistant._key("answer", q + (f" || after: {last_q}" if last_q else ""), context)
    cached = assistant._cache_get(key)
    if cached and cached.get("lines"):              # real stored answer, same layout
        for ln in cached["lines"]:
            yield {"t": "s", "cites": [], **ln}         # same fields and order of keys as the live stream
        yield _finish_events({**cached, "cached": True}, lang)
        return

    calls, search_q = 0, q
    prompt, text = None, q
    if last_q:                                       # follow-up: make a standalone query from the chat
        prompt, text = FOLLOWUP_PROMPT, f"Conversation so far:\n{convo}\n\nNew message: {q}"
    elif needs_rewrite(q) and assistant.rewrite_latin_queries:
        prompt = REWRITE_PROMPT
    if prompt:
        rkey = assistant._key("rewrite", text)
        search_q = assistant._cache_get(rkey) or ""
        if not search_q:
            try:
                search_q = assistant.llm.generate(prompt, text).strip()[:200]
                calls += 1
            except RateLimited:
                yield {"t": "error", "code": "ai_busy"}
                return
            except LLMError:
                search_q = q if not last_q else f"{last_q} {q}"
            if search_q and search_q != q:
                assistant._cache_put(rkey, search_q)
        search_q = search_q or q

    hits = assistant._search(search_q, k=assistant.k)
    sources = ("\n\n".join(f"[{i}] (page {h.chunk.get('printed_page') or h.chunk['pdf_page']})\n{h.chunk['text']}"
                           for i, h in enumerate(hits, start=1)) if hits else "(no matching passages found)")
    user = (f"Sources:\n{sources}\n\n" + (f"Farmer: {context}\n" if context else "")
            + (f"Conversation so far:\n{convo}\n\n" if convo else "") + f"Question: {q}")
    g, info, buf = _Guarded(hits), {}, ""
    try:
        for piece in stream_text(assistant.llm, SYSTEM_PROMPT, user, info):
            buf += piece
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                yield from g.line(line, finished=True)
            last = None                               # long line still being written: show finished sentences
            for m in _BOUNDARY.finditer(buf):
                last = m
            if last and len(buf) > last.end():
                done, buf = buf[:last.end()], buf[last.end():]
                yield from g.line(done, finished=False)
        if buf.strip() or getattr(g, "_open", False):
            yield from g.line(buf, finished=True)
        calls += 1
    except RateLimited:
        yield {"t": "error", "code": "ai_busy"}
        return
    except LLMError:
        yield {"t": "error", "code": "ai_error"}
        return

    L = LABELS[lang]
    verified, advice = "\n".join(g.verified), "\n".join(g.advice)
    answer = lines_to_text(g.lines) or L["fallback"]
    if needs_safety(q, verified) and (verified or advice):
        answer += "\n" + L["safety"]
    status = ("verified_and_advice" if verified and advice else "verified" if verified
              else "advice_only" if advice else "need_more_info")
    refs = [assistant._source(n, hits[n - 1]) for n in sorted(g.cited)]
    if info.get("model") and hasattr(assistant.llm, "last_model"):
        assistant.llm.last_model = info["model"]
    result = assistant._finish(key, q, search_q, status, answer, refs, g.removed, calls,
                               verified=verified, advice=advice, notes=g.notes, lines=g.lines)
    result["model"] = info.get("model") or result.get("model")
    yield _finish_events(result, lang)
