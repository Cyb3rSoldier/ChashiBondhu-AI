"""Tests for the Phase 2b CHIRPS rainfall outputs."""

from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
CLIMATE = ROOT / "data/processed/climate"
ADMIN = ROOT / "data/processed/admin"


def load(name):
    path = CLIMATE / name
    if not path.exists():
        pytest.skip(f"{path} not found; run build_chirps_rainfall.py first")
    return pd.read_csv(path)


def test_all_districts_and_months():
    m = load("chirps_district_monthly.csv")
    assert m["district_code"].nunique() == 64
    n_months = m.groupby("district_code").size()
    assert n_months.nunique() == 1, "every district should have the same months"


def test_no_missing_district_rainfall():
    m = load("chirps_district_monthly.csv")
    assert m["rain_mm"].notna().all()
    assert (m["rain_mm"] >= 0).all()


def test_all_upazilas_present():
    u = load("chirps_upazila_monthly.csv")
    admin = pd.read_csv(ADMIN / "upazilas.csv")
    assert u["upazila_code"].nunique() == len(admin)


def test_climatology_shape():
    c = load("chirps_district_climatology.csv")
    assert len(c) == 64 * 12


def test_monsoon_wetter_than_winter():
    c = load("chirps_district_climatology.csv")
    piv = c.pivot(index="district_code", columns="month", values="rain_mm_mean")
    assert (piv[7] > piv[1]).all()


def test_sylhet_wetter_than_rajshahi():
    """Well-known pattern: the northeast (Sylhet) is far wetter than the
    northwest (Rajshahi). Compares mean annual rainfall of the two divisions."""
    c = load("chirps_district_climatology.csv")
    dist = pd.read_csv(ADMIN / "districts.csv")
    div = pd.read_csv(ADMIN / "divisions.csv")
    annual = c.groupby("district_code")["rain_mm_mean"].sum().rename("annual")
    d = dist.merge(div[["division_code", "division_name"]], on="division_code")
    d = d.merge(annual, left_on="district_code", right_index=True)
    by_div = d.groupby("division_name")["annual"].mean()
    assert by_div["Sylhet"] > by_div["Rajshahi"]
