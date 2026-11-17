"""Fixed Bangla farmer messages (Phase 5).

Rules (project decision):
  - Fixed templates only. No LLM writes farmer text.
  - One crop = one line = one sign.
  - Very simple Bangla, voice-friendly, Bangla digits.
  - Anything not clearly understood gets the "not sure - ask the agriculture office" line.
    An unknown status can NEVER produce a positive sign.

TEMPLATE_VERSION is returned with every answer. Keep it "draft" until the wording
has been tested with 5-10 farmers; bump the version whenever the wording changes.
"""
from __future__ import annotations

TEMPLATE_VERSION = "suitability-bn-v1-draft"

STATUS_LINE = {
    "suitable": ("✅", "ভালো হবে"),
    "marginal": ("⚠️", "মোটামুটি"),
    "not_suitable": ("❌", "হবে না"),
    "unknown": ("❓", "নিশ্চিত না — কৃষি অফিসে জিজ্ঞেস করুন"),
}

# Questions asked when the engine reports a missing farmer input.
ASK_LINE = {
    "land_type": "আপনার জমিতে বর্ষায় কতটুকু পানি ওঠে?",
    "irrigation_available": "আপনার কি সেচের ব্যবস্থা আছে?",
}

HEADER_WITH_NAME = "{name} এলাকার জন্য:"
HEADER_NO_NAME = "আপনার এলাকার জন্য:"
DISTRICT_HINT = "উপজেলার নাম বললে আরো ঠিকভাবে বলা যাবে।"
FOOTER = "এটা আগের বছরগুলোর আবহাওয়া আর মাটির হিসাব, আবহাওয়ার পূর্বাভাস না।"

_BN_DIGITS = str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")


def to_bn_digits(text: str) -> str:
    return str(text).translate(_BN_DIGITS)


def _clean(value) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def crop_line(name_bn: str, status: str) -> str:
    sign, words = STATUS_LINE.get(status, STATUS_LINE["unknown"])
    return f"{sign} {name_bn} — {words}"


def suitability_message(area_name_bn: str | None, level: str, results: list[dict]) -> str:
    """results: CropResult.to_dict() items (uses name_bn, crop_id, status, missing_inputs)."""
    name = _clean(area_name_bn)
    lines = [HEADER_WITH_NAME.format(name=name) if name else HEADER_NO_NAME]
    asked: list[str] = []
    for r in results:
        crop_name = _clean(r.get("name_bn")) or _clean(r.get("crop_id"))
        lines.append(crop_line(crop_name, _clean(r.get("status"))))
        for item in r.get("missing_inputs") or []:
            if item in ASK_LINE and item not in asked:
                asked.append(item)
    lines += [ASK_LINE[item] for item in asked]
    if level == "district":
        lines.append(DISTRICT_HINT)
    lines.append(FOOTER)
    return to_bn_digits("\n".join(lines))
