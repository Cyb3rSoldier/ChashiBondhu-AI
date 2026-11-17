"""Tests for the admin reference tables built in Phase 0."""

from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
ADMIN = ROOT / "data/processed/admin"

# Rough bounding box of Bangladesh (sanity check for reference points)
LAT_RANGE = (20.3, 26.8)
LON_RANGE = (87.9, 92.8)


def load(name):
    path = ADMIN / f"{name}.csv"
    if not path.exists():
        pytest.skip(f"{path} not found; run build_admin_reference.py first")
    return pd.read_csv(path)


def test_counts():
    assert len(load("divisions")) == 8
    assert len(load("districts")) == 64
    assert len(load("upazilas")) > 0


def test_codes_unique_and_present():
    for name, code in [("divisions", "division_code"),
                       ("districts", "district_code"),
                       ("upazilas", "upazila_code")]:
        df = load(name)
        assert df[code].notna().all(), f"{name}: missing codes"
        assert df[code].is_unique, f"{name}: duplicate codes"


def test_hierarchy_links():
    div, dist, upz = load("divisions"), load("districts"), load("upazilas")
    assert set(dist["division_code"]) <= set(div["division_code"])
    assert set(upz["district_code"]) <= set(dist["district_code"])
    assert set(dist["district_code"]) <= set(upz["district_code"])


def test_reference_points_inside_bangladesh():
    for name in ["divisions", "districts", "upazilas"]:
        df = load(name)
        assert df["ref_lat"].between(*LAT_RANGE).all(), f"{name}: lat out of range"
        assert df["ref_lon"].between(*LON_RANGE).all(), f"{name}: lon out of range"


def test_new_official_spellings():
    names = set(load("districts")["district_name"])
    for new in ["Chattogram", "Barishal", "Cumilla", "Jashore", "Bogura"]:
        assert new in names, f"expected official spelling {new}"
