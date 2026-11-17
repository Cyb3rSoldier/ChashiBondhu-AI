"""Test the vision model on BARI potato field photos (Phase 14). Vision step only, no book.

Run:  python scripts/eval_vision_potato.py --data data/raw/potato_bari [--per-class 20]
Uses ONLY original photos (any path part containing "aug" is skipped).
Dataset classes -> our problem ids: Leaf Roll / PVX / PVY -> virus (the book does not split them).
Results are saved after every photo, so a stopped run continues where it left off.
Each row records which model answered (Groq or the Gemma fallback); the summary reports
accuracy per model too, so the two are never mixed silently.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

IMG_EXT = {".jpg", ".jpeg", ".png"}
FOLDER_RULES = [("healthy", "healthy"), ("late", "late_blight"), ("soft", "soft_rot"),
                ("roll", "virus"), ("pvx", "virus"), ("pvy", "virus"), ("virus", "virus")]


def true_label(folder: str) -> str | None:
    f = folder.lower()
    return next((lab for key, lab in FOLDER_RULES if key in f), None)


def collect(data_dir: Path) -> dict[str, list[Path]]:
    by_folder: dict[str, list[Path]] = {}
    for p in sorted(data_dir.rglob("*")):
        if p.is_file() and p.suffix.lower() in IMG_EXT and \
                not any("aug" in part.lower() for part in p.relative_to(data_dir).parts):
            by_folder.setdefault(p.parent.name, []).append(p)
    unknown = [f for f in by_folder if true_label(f) is None]
    if unknown:
        raise SystemExit(f"unknown class folders {unknown}: update FOLDER_RULES")
    if not by_folder:
        raise SystemExit(f"no original images found under {data_dir}")
    return by_folder


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", type=Path, default=ROOT / "data" / "raw" / "potato_bari")
    ap.add_argument("--per-class", type=int, default=20)
    ap.add_argument("--sleep", type=float, default=3.0, help="seconds between requests")
    ap.add_argument("--out", type=Path,
                    default=ROOT / "data" / "processed" / "eval" / "vision_potato.jsonl")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    from chashibondhu.assistant.llm.gemini import LLMError, RateLimited
    from chashibondhu.assistant.vision.client import VisionClient
    from chashibondhu.assistant.vision.diagnose import PhotoDiagnoser
    from chashibondhu.assistant.vision.problems import ProblemCatalogue

    by_folder = collect(args.data)
    rng = random.Random(args.seed)
    sample = []
    for folder, paths in sorted(by_folder.items()):
        pick = rng.sample(paths, min(args.per_class, len(paths)))
        sample += [(p, folder, true_label(folder)) for p in pick]
        print(f"{folder:30s} originals={len(paths):4d} sampled={len(pick)}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    done = {}
    if args.out.exists():
        for line in args.out.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if row.get("status") != "error":       # error rows are retried
                done[row["path"]] = row
    diag = PhotoDiagnoser(VisionClient.from_env(ROOT),
                          ProblemCatalogue.load(ROOT / "data" / "reference"))
    with open(args.out, "a", encoding="utf-8") as f:
        for i, (path, folder, truth) in enumerate(sample, start=1):
            key = str(path.relative_to(args.data))
            if key in done:
                continue
            row = {"path": key, "folder": folder, "true": truth}
            for attempt in range(3):
                try:
                    seen = diag.look("potato", path.read_bytes())
                    cands = [c.problem_id for c in seen["candidates"]]
                    row.update(model=getattr(diag.vision, "model", ""),
                               status=seen["status"], candidates=cands,
                               pred=cands[0] if seen["status"] in ("possible", "looks_healthy")
                               else seen["status"])
                    break
                except RateLimited:
                    print("rate limited: waiting 60 s")
                    time.sleep(60)
                except (LLMError, ValueError) as e:
                    row.update(status="error", candidates=[], pred="error",
                               error=f"{type(e).__name__}: {e}"[:200])
                    break
            else:
                row.update(status="error", candidates=[], pred="error", error="rate limited")
            done[key] = row
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            print(f"{i:3d}/{len(sample)} {truth:12s} -> {row['pred']}")
            time.sleep(args.sleep)

    rows = [done[str(p.relative_to(args.data))] for p, _, _ in sample
            if str(p.relative_to(args.data)) in done]
    n = len(rows)
    answered = [r for r in rows if r["status"] in ("possible", "looks_healthy")]
    summary = {
        "n": n, "models": getattr(diag.vision, "models", [diag.vision.model]),
        "errors": sum(r["status"] == "error" for r in rows),
        "answered_share": round(len(answered) / n, 3) if n else None,
        "top1_accuracy_all": round(sum(r["pred"] == r["true"] for r in rows) / n, 3) if n else None,
        "top1_accuracy_answered": (round(sum(r["pred"] == r["true"] for r in answered)
                                         / len(answered), 3) if answered else None),
        "top3_hit_all": round(sum(r["true"] in r["candidates"] for r in rows) / n, 3) if n else None,
        "always_most_common_class": (round(Counter(r["true"] for r in rows).most_common(1)[0][1]
                                           / n, 3) if n else None),
        "status_counts": dict(Counter(r["status"] for r in rows)),
    }
    per_class = {}
    for t in sorted({r["true"] for r in rows}):
        rs = [r for r in rows if r["true"] == t]
        per_class[t] = {"n": len(rs), "top1": round(sum(r["pred"] == t for r in rs) / len(rs), 3),
                        "predictions": dict(Counter(r["pred"] for r in rs))}
    summary["per_class"] = per_class
    by_model = {}
    for m in sorted({r.get("model", "") for r in rows if r["status"] != "error"}):
        rs = [r for r in rows if r.get("model", "") == m and r["status"] != "error"]
        by_model[m or "unknown (older rows)"] = {
            "n": len(rs), "top1": round(sum(r["pred"] == r["true"] for r in rs) / len(rs), 3)}
    summary["by_model"] = by_model
    out_json = args.out.with_suffix(".summary.json")
    out_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("saved:", out_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
