"""Download Bangla admin names (divisions, districts, upazilas).

Source: nuhil/bangladesh-geocode (GitHub, MIT license). Community dataset;
spellings taken by its author from bangladesh.gov.bd, Wikipedia, Google Maps.
We use the JSON files because the CSV files have no header row.

Usage:
    python scripts/fetch_bn_admin_names.py              # download missing files
    python scripts/fetch_bn_admin_names.py --limit 1    # quick test (1 file)
    python scripts/fetch_bn_admin_names.py --refresh    # re-download all
    python scripts/fetch_bn_admin_names.py --ref <commit_sha>   # pin a version

Output: data/raw/admin_bn/nuhil/*.json + manifest.csv (url, time, sha256).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "raw" / "admin_bn" / "nuhil"
REPO = "nuhil/bangladesh-geocode"
FILES = ["divisions/divisions.json", "districts/districts.json", "upazilas/upazilas.json"]
RETRIES = 4
PAUSE_S = 1.0
TIMEOUT_S = 60

log = logging.getLogger("fetch_bn_admin_names")


def resolve_commit(ref: str) -> str:
    """Try to get the exact commit SHA for provenance. Falls back to ref."""
    url = f"https://api.github.com/repos/{REPO}/commits/{ref}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ChashiBondhu-AI"})
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            return json.load(r)["sha"]
    except Exception as exc:  # noqa: BLE001 - provenance is best-effort
        log.warning("Could not resolve commit SHA (%s); recording ref '%s'", exc, ref)
        return ref


def download(url: str, dest: Path) -> bytes:
    last_err: Exception | None = None
    for attempt in range(1, RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ChashiBondhu-AI"})
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
                data = r.read()
            json.loads(data.decode("utf-8"))  # validate before saving
            tmp = dest.with_suffix(".part")
            tmp.write_bytes(data)
            tmp.replace(dest)
            return data
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            wait = 5 * 2 ** (attempt - 1)
            log.warning("Attempt %d/%d failed for %s: %s; retry in %ds",
                        attempt, RETRIES, url, exc, wait)
            time.sleep(wait)
    raise RuntimeError(f"Failed to download {url}: {last_err}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ref", default="master", help="branch or commit SHA (default: master)")
    p.add_argument("--limit", type=int, default=None, help="only fetch first N files")
    p.add_argument("--refresh", action="store_true", help="re-download existing files")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    commit = resolve_commit(args.ref)
    files = FILES[: args.limit] if args.limit else FILES
    rows, n_new, n_cached = [], 0, 0
    for rel in files:
        url = f"https://raw.githubusercontent.com/{REPO}/{commit}/{rel}"
        dest = OUT_DIR / Path(rel).name
        if dest.exists() and not args.refresh:
            data = dest.read_bytes()
            n_cached += 1
            log.info("cached %s", dest.name)
        else:
            data = download(url, dest)
            n_new += 1
            log.info("downloaded %s (%d bytes)", dest.name, len(data))
            time.sleep(PAUSE_S)
        rows.append({
            "file": dest.name, "url": url, "repo": REPO, "ref": args.ref,
            "commit": commit, "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "fetched_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "license": "MIT", "data_type": "community_dataset",
        })

    manifest = OUT_DIR / "manifest.csv"
    new = pd.DataFrame(rows)
    if manifest.exists():
        old = pd.read_csv(manifest)
        new = pd.concat([old[~old["file"].isin(new["file"])], new], ignore_index=True)
    new.to_csv(manifest, index=False)
    log.info("Finished: %d downloaded, %d already cached, commit=%s", n_new, n_cached, commit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
