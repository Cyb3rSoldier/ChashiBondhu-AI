"""Marketplace search: Bangla / English / Banglish names, common misspellings, synonyms.

How it works
1. The query is split into words. Each word (and each 2-word phrase) is looked up in LEXICON:
   exact alias, alias that starts with the word (4+ letters), or a close spelling (difflib, Latin only).
2. A matched word becomes a product group: a listing matches when ANY alias of the group is in its title,
   description or crop id. Several groups are OR-ed ("alu tomato" shows potatoes and tomatoes).
3. Words that are not product names ("diamond", "big", "lal") only change the ranking.
4. If no word is a known product, every word must appear in the title/description, or the title must be
   a close spelling (pg_trgm word_similarity).
Suggestions are only shown for words that match real active listings (never invented stock).
"""
from __future__ import annotations

import difflib
import re

# key -> (Bangla name, English name, aliases, crop ids that may exist in the crop catalogue)
LEXICON: dict[str, tuple[str, str, tuple[str, ...], tuple[str, ...]]] = {
    "potato": ("আলু", "Potato", ("potato", "potatoes", "potata", "potatto", "alu", "aloo", "alo", "aalu", "আলু"), ("potato",)),
    "tomato": ("টমেটো", "Tomato", ("tomato", "tomatoes", "tamato", "tometo", "tomatto", "টমেটো", "টমাটো"), ("tomato",)),
    "onion": ("পেঁয়াজ", "Onion", ("onion", "onions", "piyaj", "peyaj", "piaj", "peyaz", "piyaz", "pyaj", "পেঁয়াজ", "পেয়াজ", "পিয়াজ"), ("onion",)),
    "rice": ("চাল / ধান", "Rice / paddy", ("rice", "chal", "chaal", "chawal", "dhan", "dhaan", "paddy", "aman", "boro", "চাল", "ধান", "আমন", "বোরো"), ("aman_rice", "boro_rice", "rice")),
    "maize": ("ভুট্টা", "Maize", ("maize", "corn", "bhutta", "vutta", "butta", "ভুট্টা"), ("maize",)),
    "mustard": ("সরিষা", "Mustard", ("mustard", "shorisha", "sorisha", "sorsa", "shorsha", "sarisha", "সরিষা", "সর্ষে"), ("mustard",)),
    "mung": ("মুগ ডাল", "Mung bean", ("mung", "moong", "mug", "মুগ"), ("mung_bean", "mungbean", "mung")),
    "lentil": ("মসুর ডাল", "Lentil", ("lentil", "lentils", "masur", "mosur", "moshur", "musur", "মসুর"), ("lentil",)),
    "dal": ("ডাল", "Pulses (dal)", ("dal", "daal", "pulse", "pulses", "ডাল"), ()),
    "watermelon": ("তরমুজ", "Watermelon", ("watermelon", "tormuj", "tarmuj", "tormuz", "তরমুজ"), ("watermelon",)),
    "egg": ("ডিম", "Egg", ("egg", "eggs", "dim", "deem", "ডিম"), ()),
    "milk": ("দুধ", "Milk", ("milk", "dudh", "doodh", "দুধ"), ()),
    "fish": ("মাছ", "Fish", ("fish", "mach", "maach", "machh", "মাছ"), ()),
    "chicken": ("মুরগি", "Chicken", ("chicken", "murgi", "murghi", "মুরগি", "মুরগী"), ()),
    "mango": ("আম", "Mango", ("mango", "mangoes", "aam", "আম"), ()),
    "banana": ("কলা", "Banana", ("banana", "bananas", "kola", "kela", "কলা"), ()),
    "brinjal": ("বেগুন", "Brinjal", ("brinjal", "eggplant", "begun", "baigun", "বেগুন"), ()),
    "cabbage": ("বাঁধাকপি", "Cabbage", ("cabbage", "badhakopi", "bandhakopi", "badhakofi", "বাঁধাকপি"), ()),
    "cauliflower": ("ফুলকপি", "Cauliflower", ("cauliflower", "fulkopi", "phulkopi", "ফুলকপি"), ()),
    "carrot": ("গাজর", "Carrot", ("carrot", "carrots", "gajor", "gajar", "গাজর"), ()),
    "chili": ("মরিচ", "Chili", ("chili", "chilli", "chilies", "pepper", "morich", "marich", "মরিচ"), ()),
    "garlic": ("রসুন", "Garlic", ("garlic", "roshun", "rosun", "rasun", "রসুন"), ()),
    "ginger": ("আদা", "Ginger", ("ginger", "ada", "aada", "আদা"), ()),
    "pumpkin": ("কুমড়া", "Pumpkin", ("pumpkin", "kumra", "kumro", "কুমড়া", "কুমড়ো"), ()),
    "cucumber": ("শসা", "Cucumber", ("cucumber", "shosha", "sosha", "শসা"), ()),
    "okra": ("ঢেঁড়স", "Okra (ladies finger)", ("okra", "ladies finger", "lady finger", "dherosh", "dheros", "ঢেঁড়স", "ঢেড়স"), ()),
    "spinach": ("পালং শাক", "Spinach", ("spinach", "palong", "palang", "পালং"), ()),
    "papaya": ("পেঁপে", "Papaya", ("papaya", "pepe", "পেঁপে"), ()),
    "guava": ("পেয়ারা", "Guava", ("guava", "peyara", "payara", "পেয়ারা"), ()),
    "jackfruit": ("কাঁঠাল", "Jackfruit", ("jackfruit", "kathal", "kanthal", "কাঁঠাল"), ()),
    "lemon": ("লেবু", "Lemon", ("lemon", "lebu", "লেবু"), ()),
    "honey": ("মধু", "Honey", ("honey", "modhu", "মধু"), ()),
    "beans": ("শিম", "Beans", ("bean", "beans", "shim", "sheem", "শিম"), ()),
    "strawberry": ("স্ট্রবেরি", "Strawberry", ("strawberry", "strawberries", "স্ট্রবেরি"), ()),
}

_LATIN = re.compile(r"^[a-z][a-z ]*$")
_WORD = re.compile(r"[^\w\u0980-\u09FF ]+")
_LATIN_ALIASES = sorted({a for g in LEXICON.values() for a in g[2] if _LATIN.match(a)})
_ALIAS_TO_KEY = {a: k for k, g in LEXICON.items() for a in g[2]}


def normalize(q: str) -> str:
    return " ".join(_WORD.sub(" ", (q or "").lower()).split())[:80]


def word_group(word: str) -> str | None:
    """Which product group a word means, or None."""
    if word in _ALIAS_TO_KEY:
        return _ALIAS_TO_KEY[word]
    if len(word) >= 4:
        for a, k in _ALIAS_TO_KEY.items():
            if a.startswith(word):
                return k
    if not _LATIN.match(word):                    # Bangla endings: আলুর, ডিমের -> আলু, ডিম
        for a, k in sorted(_ALIAS_TO_KEY.items(), key=lambda x: -len(x[0])):
            if not _LATIN.match(a) and len(a) >= 2 and word.startswith(a):
                return k
    if _LATIN.match(word) and len(word) >= 4:
        close = difflib.get_close_matches(word, _LATIN_ALIASES, n=1, cutoff=0.8)
        if close:
            return _ALIAS_TO_KEY[close[0]]
    return None


def parse(q: str) -> dict:
    """-> {"groups": [keys], "rest": [other words], "text": normalized}"""
    text = normalize(q)
    words = text.split()
    groups, rest, i = [], [], 0
    while i < len(words):
        pair = " ".join(words[i:i + 2]) if i + 1 < len(words) else None
        if pair and pair in _ALIAS_TO_KEY:
            key, step = _ALIAS_TO_KEY[pair], 2
        else:
            key, step = word_group(words[i]), 1
        if key:
            if key not in groups:
                groups.append(key)
        else:
            rest.append(words[i])
        i += step
    return {"groups": groups, "rest": rest, "text": text}


def alias_patterns(key: str) -> list[str]:
    """Postgres regex patterns (case-insensitive ~*). Latin aliases must start a word (so 'alu' does not
    match inside another word); Bangla aliases match anywhere (Bangla vowel signs break word edges)."""
    out = []
    for a in LEXICON[key][2]:
        esc = re.escape(a)
        out.append(r"\m" + esc if _LATIN.match(a) else esc)
    return out


def group_crop_ids(key: str, known: set[str]) -> list[str]:
    return [c for c in LEXICON[key][3] if c in known]


def prefix_groups(prefix: str, limit: int = 6) -> list[str]:
    p = normalize(prefix)
    if not p:
        return []
    keys = []
    for k, g in LEXICON.items():
        if any(a.startswith(p) for a in g[2]) and k not in keys:
            keys.append(k)
    return keys[:limit]
