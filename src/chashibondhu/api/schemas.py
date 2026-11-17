"""Request / response models (Phase 5). Inputs are strict: unknown fields are rejected."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Must equal engine.LAND_TYPES (a test checks this).
LandType = Literal["highland", "medium_highland", "medium_lowland", "lowland", "very_lowland"]
Level = Literal["division", "district", "upazila"]

AREA_CODE_PATTERN = r"^BD\d{2,10}$"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ------------------------------------------------------------------ areas
class AreaOut(BaseModel):
    code: str
    level: Level
    name_en: str
    name_bn: str | None = None
    name_bn_status: str | None = None
    name_bn_source: str | None = None
    parent_code: str | None = None
    district_code: str | None = None
    division_code: str | None = None


class AreaHit(BaseModel):
    area: AreaOut
    score: float
    matched_on: str


class AreaSearchResponse(BaseModel):
    query: str
    count: int
    results: list[AreaHit]


# ------------------------------------------------------------------ crops
class CropOut(BaseModel):
    crop_id: str
    name_en: str | None = None
    name_bn: str | None = None
    initial_ml_model: str | None = None
    status: str | None = None


# ------------------------------------------------------------------ suitability
class SuitabilityRequest(_Strict):
    area_code: str = Field(pattern=AREA_CODE_PATTERN, examples=["BD1004"])
    crops: list[str] | None = Field(
        default=None, min_length=1, max_length=10,
        description="crop_id values from GET /crops. Omit for the initial 5 crops.")
    land_type: LandType | None = Field(
        default=None, description="BARC land type. Leave empty if not known.")
    irrigation: bool | None = Field(default=None, description="null = not asked yet")

    @field_validator("crops")
    @classmethod
    def _clean_crops(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        out: list[str] = []
        for c in v:
            c = c.strip()
            if not c or len(c) > 50:
                raise ValueError("each crop_id must be 1-50 characters")
            if c not in out:
                out.append(c)
        return out


class CheckOut(BaseModel):
    check: str
    status: str
    message: str | None = ""
    value: str | None = ""
    requirement: str | None = ""
    source: str | None = ""
    data_type: str | None = ""
    overridden_status: str | None = ""   # original verdict when demoted to "warning"


class CropResultOut(BaseModel):
    crop_id: str
    name_en: str | None = None
    name_bn: str | None = None
    status: str
    checks: list[CheckOut]
    growing_months: list[int]
    missing_inputs: list[str]
    evidence_coverage: float


class SuitabilityResponse(BaseModel):
    area: AreaOut
    inputs: dict
    data_types: dict[str, str]
    data_sources: dict[str, str]
    data_notes: list[str]
    results: list[CropResultOut]
    farmer_message_bn: str
    template_version: str


# ------------------------------------------------------------------ land units
class LandParseRequest(_Strict):
    text: str = Field(min_length=1, max_length=100, examples=["২ বিঘা ৫ কাঠা"])
    local_decimals: dict[str, float] | None = Field(
        default=None, examples=[{"bigha": 33}],
        description="Farmer-stated local unit sizes in decimals (shotok), e.g. bigha.")

    @field_validator("local_decimals")
    @classmethod
    def _check_local(cls, v: dict[str, float] | None) -> dict[str, float] | None:
        if v is None:
            return None
        if len(v) > 5:
            raise ValueError("at most 5 local units")
        for k, x in v.items():
            if not k.strip() or not (0 < x <= 1000):
                raise ValueError(f"local unit '{k}': decimals must be > 0 and <= 1000")
        return {k.strip(): x for k, x in v.items()}


class LandPartOut(BaseModel):
    value: float
    unit: str
    basis: str
    unit_status: str


class LandParseResponse(BaseModel):
    original_text: str
    sqm: float
    basis: str
    parts: list[LandPartOut]
    all_units_verified: bool
    warnings: list[str]
