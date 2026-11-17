"""Download BARC Crop Zoning upazila tables (one .xls per crop).

Source: Bangladesh Agricultural Research Council, "Land Suitability Assessment
and Crop Zoning of Bangladesh" (Hussain, Chowdhury and Chowdhury).
Page: https://apps.barc.gov.bd/cropzoning/homes/downloads/1
License: "Copyright (c) BARC. All rights reserved." -> keep raw files out of git,
credit BARC, ask BARC before redistributing.

Usage:
    python scripts/fetch_barc_cropzoning.py --limit 1 --inspect   # quick test + show structure
    python scripts/fetch_barc_cropzoning.py                        # all 15 files
    python scripts/fetch_barc_cropzoning.py --refresh              # re-download
    python scripts/fetch_barc_cropzoning.py --inspect --only mustard   # inspect a downloaded file

Output: data/raw/barc_cropzoning/*.xls + manifest.csv (url, time, sha256)
"""
from __future__ import annotations

import argparse
import hashlib
import logging
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "raw" / "barc_cropzoning"
BASE_URL = "https://apps.barc.gov.bd/cropzoning/files/data/"
# barc_crop: (file name, our crop_id or "" if outside our catalogue)
FILES = {
    "mustard": ("Mustard-zone.xls", "mustard"),
    "aman": ("Aman-zone.xls", "aman_rice"),
    "boro": ("Boro-zone.xls", "boro_rice"),
    "maize": ("Maize-zone.xls", "maize"),
    "potato": ("Potato-zone.xls", "potato"),
    "lentil": ("Lentil-zone.xls", "lentil"),
    "mungbean": ("Mung-zone.xls", "mung_bean"),
    "onion_garlic": ("Oni-Gar-zone.xls", "onion"),  # combined with garlic in BARC data
    "aus": ("Aus-zone.xls", ""),
    "wheat": ("Wheat-zone.xls", ""),
    "gram": ("Gram-zone.xls", ""),
    "groundnut": ("Groundnut-zone.xls", ""),
    "chili": ("Chili-zone.xls", ""),
    "sugarcane": ("Sugarcane-zone.xls", ""),
    "jute": ("Jute-zone.xls", ""),
}
RETRIES = 4
PAUSE_S = 1.5
TIMEOUT_S = 90
log = logging.getLogger("fetch_barc_cropzoning")


def download(url: str, dest: Path) -> bytes:
    last: Exception | None = None
    for attempt in range(1, RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ChashiBondhu-AI research"})
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
                data = r.read()
            if len(data) < 512:
                raise ValueError(f"file too small ({len(data)} bytes) - probably an error page")
            tmp = dest.with_suffix(".part")
            tmp.write_bytes(data)
            tmp.replace(dest)
            return data
        except Exception as exc:  # noqa: BLE001
            last = exc
            wait = 5 * 2 ** (attempt - 1)
            log.warning("attempt %d/%d failed for %s: %s; retry in %ds",
                        attempt, RETRIES, url, exc, wait)
            time.sleep(wait)
    raise RuntimeError(f"failed to download {url}: {last}")


def inspect(path: Path, n_rows: int = 12) -> None:
    """Print sheets, shape and the first rows so the build step can be written correctly."""
    print(f"\n===== {path.name} ({path.stat().st_size} bytes) first bytes: "
          f"{path.read_bytes()[:8]!r}")
    try:
        sheets = pd.read_excel(path, sheet_name=None, header=None, dtype=str)
    except Exception as exc:  # noqa: BLE001 - old .xls may be HTML in disguise
        log.warning("read_excel failed (%s); trying as HTML table", exc)
        try:
            sheets = {f"html_{i}": t for i, t in
                      enumerate(pd.read_html(path, header=None))}
        except Exception as exc2:  # noqa: BLE001
            log.error("could not read %s as Excel or HTML: %s", path.name, exc2)
            return
    for name, df in sheets.items():
        print(f"--- sheet '{name}': {df.shape[0]} rows x {df.shape[1]} cols")
        with pd.option_context("display.max_columns", 30, "display.width", 250):
            print(df.head(n_rows).fillna("").to_string())


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--limit", type=int, help="only the first N files (mustard first)")
    p.add_argument("--only", nargs="+", choices=list(FILES), help="only these BARC crops")
    p.add_argument("--refresh", action="store_true", help="re-download existing files")
    p.add_argument("--inspect", action="store_true", help="print structure of the files")
    p.add_argument("--base-url", default=BASE_URL, help=argparse.SUPPRESS)  # for tests
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    keys = args.only or list(FILES)
    if args.limit:
        keys = keys[: args.limit]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows, n_new, n_cached, failed = [], 0, 0, []
    for key in keys:
        fname, crop_id = FILES[key]
        url = args.base_url + fname
        dest = OUT_DIR / fname
        try:
            if dest.exists() and not args.refresh:
                data = dest.read_bytes()
                n_cached += 1
                log.info("cached %s", fname)
            else:
                data = download(url, dest)
                n_new += 1
                log.info("downloaded %s (%d bytes)", fname, len(data))
                time.sleep(PAUSE_S)
        except RuntimeError as exc:
            log.error("%s", exc)
            failed.append(fname)
            continue
        rows.append({"barc_crop": key, "crop_id": crop_id, "file": fname, "url": url,
                     "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                     "fetched_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     "license": "Copyright BARC, all rights reserved (internal use, credit BARC)",
                     "data_type": "expert_land_suitability_assessment"})
        if args.inspect:
            inspect(dest)

    manifest = OUT_DIR / "manifest.csv"
    new = pd.DataFrame(rows)
    if manifest.exists() and not new.empty:
        old = pd.read_csv(manifest)
        new = pd.concat([old[~old["file"].isin(new["file"])], new], ignore_index=True)
    if not new.empty:
        new.to_csv(manifest, index=False)
    log.info("Finished: %d downloaded, %d already cached, %d failed", n_new, n_cached, len(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
