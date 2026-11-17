"""POST /photo/diagnose, GET /photo/crops (Phase 14). Loaded lazily: if the vision key or
the problem list is missing, only these endpoints return 503. Needs python-multipart."""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from chashibondhu.api.config import get_settings

log = logging.getLogger("chashibondhu.api")
router = APIRouter(prefix="/photo", tags=["photo"])


class CandidateOut(BaseModel):
    problem_id: str
    name_bn: str
    likelihood: str          # high | medium | low
    status: str              # verified | draft | built_in


class PhotoResponse(BaseModel):
    crop_id: str
    status: str              # possible | unsure | looks_healthy | retake | not_plant | crop_mismatch
    signs: list[str]
    candidates: list[CandidateOut]
    book: dict | None
    message_bn: str
    notes: list[str]
    model: str
    llm_requests: int
    image: dict


class PhotoCropOut(BaseModel):
    crop_id: str
    name_bn: str
    name_en: str
    n_problems: int


@lru_cache(maxsize=1)
def _load_diagnoser():
    from chashibondhu.assistant.vision.client import VisionClient
    from chashibondhu.assistant.vision.diagnose import PhotoDiagnoser
    from chashibondhu.assistant.vision.problems import ProblemCatalogue
    root = get_settings().root
    catalogue = ProblemCatalogue.load(root / "data" / "reference")
    try:                                  # book answers are optional for photo help
        from chashibondhu.api.assistant_routes import _load_assistant
        assistant = _load_assistant()
    except Exception:                     # noqa: BLE001 - photo help still works without it
        log.exception("photo: book assistant not available")
        assistant = None
    return PhotoDiagnoser(VisionClient.from_env(root), catalogue, assistant)


def get_diagnoser():
    try:
        return _load_diagnoser()
    except Exception as e:
        log.exception("photo diagnoser load failed")
        raise HTTPException(status_code=503,
                            detail=f"photo help not available: {type(e).__name__}: {e}") from e


Diag = Annotated[object, Depends(get_diagnoser)]


@router.get("/crops", response_model=list[PhotoCropOut])
def photo_crops(diag: Diag) -> list[PhotoCropOut]:
    cat = diag.catalogue
    return [PhotoCropOut(crop_id=c.crop_id, name_bn=c.name_bn, name_en=c.name_en,
                         n_problems=len(cat.for_crop(c.crop_id))) for c in cat.crops.values()]


@router.post("/diagnose", response_model=PhotoResponse)
async def diagnose(diag: Diag,
                   crop_id: Annotated[str, Form(min_length=1, max_length=40)],
                   image: Annotated[UploadFile, File()],
                   note: Annotated[str, Form(max_length=200)] = "") -> PhotoResponse:
    from chashibondhu.assistant.llm.gemini import LLMError, RateLimited
    from chashibondhu.assistant.vision.image_prep import MAX_UPLOAD_BYTES, ImageError
    data = await image.read(MAX_UPLOAD_BYTES + 1)
    try:
        result = diag.diagnose(crop_id.strip(), data, note)
    except KeyError as e:
        raise HTTPException(status_code=422, detail=str(e.args[0]) if e.args else "bad crop")
    except ImageError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except RateLimited as e:
        raise HTTPException(status_code=429,
                            detail="এখন অনেক অনুরোধ এসেছে। এক মিনিট পরে আবার চেষ্টা করুন।") from e
    except LLMError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return PhotoResponse(**result)
