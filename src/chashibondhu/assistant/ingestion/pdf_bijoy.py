"""Read a PDF whose Bangla text uses legacy Bijoy fonts (e.g. SutonnyMJ) (Phase 7).

Bijoy text is stored as ASCII look-alike characters ("Avjy" = আলু). Only text in a
Bijoy font is converted; English words and numbers in normal fonts stay as they are.
Consecutive spans in the same kind of font are joined BEFORE conversion, because
Bijoy writes some vowel signs before the consonant and a split would break them.

Run `scripts/build_rag_index.py --fonts` first to see which fonts the book uses.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

BIJOY_FONT_HINTS = ("mj", "sutonny", "bijoy")   # SutonnyMJ, SutonnyOMJ, ...

_converter = None

# The book uses a newer SutonnyMJ layout than bijoy2unicode 0.1.1 expects.
# Fixes found from the book's raw text (raw_spans.txt, PDF pages 26-27):
FONT_FIXES = {
    "Ð": "ণ্ড",   # library maps it to "-"      (KvÐ  -> কাণ্ড)
    "Í": "ত",     # library maps it to "ত্ম"     (šÍ   -> ন্ত, ¯Í -> স্ত)
    "æ": "ু",     # library maps it to "ম্ন"     (iæ   -> রু)
    "ÿ": "ক্ষ",   # library does not know it    (msiÿY -> সংরক্ষণ)
}
# Reph (র্ on top, "©") is written AFTER its syllable in Bijoy, and the library does not
# move it. We swap it for a private marker, convert, then put "র্" before that syllable.
_REPH_MARK = "\ue001"
_SYLLABLE_THEN_MARK = re.compile(
    r"([\u0995-\u09B9\u09CE\u09DC-\u09DF](?:\u09CD[\u0995-\u09B9\u09DC-\u09DF])*)"
    r"([\u09BC\u09BE-\u09CC\u09D7\u0981-\u0983]*)" + _REPH_MARK)


def _get_converter():
    global _converter
    if _converter is None:
        from bijoy2unicode import converter   # imported lazily (only needed here)
        for k, v in FONT_FIXES.items():
            converter.conversionMap[re.escape(k)] = v
        _converter = converter.Unicode()
    return _converter


def _convert_core(core: str) -> str:
    conv = _get_converter()
    text = core.replace("©", _REPH_MARK)
    try:
        out = conv.convertBijoyToUnicode(text + "  ").rstrip()
    except (IndexError, ValueError):
        words = []
        for w in text.split(" "):
            try:
                words.append(conv.convertBijoyToUnicode(w + "  ").rstrip())
            except (IndexError, ValueError):
                words.append(w)
        out = " ".join(words)
    out = _SYLLABLE_THEN_MARK.sub(lambda m: "র্" + m.group(1) + m.group(2), out)
    return out.replace(_REPH_MARK, "র্")


def _bijoy_to_unicode(text: str) -> str:
    """Convert Bijoy text to Unicode. bijoy2unicode 0.1.1 crashes (IndexError) when a
    vowel sign like "‡" is near the END of the string, so two spaces are added before
    converting; original leading/trailing spaces are kept. Words that still fail are
    kept as they are instead of stopping the whole run."""
    core = text.strip()
    if not core:
        return text
    lead = text[: len(text) - len(text.lstrip())]
    trail = text[len(text.rstrip()):]
    return lead + _convert_core(core) + trail


def is_bijoy_font(font_name: str, hints: tuple[str, ...] = BIJOY_FONT_HINTS) -> bool:
    name = (font_name or "").lower()
    return any(h in name for h in hints)


def line_to_text(spans: list[tuple[str, str]], hints: tuple[str, ...] = BIJOY_FONT_HINTS) -> str:
    """spans: [(text, font_name), ...] of ONE line -> Unicode text."""
    out: list[str] = []
    run_text, run_bijoy = "", None
    for text, font in spans:
        bijoy = is_bijoy_font(font, hints)
        if run_bijoy is None or bijoy == run_bijoy:
            run_text += text
            run_bijoy = bijoy
        else:
            out.append(_bijoy_to_unicode(run_text) if run_bijoy else run_text)
            run_text, run_bijoy = text, bijoy
    if run_text:
        out.append(_bijoy_to_unicode(run_text) if run_bijoy else run_text)
    return "".join(out)


def _clean(text: str) -> str:
    text = re.sub(r"[ \t\u00a0]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def page_to_text(page, hints: tuple[str, ...] = BIJOY_FONT_HINTS) -> str:
    """One PyMuPDF page -> Unicode text (blocks separated by blank lines)."""
    data = page.get_text("dict")
    blocks = []
    for block in data.get("blocks", []):
        lines = []
        for line in block.get("lines", []):
            spans = [(s.get("text", ""), s.get("font", "")) for s in line.get("spans", [])]
            text = line_to_text(spans, hints).strip()
            if text:
                lines.append(text)
        if lines:
            blocks.append("\n".join(lines))
    return _clean("\n\n".join(blocks))


def extract_pages(pdf_path: Path, page_offset: int = 25, max_pages: int | None = None,
                  min_chars: int = 40) -> list[dict]:
    """Return [{pdf_page, printed_page, text}] (1-based pdf_page).

    printed_page = pdf_page - page_offset (None for front matter)."""
    import pymupdf

    pages = []
    with pymupdf.open(str(pdf_path)) as doc:
        n = len(doc) if max_pages is None else min(max_pages, len(doc))
        for i in range(n):
            text = page_to_text(doc[i])
            if len(text) < min_chars:
                continue
            pdf_page = i + 1
            printed = pdf_page - page_offset
            pages.append({"pdf_page": pdf_page,
                          "printed_page": printed if printed > 0 else None,
                          "text": text})
    return pages


def font_report(pdf_path: Path, max_pages: int = 40) -> list[tuple[str, int, bool, str]]:
    """[(font, n_spans, treated_as_bijoy, sample_text)] for the first pages."""
    import pymupdf

    counts: Counter[str] = Counter()
    sample: dict[str, str] = {}
    with pymupdf.open(str(pdf_path)) as doc:
        for i in range(min(max_pages, len(doc))):
            for block in doc[i].get_text("dict").get("blocks", []):
                for line in block.get("lines", []):
                    for s in line.get("spans", []):
                        font, text = s.get("font", ""), s.get("text", "").strip()
                        if text:
                            counts[font] += 1
                            sample.setdefault(font, text[:40])
    return [(f, n, is_bijoy_font(f), sample[f]) for f, n in counts.most_common()]
