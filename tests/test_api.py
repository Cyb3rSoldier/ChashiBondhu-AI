"""Phase 5 API tests with small fakes (no real data needed).

The area names below (Testpur etc.) are invented test fixtures, not real places.
"""
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import get_args

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd  # noqa: E402
import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from chashibondhu.api.areas import AreaDirectory, normalize  # noqa: E402
from chashibondhu.api.farmer_messages import (FOOTER, crop_line,  # noqa: E402
                                              suitability_message, to_bn_digits)
from chashibondhu.api.main import app, get_services  # noqa: E402
from chashibondhu.api.schemas import LandType  # noqa: E402
from chashibondhu.api.services import Services  # noqa: E402
from chashibondhu.common.land_units import AreaResult, LandUnitError  # noqa: E402
from chashibondhu.crop_planning.rules.engine import (LAND_TYPES, CheckResult,  # noqa: E402
                                                     CropResult)

DIV, DIST, UPZ = "BD90", "BD9001", "BD90010001"


def _directory() -> AreaDirectory:
    divisions = pd.DataFrame([{"division_code": DIV, "division_name": "Testdiv"}])
    districts = pd.DataFrame([{"district_code": DIST, "district_name": "Testpur",
                               "division_code": DIV}])
    upazilas = pd.DataFrame([
        {"upazila_code": UPZ, "upazila_name": "Sample Sadar", "district_code": DIST},
        {"upazila_code": "BD90010002", "upazila_name": "Nodupur", "district_code": DIST}])
    names = pd.DataFrame([
        {"pcode": DIST, "name_bn": "টেস্টপুর", "aliases_bn": "", "alt_name_en": "Testpore",
         "status": "draft", "source": "test"},
        {"pcode": UPZ, "name_bn": "নমুনা সদর", "aliases_bn": "নমুনা", "alt_name_en": "",
         "status": "draft", "source": "test"}])
    return AreaDirectory(divisions, districts, upazilas, names)


class FakeStore:
    def get(self, code):
        if code == "BD90010002":
            raise KeyError(f"no soil data for upazila {code}")
        if code not in (DIST, UPZ):
            raise KeyError(f"unknown area code '{code}'")
        level = "district" if code == DIST else "upazila"
        return SimpleNamespace(area_code=code, level=level, name_en="x", district_code=DIST,
                               flags=["test flag"],
                               data_types={"temperature": "historical_reanalysis"},
                               sources={"temperature": "NASA POWER"})


class FakeEngine:
    def evaluate(self, area, crops=None, land_type=None, irrigation=None):
        if land_type is not None and land_type not in LAND_TYPES:
            raise ValueError("bad land_type")
        crops = crops or ["mustard", "potato"]
        if "bad_crop" in crops:
            raise ValueError("unknown crop_id(s): ['bad_crop']")
        names = {"mustard": "সরিষা", "potato": "আলু", "tomato": "টমেটো"}
        status = {"mustard": "suitable", "potato": "marginal", "tomato": "unknown"}
        out = []
        for c in crops:
            r = CropResult(c, c.title(), names.get(c, ""), status.get(c, "unknown"),
                           checks=[CheckResult("soil_ph", "suitable", "pH 6.1", "6.1",
                                               "5.5-7.0", "BARI_KPH p. 1", "global_model_estimate")],
                           growing_months=[11, 12, 1], evidence_coverage=0.5)
            if land_type is None:
                r.missing_inputs.append("land_type")
            out.append(r)
        return out


class FakeLandUnits:
    table = pd.DataFrame({"status": ["draft", "verified"]},
                         index=pd.Index(["bigha", "decimal"], name="unit_id"))

    def parse(self, text, local_decimals=None):
        if "bad" in text:
            raise LandUnitError(f"could not read an amount from '{text}'")
        if "decimal" in text:
            return AreaResult(404.69, [(10.0, "decimal", "standard")], text)
        return AreaResult(1337.8, [(1.0, "bigha", "farmer_stated")], text)


def _services() -> Services:
    cat = pd.DataFrame({"name_en": ["Mustard", "Potato"], "name_bn": ["সরিষা", "আলু"],
                        "initial_ml_model": ["true", "true"], "status": ["draft", "draft"]},
                       index=pd.Index(["mustard", "potato"], name="crop_id"))
    return Services(areas=_directory(), store=FakeStore(), engine=FakeEngine(), catalogue=cat,
                    land_units=FakeLandUnits(), allow_draft_land_units=True)


@pytest.fixture
def client():
    svc = _services()
    app.dependency_overrides[get_services] = lambda: svc
    yield TestClient(app)
    app.dependency_overrides.clear()


# ------------------------------------------------------------------ health
def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_ready_counts(client):
    body = client.get("/ready").json()
    assert body["areas"]["division"] == 1 and body["areas"]["upazila"] == 2
    assert body["areas"]["with_name_bn"] == 2 and body["crops"] == 2


def test_service_unavailable_gives_503():
    def broken():
        raise HTTPException(status_code=503, detail="missing data")
    app.dependency_overrides[get_services] = broken
    try:
        r = TestClient(app).get("/ready")
        assert r.status_code == 503
    finally:
        app.dependency_overrides.clear()


# ------------------------------------------------------------------ areas
def test_search_english_exact(client):
    body = client.get("/areas/search", params={"q": "testpur"}).json()
    assert body["results"][0]["area"]["code"] == DIST
    assert body["results"][0]["score"] == 3.0


def test_search_bangla_alias(client):
    body = client.get("/areas/search", params={"q": "নমুনা"}).json()
    assert body["results"][0]["area"]["code"] == UPZ
    assert body["results"][0]["area"]["name_bn"] == "নমুনা সদর"


def test_search_alt_spelling_and_fuzzy(client):
    alt = client.get("/areas/search", params={"q": "Testpore"}).json()
    assert alt["results"][0]["matched_on"] == "alt_name_en"
    fuzzy = client.get("/areas/search", params={"q": "Tastpur"}).json()
    assert fuzzy["results"][0]["area"]["code"] == DIST
    assert fuzzy["results"][0]["score"] == 0.5


def test_search_level_filter(client):
    body = client.get("/areas/search", params={"q": "s", "level": "upazila"}).json()
    assert body["count"] >= 1
    assert all(h["area"]["level"] == "upazila" for h in body["results"])


def test_search_validation(client):
    assert client.get("/areas/search", params={"q": ""}).status_code == 422
    assert client.get("/areas/search", params={"q": "x", "level": "union"}).status_code == 422


def test_get_area(client):
    body = client.get(f"/areas/{UPZ}").json()
    assert body["district_code"] == DIST and body["division_code"] == DIV
    assert client.get("/areas/BD0000").status_code == 404

def test_area_children(client):
    body = client.get(f"/areas/{DIST}/children").json()
    assert [a["code"] for a in body] == ["BD90010002", UPZ]   # sorted by English name
    assert client.get(f"/areas/{DIV}/children").json()[0]["code"] == DIST
    assert client.get("/areas/BD0000/children").status_code == 404


def test_normalize_keeps_bangla_vowel_signs():
    assert normalize("নমুনা  সদর") == "নমুনাসদর"
    assert normalize("Cox's Bazar") == "coxsbazar"


# ------------------------------------------------------------------ crops
def test_crops(client):
    body = client.get("/crops").json()
    assert [c["crop_id"] for c in body] == ["mustard", "potato"]


# ------------------------------------------------------------------ suitability
def test_suitability_upazila(client):
    r = client.post("/suitability", json={"area_code": UPZ, "crops": ["mustard", "potato"]})
    assert r.status_code == 200
    body = r.json()
    assert [x["status"] for x in body["results"]] == ["suitable", "marginal"]
    assert body["results"][0]["checks"][0]["source"] == "BARI_KPH p. 1"
    msg = body["farmer_message_bn"].split("\n")
    assert msg[0] == "নমুনা সদর এলাকার জন্য:"
    assert msg[1] == "✅ সরিষা — ভালো হবে"
    assert msg[2] == "⚠️ আলু — মোটামুটি"
    assert "আপনার জমিতে বর্ষায় কতটুকু পানি ওঠে?" in msg      # asked once
    assert msg.count("আপনার জমিতে বর্ষায় কতটুকু পানি ওঠে?") == 1
    assert msg[-1] == FOOTER
    assert body["template_version"].endswith("draft")
    assert any("not a weather forecast" in n for n in body["data_notes"])


def test_suitability_district_adds_hint(client):
    body = client.post("/suitability", json={"area_code": DIST}).json()
    assert "উপজেলার নাম বললে আরো ঠিকভাবে বলা যাবে।" in body["farmer_message_bn"]
    assert any("upazila code" in n for n in body["data_notes"])


def test_suitability_land_type_given_no_question(client):
    body = client.post("/suitability", json={"area_code": UPZ, "crops": ["mustard"],
                                             "land_type": "highland"}).json()
    assert "পানি ওঠে" not in body["farmer_message_bn"]


def test_suitability_errors(client):
    post = lambda j: client.post("/suitability", json=j).status_code  # noqa: E731
    assert post({"area_code": "BD9999"}) == 404                       # not in directory
    assert post({"area_code": "BD90010002"}) == 404                   # no data in store
    assert post({"area_code": DIV}) == 422                            # division
    assert post({"area_code": UPZ, "land_type": "swamp"}) == 422      # bad land type
    assert post({"area_code": UPZ, "crops": ["bad_crop"]}) == 422     # engine ValueError
    assert post({"area_code": UPZ, "extra": 1}) == 422                # unknown field
    assert post({"area_code": "dhaka"}) == 422                        # bad code format
    assert post({"area_code": UPZ, "crops": []}) == 422               # empty list


def test_land_types_match_engine():
    assert set(get_args(LandType)) == LAND_TYPES


# ------------------------------------------------------------------ farmer messages
def test_unknown_status_never_positive():
    assert crop_line("টমেটো", "something_new").startswith("❓")
    msg = suitability_message(None, "upazila",
                              [{"crop_id": "tomato", "name_bn": "টমেটো", "status": "unknown",
                                "missing_inputs": []}])
    assert msg.split("\n")[0] == "আপনার এলাকার জন্য:"
    assert "❓ টমেটো — নিশ্চিত না — কৃষি অফিসে জিজ্ঞেস করুন" in msg


def test_bn_digits():
    assert to_bn_digits("2025 - 10") == "২০২৫ - ১০"


# ------------------------------------------------------------------ land units
def test_land_parse_draft_warning(client):
    body = client.post("/land-units/parse",
                       json={"text": "১ বিঘা", "local_decimals": {"bigha": 33}}).json()
    assert body["sqm"] == 1337.8 and body["all_units_verified"] is False
    assert body["parts"][0]["unit_status"] == "draft"
    assert len(body["warnings"]) == 2


def test_land_parse_verified(client):
    body = client.post("/land-units/parse", json={"text": "10 decimal"}).json()
    assert body["all_units_verified"] is True and body["warnings"] == []


def test_land_parse_errors(client):
    post = lambda j: client.post("/land-units/parse", json=j).status_code  # noqa: E731
    assert post({"text": "bad text"}) == 422
    assert post({"text": ""}) == 422
    assert post({"text": "1 bigha", "local_decimals": {"bigha": -5}}) == 422
