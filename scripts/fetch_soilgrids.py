"""
fetch_soilgrids.py
------------------
Phase 2 (ChashiBondhu AI): download SoilGrids 2.0 (ISRIC, 250 m, CC BY 4.0)
soil layers clipped to Bangladesh and save them as local GeoTIFFs.

Reads only the Bangladesh window from ISRIC's global VRT files, so it does
not download the whole world.

Layers: mean of phh2o, soc, nitrogen, clay, sand, silt, cec at 0-5, 5-15,
15-30 cm, plus Q0.05 and Q0.95 of phh2o (prediction uncertainty for pH).

Data type: GLOBAL MODEL PREDICTION, not soil samples or field measurements.

Usage:
  python scripts/fetch_soilgrids.py
  python scripts/fetch_soilgrids.py --refresh
"""

import argparse
import csv
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd

# GDAL network settings must be set before rasterio opens anything
os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ.setdefault("GDAL_HTTP_MAX_RETRY", "5")
os.environ.setdefault("GDAL_HTTP_RETRY_DELAY", "5")
os.environ.setdefault("CPL_VSIL_CURL_ALLOWED_EXTENSIONS", ".vrt,.tif")

import rasterio  # noqa: E402
from rasterio.warp import transform_bounds  # noqa: E402
from rasterio.windows import from_bounds  # noqa: E402

log = logging.getLogger("fetch_soilgrids")

BASE_URL = "https://files.isric.org/soilgrids/latest/data"
PROPERTIES = ["phh2o", "soc", "nitrogen", "clay", "sand", "silt", "cec"]
DEPTHS = ["0-5cm", "5-15cm", "15-30cm"]
EXTRA = [("phh2o", d, q) for d in DEPTHS for q in ("Q0.05", "Q0.95")]

ROOT = Path(__file__).resolve().parents[1]
ADMIN_GPKG = ROOT / "data/processed/admin/admin_boundaries.gpkg"
OUT_DIR = ROOT / "data/raw/soil/soilgrids"
MANIFEST = OUT_DIR / "manifest.csv"
BUFFER_DEG = 0.1  # small margin around Bangladesh


def layer_list():
    layers = [(p, d, "mean") for p in PROPERTIES for d in DEPTHS]
    return layers + EXTRA


def download_layer(prop, depth, stat, bounds_4326, out_path, retries=3):
    url = f"{BASE_URL}/{prop}/{prop}_{depth}_{stat}.vrt"
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            with rasterio.open(f"/vsicurl/{url}") as src:
                b = transform_bounds("EPSG:4326", src.crs, *bounds_4326, densify_pts=21)
                win = from_bounds(*b, transform=src.transform).round_offsets().round_lengths()
                data = src.read(1, window=win, boundless=True, fill_value=src.nodata)
                profile = src.profile.copy()
                profile.update(driver="GTiff", height=data.shape[0], width=data.shape[1],
                               transform=src.window_transform(win), compress="deflate",
                               count=1)
                big = data.shape[0] >= 256 and data.shape[1] >= 256
                profile.update(tiled=big)
                if big:
                    profile.update(blockxsize=256, blockysize=256)
                else:
                    profile.pop("blockxsize", None)
                    profile.pop("blockysize", None)
                tmp = out_path.with_suffix(".tmp.tif")
                with rasterio.open(tmp, "w", **profile) as dst:
                    dst.write(data, 1)
                tmp.replace(out_path)
                return url
        except Exception as e:  # network/GDAL errors come in many types
            last_err = e
            log.warning("  attempt %d failed: %s", attempt, e)
            time.sleep(10 * attempt)
    raise RuntimeError(f"{url}: {last_err}")


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--refresh", action="store_true")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if not ADMIN_GPKG.exists():
        log.error("Missing %s. Run build_admin_reference.py first.", ADMIN_GPKG)
        return 1
    minx, miny, maxx, maxy = gpd.read_file(ADMIN_GPKG, layer="divisions").total_bounds
    bounds = (minx - BUFFER_DEG, miny - BUFFER_DEG, maxx + BUFFER_DEG, maxy + BUFFER_DEG)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    new_manifest = not MANIFEST.exists()
    layers = layer_list()
    ok = skipped = failed = 0

    with open(MANIFEST, "a", newline="", encoding="utf-8") as mf:
        w = csv.writer(mf)
        if new_manifest:
            w.writerow(["property", "depth", "stat", "url", "file", "status", "fetched_at_utc"])
        for i, (prop, depth, stat) in enumerate(layers, start=1):
            out = OUT_DIR / f"{prop}_{depth}_{stat}.tif"
            if out.exists() and not args.refresh:
                skipped += 1
                continue
            log.info("[%d/%d] %s %s %s", i, len(layers), prop, depth, stat)
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            try:
                url = download_layer(prop, depth, stat, bounds, out)
                w.writerow([prop, depth, stat, url, out.relative_to(ROOT), "ok", now])
                ok += 1
            except RuntimeError as e:
                log.error("  FAILED: %s", e)
                w.writerow([prop, depth, stat, "", "", f"failed: {e}"[:300], now])
                failed += 1
            mf.flush()

    log.info("Finished: %d downloaded, %d already cached, %d failed", ok, skipped, failed)
    if failed:
        log.info("Run the same command again to retry only the missing layers.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
