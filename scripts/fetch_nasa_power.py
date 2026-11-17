"""
fetch_nasa_power.py
-------------------
Phase 1 (ChashiBondhu AI): download daily NASA POWER data for every district.

For each district in data/processed/admin/districts.csv, requests daily data
at the district's reference point (ref_lat, ref_lon) and saves the raw JSON
response unchanged. A manifest records every request (provenance).

Data type: REANALYSIS (historical), NOT observations and NOT forecasts.
Native resolution is coarse (~0.5 x 0.625 degrees); values represent a grid
cell, not a field.

Usage:
  python scripts/fetch_nasa_power.py                 # 1991-2025, skip cached
  python scripts/fetch_nasa_power.py --start 1991 --end 2025 --refresh
  python scripts/fetch_nasa_power.py --limit 2       # quick test on 2 districts
"""

import argparse
import csv
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

log = logging.getLogger("fetch_nasa_power")

API_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
PARAMETERS = ["T2M", "T2M_MAX", "T2M_MIN", "PRECTOTCORR", "RH2M"]
COMMUNITY = "AG"

ROOT = Path(__file__).resolve().parents[1]
DISTRICTS_CSV = ROOT / "data/processed/admin/districts.csv"
OUT_DIR = ROOT / "data/raw/climate/nasa_power/daily"
MANIFEST = ROOT / "data/raw/climate/nasa_power/manifest.csv"

MANIFEST_FIELDS = ["district_code", "district_name", "ref_lat", "ref_lon",
                   "start", "end", "parameters", "url", "status",
                   "http_status", "fetched_at_utc", "file"]


def fetch_one(lat, lon, start, end, timeout, retries):
    """Request one point. Returns (json_dict, http_status, url). Retries on failure."""
    params = {
        "parameters": ",".join(PARAMETERS),
        "community": COMMUNITY,
        "latitude": f"{lat:.5f}",
        "longitude": f"{lon:.5f}",
        "start": f"{start}0101",
        "end": f"{end}1231",
        "format": "JSON",
        "time-standard": "LST",
    }
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(API_URL, params=params, timeout=timeout)
            if r.status_code == 200:
                data = r.json()
                if "properties" not in data or "parameter" not in data["properties"]:
                    raise ValueError("Response has no properties.parameter block")
                return data, r.status_code, r.url
            last_err = f"HTTP {r.status_code}: {r.text[:200]}"
            # 429 = rate limited, 5xx = server problem -> wait and retry
            if r.status_code not in (429, 500, 502, 503, 504):
                break
        except (requests.RequestException, ValueError) as e:
            last_err = str(e)
        wait = 10 * attempt
        log.warning("  attempt %d failed (%s); retrying in %ds", attempt, last_err, wait)
        time.sleep(wait)
    raise RuntimeError(last_err)


def append_manifest(row: dict):
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    new = not MANIFEST.exists()
    with open(MANIFEST, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--start", type=int, default=1991, help="first year (>=1981)")
    p.add_argument("--end", type=int, default=2025, help="last full year")
    p.add_argument("--refresh", action="store_true", help="re-download cached files")
    p.add_argument("--limit", type=int, default=None, help="only first N districts (testing)")
    p.add_argument("--pause", type=float, default=2.0, help="seconds between requests")
    p.add_argument("--timeout", type=int, default=180)
    p.add_argument("--retries", type=int, default=4)
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if args.start < 1981 or args.end < args.start:
        log.error("Invalid year range %s-%s", args.start, args.end)
        return 1
    if not DISTRICTS_CSV.exists():
        log.error("Missing %s. Run build_admin_reference.py first.", DISTRICTS_CSV)
        return 1

    districts = pd.read_csv(DISTRICTS_CSV)
    required = {"district_code", "district_name", "ref_lat", "ref_lon"}
    if not required.issubset(districts.columns):
        log.error("districts.csv must contain %s", required)
        return 1
    if args.limit:
        districts = districts.head(args.limit)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ok = skipped = failed = 0

    for i, d in enumerate(districts.itertuples(index=False), start=1):
        out_file = OUT_DIR / f"{d.district_code}_{args.start}_{args.end}.json"
        if out_file.exists() and not args.refresh:
            skipped += 1
            continue
        log.info("[%d/%d] %s (%s)", i, len(districts), d.district_name, d.district_code)
        row = {"district_code": d.district_code, "district_name": d.district_name,
               "ref_lat": d.ref_lat, "ref_lon": d.ref_lon,
               "start": args.start, "end": args.end,
               "parameters": ";".join(PARAMETERS),
               "fetched_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        try:
            data, status, url = fetch_one(d.ref_lat, d.ref_lon, args.start, args.end,
                                          args.timeout, args.retries)
            out_file.write_text(json.dumps(data), encoding="utf-8")
            row.update(status="ok", http_status=status, url=url,
                       file=str(out_file.relative_to(ROOT)))
            ok += 1
        except RuntimeError as e:
            log.error("  FAILED: %s", e)
            row.update(status=f"failed: {e}"[:300], http_status="", url="", file="")
            failed += 1
        append_manifest(row)
        time.sleep(args.pause)

    log.info("Finished: %d downloaded, %d already cached, %d failed", ok, skipped, failed)
    if failed:
        log.info("Run the same command again to retry only the failed districts.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
