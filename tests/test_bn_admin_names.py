"""Tests for Phase 3d: Bangla admin names attached to COD-AB codes."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from chashibondhu.data_pipeline.admin.bn_names import (  # noqa: E402
    has_bengali, match_one_to_one, score,
)

OUT = ROOT / "data" / "processed" / "admin" / "admin_names_bn.csv"


@pytest.fixture(scope="module")
def names() -> pd.DataFrame:
    if not OUT.exists():
        pytest.skip("admin_names_bn.csv missing - run scripts/build_bn_admin_names.py")
    return pd.read_csv(OUT, dtype=str, keep_default_na=False, encoding="utf-8-sig")


# ---- matching logic (no data needed) ----
@pytest.mark.parametrize("a,b", [("Jessore", "Jashore"), ("Bogra", "Bogura"),
                                 ("Comilla", "Cumilla"), ("Barisal", "Barishal"),
                                 ("Chattogram", "Chattagram")])
def test_spelling_variants_match(a, b):
    assert score(a, b)[0] >= 0.88


def test_matching_is_one_to_one():
    res = match_one_to_one(["Sadar", "Sadar Dakshin"], ["Sadar Dakshin", "Sadar"])
    assert [m.right for m in res] == [1, 0]


def test_unrelated_names_not_matched():
    res = match_one_to_one(["Dhanmondi"], ["Kaliganj"])
    assert res[0].status == "missing"


# ---- built output ----
def test_counts_and_unique_codes(names):
    counts = names["level"].value_counts().to_dict()
    assert counts == {"division": 8, "district": 64, "upazila": 507}
    assert not names.duplicated(["level", "pcode"]).any()


def test_all_divisions_and_districts_have_bangla(names):
    top = names[names["level"].isin(["division", "district"])]
    assert (top["name_bn"] != "").all(), top.loc[top["name_bn"] == "", "name_en"].tolist()


def test_bangla_text_is_bengali_script(names):
    filled = names[names["name_bn"] != ""]
    assert filled["name_bn"].map(has_bengali).all()


def test_no_duplicate_bangla_name_within_a_district(names):
    upz = names[(names["level"] == "upazila") & (names["name_bn"] != "")]
    assert not upz.duplicated(["parent_pcode", "name_bn"]).any()


def test_upazila_coverage(names):
    upz = names[names["level"] == "upazila"]
    share = (upz["name_bn"] != "").mean()
    assert share >= 0.90, f"only {share:.0%} of upazilas have a Bangla name"


def test_every_named_row_has_provenance(names):
    filled = names[names["name_bn"] != ""]
    assert (filled["source"] != "").all()
    assert filled["data_type"].isin(["community_dataset", "manual_curated"]).all()
    assert set(names["status"]) <= {"draft", "needs_review", "missing", "verified"}


def test_real_world_dhaka_and_sylhet(names):
    """Physical sanity check: well-known names must come out right."""
    def bn(level, en):
        row = names[(names["level"] == level) & (names["name_en"].str.lower() == en)]
        assert len(row) == 1, f"{level} {en} not found exactly once"
        return row["name_bn"].iloc[0]
    assert bn("district", "dhaka") == "ঢাকা"
    assert bn("division", "sylhet") == "সিলেট"
