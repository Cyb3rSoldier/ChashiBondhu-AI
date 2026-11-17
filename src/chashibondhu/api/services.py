"""Loads the data and the engine once and keeps them in memory (Phase 5).

The API only talks to these objects. Tests replace them with small fakes.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from functools import lru_cache

import pandas as pd

from chashibondhu.api.areas import AreaDirectory
from chashibondhu.api.config import Settings, get_settings
from chashibondhu.common.land_units import LandUnits
from chashibondhu.crop_planning.features.area_features import FeatureStore
from chashibondhu.crop_planning.features.barc_zoning import BarcStore
from chashibondhu.crop_planning.rules.engine import Knowledge, SuitabilityEngine

log = logging.getLogger("chashibondhu.api")


class ServiceUnavailable(RuntimeError):
    """Data or models could not be loaded."""


@dataclass
class Services:
    areas: AreaDirectory
    store: object                 # FeatureStore: .get(code) -> AreaFeatures, KeyError if unknown
    engine: object                # SuitabilityEngine: .evaluate(...) -> list[CropResult]
    catalogue: pd.DataFrame       # crop catalogue, index = crop_id
    land_units: object            # LandUnits: .parse(...), .table (index = unit_id)
    allow_draft_land_units: bool
    notes: list[str] = field(default_factory=list)


def build_services(settings: Settings) -> Services:
    required = [settings.admin_dir / "districts.csv", settings.reference_dir,
                settings.land_units_file]
    missing = [p.relative_to(settings.root).as_posix() for p in required if not p.exists()]
    if missing:
        raise ServiceUnavailable(f"missing data: {missing}")

    notes: list[str] = []
    try:
        areas = AreaDirectory.from_dir(settings.admin_dir)
        store = FeatureStore(settings.processed_dir)
        knowledge = Knowledge(settings.reference_dir)
        barc = None
        if settings.barc_file.exists():
            barc = BarcStore(settings.barc_file)
        else:
            notes.append("BARC crop zoning file missing: barc_zoning check disabled")
        engine = SuitabilityEngine(knowledge, barc)
        allowed = ("verified", "draft") if settings.allow_draft_land_units else ("verified",)
        land_units = LandUnits.from_csv(settings.land_units_file, allowed_status=allowed)
    except (OSError, ValueError, KeyError) as e:
        log.exception("service load failed")
        raise ServiceUnavailable(f"could not load data: {e}") from e

    return Services(areas=areas, store=store, engine=engine, catalogue=knowledge.catalogue,
                    land_units=land_units,
                    allow_draft_land_units=settings.allow_draft_land_units, notes=notes)


@lru_cache(maxsize=1)
def load_services() -> Services:
    """Load once per process. Failures are not cached, so a fixed data folder works
    on the next request without restarting."""
    return build_services(get_settings())
