"""Photo diagnosis for Dr. Krishi: one structured, checked result per photo.

The vision model returns JSON (schema in VISION_SYSTEM). check() turns it into the payload the cards show:
  * one crop for the whole result: any line that names a DIFFERENT crop is removed (no "jute" diagnosis with
    "tomato leaf" advice); if the problem name itself names another crop, the problem is dropped (uncertain);
  * crop not recognised / model not sure -> "ফসল নিশ্চিতভাবে শনাক্ত করা যায়নি", sure-ness forced to low;
  * not a plant -> "not_plant"; poor photo -> "poor_image" (asks for a clearer photo, gives no treatment);
  * seen signs (in this photo) and usual signs (of the suspected problem) are kept apart;
  * no numbers that the farmer did not write, no product / chemical / fertilizer names, no percentages;
  * sure-ness is only the model's own low / medium / high guess (it is not calibrated, so never a %);
  * risk is shown only when crop is known and sure-ness is not low.
"""
from __future__ import annotations

import json
import re

from chashibondhu.assistant.advice_terms import _find_terms
from chashibondhu.assistant.guard import numbers_in

VISION_SYSTEM = """You look at a photo from a farmer in Bangladesh and describe a POSSIBLE crop problem.
Return ONLY one JSON object (no markdown) with exactly these keys:
{"is_plant": true, "image_quality": "good|poor",
 "crop": {"bn": "", "en": "", "sure": true},
 "diagnosis": {"bn": "", "en": "", "scientific_name": "", "confidence": "low|medium|high"},
 "other_possibilities": [{"bn": "", "en": ""}],
 "observed_symptoms": [], "typical_symptoms": [], "possible_causes": [],
 "immediate_actions": [], "prevention": [], "risk_level": "low|moderate|high|",
 "follow_up_questions": [], "summary": ""}
Rules:
- Everything is about ONE crop: the crop in the photo. Never mention any other crop anywhere.
- "observed_symptoms" = only what you can really SEE in this photo. "typical_symptoms" = other signs this
  problem usually has (not visible here). Do not mix them.
- If you are not sure of the crop, set crop.sure false. If you are not sure of the problem, leave diagnosis
  names empty and put up to 3 candidates in "other_possibilities".
- If it is not a plant: is_plant false. If the photo is blurry, too far or too dark: image_quality "poor".
- Simple Bangla (Bangla script) for all Bangla fields, short lines. English names in the "en" fields.
- Never write doses, amounts, numbers, percentages, product, chemical, pesticide or fertilizer names.
- "immediate_actions": 3-5 safe steps a farmer can do today. "prevention": 3-5 short points.
- "follow_up_questions": 3-4 short questions the FARMER may want to ask next about THIS problem
  (for example how it spreads, when it is worse, how to control it), in Bangla, each ending with "?".
- "summary": one or two simple Bangla lines that answer the farmer's question.
- Never say the problem is confirmed."""

# crop key -> (Bangla words, English words). Used to keep a result to ONE crop.
CROPS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "rice": (("ধান", "চাল"), ("rice", "paddy")), "jute": (("পাট",), ("jute",)),
    "wheat": (("গম",), ("wheat",)), "maize": (("ভুট্টা",), ("maize", "corn")),
    "potato": (("আলু",), ("potato",)), "tomato": (("টমেটো",), ("tomato",)),
    "brinjal": (("বেগুন",), ("brinjal", "eggplant", "aubergine")), "chilli": (("মরিচ", "লঙ্কা"), ("chilli", "chili", "pepper")),
    "mustard": (("সরিষা", "সর্ষে"), ("mustard",)), "lentil": (("মসুর",), ("lentil",)),
    "mungbean": (("মুগ",), ("mung", "mungbean", "mung bean")), "onion": (("পেঁয়াজ", "পিঁয়াজ"), ("onion",)),
    "garlic": (("রসুন",), ("garlic",)), "watermelon": (("তরমুজ",), ("watermelon",)),
    "cucumber": (("শসা",), ("cucumber",)), "bottle_gourd": (("লাউ",), ("bottle gourd",)),
    "pumpkin": (("কুমড়া", "কুমড়ো"), ("pumpkin",)), "cabbage": (("বাঁধাকপি",), ("cabbage",)),
    "cauliflower": (("ফুলকপি",), ("cauliflower",)), "okra": (("ঢেঁড়স", "ঢেড়স"), ("okra", "lady's finger")),
    "bean": (("শিম",), ("bean", "beans")), "banana": (("কলাগাছ", "কলার"), ("banana",)),
    "mango": (("আমগাছ", "আমের"), ("mango",)), "sugarcane": (("আখ", "ইক্ষু"), ("sugarcane",)),
    "papaya": (("পেঁপে",), ("papaya",)), "groundnut": (("চিনাবাদাম",), ("groundnut", "peanut")),
    "sesame": (("তিল",), ("sesame",)), "tea": (("চা-গাছ", "চা গাছ"), ("tea",)),
}
_BN_LETTER = "ঀ-৿"
# Bangla words take endings (ধানের, টমেটোতেও). Long crop words match with any ending; short ones (ধান, আলু, পাট …)
# only with a known ending, so "প্রধান", "আমার", "গমন" are not read as crops.
_SUFFIX = "(?:েরও|ের|এর|রও|র|েও|েই|ে|তেও|তে|ও|কে|য়|গাছে|গাছ|ক্ষেতে|ক্ষেত|গুলোতে|গুলো|সহ)?"


def _compile():
    out = {}
    for key, (bn, en) in CROPS.items():
        parts = [f"(?<![{_BN_LETTER}]){re.escape(w)}" + ("" if len(w) >= 5 else f"{_SUFFIX}(?![{_BN_LETTER}])") for w in bn]
        parts += [rf"\b{re.escape(w)}s?\b" for w in en]
        out[key] = re.compile("|".join(parts), re.I)
    return out


_CROP_RE = _compile()


def crops_in(text: str) -> set[str]:
    found = {k for k, rx in _CROP_RE.items() if rx.search(text or "")}
    if "mungbean" in found:               # "mung bean" also contains "bean"
        found.discard("bean")
    return found


CONF = ("low", "medium", "high")
RISK = ("low", "moderate", "high")
UNKNOWN_CROP = {"bn": "ফসল নিশ্চিতভাবে শনাক্ত করা যায়নি", "en": "Crop could not be identified with certainty"}
NOTE_BN = "শুধু ছবি দেখে রোগ নিশ্চিত বলা যায় না। প্রয়োজনে গাছ বা পাতা উপজেলা কৃষি অফিসে দেখান।"
CLEARER_BN = "আরও ভালোভাবে বুঝতে আক্রান্ত গাছের পুরো ছবি এবং আক্রান্ত অংশের কাছ থেকে আলোতে তোলা একটি পরিষ্কার ছবি দিন।"
NOT_PLANT_BN = "ছবিতে কোনো ফসল বা গাছ বোঝা যাচ্ছে না, তাই কৃষি-সমস্যা দেখা সম্ভব নয়। আক্রান্ত গাছ বা পাতার ছবি দিন।"
POOR_BN = "ছবিটা পরিষ্কার নয় (ঝাপসা, অনেক দূর থেকে বা অন্ধকার)। তাই এখন কোনো রোগের কথা বলা ঠিক হবে না।"
UNCERTAIN_BN = "ছবি দেখে একটি নির্দিষ্ট রোগ বলা যাচ্ছে না। নিচে কয়েকটি সম্ভাবনা দেওয়া হলো।"


class BadJSON(ValueError):
    pass


def parse(raw: str) -> dict:
    try:
        data = json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
    except ValueError as e:
        raise BadJSON(str(e)) from e
    if not isinstance(data, dict):
        raise BadJSON("not an object")
    return data


def _s(v, n: int = 300) -> str:
    return " ".join(str(v or "").replace("**", "").split())[:n] if isinstance(v, (str, int, float)) else ""


def check(data: dict, question: str = "") -> dict:
    """Validated payload for the cards. Never raises on odd model output; drops what fails."""
    allowed = set(numbers_in(question or ""))
    removed: list[str] = []

    def ok_text(t: str, crop_key: str | None) -> bool:
        if not t:
            return False
        bad = (numbers_in(t) - allowed) or _find_terms(t) or re.search(r"\d\s*%|[০-৯]\s*%|নিশ্চিত(?:ভাবে)? (?:এটি|এটা)", t)
        if not bad and crop_key is not None and (crops_in(t) - {crop_key}):
            bad = True
        if bad:
            removed.append(t)
        return not bad

    def items(key: str, crop_key: str | None, limit: int = 5, q: bool = False) -> list[str]:
        out = []
        for v in (data.get(key) or [])[:8] if isinstance(data.get(key), list) else []:
            t = _s(v, 200)
            if q and t and not re.search(r"[?？]$", t):
                t += "?"
            if ok_text(t, crop_key) and t not in out:
                out.append(t)
        return out[:limit]

    base = {"version": 1, "limitations": [NOTE_BN]}
    if data.get("is_plant") is False:
        return {**base, "status": "not_plant", "message": NOT_PLANT_BN, "next_step": CLEARER_BN}

    crop = data.get("crop") if isinstance(data.get("crop"), dict) else {}
    found = crops_in(_s(crop.get("bn")) + " " + _s(crop.get("en")))
    crop_key = next(iter(found)) if len(found) == 1 else None
    crop_sure = bool(crop_key) and crop.get("sure") is not False
    crop_out = ({"bn": _s(crop.get("bn"), 40) or _s(crop.get("en"), 40), "en": _s(crop.get("en"), 40), "key": crop_key}
                if crop_sure else {**UNKNOWN_CROP, "key": None})
    # with an unknown crop, a line naming ANY crop could mix crops: allow none of them
    line_crop = crop_key if crop_sure else "__none__"

    if str(data.get("image_quality", "")).lower() == "poor":
        return {**base, "status": "poor_image", "crop": crop_out, "message": POOR_BN, "next_step": CLEARER_BN,
                "observed_symptoms": items("observed_symptoms", line_crop, 3), "removed": len(removed)}

    dg = data.get("diagnosis") if isinstance(data.get("diagnosis"), dict) else {}
    conf = str(dg.get("confidence", "")).lower()
    conf = conf if conf in CONF else "low"
    if not crop_sure:
        conf = "low"
    name_bn, name_en = _s(dg.get("bn"), 80), _s(dg.get("en"), 80)
    if name_bn and not ok_text(name_bn, line_crop):
        name_bn = name_en = ""
    if name_en and not ok_text(name_en, line_crop):
        name_bn = name_en = ""
    sci = _s(dg.get("scientific_name"), 60)
    if not re.fullmatch(r"[A-Z][a-z]+(?: [a-z]+){1,2}(?: (?:pv|f\. ?sp|var)\.? [a-z]+)?", sci) or conf == "low":
        sci = ""
    others = []
    for o in (data.get("other_possibilities") or [])[:4] if isinstance(data.get("other_possibilities"), list) else []:
        if isinstance(o, dict):
            bn, en = _s(o.get("bn"), 80), _s(o.get("en"), 80)
            if bn and ok_text(bn + " " + en, line_crop):
                others.append({"bn": bn, "en": en})
    status = "possible" if name_bn else "uncertain"
    risk = str(data.get("risk_level", "")).lower()
    risk = risk if risk in RISK and crop_sure and conf != "low" and status == "possible" else None
    summary = _s(data.get("summary"), 300)
    if not ok_text(summary, line_crop):
        summary = ""
    out = {
        **base, "status": status, "crop": crop_out,
        "diagnosis": {"bn": name_bn, "en": name_en, "scientific_name": sci, "confidence": conf} if name_bn else None,
        "other_possibilities": others[:3],
        "message": UNCERTAIN_BN if status == "uncertain" else "",
        "summary": summary,
        "observed_symptoms": items("observed_symptoms", line_crop),
        "typical_symptoms": items("typical_symptoms", line_crop),
        "possible_causes": items("possible_causes", line_crop),
        "immediate_actions": items("immediate_actions", line_crop),
        "prevention": items("prevention", line_crop),
        "risk_level": risk,
        "follow_up_questions": items("follow_up_questions", line_crop, 4, q=True) if status == "possible" else [],
        "next_step": CLEARER_BN if conf == "low" or status == "uncertain" else "",
    }
    out["removed"] = len(removed)
    return out


def as_text(p: dict) -> str:
    """Plain Bangla version: saved as the message text, read aloud, and given to the AI as context
    for follow-up questions (so a follow-up stays about the same crop and problem)."""
    lines = []
    if p.get("crop"):
        lines.append("ফসল: " + p["crop"]["bn"])
    if p.get("diagnosis"):
        lines.append("সম্ভাব্য সমস্যা: " + p["diagnosis"]["bn"])
        lines.append("নিশ্চয়তা (এআই-এর অনুমান): " + {"low": "কম", "medium": "মাঝারি", "high": "বেশি"}[p["diagnosis"]["confidence"]])
    if p.get("message"):
        lines.append(p["message"])
    for o in p.get("other_possibilities") or []:
        lines.append("সম্ভাবনা: " + o["bn"])
    if p.get("summary"):
        lines.append(p["summary"])
    for label, key in (("ছবিতে দেখা লক্ষণ", "observed_symptoms"), ("সাধারণ লক্ষণ", "typical_symptoms"),
                       ("সম্ভাব্য কারণ", "possible_causes"), ("করণীয়", "immediate_actions"), ("প্রতিরোধ", "prevention")):
        for x in p.get(key) or []:
            lines.append(f"{label}: {x}")
    if p.get("next_step"):
        lines.append(p["next_step"])
    lines.extend(p.get("limitations") or [])
    return "\n".join(lines)
