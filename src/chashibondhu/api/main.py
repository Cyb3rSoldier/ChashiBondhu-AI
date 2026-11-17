"""ChashiBondhu AI - FastAPI service (Phase 5).

Run:  uvicorn chashibondhu.api.main:app --app-dir src --reload
Docs: http://127.0.0.1:8000/docs

Endpoints
  GET  /health              liveness (does not load data)
  GET  /ready               loads data, returns counts
  GET  /areas/search        find district / upazila by English, Banglish or Bangla name
  GET  /areas/{code}        one area
  GET  /crops               crop catalogue (crop_id values for /suitability)
  POST /suitability         rule engine result + fixed Bangla farmer message
  POST /land-units/parse    "২ বিঘা ৫ কাঠা" -> square metres
  POST /assistant/ask       Bangla/Banglish/English book assistant (Phase 7)
  GET  /photo/crops, POST /photo/diagnose   photo help (Phase 14; needs python-multipart)
  GET  /chat                developer test chat page (Phase 9a)
  GET  /, /login, /register, /farmer/..., /assistant   website (Phase 9b, chashibondhu.web)
Security: set CHASHIBONDHU_API_KEY in .env to require the X-API-Key header on /assistant and /photo
(the PHP site sends it from ai_proxy.php).
"""
from __future__ import annotations

import logging
import math
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query

from chashibondhu.api.farmer_messages import TEMPLATE_VERSION, suitability_message
from chashibondhu.api.schemas import (AreaHit, AreaOut, AreaSearchResponse, CropOut,
                                      LandParseRequest, LandParseResponse, LandPartOut, Level,
                                      SuitabilityRequest, SuitabilityResponse)
from chashibondhu.api.services import ServiceUnavailable, Services, load_services
from chashibondhu.common.land_units import LandUnitError

API_VERSION = "0.5.0"
log = logging.getLogger("chashibondhu.api")

app = FastAPI(
    title="ChashiBondhu AI API",
    version=API_VERSION,
    description="Crop suitability (rules, cited), area lookup and land-unit parsing. "
                "Climate inputs are historical averages, never forecasts.",
)

HISTORICAL_NOTE = ("Climate values are historical averages (reanalysis / satellite-gauge), "
                   "not a weather forecast.")
DISTRICT_NOTE = ("District result mixes many land types; use an upazila code for a "
                 "farmer answer.")
from chashibondhu.api.security import install_api_key_check  # noqa: E402

install_api_key_check(app)          # X-API-Key for /assistant and /photo when CHASHIBONDHU_API_KEY is set

DRAFT_UNIT_WARNING = ("Some land units are draft (not yet verified against their source). "
                      "Treat the area as approximate.")


def get_services() -> Services:
    try:
        return load_services()
    except ServiceUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


Svc = Annotated[Services, Depends(get_services)]


def _plain(obj):
    """numpy / pandas scalars -> plain Python; NaN -> None (JSON safe)."""
    if isinstance(obj, dict):
        return {k: _plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_plain(v) for v in obj]
    if hasattr(obj, "item") and not isinstance(obj, (str, bytes)):
        try:
            obj = obj.item()
        except (ValueError, TypeError):
            pass
    if isinstance(obj, float) and math.isnan(obj):
        return None
    return obj


def _key_error_text(e: KeyError) -> str:
    return str(e.args[0]) if e.args else "not found"


# ------------------------------------------------------------------ health
@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": API_VERSION}


@app.get("/ready")
def ready(svc: Svc) -> dict:
    return {"status": "ready", "areas": svc.areas.counts(),
            "crops": int(len(svc.catalogue)),
            "allow_draft_land_units": svc.allow_draft_land_units, "notes": svc.notes}


# ------------------------------------------------------------------ areas
@app.get("/areas/search", response_model=AreaSearchResponse)
def search_areas(svc: Svc,
                 q: Annotated[str, Query(min_length=1, max_length=60)],
                 level: Level | None = None,
                 limit: Annotated[int, Query(ge=1, le=50)] = 10) -> AreaSearchResponse:
    hits = svc.areas.search(q, level=level, limit=limit)
    return AreaSearchResponse(
        query=q, count=len(hits),
        results=[AreaHit(area=AreaOut(**h.area.to_dict()), score=h.score,
                         matched_on=h.matched_on) for h in hits])


@app.get("/areas/{code}", response_model=AreaOut)
def get_area(code: str, svc: Svc) -> AreaOut:
    area = svc.areas.get(code)
    if area is None:
        raise HTTPException(status_code=404, detail=f"unknown area code '{code}'")
    return AreaOut(**area.to_dict())

@app.get("/areas/{code}/children", response_model=list[AreaOut])
def area_children(code: str, svc: Svc) -> list[AreaOut]:
    if svc.areas.get(code) is None:
        raise HTTPException(status_code=404, detail=f"unknown area code '{code}'")
    return [AreaOut(**a.to_dict()) for a in svc.areas.children(code)]
# ------------------------------------------------------------------ crops
@app.get("/crops", response_model=list[CropOut])
def list_crops(svc: Svc) -> list[CropOut]:
    out = []
    for crop_id, row in svc.catalogue.iterrows():
        r = _plain(row.to_dict())
        out.append(CropOut(crop_id=str(crop_id),
                           **{k: (None if r.get(k) is None else str(r.get(k)))
                              for k in ("name_en", "name_bn", "initial_ml_model", "status")}))
    return out


# ------------------------------------------------------------------ suitability
@app.post("/suitability", response_model=SuitabilityResponse)
def suitability(req: SuitabilityRequest, svc: Svc) -> SuitabilityResponse:
    area = svc.areas.get(req.area_code)
    if area is None:
        raise HTTPException(status_code=404, detail=f"unknown area code '{req.area_code}'")
    if area.level == "division":
        raise HTTPException(status_code=422,
                            detail="division is too large; use a district or upazila code")
    try:
        features = svc.store.get(req.area_code)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=_key_error_text(e)) from e
    try:
        results = svc.engine.evaluate(features, req.crops, req.land_type, req.irrigation)
    except ValueError as e:      # unknown crop_id or land_type (engine validation)
        raise HTTPException(status_code=422, detail=str(e)) from e

    rows = [_plain(r.to_dict()) for r in results]
    notes = [HISTORICAL_NOTE] + list(features.flags)
    if features.level == "district":
        notes.append(DISTRICT_NOTE)
    notes += svc.notes

    return SuitabilityResponse(
        area=AreaOut(**area.to_dict()),
        inputs={"crops": req.crops, "land_type": req.land_type, "irrigation": req.irrigation},
        data_types={k: str(v) for k, v in features.data_types.items()},
        data_sources={k: str(v) for k, v in features.sources.items()},
        data_notes=notes,
        results=rows,
        farmer_message_bn=suitability_message(area.name_bn, features.level, rows),
        template_version=TEMPLATE_VERSION,
    )


# ------------------------------------------------------------------ land units
@app.post("/land-units/parse", response_model=LandParseResponse)
def parse_land(req: LandParseRequest, svc: Svc) -> LandParseResponse:
    try:
        res = svc.land_units.parse(req.text, req.local_decimals)
    except LandUnitError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"could not read area: {e}") from e

    table = svc.land_units.table
    parts = []
    for value, unit, basis in res.parts:
        status = str(table.loc[unit, "status"]) if unit in table.index else "unknown"
        parts.append(LandPartOut(value=float(value), unit=str(unit), basis=str(basis),
                                 unit_status=status))
    all_verified = bool(parts) and all(p.unit_status == "verified" for p in parts)
    warnings = [] if all_verified else [DRAFT_UNIT_WARNING]
    if res.basis == "farmer_stated":
        warnings.append("Uses the farmer's own local unit size.")
    return LandParseResponse(original_text=res.original_text or req.text,
                             sqm=round(float(res.sqm), 2), basis=res.basis, parts=parts,
                             all_units_verified=all_verified, warnings=warnings)


# ------------------------------------------------------------------ assistant (Phase 7)
from chashibondhu.api.assistant_routes import router as assistant_router  # noqa: E402

app.include_router(assistant_router)

# ------------------------------------------------------------------ photo help (Phase 14)
try:
    from chashibondhu.api.photo_routes import router as photo_router  # noqa: E402
    app.include_router(photo_router)
except RuntimeError as e:          # python-multipart missing -> only photo endpoints disabled
    log.warning("photo endpoints disabled: %s", e)

# ------------------------------------------------------------------ farmer chat page (Phase 9a)
from chashibondhu.api.web_routes import router as web_router  # noqa: E402

app.include_router(web_router)

# ------------------------------------------------------------------ website (Phase 9b)
from chashibondhu.web.app import mount_website  # noqa: E402

mount_website(app)
