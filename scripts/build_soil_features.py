"""
build_soil_features.py
----------------------
Phase 2 (ChashiBondhu AI): turn SoilGrids rasters into topsoil (0-30 cm)
statistics for every district and upazila.

For each area: mean, 10th and 90th percentile of every property, the share of
the area with valid soil data, the dominant USDA texture class (and its share),
and the mean SoilGrids 5%/95% prediction limits for pH.

Topsoil 0-30 cm = thickness-weighted mean of 0-5 (5 cm), 5-15 (10 cm) and
15-30 cm (15 cm) layers, computed per pixel.

Outputs in data/processed/soil/:
  district_soil_topsoil.csv
  upazila_soil_topsoil.csv

All values are GLOBAL MODEL ESTIMATES (SoilGrids 2.0), not field measurements.

Usage:
  python scripts/build_soil_features.py
"""

import logging
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import rasterize

log = logging.getLogger("build_soil_features")

ROOT = Path(__file__).resolve().parents[1]
RASTER_DIR = ROOT / "data/raw/soil/soilgrids"
ADMIN_GPKG = ROOT / "data/processed/admin/admin_boundaries.gpkg"
OUT_DIR = ROOT / "data/processed/soil"

DEPTHS = {"0-5cm": 5, "5-15cm": 10, "15-30cm": 15}

# SoilGrids mapped units -> conventional units (divide by factor)
PROPERTIES = {
    # name: (factor, output column)
    "phh2o": (10, "ph"),
    "soc": (10, "soc_g_kg"),
    "nitrogen": (100, "nitrogen_g_kg"),
    "clay": (10, "clay_pct"),
    "sand": (10, "sand_pct"),
    "silt": (10, "silt_pct"),
    "cec": (10, "cec_cmol_kg"),
}

SOURCE_LABEL = "SoilGrids 2.0 (ISRIC), 250 m, CC BY 4.0"
DATA_TYPE = "global_model_estimate"

TEXTURE_CLASSES = ["sand", "loamy sand", "sandy loam", "loam", "silt loam", "silt",
                   "sandy clay loam", "clay loam", "silty clay loam", "sandy clay",
                   "silty clay", "clay"]


def read_raster(name):
    path = RASTER_DIR / f"{name}.tif"
    if not path.exists():
        raise FileNotFoundError(f"{path} missing; run fetch_soilgrids.py")
    with rasterio.open(path) as src:
        arr = src.read(1).astype("float32")
        if src.nodata is not None:
            arr[arr == src.nodata] = np.nan
        return arr, src.transform, src.crs


def topsoil(prop, stat="mean"):
    """Thickness-weighted 0-30 cm value per pixel (NaN if any depth missing)."""
    total, weights = None, sum(DEPTHS.values())
    transform = crs = None
    for depth, thick in DEPTHS.items():
        arr, transform, crs = read_raster(f"{prop}_{depth}_{stat}")
        total = arr * thick if total is None else total + arr * thick
    return total / weights, transform, crs


def usda_texture(sand, silt, clay):
    """USDA texture class index per pixel (0..11), -1 where invalid."""
    s = sand + silt + clay
    with np.errstate(invalid="ignore", divide="ignore"):
        sand, silt, clay = sand / s * 100, silt / s * 100, clay / s * 100
    conds = [
        (silt + 1.5 * clay) < 15,                                              # sand
        ((silt + 1.5 * clay) >= 15) & ((silt + 2 * clay) < 30),                # loamy sand
        ((clay >= 7) & (clay < 20) & (sand > 52) & ((silt + 2 * clay) >= 30))
        | ((clay < 7) & (silt < 50) & ((silt + 2 * clay) >= 30)),              # sandy loam
        (clay >= 7) & (clay < 27) & (silt >= 28) & (silt < 50) & (sand <= 52), # loam
        ((silt >= 50) & (clay >= 12) & (clay < 27))
        | ((silt >= 50) & (silt < 80) & (clay < 12)),                          # silt loam
        (silt >= 80) & (clay < 12),                                            # silt
        (clay >= 20) & (clay < 35) & (silt < 28) & (sand > 45),                # sandy clay loam
        (clay >= 27) & (clay < 40) & (sand > 20) & (sand <= 45),               # clay loam
        (clay >= 27) & (clay < 40) & (sand <= 20),                             # silty clay loam
        (clay >= 35) & (sand > 45),                                            # sandy clay
        (clay >= 40) & (silt >= 40),                                           # silty clay
        (clay >= 40) & (sand <= 45) & (silt < 40),                             # clay
    ]
    out = np.select(conds, list(range(12)), default=-1)
    out[~np.isfinite(s) | (s <= 0)] = -1
    return out


def zone_ids(gdf, crs, transform, shape):
    g = gdf.to_crs(crs.to_wkt())
    shapes = ((geom, i + 1) for i, geom in enumerate(g.geometry))
    return rasterize(shapes, out_shape=shape, transform=transform,
                     fill=0, dtype="int32")


def zonal_table(zones, layers, texture, n_zones):
    """Per-zone statistics. zones: int array (0 = outside)."""
    inside = zones > 0
    z = zones[inside]
    df = pd.DataFrame({"zone": z})
    for col, arr in layers.items():
        df[col] = arr[inside]
    df["texture"] = texture[inside]

    total = df.groupby("zone").size()
    out = pd.DataFrame(index=pd.RangeIndex(1, n_zones + 1, name="zone"))
    out["n_pixels"] = total
    valid = df["ph"].notna()
    n_valid = df[valid].groupby("zone").size().reindex(out.index, fill_value=0)
    out["valid_fraction"] = n_valid / out["n_pixels"]

    for col in layers:
        g = df[df[col].notna()].groupby("zone")[col]
        if col.startswith("ph_q"):
            out[f"{col}_mean"] = g.mean()
            continue
        out[f"{col}_mean"] = g.mean()
        out[f"{col}_p10"] = g.quantile(0.10)
        out[f"{col}_p90"] = g.quantile(0.90)

    tex = df[df["texture"] >= 0]
    if len(tex):
        counts = tex.groupby(["zone", "texture"]).size().unstack(fill_value=0)
        out["texture_dominant"] = counts.idxmax(axis=1).map(dict(enumerate(TEXTURE_CLASSES)))
        out["texture_dominant_share"] = counts.max(axis=1) / counts.sum(axis=1)
    return out.reset_index()


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        layers, transform, crs = {}, None, None
        for prop, (factor, col) in PROPERTIES.items():
            arr, transform, crs = topsoil(prop)
            layers[col] = arr / factor
            log.info("Loaded %s", col)
        layers["ph_q05"] = topsoil("phh2o", "Q0.05")[0] / 10
        layers["ph_q95"] = topsoil("phh2o", "Q0.95")[0] / 10
    except FileNotFoundError as e:
        log.error(e)
        return 1

    # pH of 0 is not a real soil value -> treat as no data
    bad = ~(layers["ph"] > 0)
    for arr in layers.values():
        arr[bad] = np.nan

    texture = usda_texture(layers["sand_pct"], layers["silt_pct"], layers["clay_pct"])
    shape = layers["ph"].shape
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    for level, code, name in [("districts", "district_code", "district_name"),
                              ("upazilas", "upazila_code", "upazila_name")]:
        gdf = gpd.read_file(ADMIN_GPKG, layer=level)
        zones = zone_ids(gdf, crs, transform, shape)
        stats = zonal_table(zones, layers, texture, len(gdf))
        meta = gdf.drop(columns="geometry").reset_index(drop=True)
        meta["zone"] = np.arange(1, len(gdf) + 1)
        result = meta.merge(stats, on="zone", how="left").drop(columns="zone")
        num = result.select_dtypes("number").columns.difference(["ref_lat", "ref_lon"])
        result[num] = result[num].round(3)
        result["source"] = SOURCE_LABEL
        result["data_type"] = DATA_TYPE
        out = OUT_DIR / f"{level[:-1]}_soil_topsoil.csv"
        result.to_csv(out, index=False)

        no_data = result["ph_mean"].isna().sum()
        low = (result["valid_fraction"] < 0.5).sum()
        log.info("%s: %d areas | %d with no soil data | %d with <50%% valid area",
                 level, len(result), no_data, low)
        log.info("  pH range of %s means: %.2f - %.2f", level,
                 result["ph_mean"].min(), result["ph_mean"].max())

    log.info("Saved outputs to %s", OUT_DIR)
    return 0


if __name__ == "__main__":
    sys.exit(main())
