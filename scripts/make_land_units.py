"""Create data/reference/land_units.csv (never overwrites) and register sources.

Each unit is defined as `factor x base_unit` (base_unit = sqft, sqm or another
unit_id), so the real definition is stored (e.g. bigha = 20 katha), and the
code derives square metres. Rows start as draft; you verify them against the
cited page and set status=verified.

Usage:
    python scripts/make_land_units.py            # create if missing
    python scripts/make_land_units.py --force    # overwrite (destroys curation!)
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from chashibondhu.common.land_units import validate_land_units  # noqa: E402

REF_DIR = ROOT / "data" / "reference"
OUT = REF_DIR / "land_units.csv"
ENC = "utf-8-sig"
log = logging.getLogger("make_land_units")

NEW_SOURCES = [
    {"source_id": "MINLAND_UNITS", "title": "Land Measurement Unit",
     "publisher": "Ministry of Land, Government of Bangladesh",
     "edition_or_version": "web page",
     "url": "https://minland.gov.bd/site/page/4e44d7ef-2c36-4483-aa4e-77b294de729c/Land-Measurement-Unit",
     "language": "bn|en", "source_type": "government_portal", "license_note": "FILL",
     "accessed_on": "", "notes": "Open the page and confirm katha/bigha/decimal values."},
    {"source_id": "NIST_SP811", "title": "Guide for the Use of the International System of Units (SP 811)",
     "publisher": "NIST (USA)", "edition_or_version": "FILL", "url": "",
     "language": "en", "source_type": "institutional_handbook", "license_note": "public domain (US gov)",
     "accessed_on": "", "notes": "Exact definitions of acre and hectare."},
]

# unit_id, name_en, name_bn, aliases_latin, aliases_bn, factor, base_unit, scope,
# source_id, status, notes
UNITS = [
    ("sq_ft", "square foot", "বর্গফুট", "sqft|sq ft|square feet|ft2|sft", "বর্গ ফুট",
     "1", "sqft", "national", "NIST_SP811", "draft", "root unit"),
    ("sq_m", "square metre", "বর্গমিটার", "sqm|sq m|square meter|square meters|m2", "বর্গ মিটার",
     "1", "sqm", "national", "NIST_SP811", "draft", "root unit (storage unit)"),
    ("acre", "acre", "একর", "acre|acres|akor", "একর", "43560", "sqft", "national",
     "NIST_SP811", "draft", "1 acre = 43,560 sq ft"),
    ("hectare", "hectare", "হেক্টর", "ha|hectares", "হেক্টর", "10000", "sqm", "national",
     "NIST_SP811", "draft", "1 ha = 10,000 m2"),
    ("decimal", "decimal", "শতাংশ", "decimals|dec|shotok|shatak|shotangsho|shotangsha|sotok",
     "শতক|শতাংশ", "0.01", "acre", "national", "MINLAND_UNITS", "draft", "1/100 acre"),
    ("katha", "katha", "কাঠা", "kata|kotha|kattha|cottah", "কাঠা", "720", "sqft", "national",
     "MINLAND_UNITS", "draft", "standard katha"),
    ("bigha", "bigha", "বিঘা", "biga|bigah|bighas", "বিগা", "20", "katha", "national",
     "MINLAND_UNITS", "draft",
     "standard bigha; size differs in some regions -> ask farmer, store farmer_stated"),
    ("kani", "kani", "কানি", "kani|kaani", "কানি", "", "", "regional", "MINLAND_UNITS", "todo",
     "size differs by region; always ask the farmer how many decimals"),
]


def ensure_sources() -> set[str]:
    path = REF_DIR / "sources.csv"
    if not path.exists():
        raise FileNotFoundError(f"{path} missing - run scripts/make_phase3_templates.py")
    src = pd.read_csv(path, dtype=str, keep_default_na=False, encoding=ENC)
    add = [s for s in NEW_SOURCES if s["source_id"] not in set(src["source_id"])]
    if add:
        src = pd.concat([src, pd.DataFrame(add)], ignore_index=True).fillna("")
        src.to_csv(path, index=False, encoding=ENC)
        log.info("Added source(s) to sources.csv: %s", [s["source_id"] for s in add])
    return set(src["source_id"])


def build_table() -> pd.DataFrame:
    rows = []
    for (uid, en, bn, al, abn, factor, base, scope, src, status, notes) in UNITS:
        rows.append({"unit_id": uid, "name_en": en, "name_bn": bn, "aliases_latin": al,
                     "aliases_bn": abn, "factor": factor, "base_unit": base, "scope": scope,
                     "source_id": src, "source_locator": "", "status": status,
                     "verified_by": "", "verified_on": "", "notes": notes})
    return pd.DataFrame(rows)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--force", action="store_true", help="overwrite existing land_units.csv")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        source_ids = ensure_sources()
    except FileNotFoundError as exc:
        log.error("%s", exc)
        return 1
    if OUT.exists() and not args.force:
        log.info("Kept existing %s (not overwritten)", OUT.name)
    else:
        build_table().to_csv(OUT, index=False, encoding=ENC)
        log.info("Wrote %s", OUT.name)

    df = pd.read_csv(OUT, dtype=str, keep_default_na=False, encoding=ENC)
    errors = validate_land_units(df, source_ids)
    for e in errors:
        log.error(e)
    log.info("land_units.csv status: %s", df["status"].value_counts().to_dict())
    log.info("%s", "VALID" if not errors else f"{len(errors)} error(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
