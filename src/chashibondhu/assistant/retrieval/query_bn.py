"""Bangla helpers for book search (Phase 7b).

Why this exists:
  * Farmers describe SIGNS ("পাতা হলুদ"); the book uses PROBLEM words ("রোগ", "লক্ষণ", "দমন").
  * Plain BM25 treats "আলুর" and "আলু" as different words.
  * Question words ("কেন", "হয়ে", "যাচ্ছে") add noise.
  * Variety pages say "রং হলুদ" (tuber colour), which looks like a leaf problem to BM25.

What it does (all rules, no model, no network):
  1. light suffix stemming - the raw word is kept too, so nothing is lost,
  2. removes common question/helper words,
  3. detects "problem" questions (disease/pest signs),
  4. tags each passage as problem / variety / general by the words it uses.
The word lists are drafts. Extend them only together with a test.
"""
from __future__ import annotations

from dataclasses import dataclass

from chashibondhu.assistant.retrieval.index import normalize_text, tokenize


def _set(words: list[str]) -> frozenset[str]:
    return frozenset(normalize_text(w) for w in words)


def _tuple(words: list[str]) -> tuple[str, ...]:
    return tuple(normalize_text(w) for w in words)


# Longest first, so "গুলোর" is tried before "র".
SUFFIXES = tuple(sorted(_set(["গুলোর", "গুলোতে", "গুলো", "গুলি", "দের", "য়ের", "ের",
                              "তে", "কে", "টির", "টি", "টা", "র", "য়", "ে"]),
                        key=len, reverse=True))
MIN_STEM = 2          # code points left after stripping

STOPWORDS = _set(["হয়ে", "হয়", "হচ্ছে", "যাচ্ছে", "যায়", "কেন", "কি", "কী", "কীভাবে",
                  "কিভাবে", "কখন", "কোন", "কোথায়", "কত", "আমার", "আমি", "আমাদের", "করে",
                  "করব", "করবো", "করতে", "দিয়ে", "থেকে", "জন্য", "এবং", "ও", "বা", "যে",
                  "এই", "সেই", "এর", "না", "তো", "আছে", "হবে", "হলে"])

# --- question intent -------------------------------------------------------------
Q_STRONG_EXACT = _set(["রোগ", "দাগ"])
Q_STRONG_PREFIX = _tuple(["পোকা", "পচ", "শুকি", "শুকা", "শুকো", "কোঁকড়", "কুঁকড়", "কুঁচকে",
                          "ছিদ্র", "ফুটো", "আক্রমণ", "আক্রান্ত", "ঝরে", "ঝরা", "ঝলসা",
                          "পোড়া", "মোচড়", "ঢলে", "মরে", "মরছে"])
Q_COLOR = _set(["হলুদ", "হলদে", "বাদামি", "বাদামী", "কালো", "সাদা", "লাল", "ফ্যাকাশে"])
Q_PART = _set(["পাতা", "কাণ্ড", "কান্ড", "গাছ", "ফল", "শিকড়", "গোড়া", "ডগা", "শীষ",
               "ফুল", "চারা", "লতা"])

# --- passage tags ----------------------------------------------------------------
D_PROBLEM_EXACT = _set(["রোগ", "দমন", "জাব"])
D_PROBLEM_PREFIX = _tuple(["লক্ষণ", "আক্রমণ", "আক্রান্ত", "ছত্রাক", "ভাইরাস", "ব্যাকটেরিয়া",
                           "পোকা", "কীড়া", "বালাই", "প্রতিকার"])
D_VARIETY_EXACT = _set(["জাত", "ফলন", "টন"])
D_VARIETY_PREFIX = _tuple(["পরিপক্ক", "উদ্ভাবি", "অবমুক্ত", "হেক্টর", "বৈশিষ্ট্য", "শাঁস", "শাস"])

EXPANSION = normalize_text("রোগ লক্ষণ দমন")


def _is_bangla(token: str) -> bool:
    return bool(token) and "\u0980" <= token[0] <= "\u09FF"


def stem(token: str) -> str:
    """Strip ONE common Bangla ending: আলুর -> আলু, পাতায় -> পাতা, রোগের -> রোগ."""
    if not _is_bangla(token):
        return token
    for suffix in SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) >= MIN_STEM:
            return token[: -len(suffix)]
    return token


def bm25_tokens(text: str) -> list[str]:
    """Raw word + its stem (when different); stopwords removed."""
    out: list[str] = []
    for tok in tokenize(text):
        if tok in STOPWORDS:
            continue
        out.append(tok)
        s = stem(tok)
        if s != tok and s not in STOPWORDS:
            out.append(s)
    return out


def _count(tokens: list[str], exact: frozenset[str], prefix: tuple[str, ...]) -> int:
    n = 0
    for tok in tokens:
        if tok in exact or stem(tok) in exact or (prefix and tok.startswith(prefix)):
            n += 1
    return n


def detect_intent(text: str) -> str:
    """'problem' if the question describes a disease/pest sign, else 'general'.
    A colour word counts only together with a plant part ("পাতা হলুদ"),
    so "আলুর রং হলুদ কোন জাত" stays general."""
    toks = tokenize(text)
    if _count(toks, Q_STRONG_EXACT, Q_STRONG_PREFIX):
        return "problem"
    if _count(toks, Q_COLOR, ()) and _count(toks, Q_PART, ()):
        return "problem"
    return "general"


def tag_passage(text: str) -> str:
    """'problem' (disease/pest/control), 'variety' (variety description) or 'general'."""
    toks = tokenize(text)
    p = _count(toks, D_PROBLEM_EXACT, D_PROBLEM_PREFIX)
    v = _count(toks, D_VARIETY_EXACT, D_VARIETY_PREFIX)
    if p >= 2 and p >= v:
        return "problem"
    if v >= 2 and v > p:
        return "variety"
    return "general"


@dataclass(frozen=True)
class QueryPlan:
    question: str
    intent: str
    search_text: str            # question (+ expansion words for problem questions)
    tokens: tuple[str, ...]     # BM25 tokens of search_text


def plan_query(question: str) -> QueryPlan:
    q = " ".join(question.split())
    intent = detect_intent(q)
    search_text = f"{q} {EXPANSION}" if intent == "problem" else q
    return QueryPlan(q, intent, search_text, tuple(bm25_tokens(search_text)))
