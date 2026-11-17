"""API settings (Phase 5).

All paths come from environment variables with safe defaults. No secrets here.

  CHASHIBONDHU_ROOT                    repo root (default: found from this file)
  CHASHIBONDHU_ALLOW_DRAFT_LAND_UNITS  1/0 (default 1). When 1, draft land-unit rows
                                       are used but every answer is labelled
                                       "not verified". When 0, only verified rows.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# src/chashibondhu/api/config.py -> parents[3] is the repo root
REPO_ROOT = Path(__file__).resolve().parents[3]


def _flag(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    root: Path
    allow_draft_land_units: bool

    @property
    def processed_dir(self) -> Path:
        return self.root / "data" / "processed"

    @property
    def reference_dir(self) -> Path:
        return self.root / "data" / "reference"

    @property
    def admin_dir(self) -> Path:
        return self.processed_dir / "admin"

    @property
    def barc_file(self) -> Path:
        return self.processed_dir / "barc" / "barc_cropzoning_upazila.csv"

    @property
    def land_units_file(self) -> Path:
        return self.reference_dir / "land_units.csv"


def get_settings() -> Settings:
    root = Path(os.environ.get("CHASHIBONDHU_ROOT", str(REPO_ROOT))).resolve()
    return Settings(
        root=root,
        allow_draft_land_units=_flag("CHASHIBONDHU_ALLOW_DRAFT_LAND_UNITS", True),
    )
