"""
build_chirps_rainfall.py
------------------------
Phase 2b (ChashiBondhu AI): area-averaged monthly rainfall from CHIRPS v3.0
for every district and upazila.

Method: each CHIRPS cell (~5 km) whose centre falls inside an area counts
toward that area's mean. Very small areas with no cell centre inside fall back
to the single cell containing their reference point (method = "point").

Outputs in data/processed/climate/:
  chirps_district_monthly.csv           district x year x month rainfall (mm)
  chirps_upazila_monthly.csv            upazila  x year x month rainfall (mm)
  chirps_district_climatology.csv       district x calendar month, baseline stats
  chirps_upazila_climatology.csv        upazila  x calendar month, baseline stats
  rainfall_source_comparison.csv        CHIRPS vs NASA POWER annual means per district

All values are HISTORICAL estimates (satellite + gauge blend), not forecasts.

Usage:
  python scripts/build_chirps_rainfall.py
  python scripts/build_chirps_rainfall.py --baseline-start 1991 --baseline-end 2020
"""

import argparse
import logging
import re
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import rasterize
from rasterio.transform import rowcol

log = logging.getLogger("build_chirps_rainfall")

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data/raw/climate/chirps_v3/monthly"
ADMIN_GPKG = ROOT / "data/processed/admin/admin_boundaries.gpkg"
OUT_DIR = ROOT / "data/processed/climate"
NASA_CLIM = OUT_DIR / "district_climatology_monthly.csv"

FILE_RE = re.compile(r"chirps-v3\.0\.(\d{4})\.(\d{2})_bgd\.tif$")
SOURCE_LABEL = "CHIRPS v3.0 monthly (UCSB Climate Hazards Center), ~0.05 deg"
DATA_TYPE = "historical_satellite_gauge_estimate"
MAX_RAIN_MM_MONTH = 3000  # sanity ceiling for a single month


class Zones:
    """Pre-computed zone index for one admin level on the CHIRPS grid."""

    def __init__(self, gdf, code_col, transform, shape):
        self.codes = gdf[code_col].to_numpy()
        self.n = len(gdf)
        g = gdf.to_crs("EPSG:4326")
        shapes = ((geom, i + 1) for i, geom in enumerate(g.geometry))
        self.grid = rasterize(shapes, out_shape=shape, transform=transform,
                              fill=0, dtype="int32").ravel()
        counts = np.bincount(self.grid, minlength=self.n + 1)[1:]
        self.n_cells = counts
        self.method = np.where(counts > 0, "area_mean", "point")
        # fallback cell for areas with no cell centre inside
        self.point_idx = np.full(self.n, -1)
        for i in np.where(counts == 0)[0]:
            r, c = rowcol(transform, gdf["ref_lon"].iloc[i], gdf["ref_lat"].iloc[i])
            if 0 <= r < shape[0] and 0 <= c < shape[1]:
                self.point_idx[i] = r * shape[1] + c

    def mean(self, values):
        """Mean of valid cells per zone (NaN cells ignored)."""
        v = values.ravel()
        ok = np.isfinite(v)
        s = np.bincount(self.grid[ok], weights=v[ok], minlength=self.n + 1)[1:]
        c = np.bincount(self.grid[ok], minlength=self.n + 1)[1:]
        with np.errstate(invalid="ignore", divide="ignore"):
            out = s / c
        for i in np.where(self.point_idx >= 0)[0]:
            out[i] = v[self.point_idx[i]]
        return out


def read_month(path):
    with rasterio.open(path) as src:
        a = src.read(1).astype("float64")
        if src.nodata is not None:
            a[a == src.nodata] = np.nan
        a[(a < 0) | (a > MAX_RAIN_MM_MONTH)] = np.nan
        return a, src.transform, a.shape


def climatology(monthly, code_col, name_col, start, end):
    base = monthly[monthly["year"].between(start, end)]
    clim = (base.groupby([code_col, name_col, "month"])["rain_mm"]
            .agg(rain_mm_mean="mean", rain_mm_sd="std",
                 rain_mm_p10=lambda s: s.quantile(0.10),
                 rain_mm_p90=lambda s: s.quantile(0.90),
                 n_years="count")
            .reset_index().round(2))
    clim["baseline"] = f"{start}-{end}"
    clim["source"] = SOURCE_LABEL
    clim["data_type"] = DATA_TYPE
    return clim


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--baseline-start", type=int, default=1991)
    p.add_argument("--baseline-end", type=int, default=2020)
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    files = sorted(f for f in RAW_DIR.glob("*_bgd.tif") if FILE_RE.search(f.name))
    if not files:
        log.error("No CHIRPS files in %s. Run fetch_chirps.py first.", RAW_DIR)
        return 1

    _, transform, shape = read_month(files[0])
    levels = {}
    for layer, code, name in [("districts", "district_code", "district_name"),
                              ("upazilas", "upazila_code", "upazila_name")]:
        gdf = gpd.read_file(ADMIN_GPKG, layer=layer)
        levels[layer] = (gdf, code, name, Zones(gdf, code, transform, shape))
        z = levels[layer][3]
        log.info("%s: %d areas, cells per area min/median = %d/%d, %d use point fallback",
                 layer, z.n, z.n_cells.min(), int(np.median(z.n_cells)),
                 int((z.method == "point").sum()))

    rows = {layer: [] for layer in levels}
    for f in files:
        year, month = map(int, FILE_RE.search(f.name).groups())
        arr, tr, shp = read_month(f)
        if shp != shape or tr != transform:
            log.error("%s has a different grid than the first file; refetch it.", f.name)
            return 1
        for layer, (gdf, code, name, z) in levels.items():
            vals = z.mean(arr)
            rows[layer].append(pd.DataFrame({code: z.codes, name: gdf[name].to_numpy(),
                                             "year": year, "month": month,
                                             "rain_mm": vals, "method": z.method,
                                             "n_cells": z.n_cells}))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for layer, (gdf, code, name, z) in levels.items():
        monthly = pd.concat(rows[layer], ignore_index=True).round({"rain_mm": 2})
        monthly["source"] = SOURCE_LABEL
        monthly["data_type"] = DATA_TYPE
        short = layer[:-1]
        monthly.to_csv(OUT_DIR / f"chirps_{short}_monthly.csv", index=False)
        clim = climatology(monthly, code, name, args.baseline_start, args.baseline_end)
        clim.to_csv(OUT_DIR / f"chirps_{short}_climatology.csv", index=False)
        n_missing = monthly["rain_mm"].isna().sum()
        log.info("%s: %d rows, %d missing values, years %d-%d", layer, len(monthly),
                 n_missing, monthly["year"].min(), monthly["year"].max())

    # ---------- Compare with NASA POWER (district annual means) ----------
    if NASA_CLIM.exists():
        chirps_c = pd.read_csv(OUT_DIR / "chirps_district_climatology.csv")
        nasa_c = pd.read_csv(NASA_CLIM)
        a = chirps_c.groupby(["district_code", "district_name"])["rain_mm_mean"].sum()
        b = nasa_c.groupby("district_code")["rain_mm_mean"].sum()
        comp = a.rename("chirps_annual_mm").reset_index()
        comp["nasa_power_annual_mm"] = comp["district_code"].map(b)
        comp["ratio_nasa_to_chirps"] = comp["nasa_power_annual_mm"] / comp["chirps_annual_mm"]
        comp = comp.round(2).sort_values("ratio_nasa_to_chirps")
        comp.to_csv(OUT_DIR / "rainfall_source_comparison.csv", index=False)
        r = comp["ratio_nasa_to_chirps"]
        log.info("NASA/CHIRPS annual rainfall ratio: median %.2f, range %.2f-%.2f",
                 r.median(), r.min(), r.max())
        log.info("CHIRPS annual rainfall across districts: %.0f-%.0f mm",
                 comp["chirps_annual_mm"].min(), comp["chirps_annual_mm"].max())
    else:
        log.warning("NASA climatology not found; skipping comparison.")

    log.info("Saved outputs to %s", OUT_DIR)
    return 0


if __name__ == "__main__":
    sys.exit(main())
