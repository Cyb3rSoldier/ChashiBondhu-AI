"""Tests for Phase 3e: land units (bigha/katha/decimal) and conversion."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from chashibondhu.common.land_units import (  # noqa: E402
    LandUnitError, LandUnits, validate_land_units,
)
from chashibondhu.reference.validate import read_reference  # noqa: E402

REF = ROOT / "data" / "reference"
UNITS_CSV = REF / "land_units.csv"


@pytest.fixture(scope="module")
def table() -> pd.DataFrame:
    if not UNITS_CSV.exists():
        pytest.skip("land_units.csv missing - run scripts/make_land_units.py")
    return read_reference(UNITS_CSV)


@pytest.fixture(scope="module")
def math_units(table) -> LandUnits:
    """Same definitions, all treated as usable: tests the arithmetic only."""
    return LandUnits(table, allowed_status=("draft", "verified"))


def test_file_valid(table):
    sources = set(read_reference(REF / "sources.csv")["source_id"])
    assert validate_land_units(table, sources) == []


def test_core_units_present(table):
    assert {"decimal", "katha", "bigha", "acre", "hectare", "sq_m"} <= set(table["unit_id"])


def test_physical_definitions(math_units):
    """Real-world check: 1 acre = 4046.8564224 m2 exactly, 1 ha = 10,000 m2."""
    assert math_units.sqm_per("acre") == pytest.approx(4046.8564224, abs=1e-6)
    assert math_units.sqm_per("hectare") == pytest.approx(10000.0)
    assert math_units.sqm_per("decimal") == pytest.approx(40.468564224, abs=1e-9)


def test_standard_bigha_is_about_33_decimals(math_units):
    ratio = math_units.sqm_per("bigha") / math_units.sqm_per("decimal")
    assert ratio == pytest.approx(33.06, abs=0.01)


def test_parse_bangla_digits_and_compound(math_units):
    res = math_units.parse("২ বিঘা ৫ কাঠা")
    expected = 2 * math_units.sqm_per("bigha") + 5 * math_units.sqm_per("katha")
    assert res.sqm == pytest.approx(expected)
    assert [p[1] for p in res.parts] == ["bigha", "katha"]


def test_parse_banglish(math_units):
    assert math_units.parse("33 shotok").sqm == pytest.approx(33 * math_units.sqm_per("decimal"))
    assert math_units.parse("1.5 acre").parts[0][1] == "acre"


def test_farmer_stated_bigha_wins(math_units):
    res = math_units.parse("1 bigha", local_decimals={"bigha": 50})
    assert res.sqm == pytest.approx(50 * math_units.sqm_per("decimal"))
    assert res.basis == "farmer_stated"


def test_kani_needs_farmer_value(math_units):
    with pytest.raises(LandUnitError):
        math_units.parse("2 কানি")
    assert math_units.parse("2 কানি", local_decimals={"kani": 100}).basis == "farmer_stated"


def test_unknown_unit_and_missing_unit_rejected(math_units):
    with pytest.raises(LandUnitError):
        math_units.parse("3 gonda")
    with pytest.raises(LandUnitError):
        math_units.parse("3")


def test_draft_rows_blocked_by_default(table):
    units = LandUnits(table)  # default: verified only
    if (table.set_index("unit_id").loc["bigha", "status"]) != "verified":
        with pytest.raises(LandUnitError):
            units.sqm_per("bigha")


def test_circular_definition_rejected():
    df = pd.DataFrame([
        {"unit_id": "a", "name_en": "a", "name_bn": "ক", "aliases_latin": "", "aliases_bn": "",
         "factor": "2", "base_unit": "b", "scope": "national", "source_id": "X",
         "source_locator": "", "status": "draft", "verified_by": "", "verified_on": "",
         "notes": ""},
        {"unit_id": "b", "name_en": "b", "name_bn": "খ", "aliases_latin": "", "aliases_bn": "",
         "factor": "2", "base_unit": "a", "scope": "national", "source_id": "X",
         "source_locator": "", "status": "draft", "verified_by": "", "verified_on": "",
         "notes": ""},
    ])
    errors = validate_land_units(df, {"X"})
    assert any("circular" in e for e in errors)
