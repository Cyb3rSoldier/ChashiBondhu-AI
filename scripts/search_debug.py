"""Compare SMART vs PLAIN book search for one question. No LLM calls (free).

Run:  python scripts/search_debug.py "আলুর পাতা হলুদ হয়ে যাচ্ছে কেন?" [--k 6]
Shows: question intent, the search text, passage tags, and both ranked lists.
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def _preview(text: str, n: int = 160) -> str:
    return " ".join(text.split())[:n]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("question")
    ap.add_argument("--k", type=int, default=6)
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass

    from chashibondhu.assistant.retrieval.index import E5Embedder, RagIndex
    from chashibondhu.assistant.retrieval.query_bn import plan_query, tag_passage
    from chashibondhu.assistant.retrieval.smart import SmartSearch

    index_dir = Path(os.environ.get("RAG_INDEX_DIR",
                                    ROOT / "data" / "processed" / "rag" / "kph10"))
    index = RagIndex.load(index_dir, E5Embedder())
    smart = SmartSearch(index)

    plan = plan_query(args.question)
    print(f"intent      : {plan.intent}")
    print(f"search text : {plan.search_text}")
    print(f"bm25 tokens : {' '.join(plan.tokens)}")
    print(f"passage tags: {dict(Counter(smart.tags))}")

    print("\n=== SMART ===")
    for h in smart.search(args.question, k=args.k):
        page = h.chunk.get("printed_page") or h.chunk["pdf_page"]
        print(f"--- p.{page} (pdf {h.chunk['pdf_page']}) [{h.tag}] score={h.score} "
              f"bm25={h.bm25_rank} dense={h.dense_rank}")
        print(_preview(h.chunk["text"]))

    print("\n=== PLAIN (old) ===")
    for h in index.search(args.question, k=args.k):
        page = h.chunk.get("printed_page") or h.chunk["pdf_page"]
        print(f"--- p.{page} (pdf {h.chunk['pdf_page']}) [{tag_passage(h.chunk['text'])}] "
              f"score={h.score} bm25={h.bm25_rank} dense={h.dense_rank}")
        print(_preview(h.chunk["text"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
