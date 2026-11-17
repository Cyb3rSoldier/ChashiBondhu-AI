"""Create the initial Phase 3 reference files in data/reference/.

Safety rule: this script NEVER overwrites an existing file, because files in
data/reference/ are hand-curated. Use --force only on a fresh clone.

Pre-filled values are marked status=draft (names only). Requirement numbers
and calendar dates are left empty (status=todo) and must be filled from the
source documents, with page numbers, then marked verified.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
REF_DIR = ROOT / "data" / "reference"
ENCODING = "utf-8-sig"  # keeps Bangla readable if opened in Excel

log = logging.getLogger("make_phase3_templates")

PROVENANCE_COLS = ["source_id", "source_locator", "status", "verified_by", "verified_on", "notes"]

SOURCES = [
    {
        "source_id": "BARI_KPH",
        "title": "Krishi Projukti Hatboi (Handbook of Agro-technology)",
        "publisher": "Bangladesh Agricultural Research Institute (BARI), Gazipur",
        "edition_or_version": "FILL: exact edition and year you use",
        "url": "",
        "language": "bn",
        "source_type": "institutional_handbook",
        "license_note": "FILL",
        "accessed_on": "",
        "notes": "Several editions exist; values may differ between editions.",
    },
    {
        "source_id": "BRRI_ADHUNIK",
        "title": "Adhunik Dhaner Chash (Modern Rice Cultivation)",
        "publisher": "Bangladesh Rice Research Institute (BRRI), Gazipur",
        "edition_or_version": "FILL: exact edition and year you use",
        "url": "",
        "language": "bn",
        "source_type": "institutional_handbook",
        "license_note": "FILL",
        "accessed_on": "",
        "notes": "Primary source for Aman and Boro rice.",
    },
    {
        "source_id": "FAO_ECOCROP",
        "title": "ECOCROP crop environmental requirements database",
        "publisher": "FAO (hosted on GAEZ platform)",
        "edition_or_version": "GAEZ-hosted version",
        "url": "https://gaez.fao.org/pages/ecocrop-search",
        "language": "en",
        "source_type": "global_database",
        "license_note": "FILL: check FAO terms",
        "accessed_on": "",
        "notes": "Species-level global ranges. Use only for absolute limits, not BD optimum.",
    },
    {
        "source_id": "BBS_AGRI_YEARBOOK",
        "title": "Yearbook of Agricultural Statistics",
        "publisher": "Bangladesh Bureau of Statistics (BBS)",
        "edition_or_version": "FILL: year",
        "url": "",
        "language": "en",
        "source_type": "official_statistics",
        "license_note": "FILL",
        "accessed_on": "",
        "notes": "Use for official season definitions and later crop labels (Phase 6).",
    },
]

# (crop_id, name_en, name_bn, scientific_name, crop_group, season_systems,
#  aliases_bn, aliases_latin, initial_ml_model, source_id)
CATALOGUE = [
    ("aman_rice", "Aman Rice", "আমন ধান", "Oryza sativa", "cereal", "kharif2",
     "আমন", "aman|aman dhan", "true", "BRRI_ADHUNIK"),
    ("boro_rice", "Boro Rice", "বোরো ধান", "Oryza sativa", "cereal", "rabi",
     "বোরো", "boro|boro dhan", "false", "BRRI_ADHUNIK"),
    ("maize", "Maize", "ভুট্টা", "Zea mays", "cereal", "rabi|kharif1",
     "ভূট্টা", "bhutta|vutta|corn", "true", "BARI_KPH"),
    ("potato", "Potato", "আলু", "Solanum tuberosum", "tuber", "rabi",
     "গোল আলু", "alu|aloo", "true", "BARI_KPH"),
    ("tomato", "Tomato", "টমেটো", "Solanum lycopersicum", "vegetable", "rabi|kharif1",
     "টমাটো", "tometo|tamato", "true", "BARI_KPH"),
    ("mustard", "Mustard", "সরিষা", "Brassica spp. (rapa/juncea/napus; varies by variety)",
     "oilseed", "rabi", "সরষে|সর্ষে", "sorisha|shorisha|sorshe", "true", "BARI_KPH"),
    ("mung_bean", "Mung Bean", "মুগ ডাল", "Vigna radiata", "pulse", "kharif1|rabi",
     "মুগ|মুগডাল", "mug|mug dal|moong", "false", "BARI_KPH"),
    ("lentil", "Lentil", "মসুর ডাল", "Lens culinaris", "pulse", "rabi",
     "মসুর|মশুর", "mosur|masur|moshur", "false", "BARI_KPH"),
    ("onion", "Onion", "পেঁয়াজ", "Allium cepa", "spice", "rabi|kharif1",
     "পিঁয়াজ|পিয়াজ", "peyaj|piyaj|peyaz", "false", "BARI_KPH"),
    ("watermelon", "Watermelon", "তরমুজ", "Citrullus lanatus", "fruit_vegetable", "kharif1",
     "তরমুজ", "tormuj|tarmuj", "false", "BARI_KPH"),
]

SEASONS = [
    ("rabi", "Rabi", "রবি"),
    ("kharif1", "Kharif-1", "খরিফ-১"),
    ("kharif2", "Kharif-2", "খরিফ-২"),
]

# Parameters to extract for the first 5 crops (Phase 4 needs these).
REQUIREMENT_PARAMS = [
    ("air_temp_c", "degC", "BARI_KPH"),
    ("soil_ph", "pH", "BARI_KPH"),
    ("season_rain_mm", "mm", "BARI_KPH"),
    ("crop_duration_days", "days", "BARI_KPH"),
    ("water_regime", "category", "BARI_KPH"),
    ("land_type", "category", "BARI_KPH"),
    ("soil_texture", "category", "BARI_KPH"),
]
INITIAL_CROPS = ["maize", "potato", "tomato", "mustard", "aman_rice"]
CALENDAR_ACTIVITIES = {
    "maize": ["sowing", "harvest"],
    "potato": ["sowing", "harvest"],
    "tomato": ["sowing", "transplanting", "harvest"],
    "mustard": ["sowing", "harvest"],
    "aman_rice": ["seedbed_sowing", "transplanting", "harvest"],
}


def _empty_provenance(source_id: str, status: str) -> dict:
    return {"source_id": source_id, "source_locator": "", "status": status,
            "verified_by": "", "verified_on": "", "notes": ""}


def build_frames() -> dict[str, pd.DataFrame]:
    sources = pd.DataFrame(SOURCES)

    cat_rows = []
    for (cid, en, bn, sci, grp, seasons, al_bn, al_lat, ml, src) in CATALOGUE:
        row = {"crop_id": cid, "name_en": en, "name_bn": bn, "scientific_name": sci,
               "crop_group": grp, "season_systems": seasons, "aliases_bn": al_bn,
               "aliases_latin": al_lat, "initial_ml_model": ml}
        row.update(_empty_provenance(src, "draft"))
        cat_rows.append(row)
    catalogue = pd.DataFrame(cat_rows)

    season_rows = []
    for sid, en, bn in SEASONS:
        row = {"season_id": sid, "name_en": en, "name_bn": bn, "start_month": "",
               "start_day": "", "end_month": "", "end_day": ""}
        row.update(_empty_provenance("BBS_AGRI_YEARBOOK", "draft"))
        row["notes"] = "Fill dates from the official definition, then verify."
        season_rows.append(row)
    seasons = pd.DataFrame(season_rows)

    req_rows = []
    for crop in INITIAL_CROPS:
        for param, unit, src in REQUIREMENT_PARAMS:
            if crop == "aman_rice":
                src = "BRRI_ADHUNIK"
            row = {"crop_id": crop, "variety_scope": "general", "parameter": param,
                   "unit": unit, "min": "", "opt_min": "", "opt_max": "", "max": "",
                   "value_text": ""}
            row.update(_empty_provenance(src, "todo"))
            req_rows.append(row)
    requirements = pd.DataFrame(req_rows)

    cal_rows = []
    for crop, activities in CALENDAR_ACTIVITIES.items():
        src = "BRRI_ADHUNIK" if crop == "aman_rice" else "BARI_KPH"
        for act in activities:
            row = {"crop_id": crop, "variety_scope": "general", "activity": act,
                   "start_month": "", "start_day": "", "end_month": "", "end_day": "",
                   "region_scope": "national"}
            row.update(_empty_provenance(src, "todo"))
            cal_rows.append(row)
    calendar = pd.DataFrame(cal_rows)

    return {
        "sources.csv": sources,
        "crop_catalogue.csv": catalogue,
        "seasons.csv": seasons,
        "crop_requirements.csv": requirements,
        "crop_calendar.csv": calendar,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true",
                        help="Overwrite existing files (destroys curated work!)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    REF_DIR.mkdir(parents=True, exist_ok=True)
    for name, df in build_frames().items():
        path = REF_DIR / name
        if path.exists() and not args.force:
            log.info("Kept existing %s (not overwritten)", name)
            continue
        df.to_csv(path, index=False, encoding=ENCODING)
        log.info("Wrote %s (%d rows)", name, len(df))
    return 0


if __name__ == "__main__":
    sys.exit(main())
