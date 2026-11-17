"""Land area units: validation, parsing and conversion to square metres.

Storage rule: every land area is stored in square metres (SI), together with
the original text and the conversion basis. Farmers see their own unit.

Definitions live in data/reference/land_units.csv. Each unit is defined as
`factor x base_unit`, where base_unit is 'sqft', 'sqm' or another unit_id
(e.g. bigha = 20 katha). Only rows whose status is allowed (default:
verified) can be used.

Regional units (bigha in some regions, kani) differ by area. The farmer can
state their local size in decimals; that value then wins and the result is
labelled basis='farmer_stated'.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from chashibondhu.reference.validate import check_provenance, read_reference

FT_TO_M = 0.3048            # international foot, exact by definition
SQFT_TO_SQM = FT_TO_M ** 2  # 0.09290304
ROOTS = {"sqft": SQFT_TO_SQM, "sqm": 1.0}
REQUIRED_COLS = ["unit_id", "name_en", "name_bn", "aliases_latin", "aliases_bn",
                 "factor", "base_unit", "scope", "source_id", "source_locator",
                 "status", "verified_by", "verified_on", "notes"]
BN_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")
NUMBER_RE = re.compile(r"(\d+(?:[.,]\d+)?)")


class LandUnitError(ValueError):
    """Unknown, unverified or ambiguous unit."""


@dataclass
class AreaResult:
    sqm: float
    parts: list[tuple[float, str, str]] = field(default_factory=list)  # value, unit, basis
    original_text: str = ""

    @property
    def basis(self) -> str:
        bases = {b for _, _, b in self.parts}
        return "farmer_stated" if "farmer_stated" in bases else "standard"


# ---------- validation ----------
def validate_land_units(df: pd.DataFrame, source_ids: set[str]) -> list[str]:
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        return [f"land_units: missing columns {missing}"]
    errors: list[str] = []
    if df["unit_id"].duplicated().any():
        errors.append("land_units: duplicate unit_id")
    ids = set(df["unit_id"])
    for i, r in df.iterrows():
        tag = f"land_units row {i + 2}"
        if not any("\u0980" <= ch <= "\u09FF" for ch in r["name_bn"]):
            errors.append(f"{tag}: name_bn has no Bengali text")
        if r["scope"] not in {"national", "regional"}:
            errors.append(f"{tag}: scope must be national or regional")
        if r["status"] == "todo":
            continue
        try:
            if float(r["factor"]) <= 0:
                errors.append(f"{tag}: factor must be > 0")
        except ValueError:
            errors.append(f"{tag}: factor must be a number")
        if r["base_unit"] not in ROOTS and r["base_unit"] not in ids:
            errors.append(f"{tag}: base_unit '{r['base_unit']}' unknown")
    if not errors:
        try:
            LandUnits(df, allowed_status=("todo", "draft", "verified"), strict=False)
        except LandUnitError as exc:
            errors.append(f"land_units: {exc}")
    return errors + check_provenance(df, "land_units", source_ids)


# ---------- converter ----------
class LandUnits:
    def __init__(self, table: pd.DataFrame, allowed_status: tuple[str, ...] = ("verified",),
                 strict: bool = True):
        self.table = table.set_index("unit_id")
        self.allowed = set(allowed_status)
        self.strict = strict
        self._alias = self._build_aliases()
        for uid in self.table.index:  # detect cycles early
            if self.table.loc[uid, "status"] != "todo":
                self._chain_sqm(uid, seen=())

    @classmethod
    def from_csv(cls, path: Path, **kw) -> "LandUnits":
        return cls(read_reference(path), **kw)

    def _build_aliases(self) -> list[tuple[str, str]]:
        pairs = []
        for uid, r in self.table.iterrows():
            words = {uid, r["name_en"].lower(), r["name_bn"]}
            words |= {w.strip().lower() for w in r["aliases_latin"].split("|") if w.strip()}
            words |= {w.strip() for w in r["aliases_bn"].split("|") if w.strip()}
            pairs += [(w, uid) for w in words]
        return sorted(pairs, key=lambda p: -len(p[0]))  # longest alias first

    def _chain_sqm(self, uid: str, seen: tuple[str, ...]) -> float:
        if uid in ROOTS:
            return ROOTS[uid]
        if uid in seen:
            raise LandUnitError(f"circular definition: {' -> '.join(seen + (uid,))}")
        if uid not in self.table.index:
            raise LandUnitError(f"unknown unit '{uid}'")
        r = self.table.loc[uid]
        if r["status"] == "todo" or not r["factor"]:
            raise LandUnitError(f"'{uid}' has no defined size yet ({r['notes'] or 'todo'})")
        return float(r["factor"]) * self._chain_sqm(r["base_unit"], seen + (uid,))

    def sqm_per(self, uid: str) -> float:
        """Square metres in one unit. Every unit in the chain must be allowed."""
        cur = uid
        while cur not in ROOTS:
            if cur not in self.table.index:
                raise LandUnitError(f"unknown unit '{cur}'")
            status = self.table.loc[cur, "status"]
            if status == "todo":
                raise LandUnitError(f"'{cur}' size is not defined: "
                                    f"{self.table.loc[cur, 'notes'] or 'todo'}")
            if self.strict and status not in self.allowed:
                raise LandUnitError(f"'{cur}' is {status}, not usable (allowed: "
                                    f"{sorted(self.allowed)})")
            cur = self.table.loc[cur, "base_unit"]
        return self._chain_sqm(uid, seen=())

    def resolve(self, word: str) -> str:
        w = word.strip().lower()
        for alias, uid in self._alias:
            if w == alias:
                return uid
        raise LandUnitError(f"unknown land unit '{word}'")

    def to_sqm(self, value: float, unit: str,
               local_decimals: dict[str, float] | None = None) -> tuple[float, str]:
        """Convert one amount. local_decimals: farmer-stated size, e.g. {'bigha': 50}."""
        if value < 0:
            raise LandUnitError("area cannot be negative")
        uid = self.resolve(unit)
        local = (local_decimals or {}).get(uid)
        if local is not None:
            if local <= 0:
                raise LandUnitError("local unit size must be > 0 decimals")
            return value * local * self.sqm_per("decimal"), "farmer_stated"
        return value * self.sqm_per(uid), "standard"

    def from_sqm(self, sqm: float, unit: str,
                 local_decimals: dict[str, float] | None = None) -> float:
        per, _ = self.to_sqm(1.0, unit, local_decimals)
        return sqm / per

    def parse(self, text: str, local_decimals: dict[str, float] | None = None) -> AreaResult:
        """Parse '২ বিঘা ৫ কাঠা', '2 bigha 5 katha', '33 shotok' into square metres."""
        clean = text.translate(BN_DIGITS).replace(",", ".")
        tokens = NUMBER_RE.split(clean)
        # tokens: [prefix, num1, rest1, num2, rest2, ...]
        if len(tokens) < 3 or tokens[0].strip():
            raise LandUnitError(f"could not read an amount from '{text}'")
        result = AreaResult(sqm=0.0, original_text=text)
        for num, rest in zip(tokens[1::2], tokens[2::2]):
            words = rest.strip().split()
            if not words:
                raise LandUnitError(f"number {num} has no unit in '{text}'")
            unit = self._match_prefix(words)
            sqm, basis = self.to_sqm(float(num), unit, local_decimals)
            result.sqm += sqm
            result.parts.append((float(num), self.resolve(unit), basis))
        return result

    def _match_prefix(self, words: list[str]) -> str:
        """Allow multi-word aliases like 'square feet'."""
        for n in range(min(3, len(words)), 0, -1):
            cand = " ".join(words[:n])
            try:
                self.resolve(cand)
                return cand
            except LandUnitError:
                continue
        raise LandUnitError(f"unknown land unit '{words[0]}'")
