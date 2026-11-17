"""
fetch_chirps.py
---------------
Phase 2b (ChashiBondhu AI): download CHIRPS v3.0 monthly rainfall
(UCSB Climate Hazards Center, ~0.05 degree / ~5 km) clipped to Bangladesh.

Reads only the Bangladesh window from each global monthly GeoTIFF via HTTP
range requests, so it does not download the full global files.

Data type: HISTORICAL satellite + gauge blended estimate (mm per month).
Not station observations and not forecasts.

Usage:
  python scripts/fetch_chirps.py                     # 1991-2025
  python scripts/fetch_chirps.py --start 1991 --end 2025
  python scripts/fetch_chirps.py --limit 3           # quick test, 3 files
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

os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ.setdefault("GDAL_HTTP_MAX_RETRY", "5")
os.environ.setdefault("GDAL_HTTP_RETRY_DELAY", "5")
os.environ.setdefault("CPL_VSIL_CURL_ALLOWED_EXTENSIONS", ".tif")

import rasterio  # noqa: E402
from rasterio.windows import from_bounds  # noqa: E402

log = logging.getLogger("fetch_chirps")

BASE_URL = "https://data.chc.ucsb.edu/products/CHIRPS/v3.0/monthly/global/tifs"
ROOT = Path(__file__).resolve().parents[1]
ADMIN_GPKG = ROOT / "data/processed/admin/admin_boundaries.gpkg"
OUT_DIR = ROOT / "data/raw/climate/chirps_v3/monthly"
MANIFEST = OUT_DIR / "manifest.csv"
BUFFER_DEG = 0.2


def fetch_month(year, month, bounds, out_path, retries=3):
    url = f"{BASE_URL}/chirps-v3.0.{year}.{month:02d}.tif"
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            with rasterio.open(f"/vsicurl/{url}") as src:
                win = from_bounds(*bounds, transform=src.transform)
                win = win.round_offsets().round_lengths()
                data = src.read(1, window=win, boundless=True, fill_value=src.nodata)
                profile = src.profile.copy()
                profile.update(driver="GTiff", height=data.shape[0], width=data.shape[1],
                               transform=src.window_transform(win), compress="deflate",
                               count=1, tiled=False)
                profile.pop("blockxsize", None)
                profile.pop("blockysize", None)
                tmp = out_path.with_suffix(".tmp.tif")
                with rasterio.open(tmp, "w", **profile) as dst:
                    dst.write(data, 1)
                tmp.replace(out_path)
                return url
        except Exception as e:  # GDAL/network errors come in many types
            last_err = e
            log.warning("  attempt %d failed: %s", attempt, e)
            time.sleep(10 * attempt)
    raise RuntimeError(f"{url}: {last_err}")


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--start", type=int, default=1991)
    p.add_argument("--end", type=int, default=2025)
    p.add_argument("--limit", type=int, default=None, help="only first N months (testing)")
    p.add_argument("--refresh", action="store_true")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if args.start < 1981 or args.end < args.start:
        log.error("Invalid year range %s-%s", args.start, args.end)
        return 1
    if not ADMIN_GPKG.exists():
        log.error("Missing %s. Run build_admin_reference.py first.", ADMIN_GPKG)
        return 1
    minx, miny, maxx, maxy = gpd.read_file(ADMIN_GPKG, layer="divisions").total_bounds
    bounds = (minx - BUFFER_DEG, miny - BUFFER_DEG, maxx + BUFFER_DEG, maxy + BUFFER_DEG)

    months = [(y, m) for y in range(args.start, args.end + 1) for m in range(1, 13)]
    if args.limit:
        months = months[:args.limit]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    new_manifest = not MANIFEST.exists()
    ok = skipped = failed = 0

    with open(MANIFEST, "a", newline="", encoding="utf-8") as mf:
        w = csv.writer(mf)
        if new_manifest:
            w.writerow(["year", "month", "url", "file", "status", "fetched_at_utc"])
        for i, (y, m) in enumerate(months, start=1):
            out = OUT_DIR / f"chirps-v3.0.{y}.{m:02d}_bgd.tif"
            if out.exists() and not args.refresh:
                skipped += 1
                continue
            if i % 12 == 1 or args.limit:
                log.info("[%d/%d] %d-%02d", i, len(months), y, m)
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            try:
                url = fetch_month(y, m, bounds, out)
                w.writerow([y, m, url, out.relative_to(ROOT), "ok", now])
                ok += 1
            except RuntimeError as e:
                log.error("  FAILED %d-%02d: %s", y, m, e)
                w.writerow([y, m, "", "", f"failed: {e}"[:300], now])
                failed += 1
            mf.flush()
            time.sleep(0.5)

    log.info("Finished: %d downloaded, %d already cached, %d failed", ok, skipped, failed)
    if failed:
        log.info("Run the same command again to retry only the missing months.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
