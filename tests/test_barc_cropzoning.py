"""Tests for Phase 4b: BARC Crop Zoning table and its use in the engine."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from chashibondhu.crop_planning.features.area_features import AreaFeatures  # noqa: E402
from chashibondhu.crop_planning.features.barc_zoning import CLASS_COLS, BarcStore  # noqa: E402
from chashibondhu.crop_planning.rules.engine import Knowledge, SuitabilityEngine  # noqa: E402

OUT = ROOT / "data" / "processed" / "barc" / "barc_cropzoning_upazila.csv"
MANIFEST = ROOT / "data" / "raw" / "barc_cropzoning" / "manifest.csv"
ADMIN = ROOT / "data" / "processed" / "admin"
ENC = "utf-8-sig"


# ---------- helpers (test-only numbers, not real data) ----------
def store(tmp: Path, rows: list[tuple]) -> BarcStore:
    recs = [{"crop_id": c, "district_code": d, "upazila_code": u,
             **dict(zip(CLASS_COLS, areas)), "zone": "1", "note": "",
             "data_type": "expert_land_suitability_assessment"} for c, d, u, areas in rows]
    path = tmp / "barc.csv"
    pd.DataFrame(recs).to_csv(path, index=False, encoding=ENC)
    return BarcStore(path)


def engine(tmp: Path, barc: BarcStore) -> SuitabilityEngine:
    pd.DataFrame([{"crop_id": "testcrop", "name_en": "Test", "name_bn": "পরীক্ষা",
                   "season_systems": "rabi", "initial_ml_model": "true"}]
                 ).to_csv(tmp / "crop_catalogue.csv", index=False, encoding=ENC)
    for name, cols in (("crop_requirements.csv", ["crop_id", "variety_scope", "parameter",
                                                  "min", "opt_min", "opt_max", "max",
                                                  "value_text", "source_id",
                                                  "source_locator", "status"]),
                       ("crop_calendar.csv", ["crop_id", "variety_scope", "activity",
                                              "start_month", "end_month", "region_scope",
                                              "source_id", "source_locator", "status"]),
                       ("seasons.csv", ["season_id", "start_month", "end_month",
                                        "source_id", "source_locator", "status"])):
        pd.DataFrame(columns=cols).to_csv(tmp / name, index=False, encoding=ENC)
    return SuitabilityEngine(Knowledge(tmp), barc)


def area(code="U1", level="upazila") -> AreaFeatures:
    m = range(1, 13)
    return AreaFeatures(code, level, "Testpur", "D1", {i: 20.0 for i in m},
                        {i: 50.0 for i in m}, {i: 25.0 for i in m}, {i: 75.0 for i in m},
                        6.5, 6.3, 6.7, "loam", 0.8, {}, {}, [])


def status(tmp, areas, level="upazila", code="U1") -> str:
    s = store(tmp, [("testcrop", "D1", "U1", areas), ("testcrop", "D1", "U2", areas)])
    return engine(tmp, s).evaluate(area(code, level))[0].status


# ---------- unit tests ----------
def test_mostly_good_is_suitable_even_without_book_rules(tmp_path):
    assert status(tmp_path, (60, 20, 10, 5, 5)) == "suitable"


def test_mostly_poor_is_not_suitable(tmp_path):
    assert status(tmp_path, (0, 5, 10, 40, 45)) == "not_suitable"


def test_mixed_area_is_marginal(tmp_path):
    assert status(tmp_path, (20, 10, 30, 20, 20)) == "marginal"


def test_no_barc_data_stays_unknown(tmp_path):
    s = store(tmp_path, [("othercrop", "D1", "U1", (100, 0, 0, 0, 0))])
    assert engine(tmp_path, s).evaluate(area())[0].status == "unknown"


def test_district_adds_upazila_areas(tmp_path):
    s = store(tmp_path, [("testcrop", "D1", "U1", (100, 0, 0, 0, 0)),
                         ("testcrop", "D1", "U2", (0, 0, 0, 0, 300))])
    z = s.get("testcrop", "district", "D1")
    assert z.n_upazilas == 2 and z.good == pytest.approx(0.25)


# ---------- built table (your real files) ----------
@pytest.fixture(scope="module")
def table() -> pd.DataFrame:
    if not OUT.exists():
        pytest.skip("barc_cropzoning_upazila.csv missing - run scripts/build_barc_cropzoning.py")
    return pd.read_csv(OUT, dtype={"upazila_code": str, "district_code": str,
                                   "crop_id": str}, keep_default_na=False, encoding=ENC)


def test_catalogue_crops_present(table):
    expected = {"aman_rice", "boro_rice", "maize", "potato", "lentil", "mung_bean",
                "mustard", "onion"}
    assert expected <= set(table["crop_id"])


def test_class_areas_are_valid(table):
    areas = table[CLASS_COLS].astype(float)
    assert (areas >= 0).all().all()
    # rows with zero total are allowed (BARC gave no area); the engine treats them as no data
    nonzero = areas.sum(axis=1) > 0
    assert nonzero.mean() >= 0.80, f"only {nonzero.mean():.0%} of rows have any area"


def test_matched_codes_exist_and_are_unique(table):
    ours = set(pd.read_csv(ADMIN / "upazilas.csv", dtype=str)["upazila_code"])
    m = table[table["upazila_code"] != ""]
    assert set(m["upazila_code"]) <= ours
    assert not m.duplicated(["barc_crop", "upazila_code"]).any()


def test_most_rows_matched(table):
    share = (table["upazila_code"] != "").mean()
    assert share >= 0.85, f"only {share:.0%} of BARC rows matched our upazilas"


def test_labelled_honestly(table):
    assert (table["data_type"] == "expert_land_suitability_assessment").all()
    assert table["area_unit"].str.contains("unverified").all()


def test_real_world_aman_suits_barguna(table):
    """Physical sanity: monsoon (Aman) rice suits the southern coastal floodplain."""
    if not MANIFEST.exists() or "apps.barc.gov.bd" not in MANIFEST.read_text():
        pytest.skip("real BARC download not present")
    sub = table[(table["crop_id"] == "aman_rice") &
                (table["barc_district"].str.upper() == "BARGUNA")]
    areas = sub[CLASS_COLS].astype(float).sum()
    assert (areas.iloc[0] + areas.iloc[1]) / areas.sum() >= 0.7
