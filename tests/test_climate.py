"""Tests for the Phase 1 climate outputs."""

from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
CLIMATE = ROOT / "data/processed/climate"


def load_csv(name):
    path = CLIMATE / name
    if not path.exists():
        pytest.skip(f"{path} not found; run build_climatology.py first")
    return pd.read_csv(path)


def load_daily():
    path = CLIMATE / "nasa_power_daily.parquet"
    if not path.exists():
        pytest.skip(f"{path} not found; run build_climatology.py first")
    return pd.read_parquet(path)


def test_all_64_districts_present():
    assert load_daily()["district_code"].nunique() == 64


def test_no_duplicate_days():
    daily = load_daily()
    assert not daily.duplicated(["district_code", "date"]).any()


def test_values_in_plausible_range():
    daily = load_daily()
    assert daily["rain_mm"].dropna().ge(0).all()
    assert daily["rh_pct"].dropna().between(0, 100).all()
    assert daily["t_mean_c"].dropna().between(-5, 48).all()


def test_missing_share_is_small():
    daily = load_daily()
    for col in ["t_mean_c", "t_max_c", "t_min_c", "rain_mm", "rh_pct"]:
        share = daily[col].isna().mean()
        assert share < 0.01, f"{col}: {share:.2%} missing"


def test_climatology_shape():
    clim = load_csv("district_climatology_monthly.csv")
    assert len(clim) == 64 * 12
    assert set(clim["month"]) == set(range(1, 13))
    assert (clim["data_type"] == "historical_reanalysis").all()


def test_monsoon_wetter_than_winter():
    """Physical sanity check: July rainfall should exceed January in every district."""
    clim = load_csv("district_climatology_monthly.csv")
    piv = clim.pivot(index="district_code", columns="month", values="rain_mm_mean")
    assert (piv[7] > piv[1]).all()
