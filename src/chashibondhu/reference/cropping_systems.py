"""Intercropping and relay cropping systems (Phase 3c).

Each row is ONE documented system: a main crop plus a companion crop, how and
when the companion is added, and where the evidence comes from.

evidence_level matters:
  - recommended_package: an official recommendation (e.g. BARI handbook)
  - field_trial: tested at specific sites -> tested_districts is required,
    and the app must say "tested in <district>", never "recommended".
Only status == verified rows may reach farmers.
"""
from __future__ import annotations

import pandas as pd

from chashibondhu.reference.validate import (
    CATEGORY_VALUES, SEASON_IDS, check_provenance,
)

COLUMNS = [
    "system_id", "system_type", "main_crop_id", "companion_crop_id",
    "companion_other_en", "companion_other_bn", "main_variety_scope",
    "companion_variety_scope", "companion_timing", "timing_days_min",
    "timing_days_max", "row_ratio", "season_system", "land_type", "water_regime",
    "evidence_level", "tested_districts", "source_id", "source_locator", "status",
    "verified_by", "verified_on", "notes",
]
SYSTEM_TYPES = {"intercrop", "relay"}
TIMINGS = {  # what timing_days means for each
    "same_time": "days apart at sowing (0 = same day)",
    "after_main_sowing": "days after the main crop is sown",
    "before_main_harvest": "days before the main crop is harvested",
}
VALID_TIMING = {"relay": {"before_main_harvest"},
                "intercrop": {"same_time", "after_main_sowing"}}
EVIDENCE = {"recommended_package", "field_trial"}


def _num(v: str) -> float | None:
    v = v.strip()
    return float(v) if v else None


def validate_cropping_systems(df: pd.DataFrame, crop_ids: set[str],
                              source_ids: set[str]) -> list[str]:
    missing = [c for c in COLUMNS if c not in df.columns]
    if missing:
        return [f"cropping_systems: missing columns {missing}"]
    errors: list[str] = []
    if df["system_id"].duplicated().any():
        errors.append("cropping_systems: duplicate system_id")
    for i, r in df.iterrows():
        tag = f"cropping_systems row {i + 2}"
        if not r["system_id"].strip():
            errors.append(f"{tag}: system_id required")
        if r["system_type"] not in SYSTEM_TYPES:
            errors.append(f"{tag}: system_type must be one of {sorted(SYSTEM_TYPES)}")
        if r["main_crop_id"] not in crop_ids:
            errors.append(f"{tag}: main_crop_id '{r['main_crop_id']}' not in catalogue")
        comp, other = r["companion_crop_id"].strip(), r["companion_other_en"].strip()
        if bool(comp) == bool(other):
            errors.append(f"{tag}: give exactly one of companion_crop_id or companion_other_en")
        if comp and comp not in crop_ids:
            errors.append(f"{tag}: companion_crop_id '{comp}' not in catalogue")
        if comp and comp == r["main_crop_id"]:
            errors.append(f"{tag}: companion cannot be the main crop")
        if other and not any("\u0980" <= ch <= "\u09FF" for ch in r["companion_other_bn"]):
            errors.append(f"{tag}: companion_other_bn (Bangla name) required")
        if r["evidence_level"] not in EVIDENCE:
            errors.append(f"{tag}: evidence_level must be one of {sorted(EVIDENCE)}")
        if r["status"] == "todo":
            continue
        # ---- filled rows ----
        if r["companion_timing"] not in VALID_TIMING.get(r["system_type"], set()):
            errors.append(f"{tag}: companion_timing '{r['companion_timing']}' invalid for "
                          f"{r['system_type']}")
        try:
            lo, hi = _num(r["timing_days_min"]), _num(r["timing_days_max"])
            if lo is not None and not 0 <= lo <= 150:
                errors.append(f"{tag}: timing_days_min outside 0-150")
            if lo is not None and hi is not None and lo > hi:
                errors.append(f"{tag}: timing_days_min > timing_days_max")
        except ValueError:
            errors.append(f"{tag}: timing days must be numbers")
        ratio = r["row_ratio"].strip()
        if ratio and not (len(ratio.split(":")) == 2
                          and all(p.isdigit() for p in ratio.split(":"))):
            errors.append(f"{tag}: row_ratio must look like 1:1 or 2:1")
        seasons = {s for s in r["season_system"].split("|") if s}
        if not seasons or seasons - SEASON_IDS:
            errors.append(f"{tag}: season_system must use {sorted(SEASON_IDS)}")
        for col in ("land_type", "water_regime"):
            vals = {v for v in r[col].split("|") if v}
            bad = vals - CATEGORY_VALUES[col]
            if bad:
                errors.append(f"{tag}: invalid {col} {sorted(bad)}")
        if r["evidence_level"] == "field_trial" and not r["tested_districts"].strip():
            errors.append(f"{tag}: field_trial rows need tested_districts")
    return errors + check_provenance(df, "cropping_systems", source_ids)


def candidate_systems(df: pd.DataFrame, main_crop_id: str, season: str | None = None,
                      statuses: tuple[str, ...] = ("verified",)) -> pd.DataFrame:
    """Systems that can be suggested for a field with this main crop.

    Official recommendations come first; field trials keep tested_districts so
    the app can say where the system was actually tested.
    """
    out = df[(df["main_crop_id"] == main_crop_id) & (df["status"].isin(statuses))]
    if season:
        out = out[out["season_system"].str.split("|").map(lambda s: season in s)]
    order = {"recommended_package": 0, "field_trial": 1}
    return out.sort_values("evidence_level", key=lambda s: s.map(order)).reset_index(drop=True)
