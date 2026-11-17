"""Ask the assistant from the command line (Phase 7).

  python scripts/ask_assistant.py "আলু কখন লাগাতে হয়?"
  python scripts/ask_assistant.py "alu kokhon lagate hoy"
  python scripts/ask_assistant.py --search-only "সরিষার জাত"     # no Gemini call
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("question")
    ap.add_argument("--search-only", action="store_true")
    args = ap.parse_args()

    if args.search_only:
        from chashibondhu.assistant.retrieval.index import E5Embedder, RagIndex
        index = RagIndex.load(ROOT / "data" / "processed" / "rag" / "kph10", E5Embedder())
        for h in index.search(args.question, k=5):
            c = h.chunk
            print(f"--- printed p.{c['printed_page']} (pdf {c['pdf_page']}) "
                  f"score={h.score} bm25={h.bm25_rank} dense={h.dense_rank}")
            print(c["text"][:300])
        return 0

    from chashibondhu.assistant.service import Assistant
    r = Assistant.from_env(ROOT).ask(args.question)
    print(f"[{r['status']}] requests={r['llm_requests']} cached={r['cached']}")
    print(r["answer"])
    for s in r["sources"]:
        print(f"  [{s['n']}] {s['source']}, page {s['printed_page']} (pdf {s['pdf_page']})")
    for s in r["removed_sentences"]:
        print(f"  removed (number not in source): {s}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
