"""Dr. Krishi (ড. কৃষি): the broad farming assistant (AI-2). Separate from Fosholi (handbook only).

Per question, only the tools the question needs (no AI call to decide):
  image   -> vision model (Groq, Gemma fallback) -> JSON -> diagnosis.check() -> one "diagnosis" event (cards)
  weather -> Open-Meteo for the chosen area (real numbers in a card) + fixed rule tips + short AI explanation
  climate -> 30-year district normal + 2001-2025 NASA grid history (card; history, not a forecast)
  risk    -> says honestly that no live outbreak reports are connected; general seasonal risks only, as possibilities
  general -> AI answer with the conversation so far
Guards on every AI sentence (shown sentence by sentence, like Fosholi):
  * a number is allowed only if it is in the tool data or in the farmer's own question (no invented doses/yields);
  * no fertilizer / nutrient / pesticide / product names (those come from the handbook = Fosholi, or the office).
"""
from __future__ import annotations

import json
import re
from typing import Callable, Iterator

from chashibondhu.assistant.advice_terms import _find_terms
from chashibondhu.assistant.guard import numbers_in, split_sentences
from chashibondhu.assistant.llm.gemini import LLMError, RateLimited
from chashibondhu.assistant.llm.streaming import stream_text

SAFETY_BN = "ওষুধ বা সার দেওয়ার আগে স্থানীয় কৃষি অফিসে নিশ্চিত হোন। মাত্রা জানতে ফসলি-তে (হাতবই) জিজ্ঞেস করুন।"
NO_LOCAL_DATA_BN = ("আপনার এলাকার রোগ-পোকার সর্বশেষ মাঠ-রিপোর্ট এখনো চাষীবন্ধুতে যুক্ত নেই, তাই নিশ্চিত করে বলা যাচ্ছে না। "
                    "নিচে শুধু এই মৌসুমের সাধারণ ঝুঁকি বলা হলো — সর্বশেষ খবরের জন্য উপজেলা কৃষি অফিসে যোগাযোগ করুন।")
REMOVED_ALL_BN = ("এই প্রশ্নের নির্দিষ্ট মাত্রা বা ওষুধের নাম আমি বলি না। হাতবই থেকে উত্তর পেতে ফসলি-তে জিজ্ঞেস করুন, "
                  "অথবা উপজেলা কৃষি অফিসে যোগাযোগ করুন।")

BASE_RULES = """You are Dr. Krishi (ড. কৃষি), a friendly farming advisor in the ChashiBondhu app for farmers in Bangladesh.
Write in simple everyday Bangla (Bangla script) even if the question uses English letters. Short sentences.
Put each sentence on its own line. You may start a line with a short label and a colon, for example "করণীয়: ...".
Strict rules:
- Never give doses, amounts, mixing rates or product / chemical / fertilizer / pesticide names. Say that the dose comes
  from the handbook (ফসলি) or the agriculture office.
- Never invent numbers. Use a number only if it is written in FACTS or in the farmer's question.
- Never say a disease is certain. Say "হতে পারে" (may be).
- No promises about yield or money.
- If you do not know, say so and suggest the local agriculture office.
- If the conversation so far is about a photo diagnosis, stay with that same crop and problem unless the farmer
  clearly asks about something else. Never mix two crops.
Answer the farmer's actual question first. At most 7 short lines."""

WEATHER_TASK = """FACTS has the real weather forecast for the farmer's area (Open-Meteo) and simple farm tips.
Explain in 2-4 lines what it means for the farmer's question (for example when to irrigate or spray). The farmer
already sees the numbers in a card, so repeat at most one or two of them, exactly as written in FACTS."""
CLIMATE_TASK = """FACTS has climate HISTORY for the farmer's area: a 30-year normal and 2001-2025 values for this month.
This is history, not a forecast: say so. Explain in 2-4 lines what it means, using only those numbers."""
RISK_TASK = """No live local disease or pest reports are available. Do not claim any outbreak, number or place.
Give 2-4 lines of GENERAL seasonal risks for the crop or season the farmer asks about, each as a possibility
("... হতে পারে"), and what signs to watch for."""

def _clean_line(s: str) -> str:
    return re.sub(r"^\s*(?:[-•*]|[\d০-৯]{1,2}[.)])\s+", "", s).strip(" *#")


class Guard:
    """Sentence checks. allowed = numbers that are in tool data or in the question."""

    def __init__(self, allowed: set[str]):
        self.allowed, self.kept, self.removed = allowed, [], []

    def check(self, sentence: str) -> str | None:
        s = _clean_line(sentence)
        if not s or s.upper().strip(" .") in ("NONE", "FACTS"):
            return None
        if (numbers_in(s) - self.allowed) or _find_terms(s):
            self.removed.append(s)
            return None
        self.kept.append(s)
        return s


def _context(history: list[dict], limit: int = 6) -> str:
    lines = []
    for m in history[-limit:]:
        who = "Farmer" if m.get("role") == "user" else "Dr. Krishi"
        lines.append(f"{who}: {str(m.get('content') or '')[:400]}")
    return "\n".join(lines)


def _stream_lines(llm, system: str, user: str, guard: Guard, info: dict) -> Iterator[dict]:
    buf = ""
    for piece in stream_text(llm, system, user, info):
        buf += piece
        while "\n" in buf:
            line, buf = buf.split("\n", 1)
            for s in split_sentences(line):
                ok = guard.check(s)
                if ok:
                    yield {"t": "s", "part": "main", "text": ok}
    for s in split_sentences(buf):
        ok = guard.check(s)
        if ok:
            yield {"t": "s", "part": "main", "text": ok}


def answer(question: str, *, llm, intents: list[str], history: list[dict] | None = None,
           image_jpeg: bytes | None = None, vision=None, weather_fn: Callable | None = None,
           climate_fn: Callable | None = None, area: dict | None = None,
           numbers_of: Callable | None = None, catalogue=None, crop_hint: str | None = None,
           book=None) -> Iterator[dict]:
    """Events: start, diagnosis (photo), treat (handbook treatment sentences), card (weather / climate / note),
    s (checked sentences), done, error. catalogue = crop list + problem lists; book = Fosholi assistant."""
    q = " ".join((question or "").split())
    yield {"t": "start", "intents": intents}
    allowed = set(numbers_in(q))
    facts: list[str] = []
    task = ""
    model = None
    history = history or []

    # ---------------------------------------------------------- photo -> one checked, structured diagnosis
    if "image" in intents:
        if vision is None or image_jpeg is None:
            yield {"t": "error", "code": "ai_down"}
            return
        from chashibondhu.assistant import diagnosis as dx
        crop_hint = crop_hint or crop_from_text(q, catalogue)
        ctx = _context(history)
        text = (f"Conversation so far:\n{ctx}\n\n" if ctx else "") + f"Farmer's question: {q or '(no text, only the photo)'}"
        system = dx.build_prompt(catalogue or _NoCatalogue(), crop_hint)
        data = None
        for _ in range(2):                         # one retry if the model's JSON is broken
            try:
                raw = vision.analyze(system, text, image_jpeg)
                model = getattr(vision, "model", None)
            except RateLimited:
                yield {"t": "error", "code": "ai_busy"}
                return
            except LLMError:
                yield {"t": "error", "code": "ai_error"}
                return
            try:
                data = dx.parse(raw)
                break
            except dx.BadJSON:
                continue
        if data is None:
            yield {"t": "error", "code": "ai_error"}
            return
        payload = dx.check(data, q, catalogue, crop_hint)
        yield {"t": "diagnosis", "data": payload}
        text_out = dx.as_text(payload)
        if payload["status"] == "possible" and payload.get("diagnosis") and book is not None:
            treat = yield from _book_treatment(book, payload)
            payload["treatment"] = treat
            if treat["lines"]:
                text_out += "\nচিকিৎসা (হাতবই থেকে):\n" + "\n".join(treat["lines"])
            else:
                payload["support"] = True
        yield {"t": "done", "safety": SAFETY_BN if payload.get("treatment", {}).get("lines") else "", "model": model,
               "removed": payload.get("removed", 0), "answer": text_out, "payload": payload,
               "support": bool(payload.get("support"))}
        return

    # ---------------------------------------------------------- tools for text questions
    pre = _prefetch(intents, area, weather_fn, climate_fn)
    if "weather" in intents:
        if not area:
            yield {"t": "card", "kind": "note", "code": "need_area"}
        else:
            try:
                w = pre["weather"]()
                from chashibondhu.web.drkrishi_tools import farm_tips
                tips = farm_tips(w)
                yield {"t": "card", "kind": "weather", "area": {"bn": area["name_bn"], "en": area["name_en"]},
                       "data": w, "tips": [{"bn": b, "en": e} for b, e in tips]}
                allowed |= numbers_of(w)
                facts.append("WEATHER " + json.dumps(w, ensure_ascii=False))
                facts.append("TIPS " + " ".join(b for b, _ in tips))
                task = WEATHER_TASK
            except Exception:  # noqa: BLE001 - WeatherUnavailable or network
                yield {"t": "card", "kind": "note", "code": "weather_down"}
    if "climate" in intents and area:
        c = pre["climate"]() if climate_fn else None
        if c:
            yield {"t": "card", "kind": "climate", "data": c}
            allowed |= numbers_of(c)
            facts.append("CLIMATE_HISTORY " + json.dumps(c, ensure_ascii=False))
            task = task or CLIMATE_TASK
        else:
            yield {"t": "card", "kind": "note", "code": "climate_missing"}
    if "risk" in intents:
        yield {"t": "card", "kind": "note", "code": "no_local_reports", "text": NO_LOCAL_DATA_BN}
        task = RISK_TASK

    ctx = _context(history)
    user = ((f"FACTS:\n" + "\n".join(facts) + "\n\n") if facts else "") + \
           (f"Conversation so far:\n{ctx}\n\n" if ctx else "") + f"Farmer's question: {q}"
    system = BASE_RULES + ("\n\n" + task if task else "")
    g, info = Guard(allowed), {}
    try:
        yield from _stream_lines(llm, system, user, g, info)
    except RateLimited:
        yield {"t": "error", "code": "ai_busy"}
        return
    except LLMError:
        yield {"t": "error", "code": "ai_error"}
        return
    if not g.kept:
        yield {"t": "s", "part": "main", "text": REMOVED_ALL_BN}
        g.kept.append(REMOVED_ALL_BN)
    yield {"t": "done", "safety": SAFETY_BN if g.removed or "general" in intents else "",
           "model": info.get("model") or getattr(llm, "model", None), "removed": len(g.removed),
           "answer": "\n".join(g.kept)}


class _NoCatalogue:
    crops: dict = {}

    def for_crop(self, crop_id):
        return []


_TEXT_CROP = {"potato": "potato", "maize": "maize", "tomato": "tomato", "mustard": "mustard",
              "mungbean": "mung_bean", "lentil": "lentil", "onion": "onion", "watermelon": "watermelon"}


def crop_from_text(q: str, catalogue) -> str | None:
    """The farmer's own words name ONE catalogue crop ("আলুর পাতায় দাগ") -> use it as the crop hint.
    Rice is skipped (Aman or Boro cannot be told from the word)."""
    if not q or catalogue is None:
        return None
    from chashibondhu.assistant.diagnosis import crops_in
    found = {_TEXT_CROP[k] for k in crops_in(q) if k in _TEXT_CROP}
    found = {c for c in found if c in getattr(catalogue, "crops", {})}
    return next(iter(found)) if len(found) == 1 else None


def _prefetch(intents, area, weather_fn, climate_fn) -> dict:
    """Start the weather (network) and climate (database) look-ups at the same time; each result is
    read with pre[...]() which waits only if it is not ready yet. Errors surface when read."""
    from concurrent.futures import ThreadPoolExecutor
    out = {"weather": lambda: None, "climate": lambda: None}
    jobs = {}
    if "weather" in intents and area and weather_fn:
        jobs["weather"] = lambda: weather_fn(area["lat"], area["lon"])
    if "climate" in intents and area and climate_fn:
        jobs["climate"] = lambda: climate_fn(area["code"])
    if not jobs:
        return out
    ex = ThreadPoolExecutor(max_workers=len(jobs))
    futs = {k: ex.submit(f) for k, f in jobs.items()}
    ex.shutdown(wait=False)
    for k, fut in futs.items():
        out[k] = fut.result
    return out


TREAT_NONE_BN = "হাতবইয়ে এই সমস্যার চিকিৎসা খুঁজে পাওয়া যায়নি। নিচের কৃষি কল সেন্টারে ফোন করে নিশ্চিত হোন।"


def _book_treatment(book, payload: dict):
    """Ask the BARI handbook (Fosholi: verified pages + checked advice) how to manage THIS problem.
    Sends {"t": "treat", ...} events; returns {"lines", "sources", "query"} for saving."""
    from chashibondhu.assistant.fosholi import ask_stream
    d, crop = payload["diagnosis"], payload["crop"]
    query = d.get("search_bn") or f"{crop['bn']} {d['bn']} দমন"
    if crop["bn"] not in query:
        query = f"{crop['bn']} {query}"
    yield {"t": "treat_start", "query": query}
    lines, sources, verified = [], [], 0
    try:
        for ev in ask_stream(book, query):
            if ev["t"] == "s" and ev["part"] != "head":
                lines.append(ev["text"])
                verified += ev["part"] == "verified"
                yield {"t": "treat", "part": ev["part"], "text": ev["text"]}
            elif ev["t"] == "done":
                sources = ev.get("sources") or []
            elif ev["t"] == "error":
                break
    except Exception:  # noqa: BLE001 - the diagnosis is still shown without the book part
        pass
    if not verified:                     # no page-backed treatment: say so, do not pretend
        yield {"t": "treat", "part": "note", "text": TREAT_NONE_BN}
    yield {"t": "treat_done", "sources": sources}
    return {"lines": lines, "sources": sources, "query": query, "verified": verified}
