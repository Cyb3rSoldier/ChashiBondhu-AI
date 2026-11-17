"""Photo help from the command line (Phase 14). 1 vision request (+1-2 for the book answer).

Run:  python scripts/diagnose_photo.py PHOTO.jpg --crop potato [--note "..."] [--no-book]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("photo", type=Path)
    ap.add_argument("--crop", required=True, help="crop_id from data/reference/crop_catalogue.csv")
    ap.add_argument("--note", default="")
    ap.add_argument("--no-book", action="store_true", help="skip the book answer (saves requests)")
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    from chashibondhu.assistant.vision.client import VisionClient
    from chashibondhu.assistant.vision.diagnose import PhotoDiagnoser
    from chashibondhu.assistant.vision.problems import ProblemCatalogue

    assistant = None
    if not args.no_book:
        from chashibondhu.assistant.service import Assistant
        assistant = Assistant.from_env(ROOT)
    diag = PhotoDiagnoser(VisionClient.from_env(ROOT),
                          ProblemCatalogue.load(ROOT / "data" / "reference"), assistant)
    r = diag.diagnose(args.crop, args.photo.read_bytes(), args.note)
    print(f"[{r['status']}] model={r['model']} requests={r['llm_requests']}")
    print(r["message_bn"])
    print("\ncandidates:", json.dumps(r["candidates"], ensure_ascii=False))
    if r["book"]:
        print("book pages:", [s.get("printed_page") for s in r["book"]["sources"]])
    for n in r["notes"]:
        print("note:", n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
