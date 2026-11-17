"""Build the search index for the BARI book (Phase 7).

  python scripts/build_rag_index.py --fonts --max-pages 40     # 1) check fonts only
  python scripts/build_rag_index.py --max-pages 60             # 2) quick test index
  python scripts/build_rag_index.py                            # 3) full book

Writes data/processed/rag/kph10/ (chunks.jsonl, embeddings.npy, meta.json) and
pages_preview.txt so you can read a few converted pages and check the Bangla.
No Gemini calls here: everything runs on your PC.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from chashibondhu.assistant.ingestion.chunking import chunk_pages  # noqa: E402
from chashibondhu.assistant.ingestion.pdf_bijoy import extract_pages, font_report  # noqa: E402

DEFAULT_PDF = ROOT / "data" / "raw" / "books" / "krishiProjuktiHatboi_10.pdf"
DEFAULT_OUT = ROOT / "data" / "processed" / "rag" / "kph10"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", type=Path, default=DEFAULT_PDF)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--page-offset", type=int, default=25, help="printed page = pdf page - offset")
    ap.add_argument("--max-pages", type=int, default=None)
    ap.add_argument("--fonts", action="store_true", help="only list fonts and stop")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if not args.pdf.exists():
        logging.error("PDF not found: %s", args.pdf)
        return 1
    if args.fonts:
        for font, n, bijoy, sample in font_report(args.pdf, args.max_pages or 40):
            print(f"{'BIJOY ' if bijoy else 'normal'} | {n:6d} spans | {font} | {sample}")
        return 0

    pages = extract_pages(args.pdf, args.page_offset, args.max_pages)
    chunks = chunk_pages(pages)
    logging.info("pages with text: %d | chunks: %d", len(pages), len(chunks))
    if not chunks:
        logging.error("no text extracted; is this a scanned (image-only) PDF?")
        return 1

    args.out.mkdir(parents=True, exist_ok=True)
    preview = [p for p in pages if p["printed_page"]][:3]
    (args.out / "pages_preview.txt").write_text(
        "\n\n".join(f"===== pdf page {p['pdf_page']} / printed {p['printed_page']} =====\n"
                    f"{p['text'][:1500]}" for p in preview), encoding="utf-8")

    from chashibondhu.assistant.retrieval.index import E5Embedder, RagIndex
    logging.info("embedding with multilingual-e5-small on CPU (first run downloads the model)")
    index = RagIndex.build(chunks, E5Embedder())
    index.meta.update({"pdf": args.pdf.name, "page_offset": args.page_offset,
                       "max_pages": args.max_pages})
    index.save(args.out)
    for f in ("answer_cache.json",):            # old answers belong to the old index
        (args.out / f).unlink(missing_ok=True)
    logging.info("Saved %s", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
