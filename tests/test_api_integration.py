"""Phase 5 integration tests on the REAL local data (data/processed is gitignored).

Skipped automatically when the processed data is not present (e.g. fresh clone / CI).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd  # noqa: E402
import pytest  # noqa: E402

ADMIN = ROOT / "data" / "processed" / "admin"
pytestmark = pytest.mark.skipif(not (ADMIN / "districts.csv").exists(),
                                reason="processed data not available")

from fastapi.testclient import TestClient  # noqa: E402

from chashibondhu.api.main import app  # noqa: E402
from chashibondhu.api.services import load_services  # noqa: E402
from chashibondhu.common.land_units import LandUnitError, LandUnits  # noqa: E402


@pytest.fixture(scope="module")
def client():
    app.dependency_overrides.clear()
    load_services.cache_clear()
    return TestClient(app)


def _codes(name: str, col: str) -> list[str]:
    return pd.read_csv(ADMIN / name, dtype=str)[col].tolist()


def test_ready_counts(client):
    r = client.get("/ready")
    assert r.status_code == 200, r.text
    areas = r.json()["areas"]
    assert (areas["division"], areas["district"], areas["upazila"]) == (8, 64, 507)


def test_search_dhaka(client):
    body = client.get("/areas/search", params={"q": "Dhaka"}).json()
    assert body["count"] >= 1
    assert "dhaka" in body["results"][0]["area"]["name_en"].lower()


def test_suitability_district_default_crops(client):
    code = _codes("districts.csv", "district_code")[0]
    r = client.post("/suitability", json={"area_code": code})
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["results"]) == 5                      # initial 5 ML crops
    lines = body["farmer_message_bn"].split("\n")
    assert sum(line[:1] in "✅⚠❌❓" for line in lines) == 5   # one line per crop


def test_suitability_some_upazila(client):
    for code in _codes("upazilas.csv", "upazila_code")[:30]:
        r = client.post("/suitability", json={"area_code": code, "irrigation": True})
        if r.status_code == 200:
            assert "উপজেলার নাম বললে" not in r.json()["farmer_message_bn"]
            return
        assert r.status_code == 404, r.text               # only "no data" is acceptable
    pytest.fail("no upazila among the first 30 returned a result")


def test_land_parse_matches_library(client):
    allowed = ("verified", "draft")
    lu = LandUnits.from_csv(ROOT / "data" / "reference" / "land_units.csv",
                            allowed_status=allowed)
    text, local = "২ বিঘা ৫ কাঠা", {"bigha": 33}
    r = client.post("/land-units/parse", json={"text": text, "local_decimals": local})
    try:
        expected = lu.parse(text, local)
    except LandUnitError:
        assert r.status_code == 422
        return
    assert r.status_code == 200, r.text
    assert r.json()["sqm"] == pytest.approx(expected.sqm, abs=0.01)
