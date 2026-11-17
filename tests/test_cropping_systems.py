"""Tests for Phase 3c: intercropping / relay cropping systems."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from chashibondhu.reference.cropping_systems import (  # noqa: E402
    COLUMNS, candidate_systems, validate_cropping_systems,
)
from chashibondhu.reference.validate import read_reference  # noqa: E402

REF = ROOT / "data" / "reference"
CSV = REF / "cropping_systems.csv"
CROPS = {"aman_rice", "maize", "potato", "lentil", "mustard"}
SOURCES = {"P1"}


def _row(**kw) -> dict:
    """A complete, valid, verified test row (values are test-only, not data)."""
    row = {c: "" for c in COLUMNS}
    row.update({"system_id": "s1", "system_type": "relay", "main_crop_id": "aman_rice",
                "companion_crop_id": "lentil", "companion_timing": "before_main_harvest",
                "timing_days_min": "5", "timing_days_max": "10", "season_system": "rabi",
                "land_type": "medium_highland", "evidence_level": "field_trial",
                "tested_districts": "Pabna", "source_id": "P1", "source_locator": "Table 2",
                "status": "verified", "verified_by": "siyam", "verified_on": "2026-11-09"})
    row.update(kw)
    return row


def _errors(**kw) -> list[str]:
    return validate_cropping_systems(pd.DataFrame([_row(**kw)]), CROPS, SOURCES)


@pytest.fixture(scope="module")
def table() -> pd.DataFrame:
    if not CSV.exists():
        pytest.skip("cropping_systems.csv missing - run scripts/make_cropping_systems.py")
    return read_reference(CSV)


def test_file_valid(table):
    sources = set(read_reference(REF / "sources.csv")["source_id"])
    crops = set(read_reference(REF / "crop_catalogue.csv")["crop_id"])
    assert validate_cropping_systems(table, crops, sources) == []


def test_every_system_has_a_source(table):
    assert (table["source_id"] != "").all()


def test_valid_row_passes():
    assert _errors() == []


def test_relay_needs_before_harvest_timing():
    assert any("companion_timing" in e for e in _errors(companion_timing="same_time"))


def test_field_trial_needs_tested_districts():
    assert any("tested_districts" in e for e in _errors(tested_districts=""))


def test_companion_cannot_be_main_crop():
    assert any("cannot be the main crop" in e for e in _errors(companion_crop_id="aman_rice"))


def test_other_companion_needs_bangla_name():
    errs = _errors(companion_crop_id="", companion_other_en="red amaranth",
                   companion_other_bn="")
    assert any("companion_other_bn" in e for e in errs)


def test_bad_row_ratio_rejected():
    assert any("row_ratio" in e for e in _errors(row_ratio="2-1"))


def test_only_verified_systems_are_suggested():
    df = pd.DataFrame([_row(), _row(system_id="s2", status="todo")])
    out = candidate_systems(df, "aman_rice")
    assert list(out["system_id"]) == ["s1"]


def test_recommendations_ranked_before_trials():
    df = pd.DataFrame([_row(),
                       _row(system_id="s2", evidence_level="recommended_package",
                            tested_districts="")])
    assert candidate_systems(df, "aman_rice")["system_id"].iloc[0] == "s2"
