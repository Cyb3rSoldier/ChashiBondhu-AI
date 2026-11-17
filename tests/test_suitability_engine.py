"""Tests for Phase 4: rule-based suitability engine.

Unit tests use small test-only knowledge tables written to a temp folder
(numbers there are NOT agricultural data). Integration tests use your real
processed climate/soil files and skip if they are missing.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from chashibondhu.crop_planning.features.area_features import (  # noqa: E402
    AreaFeatures, FeatureStore,
)
from chashibondhu.crop_planning.rules.engine import (  # noqa: E402
    Knowledge, SuitabilityEngine,
)

PROCESSED = ROOT / "data" / "processed"
REF = ROOT / "data" / "reference"
ENC = "utf-8-sig"


# ---------- helpers ----------
def _req(param, mn="", omn="", omx="", mx="", text="", status="verified"):
    return {"crop_id": "testcrop", "variety_scope": "general", "parameter": param,
            "min": mn, "opt_min": omn, "opt_max": omx, "max": mx, "value_text": text,
            "source_id": "T", "source_locator": "p. 1", "status": status}


def make_knowledge(tmp: Path, reqs: list[dict], start=11, end=2) -> Knowledge:
    pd.DataFrame([{"crop_id": "testcrop", "name_en": "Test", "name_bn": "পরীক্ষা",
                   "season_systems": "rabi", "initial_ml_model": "true"}]
                 ).to_csv(tmp / "crop_catalogue.csv", index=False, encoding=ENC)
    pd.DataFrame(reqs or [_req("air_temp_c", status="todo")]).to_csv(
        tmp / "crop_requirements.csv", index=False, encoding=ENC)
    cal = [{"crop_id": "testcrop", "variety_scope": "general", "activity": a,
            "start_month": s, "end_month": e, "region_scope": "national",
            "source_id": "T", "source_locator": "p. 2", "status": "verified"}
           for a, s, e in (("sowing", start, start), ("harvest", end, end))]
    pd.DataFrame(cal).to_csv(tmp / "crop_calendar.csv", index=False, encoding=ENC)
    pd.DataFrame([{"season_id": "rabi", "start_month": "", "end_month": "",
                   "source_id": "T", "source_locator": "", "status": "draft"}]
                 ).to_csv(tmp / "seasons.csv", index=False, encoding=ENC)
    return Knowledge(tmp)


def fake_area(t=20.0, rain=50.0, ph=6.5, texture="loam") -> AreaFeatures:
    months = range(1, 13)
    return AreaFeatures("X1", "district", "Testpur", "X1",
                        {m: t for m in months}, {m: rain for m in months},
                        {m: rain * 0.5 for m in months}, {m: rain * 1.5 for m in months},
                        ph, ph - 0.2, ph + 0.2, texture, 0.8,
                        {"temperature": "historical_reanalysis", "rainfall": "x",
                         "soil": "global_model_estimate"}, {}, [])


def run(tmp, reqs, area=None, **kw):
    eng = SuitabilityEngine(make_knowledge(tmp, reqs))
    return eng.evaluate(area or fake_area(), **kw)[0]


# ---------- unit tests ----------
def test_unverified_knowledge_gives_unknown(tmp_path):
    r = run(tmp_path, [_req("air_temp_c", omn="15", omx="25", status="draft")])
    assert r.status == "unknown"


def test_inside_optimum_is_suitable(tmp_path):
    r = run(tmp_path, [_req("air_temp_c", "5", "15", "25", "35"),
                       _req("soil_ph", "4.5", "6.0", "7.5", "8.5")])
    assert r.status == "suitable"


def test_outside_optimum_is_marginal(tmp_path):
    r = run(tmp_path, [_req("air_temp_c", "5", "15", "25", "35"),
                       _req("soil_ph", "4.5", "6.0", "7.5", "8.5")], fake_area(t=28))
    assert r.status == "marginal"


def test_outside_limits_is_not_suitable(tmp_path):
    r = run(tmp_path, [_req("air_temp_c", "5", "15", "25", "35"),
                       _req("soil_ph", "4.5", "6.0", "7.5", "8.5")], fake_area(ph=4.0))
    assert r.status == "not_suitable"
    assert any(c.check == "soil_ph" and c.status == "not_suitable" for c in r.checks)


def test_rain_shortfall_uses_irrigation_answer(tmp_path):
    reqs = [_req("air_temp_c", "5", "15", "25", "35"), _req("soil_ph", "", "6", "7.5", ""),
            _req("season_rain_mm", "", "400", "", ""),
            _req("water_regime", text="irrigated")]
    asked = run(tmp_path, reqs, fake_area(rain=10))
    assert asked.status == "marginal" and "irrigation_available" in asked.missing_inputs
    assert run(tmp_path, reqs, fake_area(rain=10), irrigation=True).status == "suitable"
    assert run(tmp_path, reqs, fake_area(rain=10), irrigation=False).status == "not_suitable"


def test_land_type_is_a_hard_constraint(tmp_path):
    reqs = [_req("air_temp_c", "5", "15", "25", "35"), _req("soil_ph", "", "6", "7.5", ""),
            _req("land_type", text="highland|medium_highland")]
    assert run(tmp_path, reqs, land_type="lowland").status == "not_suitable"
    assert run(tmp_path, reqs, land_type="highland").status == "suitable"
    assert "land_type" in run(tmp_path, reqs).missing_inputs


def test_conflicting_sources_give_unknown(tmp_path):
    a = _req("air_temp_c", omn="15", omx="25")
    b = dict(a, opt_min="18", source_locator="p. 9")
    assert run(tmp_path, [a, b, _req("soil_ph", "", "6", "7.5", "")]).status == "unknown"


def test_every_reason_has_source_and_data_type(tmp_path):
    r = run(tmp_path, [_req("air_temp_c", "5", "15", "25", "35"),
                       _req("soil_ph", "4.5", "6.0", "7.5", "8.5")])
    for c in r.checks:
        if c.status != "unknown":
            assert c.source and c.data_type


# ---------- Phase 6: evidence priority (BARC vs global estimates) ----------
class FakeBarc:
    """Test-only BARC store. good/poor shares are NOT real BARC values."""
    def __init__(self, good=None, poor=0.0):
        self.good, self.poor = good, poor

    def get(self, crop, level, code):
        if self.good is None:
            return None
        return SimpleNamespace(good=self.good, poor=self.poor,
                               share_moderate=max(0.0, 1 - self.good - self.poor),
                               n_upazilas=1, note="",
                               data_type="expert_land_suitability_assessment")


def run_barc(tmp, reqs, barc, area=None, **kw):
    eng = SuitabilityEngine(make_knowledge(tmp, reqs), barc)
    return eng.evaluate(area or fake_area(), **kw)[0]


BASE = [_req("air_temp_c", "5", "15", "25", "35"), _req("soil_ph", "4.5", "6.0", "7.5", "8.5")]


def _check(r, name):
    return next(c for c in r.checks if c.check == name)


def test_global_texture_only_warns_when_barc_suitable(tmp_path):
    reqs = BASE + [_req("soil_texture", text="loam|sandy_loam")]
    r = run_barc(tmp_path, reqs, FakeBarc(good=0.6), fake_area(texture="clay_loam"))
    assert r.status == "suitable"
    tex = _check(r, "soil_texture")
    assert tex.status == "warning" and tex.overridden_status == "marginal"
    assert "warning only" in tex.message


def test_global_not_suitable_also_only_warns(tmp_path):
    r = run_barc(tmp_path, BASE, FakeBarc(good=0.6), fake_area(ph=4.0))
    assert r.status == "suitable"
    assert _check(r, "soil_ph").overridden_status == "not_suitable"


def test_global_still_counts_when_barc_has_no_data(tmp_path):
    reqs = BASE + [_req("soil_texture", text="loam|sandy_loam")]
    r = run_barc(tmp_path, reqs, FakeBarc(good=None), fake_area(texture="clay_loam"))
    assert r.status == "marginal"
    assert _check(r, "soil_texture").status == "marginal"
    assert run_barc(tmp_path, BASE, FakeBarc(good=None), fake_area(ph=4.0)).status \
        == "not_suitable"


def test_barc_not_suitable_still_wins(tmp_path):
    r = run_barc(tmp_path, BASE, FakeBarc(good=0.05, poor=0.9))
    assert r.status == "not_suitable"


def test_non_global_checks_still_lower_status(tmp_path):
    """Temperature is not a global soil estimate, so it can still lower BARC's answer."""
    r = run_barc(tmp_path, BASE, FakeBarc(good=0.6), fake_area(t=28))
    assert r.status == "marginal"
    assert _check(r, "temperature").status == "marginal"


# ---------- integration tests (real files) ----------
@pytest.fixture(scope="module")
def store() -> FeatureStore:
    try:
        return FeatureStore(PROCESSED)
    except FileNotFoundError as exc:
        pytest.skip(str(exc))


def test_all_districts_and_upazilas_load(store):
    assert len(store.districts()) == 64
    upz = list(store.upazila_to_district)[:25]
    for code in upz:
        assert store.get(code).flags  # upazilas always flag district temperature


def test_real_engine_runs_on_all_districts(store):
    eng = SuitabilityEngine(Knowledge(REF))
    for code in store.districts():
        for r in eng.evaluate(store.get(code)):
            assert r.status in {"suitable", "marginal", "unknown", "not_suitable"}


def test_physical_sanity_dhaka_winter_vs_summer(store, tmp_path):
    """Test-only requirement (opt 12-27 C): Dhaka's winter fits, its summer is too hot."""
    soil = store.soil["district"]
    code = soil.loc[soil["district_name"].str.lower() == "dhaka", "district_code"].iloc[0]
    area = store.get(code)
    reqs = [_req("air_temp_c", "", "12", "27", ""), _req("soil_ph", "", "3", "10", "")]
    winter = SuitabilityEngine(make_knowledge(tmp_path, reqs, 11, 2)).evaluate(area)[0]
    summer = SuitabilityEngine(make_knowledge(tmp_path, reqs, 5, 8)).evaluate(area)[0]
    assert winter.status == "suitable"
    assert summer.status == "marginal"
