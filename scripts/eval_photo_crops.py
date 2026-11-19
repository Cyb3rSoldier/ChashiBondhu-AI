r"""Real accuracy check for Dr. Krishi's photo step: does it name the RIGHT crop (and problem)?

Put your own labelled photos in folders (real field photos are best):
    data\eval\photos\potato\leaf1.jpg              crop only
    data\eval\photos\potato\late_blight\x.jpg      crop + problem_id (from crop_problems.csv), or "healthy"
    data\eval\photos\maize\...
Folder names must be crop_id values from data\reference\crop_catalogue.csv.

Usage (PowerShell, repo root, .venv active):
    $env:PYTHONPATH = "src"
    python scripts\eval_photo_crops.py --limit 10            # quick try
    python scripts\eval_photo_crops.py                       # all photos
    python scripts\eval_photo_crops.py --with-crop           # farmer names the crop: tests the problem step only

Prints and saves (data\interim\benchmarks\photo_eval_<time>.csv):
    crop correct / wrong / "asked the farmer" (pick_crop) - asking is NOT counted as correct,
    the wrong-crop pairs (for example potato -> maize), problem accuracy where labelled, seconds per photo.
Needs the real .env keys (calls Groq vision, Gemma fallback). Pauses between photos for free-tier limits.
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
EXT = {".jpg", ".jpeg", ".png", ".webp"}


def collect(folder: Path, crops: set[str]) -> list[tuple[Path, str, str]]:
    items = []
    for crop_dir in sorted(p for p in folder.iterdir() if p.is_dir()):
        if crop_dir.name not in crops:
            print(f"INFO: skip folder '{crop_dir.name}' (not a crop_id in crop_catalogue.csv)")
            continue
        for f in sorted(crop_dir.rglob("*")):
            if f.suffix.lower() in EXT:
                prob = f.parent.name if f.parent != crop_dir else ""
                items.append((f, crop_dir.name, prob))
    return items


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--folder", type=Path, default=ROOT / "data" / "eval" / "photos")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--pause", type=float, default=2.0)
    ap.add_argument("--with-crop", action="store_true", help="give the true crop as the farmer's choice")
    args = ap.parse_args(argv)
    from chashibondhu.assistant import diagnosis as dx
    from chashibondhu.assistant.vision.client import VisionClient
    from chashibondhu.assistant.vision.image_prep import ImageError, prepare_image
    from chashibondhu.assistant.vision.problems import ProblemCatalogue
    if not args.folder.is_dir():
        print(f"ERROR: folder not found: {args.folder}  (see the usage text at the top of this file)")
        return 2
    cat = ProblemCatalogue.load(ROOT / "data" / "reference")
    items = collect(args.folder, set(cat.crops))
    if args.limit:
        items = items[: args.limit]
    if not items:
        print("ERROR: no photos found")
        return 2
    vision = VisionClient.from_env(ROOT)
    rows = []
    for i, (path, crop, prob) in enumerate(items, 1):
        hint = crop if args.with_crop else None
        start = time.perf_counter()
        pred_crop = pred_prob = status = err = ""
        try:
            jpeg = prepare_image(path.read_bytes()).jpeg
            raw = vision.analyze(dx.build_prompt(cat, hint), "Farmer's question: (no text, only the photo)", jpeg)
            p = dx.check(dx.parse(raw), "", cat, hint)
            status = p["status"]
            pred_crop = (p.get("crop") or {}).get("id") or ""
            d = p.get("diagnosis") or {}
            pred_prob = "healthy" if status == "healthy" else d.get("problem_id") or d.get("en", "")
        except (ImageError, dx.BadJSON) as e:
            err = type(e).__name__
        except Exception as e:  # noqa: BLE001 - rate limit / network: record and go on
            err = f"{type(e).__name__}: {str(e)[:80]}"
        secs = time.perf_counter() - start
        verdict = ("asked" if status in ("pick_crop", "crop_mismatch") else
                   "error" if err or not status else "correct" if pred_crop == crop else "wrong")
        rows.append({"file": str(path.relative_to(args.folder)), "true_crop": crop, "pred_crop": pred_crop,
                     "crop_verdict": verdict, "true_problem": prob, "pred_problem": pred_prob,
                     "problem_ok": (pred_prob == prob) if prob else "", "status": status, "error": err,
                     "seconds": round(secs, 1)})
        print(f"INFO: {i}/{len(items)} {crop:10s} -> {pred_crop or status or err:12s} {verdict:7s} {secs:4.1f}s  {path.name}")
        time.sleep(args.pause)
    n = len(rows)
    c = Counter(r["crop_verdict"] for r in rows)
    print(f"INFO: photos {n} | crop correct {c['correct']} ({c['correct'] / n:.0%}) | wrong {c['wrong']} | "
          f"asked farmer {c['asked']} | errors {c['error']}")
    for (t, p), k in Counter((r["true_crop"], r["pred_crop"]) for r in rows if r["crop_verdict"] == "wrong").most_common():
        print(f"INFO: wrong crop {t} -> {p}: {k}")
    lab = [r for r in rows if r["true_problem"] and r["crop_verdict"] == "correct"]
    if lab:
        ok = sum(1 for r in lab if r["problem_ok"])
        print(f"INFO: problem correct {ok}/{len(lab)} ({ok / len(lab):.0%}) on photos with a problem label and the right crop")
    out = ROOT / "data" / "interim" / "benchmarks"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"photo_eval_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"INFO: saved {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
