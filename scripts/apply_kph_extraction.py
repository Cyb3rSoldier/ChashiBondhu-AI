"""Load the BARI Krishi Projukti Hatboi (10th edition) extraction as DRAFT rows.

The extraction file lists each fact with its printed page and a short quote.
This script copies them into crop_requirements.csv and crop_calendar.csv as
status=draft. It never overwrites a verified row. Then review them with
scripts/review_reference.py.

Usage:
    python scripts/apply_kph_extraction.py --dry-run     # show what would change
    python scripts/apply_kph_extraction.py
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from chashibondhu.reference.curation import (  # noqa: E402
    apply_extraction, load_extraction, update_source,
)
from chashibondhu.reference.validate import validate_all  # noqa: E402

REF_DIR = ROOT / "data" / "reference"
DEFAULT = REF_DIR / "extractions" / "kph10_extraction.csv"
EDITION = "KPH 10th ed."
SOURCE_FIELDS = {
    "edition_or_version": "10th edition, Agrahayan 1431 / December 2024",
    "notes": "Correct citation: Akhond et al., 2025, Edited KRISHI PROJUKTI HATBOI "
             "(Handbook on Agro-Technology), 10th edition, BARI, Gazipur. "
             "Printed page = PDF page - 25. Text uses Bijoy (SutonnyMJ) encoding.",
    "url": "http://www.bari.gov.bd/site/page/841c811d-14ad-4796-97a4-41cd602d3cfa/কৃষি-প্রযুক্তি-হাতবই",
}
log = logging.getLogger("apply_kph_extraction")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--extraction", type=Path, default=DEFAULT)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        ext = load_extraction(args.extraction)
        counts = apply_extraction(REF_DIR, ext, "BARI_KPH", EDITION, dry_run=args.dry_run)
        if not args.dry_run:
            update_source(REF_DIR, "BARI_KPH", SOURCE_FIELDS)
    except (FileNotFoundError, ValueError) as exc:
        log.error("%s", exc)
        return 1
    log.info("extraction rows: %d (crops: %s)", len(ext),
             ", ".join(sorted(ext["crop_id"].unique())))
    for name, c in counts.items():
        log.info("%-22s %s", name, c)
    if args.dry_run:
        log.info("dry run: nothing written")
        return 0
    errors = [e for errs in validate_all(REF_DIR).values() for e in errs]
    for e in errors:
        log.error(e)
    log.info("%s", "VALID - now run scripts/review_reference.py" if not errors
             else f"{len(errors)} validation error(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
