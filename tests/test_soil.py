"""Tests for the Phase 2 soil outputs."""

from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
SOIL = ROOT / "data/processed/soil"


def load(level):
    path = SOIL / f"{level}_soil_topsoil.csv"
    if not path.exists():
        pytest.skip(f"{path} not found; run build_soil_features.py first")
    return pd.read_csv(path)


def test_all_districts_present_with_data():
    d = load("district")
    assert len(d) == 64
    assert d["ph_mean"].notna().all(), "every district should have soil data"


def test_all_upazilas_present():
    u = load("upazila")
    admin = pd.read_csv(ROOT / "data/processed/admin/upazilas.csv")
    assert len(u) == len(admin)


def test_ph_plausible():
    d = load("district")
    assert d["ph_mean"].between(3.5, 9.0).all()
    assert (d["ph_q05_mean"] <= d["ph_mean"] + 0.05).all()
    assert (d["ph_mean"] <= d["ph_q95_mean"] + 0.05).all()


def test_texture_fractions_sum_near_100():
    d = load("district").dropna(subset=["clay_pct_mean"])
    total = d["clay_pct_mean"] + d["sand_pct_mean"] + d["silt_pct_mean"]
    assert total.between(90, 110).all()


def test_labelled_as_model_estimate():
    assert (load("district")["data_type"] == "global_model_estimate").all()
