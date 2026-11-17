"""Hybrid search index: BM25 (exact words) + multilingual-e5-small (meaning) (Phase 7).

Both run on CPU. The two ranked lists are merged with Reciprocal Rank Fusion (RRF),
which needs no score tuning: score = sum(1 / (60 + rank)).

Saved files (in the index folder):
  chunks.jsonl     one passage per line (text + page numbers)
  embeddings.npy   float32 [n_chunks, 384], L2-normalized
  meta.json        model name, counts, build date
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

import numpy as np

E5_MODEL = "intfloat/multilingual-e5-small"
RRF_K = 60
_BN_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")
_TOKEN_RE = re.compile(r"[\u0980-\u09FF]+|[a-z]+|\d+")


def normalize_text(text: str) -> str:
    return unicodedata.normalize("NFC", text).translate(_BN_DIGITS).casefold()


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(normalize_text(text))


class Embedder(Protocol):
    name: str

    def encode(self, texts: list[str]) -> np.ndarray: ...


class E5Embedder:
    """multilingual-e5-small via sentence-transformers. First use downloads the model
    from Hugging Face (about 0.5 GB) into the local cache. CPU is fine."""

    def __init__(self, model_name: str = E5_MODEL):
        from sentence_transformers import SentenceTransformer   # heavy: import lazily
        self.name = model_name
        self._model = SentenceTransformer(model_name, device="cpu")

    def encode(self, texts: list[str]) -> np.ndarray:
        return np.asarray(self._model.encode(texts, batch_size=32, normalize_embeddings=True,
                                             show_progress_bar=len(texts) > 64),
                          dtype=np.float32)


@dataclass
class Hit:
    chunk: dict
    score: float
    bm25_rank: int | None
    dense_rank: int | None
    dense_sim: float


class RagIndex:
    def __init__(self, chunks: list[dict], embeddings: np.ndarray, embedder: Embedder,
                 meta: dict | None = None):
        if len(chunks) != len(embeddings):
            raise ValueError("chunks and embeddings have different lengths")
        if not chunks:
            raise ValueError("index is empty")
        from rank_bm25 import BM25Okapi
        self.chunks = chunks
        self.embeddings = embeddings.astype(np.float32)
        self.embedder = embedder
        self.meta = meta or {}
        self._bm25 = BM25Okapi([tokenize(c["text"]) for c in chunks])

    # ------------------------------------------------------------ build / io
    @classmethod
    def build(cls, chunks: list[dict], embedder: Embedder) -> "RagIndex":
        emb = embedder.encode([f"passage: {c['text']}" for c in chunks])
        meta = {"embedding_model": embedder.name, "n_chunks": len(chunks),
                "built_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        return cls(chunks, emb, embedder, meta)

    def save(self, folder: Path) -> None:
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        with open(folder / "chunks.jsonl", "w", encoding="utf-8") as f:
            for c in self.chunks:
                f.write(json.dumps(c, ensure_ascii=False) + "\n")
        np.save(folder / "embeddings.npy", self.embeddings)
        (folder / "meta.json").write_text(json.dumps(self.meta, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, folder: Path, embedder: Embedder) -> "RagIndex":
        folder = Path(folder)
        for name in ("chunks.jsonl", "embeddings.npy", "meta.json"):
            if not (folder / name).exists():
                raise FileNotFoundError(f"index file missing: {folder / name}")
        meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
        if meta.get("embedding_model") != embedder.name:
            raise ValueError(f"index was built with {meta.get('embedding_model')}, "
                             f"not {embedder.name}; rebuild the index")
        with open(folder / "chunks.jsonl", encoding="utf-8") as f:
            chunks = [json.loads(line) for line in f if line.strip()]
        return cls(chunks, np.load(folder / "embeddings.npy"), embedder, meta)

    # ------------------------------------------------------------ search
    def search(self, query: str, k: int = 5, candidates: int = 20) -> list[Hit]:
        if not query.strip():
            return []
        n = len(self.chunks)
        candidates = min(candidates, n)

        bm25_scores = self._bm25.get_scores(tokenize(query))
        bm25_order = [i for i in np.argsort(-bm25_scores)[:candidates] if bm25_scores[i] > 0]

        q = self.embedder.encode([f"query: {query}"])[0]
        sims = self.embeddings @ q
        dense_order = list(np.argsort(-sims)[:candidates])

        fused: dict[int, float] = {}
        bm25_rank = {int(i): r for r, i in enumerate(bm25_order, start=1)}
        dense_rank = {int(i): r for r, i in enumerate(dense_order, start=1)}
        for ranks in (bm25_rank, dense_rank):
            for i, r in ranks.items():
                fused[i] = fused.get(i, 0.0) + 1.0 / (RRF_K + r)

        best = sorted(fused, key=lambda i: -fused[i])[:k]
        return [Hit(self.chunks[i], round(fused[i], 5), bm25_rank.get(i), dense_rank.get(i),
                    round(float(sims[i]), 4)) for i in best]
