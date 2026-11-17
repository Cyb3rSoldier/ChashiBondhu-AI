"""Validate every curated file in data/reference/ and show curation progress.

Covers: sources, crop_catalogue, seasons, crop_requirements, crop_calendar
(Phase 3a), land_units (3e) and cropping_systems (3c).
(admin_name_overrides.csv is checked by scripts/build_bn_admin_names.py.)
Exit code 0 = valid, 1 = errors found. Run after every manual edit.

Usage:
    python scripts/validate_reference.py
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from chashibondhu.common.land_units import validate_land_units  # noqa: E402
from chashibondhu.reference.cropping_systems import validate_cropping_systems  # noqa: E402
from chashibondhu.reference.validate import read_reference, validate_all  # noqa: E402

REF_DIR = ROOT / "data" / "reference"
log = logging.getLogger("validate_reference")


def main() -> int:
    argparse.ArgumentParser(description=__doc__,
                            formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    results = validate_all(REF_DIR)

    sources_path = REF_DIR / "sources.csv"
    catalogue_path = REF_DIR / "crop_catalogue.csv"
    if sources_path.exists() and catalogue_path.exists():
        source_ids = set(read_reference(sources_path)["source_id"])
        crop_ids = set(read_reference(catalogue_path)["crop_id"])
        extra = {
            "land_units.csv": lambda df: validate_land_units(df, source_ids),
            "cropping_systems.csv": lambda df: validate_cropping_systems(df, crop_ids,
                                                                         source_ids),
        }
        for name, check in extra.items():
            path = REF_DIR / name
            if path.exists():
                results[name] = check(read_reference(path))
            else:
                log.warning("%s not found (skipped)", name)

    n_errors = 0
    for name, errors in results.items():
        path = REF_DIR / name
        if path.exists():
            df = read_reference(path)
            if "status" in df.columns:
                log.info("%-24s %s", name, df["status"].value_counts().to_dict())
        for err in errors:
            log.error(err)
        n_errors += len(errors)
    if n_errors:
        log.error("%d error(s) found", n_errors)
        return 1
    log.info("All reference files valid. Only 'verified' rows reach the engine.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
