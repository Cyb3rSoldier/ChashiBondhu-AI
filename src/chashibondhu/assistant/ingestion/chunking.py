"""Cut book pages into small passages for search (Phase 7).

A passage never crosses a page, so every answer can cite one exact page.
~900 characters of Bangla stays under the e5 model's 512-token limit.
"""
from __future__ import annotations


def chunk_pages(pages: list[dict], max_chars: int = 900, overlap_lines: int = 2,
                source_id: str = "BARI_KPH10") -> list[dict]:
    if max_chars < 100:
        raise ValueError("max_chars must be >= 100")
    chunks: list[dict] = []
    for page in pages:
        lines: list[str] = []
        for line in page["text"].split("\n"):
            line = line.strip()
            while len(line) > max_chars:          # very long line: hard split
                lines.append(line[:max_chars])
                line = line[max_chars:]
            if line:
                lines.append(line)

        current: list[str] = []
        size = 0
        fresh = 0          # lines added since the last flush (overlap lines not counted)
        part = 0

        def flush() -> None:
            nonlocal part
            text = "\n".join(current).strip()
            if text:
                chunks.append({"chunk_id": f"{source_id}:p{page['pdf_page']}:{part}",
                               "source_id": source_id,
                               "pdf_page": page["pdf_page"],
                               "printed_page": page.get("printed_page"),
                               "text": text})
                part += 1

        for line in lines:
            if current and size + len(line) + 1 > max_chars:
                if fresh:
                    flush()
                    current = current[-overlap_lines:] if overlap_lines else []
                else:
                    current = []          # only overlap left: drop it, avoid duplicates
                size = sum(len(x) + 1 for x in current)
                fresh = 0
                if current and size + len(line) + 1 > max_chars:
                    current, size = [], 0
            current.append(line)
            size += len(line) + 1
            fresh += 1
        if fresh:
            flush()
    return chunks
