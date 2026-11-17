"""Create data/reference/cropping_systems.csv (never overwrites).

The starting rows are CANDIDATE systems found in peer-reviewed Bangladesh
papers. Only the crop pair and the paper are filled; every agronomic value
(timing, row ratio, land type...) is left empty with status=todo. You read
the paper, fill the values with the page/table number, then mark verified.

Usage:
    python scripts/make_cropping_systems.py            # create if missing
    python scripts/make_cropping_systems.py --force    # overwrite (destroys curation!)
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from chashibondhu.reference.cropping_systems import (  # noqa: E402
    COLUMNS, validate_cropping_systems,
)

REF_DIR = ROOT / "data" / "reference"
OUT = REF_DIR / "cropping_systems.csv"
ENC = "utf-8-sig"
log = logging.getLogger("make_cropping_systems")


def _paper(sid, title, journal, url, notes):
    return {"source_id": sid, "title": title, "publisher": journal,
            "edition_or_version": "", "url": url, "language": "en",
            "source_type": "peer_reviewed", "license_note": "FILL",
            "accessed_on": "", "notes": notes}


NEW_SOURCES = [
    _paper("PAPER_MAIZE_RELAY_TAMAN_SYLHET",
           "Relay maize with T. aman rice under zero tillage (Kushiyara floodplain)",
           "Bangladesh Journal of Agricultural Research (BJAR)",
           "https://banglajol.info/index.php/BJAR/article/view/62943/42899",
           "BARI Sylhet; BARI Hybrid Maize-9 with BRRI dhan56/57. Fill authors/year from PDF."),
    _paper("PAPER_POTATO_MAIZE_RELAY_GAIBANDHA",
           "Relaying of maize with potato under Maize-Fallow-T. Aman cropping pattern in charland",
           "BJAR 46(1): 99-106 (2021), Alam et al.",
           "https://doi.org/10.3329/bjar.v46i1.63320",
           "OFRD BARI; char land, Sundarganj, Gaibandha."),
    _paper("PAPER_LENTIL_RELAY_TAMAN_ISHURDI",
           "Performance of lentil varieties under relay and minimum tillage conditions in T. aman rice",
           "BJAR 40(2): 271-278 (2015), Islam, Uddin and Ali",
           "https://banglajol.info/index.php/BJAR/article/view/24565/16661",
           "RARS BARI Ishurdi, Pabna; BARI Masur-2/3/4."),
    _paper("PAPER_MUSTARD_RELAY_TAMAN_SAU",
           "Suitability of rapeseed-mustard varieties as a relay with T. Aman rice",
           "Bangladesh Journal of Agriculture 50(2): 69-84 (2025), Bhuiya et al.",
           "https://doi.org/10.3329/bjagri.v50i2.86131",
           "SAU farm, Dhaka; variety duration decides suitability."),
    _paper("PAPER_POTATO_MAIZE_INTERCROP_RANGPUR",
           "Improvement of potato based cropping patterns by inclusion of short duration "
           "mungbean and T. aman rice in Monga prone areas of Rangpur",
           "International Journal of Agricultural Research, Innovation and Technology (IJARIT)",
           "https://www.banglajol.info/index.php/IJARIT/article/view/22645",
           "BARI Burirhat, Rangpur; includes potato + maize intercrop treatment."),
]

# system_id, system_type, main, companion, source_id
CANDIDATES = [
    ("aman_rice__maize__relay", "relay", "aman_rice", "maize", "PAPER_MAIZE_RELAY_TAMAN_SYLHET"),
    ("potato__maize__relay", "relay", "potato", "maize", "PAPER_POTATO_MAIZE_RELAY_GAIBANDHA"),
    ("aman_rice__lentil__relay", "relay", "aman_rice", "lentil", "PAPER_LENTIL_RELAY_TAMAN_ISHURDI"),
    ("aman_rice__mustard__relay", "relay", "aman_rice", "mustard", "PAPER_MUSTARD_RELAY_TAMAN_SAU"),
    ("potato__maize__intercrop", "intercrop", "potato", "maize",
     "PAPER_POTATO_MAIZE_INTERCROP_RANGPUR"),
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
        log.info("Added %d paper source(s) to sources.csv", len(add))
    return set(src["source_id"])


def build_table() -> pd.DataFrame:
    rows = []
    for sid, stype, main, comp, src in CANDIDATES:
        row = {c: "" for c in COLUMNS}
        row.update({"system_id": sid, "system_type": stype, "main_crop_id": main,
                    "companion_crop_id": comp, "evidence_level": "field_trial",
                    "source_id": src, "status": "todo",
                    "notes": "candidate from paper; fill values from the PDF"})
        rows.append(row)
    return pd.DataFrame(rows, columns=COLUMNS)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--force", action="store_true", help="overwrite existing file")
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
    cat = pd.read_csv(REF_DIR / "crop_catalogue.csv", dtype=str, keep_default_na=False,
                      encoding=ENC)
    errors = validate_cropping_systems(df, set(cat["crop_id"]), source_ids)
    for e in errors:
        log.error(e)
    log.info("cropping_systems.csv: %d systems, status %s", len(df),
             df["status"].value_counts().to_dict())
    log.info("%s", "VALID" if not errors else f"{len(errors)} error(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
