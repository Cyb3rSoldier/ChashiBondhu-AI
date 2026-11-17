"""List book passages about diseases/pests for every crop, to help you fill
data/reference/crop_problems.csv (Phase 14). No LLM calls (free). You decide what goes in.

Run:  python scripts/draft_crop_problems.py [--k 8]
Out:  data/reference/extractions/crop_problems_candidates.csv  (crop, query, page, text preview)
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--k", type=int, default=8)
    args = ap.parse_args()
    import pandas as pd

    from chashibondhu.assistant.retrieval.index import E5Embedder, RagIndex
    from chashibondhu.assistant.retrieval.smart import SmartSearch

    cat = pd.read_csv(ROOT / "data" / "reference" / "crop_catalogue.csv", dtype=str).fillna("")
    index_dir = Path(os.environ.get("RAG_INDEX_DIR", ROOT / "data" / "processed" / "rag" / "kph10"))
    search = SmartSearch(RagIndex.load(index_dir, E5Embedder()))
    out = ROOT / "data" / "reference" / "extractions" / "crop_problems_candidates.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = 0
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["crop_id", "query", "printed_page", "pdf_page", "tag", "text_preview"])
        for r in cat.itertuples():
            for topic in ("রোগ লক্ষণ দমন", "পোকা লক্ষণ দমন"):
                query = f"{r.name_bn} {topic}"
                for h in search.search(query, k=args.k):
                    if h.tag != "problem":
                        continue
                    w.writerow([r.crop_id, query, h.chunk.get("printed_page"),
                                h.chunk["pdf_page"], h.tag, " ".join(h.chunk["text"].split())[:300]])
                    rows += 1
    print(f"{rows} candidate passages -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
