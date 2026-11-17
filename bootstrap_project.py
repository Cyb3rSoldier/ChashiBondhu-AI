"""
bootstrap_project.py
--------------------
Creates the complete ChashiBondhu AI project structure and all starter files
in one run.

Usage (from the repo root, with your venv active):
    python bootstrap_project.py              # create anything missing, never overwrite
    python bootstrap_project.py --overwrite  # also replace existing starter files

Safe to run more than once. Without --overwrite it never changes existing files.
"""

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# =====================================================================
# 1. FOLDERS
# =====================================================================

# Folders that get a .gitkeep (so Git tracks them even when empty)
KEEP_DIRS = [
    "configs",
    "data/raw/admin_boundaries",
    "data/raw/climate",
    "data/raw/soil",
    "data/raw/crop_stats",
    "data/raw/market",
    "data/raw/documents",
    "data/raw/images",
    "data/interim",
    "data/processed",
    "data/reference",
    "docs/architecture",
    "docs/decisions",
    "docs/modules",
    "models",
    "notebooks",
    "scripts",
]

# Python packages (get an __init__.py)
PACKAGE_DIRS = [
    "src/chashibondhu",
    "src/chashibondhu/common",
    # Data pipelines
    "src/chashibondhu/data_pipeline",
    "src/chashibondhu/data_pipeline/admin",
    "src/chashibondhu/data_pipeline/climate",
    "src/chashibondhu/data_pipeline/soil",
    "src/chashibondhu/data_pipeline/crop_stats",
    "src/chashibondhu/data_pipeline/market",
    # Module 1: Crop Planning (rules + ML + SHAP)
    "src/chashibondhu/crop_planning",
    "src/chashibondhu/crop_planning/rules",
    "src/chashibondhu/crop_planning/features",
    "src/chashibondhu/crop_planning/models",
    "src/chashibondhu/crop_planning/explain",
    # Module 2: Weather Intelligence
    "src/chashibondhu/weather",
    "src/chashibondhu/weather/climatology",
    "src/chashibondhu/weather/alerts",
    # Module 3: Bangla Assistant (LLM + RAG + LangGraph)
    "src/chashibondhu/assistant",
    "src/chashibondhu/assistant/ingestion",
    "src/chashibondhu/assistant/retrieval",
    "src/chashibondhu/assistant/llm",
    "src/chashibondhu/assistant/graph",
    "src/chashibondhu/assistant/speech",
    "src/chashibondhu/assistant/evaluation",
    # Module 4: Marketplace
    "src/chashibondhu/marketplace",
    "src/chashibondhu/marketplace/connectors",
    "src/chashibondhu/marketplace/matching",
    "src/chashibondhu/marketplace/demand",
    "src/chashibondhu/marketplace/prices",
    # Module 5: Surplus
    "src/chashibondhu/surplus",
    "src/chashibondhu/surplus/detection",
    "src/chashibondhu/surplus/matching",
    "src/chashibondhu/surplus/notifications",
    # API
    "src/chashibondhu/api",
    # Tests (mirror src)
    "tests",
    "tests/data_pipeline",
    "tests/crop_planning",
    "tests/weather",
    "tests/assistant",
    "tests/marketplace",
    "tests/surplus",
]

# =====================================================================
# 2. FILE CONTENTS
# =====================================================================

GITIGNORE = """\
# ---------- Secrets (NEVER commit) ----------
.env
.env.*
!.env.example
*.pem
*.key
credentials*.json
secrets/

# ---------- Data (large / licensed / private) ----------
# Tracked by source links in docs/dataset_register.csv (later with DVC), not Git.
data/raw/*
data/interim/*
data/processed/*
!data/**/.gitkeep
# NOTE: data/reference/ IS tracked (small curated tables with sources)

# ---------- Geospatial and model files ----------
*.shp
*.shx
*.dbf
*.prj
*.cpg
*.gpkg
*.tif
*.tiff
*.nc
*.grib
*.zip
*.pkl
*.joblib
*.pt
*.pth
*.onnx
models/*
!models/.gitkeep

# ---------- Python ----------
__pycache__/
*.py[cod]
.venv/
venv/
env/
*.egg-info/
.pytest_cache/
.ipynb_checkpoints/

# ---------- Experiment tracking ----------
mlruns/
mlartifacts/

# ---------- OS / editors ----------
.DS_Store
Thumbs.db
.vscode/
.idea/
"""

README = """\
# ChashiBondhu AI (চাষীবন্ধু)

A climate-aware, demand-driven agricultural intelligence and decision-support
platform for farmers across Bangladesh (8 divisions, 64 districts).

## Modules

| # | Module | Main technology | Status |
|---|--------|-----------------|--------|
| 0 | Data foundation (geographic + crop reference) | Data pipelines, GeoPandas | In development |
| 1 | Intelligent Crop Planning Engine | Rules + XGBoost/CatBoost + SHAP | Proposed |
| 2 | Weather-Aware Farming Intelligence | Climate pipelines + rule-based alerts | Proposed |
| 3 | Bangla Agricultural Assistant | LLM + RAG + LangGraph + speech | Proposed |
| 4 | Demand-Linked Marketplace | Matching + time-series forecasting | Proposed |
| 5 | Smart Surplus Management | Matching + rules + notifications | Proposed |

Status levels: Proposed → In development → Implemented → Tested → Deployed → Validated in real-world use.

## Crop catalogue

Aman Rice, Boro Rice, Maize, Potato, Tomato, Mustard, Mung Bean, Lentil, Onion, Watermelon.
First ML implementation: Maize, Potato, Tomato, Mustard, Aman Rice.

## Repository structure

```
configs/           settings
data/raw/          original downloads (not in Git)
data/interim/      partly cleaned data (not in Git)
data/processed/    final clean tables (not in Git)
data/reference/    small curated tables with sources (in Git)
docs/              dataset register, architecture, decisions
scripts/           runnable pipeline entry points
src/chashibondhu/  library code, one package per module
models/            trained models (not in Git)
notebooks/         exploration only
tests/             automated tests
```

## Setup

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate    Mac/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

## Data policy

- Data files are not committed. Every dataset is recorded in
  `docs/dataset_register.csv` with source, link, license, coverage and limitations.
- No fabricated or LLM-generated data is used as ground truth.
- Secrets go in `.env` (never committed). See `.env.example`.
"""

REQUIREMENTS = """\
geopandas>=0.14
pandas>=2.0
pyogrio>=0.7
pytest>=8.0
"""

ENV_EXAMPLE = """\
# Copy this file to .env and fill in real values. Never commit .env.
LLM_API_KEY=
MYSQL_HOST=
MYSQL_USER=
MYSQL_PASSWORD=
MYSQL_DATABASE=
"""

DATASET_REGISTER = (
    "dataset_id,name,publisher,source_url,download_date,license,"
    "collection_period,geographic_coverage,temporal_coverage,spatial_resolution,"
    "n_observations,features_labels,missing_values,known_biases,limitations,"
    "intended_use,status\n"
)

BUILD_ADMIN_REFERENCE = r'''"""
build_admin_reference.py
------------------------
Builds ChashiBondhu AI's master geographic reference tables
(division -> district -> upazila) from the OCHA/HDX COD-AB Bangladesh
administrative boundaries (source: Bangladesh Bureau of Statistics).

Outputs (in --out folder):
  divisions.csv, districts.csv, upazilas.csv   -> tables without geometry
  name_aliases.csv                              -> old/alternate spellings
  admin_boundaries.gpkg                         -> boundaries (EPSG:4326)

Usage:
  python scripts/build_admin_reference.py --adm1 <file> --adm2 <file> --adm3 <file> --inspect
  python scripts/build_admin_reference.py --adm1 <file> --adm2 <file> --adm3 <file>

NOTE: Column names follow the standard COD-AB naming (ADM1_PCODE, ADM1_EN, ...).
Run with --inspect first to confirm they match your downloaded files.
"""

import argparse
import logging
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

log = logging.getLogger("admin_reference")

# Official spelling changes (2018). The HDX file may still use old names.
NAME_UPDATES = {
    "Chittagong": "Chattogram",
    "Barisal": "Barishal",
    "Comilla": "Cumilla",
    "Jessore": "Jashore",
    "Bogra": "Bogura",
}

EXPECTED_DIVISIONS = 8
EXPECTED_DISTRICTS = 64

PROJECTED_CRS = "EPSG:32646"   # UTM 46N, for geometry operations
STORAGE_CRS = "EPSG:4326"      # WGS84, for storage and APIs


def load_layer(path: Path, rename: dict) -> gpd.GeoDataFrame:
    """Load a boundary file, check required columns, and rename them."""
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    gdf = gpd.read_file(path)
    missing = [c for c in rename if c not in gdf.columns]
    if missing:
        raise KeyError(f"{path.name} is missing columns {missing}. "
                       f"Available columns: {list(gdf.columns)}")
    if gdf.crs is None:
        raise ValueError(f"{path.name} has no CRS defined.")
    gdf = gdf[list(rename) + ["geometry"]].rename(columns=rename)
    return gdf.to_crs(STORAGE_CRS)


def apply_name_updates(df, name_col: str, level: str, aliases: list):
    """Replace old spellings with official ones; keep old name as an alias."""
    code_col = name_col.replace("_name", "_code")
    for old, new in NAME_UPDATES.items():
        mask = df[name_col].str.strip().str.lower() == old.lower()
        if mask.any():
            for code in df.loc[mask, code_col]:
                aliases.append({"level": level, "code": code,
                                "alias": old, "official_name": new})
            df.loc[mask, name_col] = new
            log.info("Renamed %s '%s' -> '%s'", level, old, new)
    df[name_col] = df[name_col].str.strip()
    return df


def add_reference_point(gdf):
    """Add a point inside each polygon (for later API queries such as NASA POWER).
    This is NOT a field location; it only represents the area."""
    pts = gdf.to_crs(PROJECTED_CRS).representative_point().to_crs(STORAGE_CRS)
    gdf["ref_lat"] = pts.y.round(5)
    gdf["ref_lon"] = pts.x.round(5)
    return gdf


def validate(div, dist, upz) -> list:
    """Return a list of problems. Empty list = all checks passed."""
    problems = []
    if len(div) != EXPECTED_DIVISIONS:
        problems.append(f"Expected {EXPECTED_DIVISIONS} divisions, got {len(div)}")
    if len(dist) != EXPECTED_DISTRICTS:
        problems.append(f"Expected {EXPECTED_DISTRICTS} districts, got {len(dist)}")
    for name, df, code in [("division", div, "division_code"),
                           ("district", dist, "district_code"),
                           ("upazila", upz, "upazila_code")]:
        if df[code].isna().any():
            problems.append(f"{name}: missing codes")
        if df[code].duplicated().any():
            dups = df.loc[df[code].duplicated(), code].tolist()
            problems.append(f"{name}: duplicate codes {dups[:5]}")
        invalid = (~df.geometry.is_valid).sum()
        if df.geometry.isna().any() or invalid:
            problems.append(f"{name}: missing or invalid geometries ({invalid} invalid)")
    orphan_d = set(dist["division_code"]) - set(div["division_code"])
    if orphan_d:
        problems.append(f"Districts with unknown division codes: {orphan_d}")
    orphan_u = set(upz["district_code"]) - set(dist["district_code"])
    if orphan_u:
        problems.append(f"Upazilas with unknown district codes: {orphan_u}")
    missing_u = set(dist["district_code"]) - set(upz["district_code"])
    if missing_u:
        problems.append(f"Districts with no upazilas: {missing_u}")
    return problems


def inspect(paths):
    for p in paths:
        gdf = gpd.read_file(p)
        print(f"\n{p.name}: {len(gdf)} rows, CRS={gdf.crs}")
        print("Columns:", list(gdf.columns))
        print(gdf.drop(columns="geometry").head(3).to_string())


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--adm1", type=Path, required=True)
    parser.add_argument("--adm2", type=Path, required=True)
    parser.add_argument("--adm3", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path("data/processed/admin"))
    parser.add_argument("--inspect", action="store_true",
                        help="Only print columns and sample rows, then exit")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if args.inspect:
        inspect([args.adm1, args.adm2, args.adm3])
        return 0

    div = load_layer(args.adm1, {"ADM1_PCODE": "division_code",
                                 "ADM1_EN": "division_name"})
    dist = load_layer(args.adm2, {"ADM2_PCODE": "district_code",
                                  "ADM2_EN": "district_name",
                                  "ADM1_PCODE": "division_code"})
    upz = load_layer(args.adm3, {"ADM3_PCODE": "upazila_code",
                                 "ADM3_EN": "upazila_name",
                                 "ADM2_PCODE": "district_code"})

    aliases = []
    div = apply_name_updates(div, "division_name", "division", aliases)
    dist = apply_name_updates(dist, "district_name", "district", aliases)
    upz = apply_name_updates(upz, "upazila_name", "upazila", aliases)

    problems = validate(div, dist, upz)
    if problems:
        log.error("Validation failed:")
        for p in problems:
            log.error("  - %s", p)
        return 1
    log.info("All checks passed: %d divisions, %d districts, %d upazilas",
             len(div), len(dist), len(upz))

    div, dist, upz = (add_reference_point(g) for g in (div, dist, upz))

    args.out.mkdir(parents=True, exist_ok=True)
    gpkg = args.out / "admin_boundaries.gpkg"
    for layer, gdf in [("divisions", div), ("districts", dist), ("upazilas", upz)]:
        gdf.drop(columns="geometry").to_csv(args.out / f"{layer}.csv", index=False)
        gdf.to_file(gpkg, layer=layer, driver="GPKG")
    pd.DataFrame(aliases, columns=["level", "code", "alias", "official_name"]) \
        .to_csv(args.out / "name_aliases.csv", index=False)

    log.info("Saved outputs to %s", args.out.resolve())
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''

FILES = {
    ".gitignore": GITIGNORE,
    "README.md": README,
    "requirements.txt": REQUIREMENTS,
    ".env.example": ENV_EXAMPLE,
    "docs/dataset_register.csv": DATASET_REGISTER,
    "scripts/build_admin_reference.py": BUILD_ADMIN_REFERENCE,
}

# =====================================================================
# 3. BUILD
# =====================================================================


def touch(path: Path) -> bool:
    if path.exists():
        return False
    path.touch()
    return True


def main():
    parser = argparse.ArgumentParser(description="Create ChashiBondhu project structure.")
    parser.add_argument("--overwrite", action="store_true",
                        help="Replace existing starter files with the versions in this script")
    args = parser.parse_args()

    created_dirs = created_files = skipped = 0

    for d in KEEP_DIRS:
        p = ROOT / d
        if not p.exists():
            created_dirs += 1
        p.mkdir(parents=True, exist_ok=True)
        touch(p / ".gitkeep")

    for d in PACKAGE_DIRS:
        p = ROOT / d
        if not p.exists():
            created_dirs += 1
        p.mkdir(parents=True, exist_ok=True)
        touch(p / "__init__.py")

    for rel, content in FILES.items():
        p = ROOT / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.exists() and not args.overwrite:
            print(f"  skip (exists): {rel}")
            skipped += 1
            continue
        p.write_text(content, encoding="utf-8", newline="\n")
        print(f"  wrote: {rel}")
        created_files += 1

    print(f"\nDone. {created_dirs} new folders, {created_files} files written, "
          f"{skipped} existing files kept.")
    if skipped and not args.overwrite:
        print("Run with --overwrite if you want to replace the kept files.")


if __name__ == "__main__":
    main()
