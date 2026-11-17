"""Area directory: division / district / upazila lookup with Bangla names (Phase 5).

Reads data/processed/admin/{divisions,districts,upazilas,admin_names_bn}.csv.
Bangla names are joined by pcode only, and their status / match_method are passed
through unchanged, so a community-sourced name is never shown as official.

Search order: exact name > name starts with query > name contains query >
close spelling (difflib, English and Banglish only). Ties: division, district, upazila.
"""
from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd

LEVEL_ORDER = {"division": 0, "district": 1, "upazila": 2}
_SPLIT_RE = re.compile(r"[|;,]")
# Remove spaces and simple punctuation only. Do NOT use \W: it would also remove
# Bangla vowel signs (e.g. া), which are not "word" characters in Python's regex.
_STRIP_RE = re.compile(r"[\s\-_.,'()/]+")


def normalize(text: str) -> str:
    return _STRIP_RE.sub("", unicodedata.normalize("NFC", str(text)).casefold())


def _read(path: Path, cols: list[str]) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"missing admin file: {path}")
    df = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"{path.name}: missing columns {missing}")
    return df


@dataclass
class Area:
    code: str
    level: str
    name_en: str
    name_bn: str | None
    name_bn_status: str | None      # status from admin_names_bn.csv, passed through
    name_bn_source: str | None
    parent_code: str | None
    district_code: str | None
    division_code: str | None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SearchHit:
    area: Area
    score: float
    matched_on: str


class AreaDirectory:
    def __init__(self, divisions: pd.DataFrame, districts: pd.DataFrame,
                 upazilas: pd.DataFrame, names_bn: pd.DataFrame | None = None):
        bn: dict[str, dict] = {}
        if names_bn is not None:
            for r in names_bn.to_dict("records"):
                code = str(r.get("pcode", "")).strip()
                if code:
                    bn[code] = r

        self._areas: dict[str, Area] = {}
        district_to_division: dict[str, str] = {}

        def add(code: str, level: str, name_en: str, parent: str | None,
                district: str | None, division: str | None) -> None:
            code = code.strip()
            if not code:
                return
            if code in self._areas:
                raise ValueError(f"duplicate area code {code}")
            b = bn.get(code, {})
            name_bn = str(b.get("name_bn", "")).strip() or None
            self._areas[code] = Area(
                code=code, level=level, name_en=name_en.strip(), name_bn=name_bn,
                name_bn_status=(str(b.get("status", "")).strip() or None) if name_bn else None,
                name_bn_source=(str(b.get("source", "")).strip() or None) if name_bn else None,
                parent_code=parent, district_code=district, division_code=division)

        for r in divisions.to_dict("records"):
            add(r["division_code"], "division", r["division_name"], None, None,
                r["division_code"].strip())
        for r in districts.to_dict("records"):
            dc, dv = r["district_code"].strip(), r["division_code"].strip()
            district_to_division[dc] = dv
            add(dc, "district", r["district_name"], dv, dc, dv)
        for r in upazilas.to_dict("records"):
            dc = r["district_code"].strip()
            add(r["upazila_code"], "upazila", r["upazila_name"], dc, dc,
                district_to_division.get(dc))

        # search index: normalized key -> list of (code, label)
        self._index: dict[str, list[tuple[str, str]]] = {}
        for code, area in self._areas.items():
            b = bn.get(code, {})
            names = [("name_en", area.name_en), ("name_bn", area.name_bn or "")]
            for col in ("alt_name_en", "aliases_bn"):
                names += [(col, x) for x in _SPLIT_RE.split(str(b.get(col, "")))]
            for label, name in names:
                key = normalize(name)
                if key:
                    self._index.setdefault(key, []).append((code, label))
        self._latin_keys = [k for k in self._index if k.isascii()]

    # ---------------------------------------------------------------- loading
    @classmethod
    def from_dir(cls, admin_dir: Path) -> "AreaDirectory":
        admin_dir = Path(admin_dir)
        divisions = _read(admin_dir / "divisions.csv", ["division_code", "division_name"])
        districts = _read(admin_dir / "districts.csv",
                          ["district_code", "district_name", "division_code"])
        upazilas = _read(admin_dir / "upazilas.csv",
                         ["upazila_code", "upazila_name", "district_code"])
        bn_path = admin_dir / "admin_names_bn.csv"
        names_bn = _read(bn_path, ["pcode", "name_bn"]) if bn_path.exists() else None
        return cls(divisions, districts, upazilas, names_bn)

    # ---------------------------------------------------------------- queries
    def get(self, code: str) -> Area | None:
        return self._areas.get(code.strip())

    def children(self, code: str) -> list[Area]:
        code = code.strip()
        kids = [a for a in self._areas.values() if a.parent_code == code]
        return sorted(kids, key=lambda a: a.name_en)

    def counts(self) -> dict[str, int]:
        out = {lvl: 0 for lvl in LEVEL_ORDER}
        for a in self._areas.values():
            out[a.level] += 1
        out["with_name_bn"] = sum(a.name_bn is not None for a in self._areas.values())
        return out

    def search(self, query: str, level: str | None = None, limit: int = 10) -> list[SearchHit]:
        q = normalize(query)
        if not q:
            return []
        best: dict[str, SearchHit] = {}

        def consider(key: str, score: float) -> None:
            for code, label in self._index[key]:
                area = self._areas[code]
                if level and area.level != level:
                    continue
                if code not in best or score > best[code].score:
                    best[code] = SearchHit(area, score, label)

        for key in self._index:
            if key == q:
                consider(key, 3.0)
            elif key.startswith(q):
                consider(key, 2.0)
            elif len(q) >= 3 and q in key:
                consider(key, 1.0)
        if not best and q.isascii() and len(q) >= 3:
            for key in difflib.get_close_matches(q, self._latin_keys, n=limit, cutoff=0.75):
                consider(key, 0.5)

        hits = sorted(best.values(), key=lambda h: (-h.score, LEVEL_ORDER[h.area.level],
                                                    h.area.name_en))
        return hits[:limit]
