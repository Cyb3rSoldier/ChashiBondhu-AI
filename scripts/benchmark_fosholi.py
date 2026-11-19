r"""Measure Fosholi's real response time, step by step (no cache), before vs after the speed fix.

Usage (PowerShell, repo root, .venv active):
    $env:PYTHONPATH = "src"
    python scripts\benchmark_fosholi.py                 # both modes, built-in questions
    python scripts\benchmark_fosholi.py --mode fast --limit 3
    python scripts\benchmark_fosholi.py --questions my_questions.txt   (one question per line)

Modes:
    legacy = the old way: the Banglish -> Bangla rewrite call runs with the model's default (long) thinking
    fast   = the new way: the rewrite call uses reasoning_effort=low (same as the answer stream)
For each question it prints: rewrite time, search time, time to the FIRST shown sentence, total time.
Results are also saved to data/interim/benchmarks/fosholi_<time>.csv (with the model that answered).
Needs the real .env keys and the handbook index (it calls Groq; free-tier limits apply, so it pauses).
"""
from __future__ import annotations

import argparse
import csv
import os
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

QUESTIONS = [
    "ধানে কখন সেচ দিতে হয়?",                                  # irrigation
    "আলুতে সার কখন দিতে হয়?",                                  # fertilizer
    "টমেটো গাছের পাতা হলুদ হয়ে যাচ্ছে, কী করব?",                # disease / symptom
    "বৃষ্টির পর আলুর জমিতে কী করব?",                            # weather decision
    "এই মৌসুমে কোন ফসল চাষ করা যায়?",                           # seasonal crop choice
    "মাটির অম্লতা কমাতে কী করব?",                                # soil
    "alur pata pochche ki korbo",                                   # Banglish (rewrite needed)
    "sorishar bhalo jat konta",                                     # Banglish (rewrite needed)
]


def run_mode(mode: str, questions: list[str], pause: float) -> list[dict]:
    os.environ["LLM_FAST_GENERATE"] = "1" if mode == "fast" else "0"
    from chashibondhu.assistant.fosholi import ask_stream
    from chashibondhu.assistant.service import Assistant
    a = Assistant.from_env(ROOT)
    a._cache, a.cache_path = {}, None                  # measure real work, never the answer cache
    t = {"rewrite": 0.0, "search": 0.0}
    gen, search = a.llm.generate, a._search

    def timed_gen(system, user):
        s = time.perf_counter()
        try:
            return gen(system, user)
        finally:
            t["rewrite"] += time.perf_counter() - s

    def timed_search(q, k=6):
        s = time.perf_counter()
        try:
            return search(q, k=k)
        finally:
            t["search"] += time.perf_counter() - s

    a.llm.generate, a._search = timed_gen, timed_search
    a._search(questions[0], k=a.k)                     # warm the embedding model once (not counted)
    rows = []
    for q in questions:
        t["rewrite"] = t["search"] = 0.0
        start = time.perf_counter()
        first, status, model, n, err = None, "", "", 0, ""
        try:
            for ev in ask_stream(a, q):
                if ev["t"] == "s":
                    n += 1
                    first = first or time.perf_counter() - start
                elif ev["t"] == "done":
                    status, model = ev.get("status", ""), ev.get("model", "")
                elif ev["t"] == "error":
                    err = ev.get("code", "")
        except Exception as e:  # noqa: BLE001 - keep measuring the other questions
            err = type(e).__name__
        total = time.perf_counter() - start
        rows.append({"mode": mode, "question": q, "rewrite_s": round(t["rewrite"], 2), "search_s": round(t["search"], 2),
                     "first_sentence_s": round(first, 2) if first else "", "total_s": round(total, 2),
                     "sentences": n, "status": status or err, "model": model})
        print(f"INFO: [{mode}] total {total:5.1f}s  first {first or 0:5.1f}s  rewrite {t['rewrite']:4.1f}s  "
              f"search {t['search']:4.2f}s  {q[:40]}")
        time.sleep(pause)
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=["both", "fast", "legacy"], default="both")
    ap.add_argument("--questions", type=Path, help="text file, one question per line")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--pause", type=float, default=3.0, help="seconds between questions (free-tier limits)")
    args = ap.parse_args(argv)
    qs = QUESTIONS
    if args.questions:
        qs = [x.strip() for x in args.questions.read_text(encoding="utf-8").splitlines() if x.strip()]
    if args.limit:
        qs = qs[: args.limit]
    rows = []
    for mode in (["legacy", "fast"] if args.mode == "both" else [args.mode]):
        rows += run_mode(mode, qs, args.pause)
    out = ROOT / "data" / "interim" / "benchmarks"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"fosholi_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    for mode in sorted({r["mode"] for r in rows}):
        ok = [r for r in rows if r["mode"] == mode and r["sentences"]]
        if ok:
            print(f"INFO: {mode:6s} median total {statistics.median(r['total_s'] for r in ok):.1f}s | "
                  f"median first sentence {statistics.median(r['first_sentence_s'] for r in ok):.1f}s | "
                  f"median rewrite (Banglish only) "
                  f"{statistics.median([r['rewrite_s'] for r in ok if r['rewrite_s']] or [0]):.1f}s  ({len(ok)} answered)")
    print(f"INFO: saved {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
