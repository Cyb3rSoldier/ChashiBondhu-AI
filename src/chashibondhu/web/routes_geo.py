"""GET /app/area-point/{code} -> reference point + name of a district/upazila (public data; no personal info)."""
from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException

from chashibondhu.web import geo_points

router = APIRouter(include_in_schema=False)


@router.get("/app/area-point/{code}")
def area_point(code: str):
    if not re.fullmatch(r"BD\d{4}(\d{4})?", code):
        raise HTTPException(status_code=404)
    p = geo_points.point(code)
    if not p:
        raise HTTPException(status_code=404)
    return p
