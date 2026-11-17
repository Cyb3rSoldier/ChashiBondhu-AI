"""Term guard for the ADVICE part (Phase 7b).

Key decision 3: numbers, doses, fertilizer / nutrient / chemical / product names come
from sources or the agriculture office - never from the LLM. The prompt asks for this,
but the LLM still wrote "নাইট্রোজেনের অভাব ... জৈব সার দিন". So this is enforced in code:
any ADVICE sentence that names one of these is removed (same idea as the number guard).
Trade-off: a safe sentence like "বৃষ্টির আগে স্প্রে করবেন না" is also removed. Safety first.
The lists are drafts: extend them together with a test.
"""
from __future__ import annotations

import re

from chashibondhu.assistant.retrieval.index import normalize_text

_BN_TERMS = [
    # nutrients / fertilizers
    "নাইট্রোজেন", "ফসফরাস", "পটাশ", "ইউরিয়া", "টিএসপি", "এমওপি", "ডিএপি", "জিপসাম",
    "বোরন", "বোরিক", "জিংক", "দস্তা", "সালফার", "গন্ধক", "ম্যাগনেসিয়াম", "ক্যালসিয়াম",
    # chemical groups
    "কীটনাশক", "ছত্রাকনাশক", "বালাইনাশক", "আগাছানাশক", "কপার", "ম্যানকোজেব",
    # instructions to apply something
    "সার দিন", "সার দেওয়", "সার দেয়", "সার প্রয়োগ", "স্প্রে কর", "ওষুধ দিন",
    "ওষুধ প্রয়োগ", "বিষ দিন", "চুন দিন",
]
BLOCKED_BN = tuple(normalize_text(t) for t in _BN_TERMS)
BLOCKED_EN = re.compile(
    r"\b(?:urea|tsp|mop|dap|gypsum|boron|zinc|sulfur|sulphur|nitrogen|phosphorus|phosphate"
    r"|potash|potassium|magnesium|fungicide|insecticide|pesticide|herbicide|bactericide"
    r"|mancozeb)\b|\bspray|\bapply\s+(?:\w+\s+)?fertili[sz]er", re.I)

# Extra signs (only for the VERIFIED part) that a book sentence gives a dose or spray step.
_SAFETY_BN = tuple(normalize_text(t) for t in
                   ["স্প্রে", "প্রতি লিটার", "লিটার পানিতে", "গ্রাম হারে", "মিলি", "শোধন"])
_SPLIT_RE = re.compile(r"(?<=[।!?.])\s+|\n+")


# Dates are not allowed in ADVICE either (key decision 3): month names carry a timing claim without a digit,
# e.g. "আগস্ট-অক্টোবর সময়ে বপন করুন". Sowing times must come from the book (VERIFIED) instead.
_MONTHS_BN = tuple(normalize_text(m) for m in [
    "জানুয়ারি", "জানুয়ারী", "ফেব্রুয়ারি", "ফেব্রুয়ারী", "মার্চ", "এপ্রিল", "জুলাই", "আগস্ট", "অগাস্ট",
    "সেপ্টেম্বর", "অক্টোবর", "নভেম্বর", "ডিসেম্বর", "বৈশাখ", "জ্যৈষ্ঠ", "জৈষ্ঠ", "আষাঢ়", "আষাঢ", "শ্রাবণ",
    "ভাদ্র", "আশ্বিন", "কার্তিক", "অগ্রহায়ণ", "অগ্রহায়ন", "পৌষ", "মাঘ", "ফাল্গুন", "চৈত্র"])
_MONTHS_BN_EXACT = (normalize_text("মে"), normalize_text("জুন"))
_MONTHS_EN = re.compile(r"\b(?:january|february|march|april|june|july|august|september|october|november"
                        r"|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\b", re.I)
_WORD_SPLIT = re.compile(r"[^\u0980-\u09FFa-z]+")


def find_dates(text: str) -> list[str]:
    words = [w for w in _WORD_SPLIT.split(normalize_text(text)) if w]
    found = [w for w in words if w in _MONTHS_BN_EXACT or any(w.startswith(m) for m in _MONTHS_BN)]
    found += [m.group(0).lower() for m in _MONTHS_EN.finditer(text)]
    return found


def _find_terms(text: str) -> list[str]:
    norm = normalize_text(text)
    found = [t for t in BLOCKED_BN if t in norm]
    found += [m.group(0).lower() for m in BLOCKED_EN.finditer(text)]
    return found


def find_blocked(text: str) -> list[str]:
    """Names (fertilizer / nutrient / chemical) and dates: not allowed in ADVICE. ("may" is not a month here:
    English advice says "may be".)"""
    return _find_terms(text) + find_dates(text)


def drop_blocked_sentences(text: str) -> tuple[str, list[str]]:
    kept, removed = [], []
    for sentence in _SPLIT_RE.split(text):
        sentence = sentence.strip()
        if sentence:
            (removed if find_blocked(sentence) else kept).append(sentence)
    return "\n".join(kept), removed


def needs_safety_line(text: str) -> bool:
    """True if a (book) text mentions fertilizer/chemical names or dose/spray steps."""
    norm = normalize_text(text)
    return bool(_find_terms(text)) or any(t in norm for t in _SAFETY_BN)
