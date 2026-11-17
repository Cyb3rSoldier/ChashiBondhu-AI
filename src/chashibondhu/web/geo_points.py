"""Reference points of Bangladesh districts and upazilas (from data/processed/admin, built in the AI phases).
Used for weather (farmer dashboard, Dr. Krishi) and the nearest climate grid point. Read once, kept in memory."""
from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path

# Bangladesh with a small margin: a location outside this box is not trusted for farm weather
BD_BOX = (20.3, 26.8, 87.9, 92.8)       # lat_min, lat_max, lon_min, lon_max


def _admin_dir() -> Path:
    from chashibondhu.web.db import _root
    return _root() / "data" / "processed" / "admin"


@lru_cache(maxsize=1)
def _points() -> dict[str, dict]:
    d = _admin_dir()
    names: dict[str, dict] = {}
    try:
        with open(d / "admin_names_bn.csv", encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                names[r["pcode"]] = {"name_bn": r.get("name_bn") or "", "name_en": r.get("name_en") or ""}
    except OSError:
        pass
    out: dict[str, dict] = {}
    for fname, code_col, name_col, parent in (("districts.csv", "district_code", "district_name", None),
                                              ("upazilas.csv", "upazila_code", "upazila_name", "district_code")):
        try:
            with open(d / fname, encoding="utf-8-sig") as f:
                for r in csv.DictReader(f):
                    try:
                        lat, lon = float(r["ref_lat"]), float(r["ref_lon"])
                    except (KeyError, TypeError, ValueError):
                        continue
                    code = r[code_col]
                    n = names.get(code, {})
                    out[code] = {"code": code, "lat": round(lat, 4), "lon": round(lon, 4),
                                 "name_en": n.get("name_en") or r.get(name_col) or code,
                                 "name_bn": n.get("name_bn") or n.get("name_en") or r.get(name_col) or code,
                                 "district_code": r.get(parent) if parent else code}
        except OSError:
            continue
    return out


def point(code: str | None) -> dict | None:
    """Upazila first, else its district. None if unknown."""
    if not code:
        return None
    pts = _points()
    return pts.get(code) or (pts.get(code[:6]) if len(code) > 6 else None)


def in_bangladesh(lat: float, lon: float) -> bool:
    a, b, c, d = BD_BOX
    return a <= lat <= b and c <= lon <= d
