"""BARC Crop Zoning shares for a crop in an upazila or district.

BARC gives, per upazila, the farmland area in 5 suitability classes
(very suitable >80% of maximum attainable yield ... not suitable <20%).
For a district we add up its upazilas' areas (areas are additive).
This is an expert land-suitability assessment, not a field measurement.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

CLASS_COLS = ["area_very_suitable", "area_suitable", "area_moderately_suitable",
              "area_marginally_suitable", "area_not_suitable"]


@dataclass
class ZoningShare:
    crop_id: str
    level: str
    area_code: str
    n_upazilas: int
    total_area: float
    share_very: float
    share_suitable: float
    share_moderate: float
    share_marginal: float
    share_not: float
    zone: str
    note: str
    data_type: str

    @property
    def good(self) -> float:
        return self.share_very + self.share_suitable

    @property
    def poor(self) -> float:
        return self.share_marginal + self.share_not


class BarcStore:
    def __init__(self, path: Path):
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"{path} missing - run scripts/build_barc_cropzoning.py")
        df = pd.read_csv(path, dtype={"district_code": str, "upazila_code": str,
                                      "crop_id": str, "zone": str}, encoding="utf-8-sig")
        need = ["crop_id", "district_code", "upazila_code", *CLASS_COLS, "data_type"]
        missing = [c for c in need if c not in df.columns]
        if missing:
            raise ValueError(f"{path.name}: missing columns {missing}")
        self.df = df[(df["crop_id"].fillna("") != "") & (df["upazila_code"].fillna("") != "")]
        self.crops = set(self.df["crop_id"])

    def get(self, crop_id: str, level: str, area_code: str) -> ZoningShare | None:
        if crop_id not in self.crops:
            return None
        sub = self.df[self.df["crop_id"] == crop_id]
        key = "upazila_code" if level == "upazila" else "district_code"
        sub = sub[sub[key] == area_code]
        if sub.empty:
            return None
        areas = sub[CLASS_COLS].fillna(0).sum()
        total = float(areas.sum())
        if total <= 0:
            return None
        s = (areas / total).tolist()
        zone = str(sub["zone"].iloc[0]) if level == "upazila" and "zone" in sub else ""
        note = str(sub["note"].iloc[0]) if "note" in sub and pd.notna(sub["note"].iloc[0]) else ""
        return ZoningShare(crop_id, level, area_code, len(sub), total, *s, zone, note,
                           str(sub["data_type"].iloc[0]))
