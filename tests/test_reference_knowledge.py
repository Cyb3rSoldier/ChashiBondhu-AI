"""Tests for Phase 3 curated reference files and their validator."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from chashibondhu.reference.validate import (  # noqa: E402
    EXPECTED_CROPS,
    INITIAL_ML_CROPS,
    check_requirements,
    read_reference,
    validate_all,
    verified_only,
)

REF_DIR = ROOT / "data" / "reference"
SOURCES = {"BARI_KPH"}
CROPS = {"maize"}


def _req_row(**overrides) -> pd.DataFrame:
    row = {"crop_id": "maize", "variety_scope": "general", "parameter": "soil_ph",
           "unit": "pH", "min": "", "opt_min": "", "opt_max": "", "max": "",
           "value_text": "", "source_id": "BARI_KPH", "source_locator": "p. 12",
           "status": "verified", "verified_by": "siyam", "verified_on": "2026-11-08",
           "notes": ""}
    row.update(overrides)
    return pd.DataFrame([row])


def test_reference_files_valid():
    results = validate_all(REF_DIR)
    problems = {k: v for k, v in results.items() if v}
    assert not problems, problems


def test_catalogue_ten_crops_five_initial():
    cat = read_reference(REF_DIR / "crop_catalogue.csv")
    assert set(cat["crop_id"]) == EXPECTED_CROPS
    assert set(cat.loc[cat["initial_ml_model"] == "true", "crop_id"]) == INITIAL_ML_CROPS


def test_bangla_names_not_corrupted():
    cat = read_reference(REF_DIR / "crop_catalogue.csv")
    for name in cat["name_bn"]:
        assert any("\u0980" <= ch <= "\u09FF" for ch in name), name


def test_verified_row_without_page_is_rejected():
    df = _req_row(opt_min="6.0", opt_max="7.0", source_locator="")
    errors = check_requirements(df, CROPS, SOURCES)
    assert any("source_locator" in e for e in errors)


def test_wrong_numeric_order_is_rejected():
    df = _req_row(opt_min="7.5", opt_max="6.0")
    errors = check_requirements(df, CROPS, SOURCES)
    assert any("min <= opt_min" in e for e in errors)


def test_unknown_source_is_rejected():
    df = _req_row(opt_min="6.0", opt_max="7.0", source_id="MEMORY")
    errors = check_requirements(df, CROPS, SOURCES)
    assert any("not in sources.csv" in e for e in errors)


@pytest.mark.parametrize("status", ["todo", "draft"])
def test_only_verified_rows_reach_engine(status):
    df = pd.concat([_req_row(opt_min="6.0", opt_max="7.0"),
                    _req_row(status=status)], ignore_index=True)
    out = verified_only(df)
    assert len(out) == 1 and (out["status"] == "verified").all()
