"""Validation rules for hand-curated reference files in data/reference/.

Every check returns a list of human-readable error strings (empty = OK),
so the same functions work in scripts, tests, and later CI.

Core rule: downstream code (suitability engine, assistant) must only use
rows with status == "verified". Use `verified_only()` for that.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

ENCODING = "utf-8-sig"
ALLOWED_STATUS = {"todo", "draft", "verified"}
ALLOWED_SOURCE_TYPES = {
    "institutional_handbook", "official_statistics", "global_database",
    "peer_reviewed", "government_portal", "community_dataset",
}
EXPECTED_CROPS = {
    "aman_rice", "boro_rice", "maize", "potato", "tomato",
    "mustard", "mung_bean", "lentil", "onion", "watermelon",
}
INITIAL_ML_CROPS = {"maize", "potato", "tomato", "mustard", "aman_rice"}
SEASON_IDS = {"rabi", "kharif1", "kharif2"}

# parameter -> (unit, plausible_low, plausible_high); None = categorical
PARAMETERS = {
    "air_temp_c": ("degC", -5.0, 50.0),
    "soil_ph": ("pH", 3.0, 10.0),
    "season_rain_mm": ("mm", 0.0, 6000.0),
    "annual_rain_mm": ("mm", 0.0, 8000.0),
    "crop_duration_days": ("days", 20.0, 250.0),
    "water_regime": ("category", None, None),
    "land_type": ("category", None, None),
    "soil_texture": ("category", None, None),
}
CATEGORY_VALUES = {
    "water_regime": {"rainfed", "irrigated", "supplementary_irrigation"},
    # BARC land types (by normal flooding depth)
    "land_type": {"highland", "medium_highland", "medium_lowland", "lowland", "very_lowland"},
    # USDA texture classes, same names as Phase 2 soil features
    "soil_texture": {
        "sand", "loamy_sand", "sandy_loam", "loam", "silt_loam", "silt",
        "sandy_clay_loam", "clay_loam", "silty_clay_loam", "sandy_clay",
        "silty_clay", "clay",
    },
}
CALENDAR_ACTIVITIES = {"seedbed_sowing", "sowing", "transplanting", "harvest"}
NUM_COLS = ["min", "opt_min", "opt_max", "max"]
BENGALI_RANGE = ("\u0980", "\u09FF")


def read_reference(path: Path) -> pd.DataFrame:
    """Read a curated CSV as strings; empty cells become ''."""
    return pd.read_csv(path, encoding=ENCODING, dtype=str, keep_default_na=False)


def verified_only(df: pd.DataFrame) -> pd.DataFrame:
    """The ONLY rows downstream modules may use."""
    return df[df["status"] == "verified"].copy()


def _has_bengali(text: str) -> bool:
    return any(BENGALI_RANGE[0] <= ch <= BENGALI_RANGE[1] for ch in text)


def _to_float(value: str) -> float | None:
    value = value.strip()
    if not value:
        return None
    return float(value)  # raises ValueError on garbage; caller reports it


def _check_columns(df: pd.DataFrame, required: list[str], name: str) -> list[str]:
    missing = [c for c in required if c not in df.columns]
    return [f"{name}: missing columns {missing}"] if missing else []


def check_provenance(df: pd.DataFrame, name: str, source_ids: set[str]) -> list[str]:
    errors: list[str] = []
    for i, r in df.iterrows():
        tag = f"{name} row {i + 2}"
        status = r["status"]
        if status not in ALLOWED_STATUS:
            errors.append(f"{tag}: status '{status}' not in {sorted(ALLOWED_STATUS)}")
            continue
        if status == "todo":
            continue
        if r["source_id"] not in source_ids:
            errors.append(f"{tag}: source_id '{r['source_id']}' not in sources.csv")
        if status == "verified":
            for col in ("source_locator", "verified_by", "verified_on"):
                if not r[col].strip():
                    errors.append(f"{tag}: verified row needs '{col}'")
            if r["verified_on"].strip():
                try:
                    date.fromisoformat(r["verified_on"].strip())
                except ValueError:
                    errors.append(f"{tag}: verified_on must be YYYY-MM-DD")
    return errors


def check_sources(df: pd.DataFrame) -> list[str]:
    errors = _check_columns(df, ["source_id", "title", "publisher", "source_type"], "sources")
    if errors:
        return errors
    if df["source_id"].duplicated().any():
        errors.append("sources: duplicate source_id")
    for i, r in df.iterrows():
        if r["source_type"] not in ALLOWED_SOURCE_TYPES:
            errors.append(f"sources row {i + 2}: source_type '{r['source_type']}' not allowed")
        if not r["title"].strip() or not r["publisher"].strip():
            errors.append(f"sources row {i + 2}: title and publisher required")
    return errors


def check_catalogue(df: pd.DataFrame, source_ids: set[str]) -> list[str]:
    errors = _check_columns(
        df, ["crop_id", "name_en", "name_bn", "season_systems", "initial_ml_model", "status"],
        "crop_catalogue")
    if errors:
        return errors
    ids = set(df["crop_id"])
    if ids != EXPECTED_CROPS or len(df) != len(EXPECTED_CROPS):
        errors.append(f"crop_catalogue: crops must be exactly {sorted(EXPECTED_CROPS)}")
    ml = set(df.loc[df["initial_ml_model"] == "true", "crop_id"])
    if ml != INITIAL_ML_CROPS:
        errors.append(f"crop_catalogue: initial_ml_model must be {sorted(INITIAL_ML_CROPS)}")
    for i, r in df.iterrows():
        if r["status"] == "todo":
            errors.append(f"crop_catalogue row {i + 2}: catalogue rows cannot be 'todo'")
        if not _has_bengali(r["name_bn"]):
            errors.append(f"crop_catalogue row {i + 2}: name_bn has no Bengali text "
                          "(encoding damaged?)")
        bad = set(r["season_systems"].split("|")) - SEASON_IDS
        if bad:
            errors.append(f"crop_catalogue row {i + 2}: unknown season(s) {sorted(bad)}")
    return errors + check_provenance(df, "crop_catalogue", source_ids)


def _check_month_day(r: pd.Series, prefix: str, tag: str) -> list[str]:
    m, d = r[f"{prefix}_month"].strip(), r[f"{prefix}_day"].strip()
    if not m or not d:
        return [f"{tag}: {prefix}_month and {prefix}_day required"]
    try:
        date(2000, int(m), int(d))  # leap year so 29 Feb is allowed
    except ValueError:
        return [f"{tag}: invalid {prefix} date month={m} day={d}"]
    return []


def check_seasons(df: pd.DataFrame, source_ids: set[str]) -> list[str]:
    errors = _check_columns(df, ["season_id", "start_month", "start_day", "end_month",
                                 "end_day", "status"], "seasons")
    if errors:
        return errors
    if set(df["season_id"]) != SEASON_IDS:
        errors.append(f"seasons: season_id must be {sorted(SEASON_IDS)}")
    for i, r in df.iterrows():
        tag = f"seasons row {i + 2}"
        if r["status"] == "verified":
            errors += _check_month_day(r, "start", tag) + _check_month_day(r, "end", tag)
    return errors + check_provenance(df, "seasons", source_ids)


def check_requirements(df: pd.DataFrame, crop_ids: set[str], source_ids: set[str]) -> list[str]:
    errors = _check_columns(df, ["crop_id", "parameter", "unit", *NUM_COLS, "value_text",
                                 "status"], "crop_requirements")
    if errors:
        return errors
    for i, r in df.iterrows():
        tag = f"crop_requirements row {i + 2}"
        if r["crop_id"] not in crop_ids:
            errors.append(f"{tag}: unknown crop_id '{r['crop_id']}'")
        param = r["parameter"]
        if param not in PARAMETERS:
            errors.append(f"{tag}: unknown parameter '{param}'")
            continue
        unit, low, high = PARAMETERS[param]
        if r["unit"] != unit:
            errors.append(f"{tag}: unit for {param} must be '{unit}'")
        if r["status"] == "todo":
            continue
        if low is None:  # categorical
            values = {v for v in r["value_text"].split("|") if v}
            if not values:
                errors.append(f"{tag}: categorical parameter needs value_text")
            bad = values - CATEGORY_VALUES[param]
            if bad:
                errors.append(f"{tag}: invalid {param} values {sorted(bad)}")
            continue
        try:
            nums = {c: _to_float(r[c]) for c in NUM_COLS}
        except ValueError:
            errors.append(f"{tag}: min/opt_min/opt_max/max must be numbers")
            continue
        present = [nums[c] for c in NUM_COLS if nums[c] is not None]
        if not present:
            errors.append(f"{tag}: numeric parameter needs at least one value")
            continue
        if present != sorted(present):
            errors.append(f"{tag}: values must satisfy min <= opt_min <= opt_max <= max")
        if any(v < low or v > high for v in present):
            errors.append(f"{tag}: {param} value outside plausible range {low}-{high}")
    return errors + check_provenance(df, "crop_requirements", source_ids)


def check_calendar(df: pd.DataFrame, crop_ids: set[str], source_ids: set[str]) -> list[str]:
    errors = _check_columns(df, ["crop_id", "activity", "start_month", "start_day",
                                 "end_month", "end_day", "region_scope", "status"],
                            "crop_calendar")
    if errors:
        return errors
    for i, r in df.iterrows():
        tag = f"crop_calendar row {i + 2}"
        if r["crop_id"] not in crop_ids:
            errors.append(f"{tag}: unknown crop_id '{r['crop_id']}'")
        if r["activity"] not in CALENDAR_ACTIVITIES:
            errors.append(f"{tag}: unknown activity '{r['activity']}'")
        if not r["region_scope"].strip():
            errors.append(f"{tag}: region_scope required (e.g. national, or a district)")
        if r["status"] != "todo":
            errors += _check_month_day(r, "start", tag) + _check_month_day(r, "end", tag)
    return errors + check_provenance(df, "crop_calendar", source_ids)


def validate_all(ref_dir: Path) -> dict[str, list[str]]:
    """Validate every Phase 3 file. Returns {file_name: [errors]}."""
    files = ["sources.csv", "crop_catalogue.csv", "seasons.csv",
             "crop_requirements.csv", "crop_calendar.csv"]
    missing = [f for f in files if not (ref_dir / f).exists()]
    if missing:
        return {f: ["file missing - run scripts/make_phase3_templates.py"] for f in missing}

    data = {f: read_reference(ref_dir / f) for f in files}
    source_ids = set(data["sources.csv"]["source_id"])
    crop_ids = set(data["crop_catalogue.csv"]["crop_id"])
    return {
        "sources.csv": check_sources(data["sources.csv"]),
        "crop_catalogue.csv": check_catalogue(data["crop_catalogue.csv"], source_ids),
        "seasons.csv": check_seasons(data["seasons.csv"], source_ids),
        "crop_requirements.csv": check_requirements(
            data["crop_requirements.csv"], crop_ids, source_ids),
        "crop_calendar.csv": check_calendar(data["crop_calendar.csv"], crop_ids, source_ids),
    }
