"""Number guard (Phase 7): every number in the answer must appear in the sources.

Any sentence with a number that is not in the retrieved passages is removed, and
the removal is reported. Bangla and English digits are treated the same.
Source markers like [1] and list markers like "১." are ignored.
"""
from __future__ import annotations

import re

_BN_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")
_NUM_RE = re.compile(r"\d+(?:\.\d+)?")
_CITE_RE = re.compile(r"\[\s*[\d০-৯]+(?:\s*,\s*[\d০-৯]+)*\s*\]")
_LIST_RE = re.compile(r"^\s*[\d০-৯]{1,2}[.)]\s+")
# split after । ! ? or a "." that does not follow a digit (so "১. " list marks stay)
_SENT_RE = re.compile(r"(?<=[।!?])\s+|(?<=[^\d০-৯]\.)\s+(?=\S)|\n+")


def numbers_in(text: str) -> set[str]:
    t = text.translate(_BN_DIGITS)
    t = re.sub(r"(?<=\d),(?=\d{3}\b)", "", t)        # 1,500 -> 1500
    out = set()
    for n in _NUM_RE.findall(t):
        if "." in n:
            n = n.rstrip("0").rstrip(".")
        out.add(n.lstrip("0") or "0")
    return out


def split_sentences(text: str) -> list[str]:
    return [s for s in (x.strip() for x in _SENT_RE.split(text)) if s]


def guard_numbers(answer: str, sources_text: str) -> tuple[str, list[str]]:
    allowed = numbers_in(sources_text)
    kept, removed = [], []
    for sentence in split_sentences(answer):
        check = _LIST_RE.sub("", _CITE_RE.sub("", sentence))
        if numbers_in(check) - allowed:
            removed.append(sentence)
        else:
            kept.append(sentence)
    return "\n".join(kept), removed
