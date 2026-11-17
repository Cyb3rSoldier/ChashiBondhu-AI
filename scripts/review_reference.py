"""Review DRAFT rows one by one and mark the correct ones as verified.

For each row it shows the crop, the value, the page and the book's words.
Open the book at that page and check, then answer:
    y = matches the book -> verified
    n = does not match   -> stays draft (fix it in the CSV, or tell Claude)
    s = skip for now
    q = quit (answers so far are saved)

Usage:
    python scripts/review_reference.py --by siyam
    python scripts/review_reference.py --by siyam --crop mustard
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from chashibondhu.reference.curation import draft_rows, mark_verified  # noqa: E402

REF_DIR = ROOT / "data" / "reference"
KPH10_PDF_OFFSET = 25  # KPH 10th edition: PDF page = printed page + 25


def describe(name: str, r) -> str:
    if name == "crop_requirements.csv":
        nums = "  ".join(f"{c}={r[c]}" for c in ("min", "opt_min", "opt_max", "max") if r[c])
        value = r["value_text"] or nums
        what = f"{r['parameter']} ({r['unit']}): {value}"
    else:
        what = (f"{r['activity']}: {r['start_day']}/{r['start_month']} -> "
                f"{r['end_day']}/{r['end_month']} (day/month), {r['region_scope']}")
    hint = ""
    m = re.search(r"p\. (\d+)", r["source_locator"])
    if m and "KPH 10th" in r["source_locator"]:
        hint = f"  (PDF page {int(m.group(1)) + KPH10_PDF_OFFSET})"
    return (f"\n[{r['crop_id']} | {r['variety_scope']}]  {what}\n"
            f"  source: {r['source_id']} {r['source_locator']}{hint}\n"
            f"  notes : {r['notes']}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--by", required=True, help="your name (stored as verified_by)")
    p.add_argument("--crop", help="only review this crop_id")
    args = p.parse_args()

    rows = draft_rows(REF_DIR, args.crop)
    if not rows:
        print("No draft rows to review.")
        return 0
    print(f"{len(rows)} draft row(s) to review. Check each against the book.")
    done = 0
    for name, idx, r in rows:
        print(describe(name, r))
        while True:
            ans = input("  matches the book? [y/n/s/q]: ").strip().lower()
            if ans in {"y", "n", "s", "q"}:
                break
            print("  please type y, n, s or q")
        if ans == "q":
            break
        if ans == "y":
            mark_verified(REF_DIR, name, idx, args.by)
            done += 1
    print(f"\nVerified {done} row(s). Next: python scripts/validate_reference.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
