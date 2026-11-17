"""Run the rule-based crop suitability engine.

Usage:
    python scripts/run_suitability.py --area BD1004
    python scripts/run_suitability.py --area BD10040009 --land-type medium_highland --irrigation yes
    python scripts/run_suitability.py --area BD1004 --crops mustard potato --json
    python scripts/run_suitability.py --all-districts      # report for 64 districts

--area takes a district code (e.g. BD1004) or an upazila code (e.g. BD10040009).
Outputs (--all-districts): data/processed/suitability/district_suitability.csv
Results use historical 1991-2020 averages; they are not a weather forecast.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from chashibondhu.crop_planning.features.area_features import FeatureStore  # noqa: E402
from chashibondhu.crop_planning.features.barc_zoning import BarcStore  # noqa: E402
from chashibondhu.crop_planning.rules.engine import (  # noqa: E402
    Knowledge, SuitabilityEngine, results_to_frame,
)

PROCESSED = ROOT / "data" / "processed"
REF_DIR = ROOT / "data" / "reference"
OUT_DIR = PROCESSED / "suitability"
BARC_FILE = PROCESSED / "barc" / "barc_cropzoning_upazila.csv"
log = logging.getLogger("run_suitability")


def print_area(area, results) -> None:
    print(f"\n{area.name_en} ({area.area_code}, {area.level})")
    for r in results:
        print(f"  {r.crop_id:<10} {r.status:<13} coverage={r.evidence_coverage:.0%}"
              + (f"  ask: {', '.join(r.missing_inputs)}" if r.missing_inputs else ""))
        for c in r.checks:
            src = f" [{c.source}]" if c.source else ""
            print(f"      - {c.check:<13} {c.status:<13} {c.message}{src}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--area", help="district or upazila code")
    g.add_argument("--all-districts", action="store_true", help="write report for all districts")
    p.add_argument("--crops", nargs="+", help="crop_ids (default: the 5 initial crops)")
    p.add_argument("--land-type", choices=["highland", "medium_highland", "medium_lowland",
                                           "lowland", "very_lowland"])
    p.add_argument("--irrigation", choices=["yes", "no"])
    p.add_argument("--json", action="store_true", help="print JSON instead of text")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    irrigation = None if args.irrigation is None else args.irrigation == "yes"
    try:
        store = FeatureStore(PROCESSED)
        barc = BarcStore(BARC_FILE) if BARC_FILE.exists() else None
        if barc is None:
            log.warning("BARC crop zoning not built yet - running without it")
        engine = SuitabilityEngine(Knowledge(REF_DIR), barc)
        if args.area:
            area = store.get(args.area)
            results = engine.evaluate(area, args.crops, args.land_type, irrigation)
            if args.json:
                print(json.dumps([r.to_dict() for r in results], ensure_ascii=False, indent=2))
            else:
                print_area(area, results)
            return 0

        frames, summary = [], []
        for code in store.districts():
            area = store.get(code)
            results = engine.evaluate(area, args.crops, args.land_type, irrigation)
            frames.append(results_to_frame(area, results))
            summary += [r.status for r in results]
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        out = OUT_DIR / "district_suitability.csv"
        pd.concat(frames, ignore_index=True).to_csv(out, index=False, encoding="utf-8-sig")
        counts = pd.Series(summary).value_counts().to_dict()
        log.info("districts evaluated: %d", len(store.districts()))
        log.info("crop x district results: %d | status %s", len(summary), counts)
        log.info("Saved %s", out.relative_to(ROOT))
        return 0
    except (FileNotFoundError, KeyError, ValueError) as exc:
        log.error("%s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
