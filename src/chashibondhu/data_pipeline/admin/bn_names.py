"""Match English admin names across sources that spell them differently.

Bangladesh place names have many romanised spellings
(Jessore/Jashore, Bogra/Bogura, Comilla/Cumilla). We compare names with
two keys:
  - norm: lowercase ASCII letters and spaces
  - key:  norm without generic words (sadar, upazila, ...), common
          spelling variants folded, doubled letters collapsed
Matching is one-to-one inside a parent area (e.g. upazilas inside one
district), so two areas can never get the same Bangla name.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

STOPWORDS = {"upazila", "upazilla", "thana", "zila", "zilla", "district",
             "division", "sadar", "adarsha", "model", "uz"}
# Order matters: longer patterns first.
VARIANTS = [("ou", "u"), ("oo", "u"), ("ee", "i"), ("ph", "f"), ("sh", "s"),
            ("bh", "b"), ("dh", "d"), ("th", "t"), ("gh", "g"), ("kh", "k"),
            ("ch", "c"), ("jh", "j"), ("w", "o"), ("z", "j"), ("y", "i"),
            ("q", "k"), ("v", "b"), ("x", "ks")]
BENGALI_RANGE = ("\u0980", "\u09FF")

# Thresholds (documented in the phase notes)
HIGH = 0.88    # auto-accept as draft
REVIEW = 0.75  # below HIGH but at least this: needs human review


def has_bengali(text: str) -> bool:
    return any(BENGALI_RANGE[0] <= ch <= BENGALI_RANGE[1] for ch in str(text))


def norm(name: str) -> str:
    s = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z ]+", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def key(name: str) -> str:
    words = [w for w in norm(name).split() if w not in STOPWORDS]
    s = "".join(words)
    for old, new in VARIANTS:
        s = s.replace(old, new)
    s = re.sub(r"(.)\1+", r"\1", s)          # collapse doubled letters
    if len(s) > 1:                            # drop vowels after first letter
        s = s[0] + re.sub(r"[aeiou]", "", s[1:])
    return s


def score(a: str, b: str) -> tuple[float, str]:
    """Return (similarity 0-1, method)."""
    na, nb = norm(a), norm(b)
    if na and na == nb:
        return 1.0, "exact"
    ka, kb = key(a), key(b)
    if ka and ka == kb:
        return 0.99, "normalized"
    s = max(SequenceMatcher(None, na, nb).ratio(),
            SequenceMatcher(None, ka, kb).ratio())
    return round(s, 3), "fuzzy"


@dataclass
class Match:
    left: int
    right: int | None
    score: float
    method: str
    status: str  # draft | needs_review | missing


def match_one_to_one(left: list[str], right: list[str]) -> list[Match]:
    """Greedy best-first one-to-one matching. Returns one Match per left item."""
    pairs = []
    for i, a in enumerate(left):
        for j, b in enumerate(right):
            s, m = score(a, b)
            if s >= REVIEW:
                pairs.append((s, i, j, m))
    pairs.sort(key=lambda p: (-p[0], p[1], p[2]))
    used_l: set[int] = set()
    used_r: set[int] = set()
    out: dict[int, Match] = {}
    for s, i, j, m in pairs:
        if i in used_l or j in used_r:
            continue
        used_l.add(i)
        used_r.add(j)
        status = "draft" if s >= HIGH else "needs_review"
        out[i] = Match(i, j, s, m, status)
    for i in range(len(left)):
        if i not in out:
            out[i] = Match(i, None, 0.0, "none", "missing")
    return [out[i] for i in range(len(left))]


def top_candidates(name: str, options: list[str], n: int = 3) -> list[tuple[int, float]]:
    """Best n option indexes for a name (for the human review file)."""
    scored = [(j, score(name, o)[0]) for j, o in enumerate(options)]
    scored.sort(key=lambda t: -t[1])
    return scored[:n]
