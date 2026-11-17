"""
build_admin_reference.py
------------------------
Builds ChashiBondhu AI's master geographic reference tables
(division -> district -> upazila) from the OCHA/HDX COD-AB Bangladesh
administrative boundaries (source: Bangladesh Bureau of Statistics).

Input files used: bgd_admin1.shp, bgd_admin2.shp, bgd_admin3.shp
(HDX COD-AB version v03, valid_on 2023-05-21; lowercase column names
such as adm1_pcode, adm1_name).

Outputs (in --out folder):
  divisions.csv, districts.csv, upazilas.csv   -> tables without geometry
  name_aliases.csv                              -> old/alternate spellings
  admin_boundaries.gpkg                         -> boundaries (EPSG:4326)

Usage:
  python scripts/build_admin_reference.py --adm1 <file> --adm2 <file> --adm3 <file> --inspect
  python scripts/build_admin_reference.py --adm1 <file> --adm2 <file> --adm3 <file>
"""

import argparse
import logging
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

log = logging.getLogger("admin_reference")

# Official spelling changes (2018). v03 already uses the new names, but older
# files or other datasets may not, so the check stays as a safety net.
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

# Column mapping: source column (HDX v03) -> our standard column name
DIVISION_COLUMNS = {
    "adm1_pcode": "division_code",
    "adm1_name": "division_name",
}
DISTRICT_COLUMNS = {
    "adm2_pcode": "district_code",
    "adm2_name": "district_name",
    "adm1_pcode": "division_code",
}
UPAZILA_COLUMNS = {
    "adm3_pcode": "upazila_code",
    "adm3_name": "upazila_name",
    "adm2_pcode": "district_code",
}


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

    div = load_layer(args.adm1, DIVISION_COLUMNS)
    dist = load_layer(args.adm2, DISTRICT_COLUMNS)
    upz = load_layer(args.adm3, UPAZILA_COLUMNS)

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