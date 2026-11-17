"""Smarter hybrid search on the SAME saved index (Phase 7b). No rebuild needed.

Differences from RagIndex.search (which stays unchanged):
  * BM25 uses query_bn.bm25_tokens (stems + stopwords) - built in memory at start.
  * Problem questions get extra book words ("রোগ লক্ষণ দমন") for BM25 and dense.
  * Problem questions: passages tagged "problem" get +SECTION_BOOST, passages tagged
    "variety" get -VARIETY_PENALTY. SECTION_BOOST = 1/(RRF_K+1) is the same as being
    rank 1 in one more ranked list, so it stays on the RRF scale (no free tuning).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from chashibondhu.assistant.retrieval.index import RRF_K
from chashibondhu.assistant.retrieval.query_bn import bm25_tokens, plan_query, tag_passage

SECTION_BOOST = 1.0 / (RRF_K + 1)
VARIETY_PENALTY = SECTION_BOOST / 2


@dataclass
class SmartHit:
    chunk: dict
    score: float
    bm25_rank: int | None
    dense_rank: int | None
    dense_sim: float
    tag: str


class SmartSearch:
    def __init__(self, index, candidates: int = 30):
        from rank_bm25 import BM25Okapi
        if candidates < 1:
            raise ValueError("candidates must be >= 1")
        self.index = index
        self.candidates = candidates
        self.tags = [tag_passage(c["text"]) for c in index.chunks]
        self._bm25 = BM25Okapi([bm25_tokens(c["text"]) or ["_empty_"] for c in index.chunks])

    def search(self, query: str, k: int = 6) -> list[SmartHit]:
        plan = plan_query(query)
        if not plan.question:
            return []
        n = len(self.index.chunks)
        cand = min(self.candidates, n)

        scores = self._bm25.get_scores(list(plan.tokens)) if plan.tokens else np.zeros(n)
        bm25_order = [int(i) for i in np.argsort(-scores, kind="stable")[:cand] if scores[i] > 0]

        qv = self.index.embedder.encode([f"query: {plan.search_text}"])[0]
        sims = self.index.embeddings @ qv
        dense_order = [int(i) for i in np.argsort(-sims, kind="stable")[:cand]]

        bm25_rank = {i: r for r, i in enumerate(bm25_order, start=1)}
        dense_rank = {i: r for r, i in enumerate(dense_order, start=1)}
        fused: dict[int, float] = {}
        for ranks in (bm25_rank, dense_rank):
            for i, r in ranks.items():
                fused[i] = fused.get(i, 0.0) + 1.0 / (RRF_K + r)

        if plan.intent == "problem":
            for i in fused:
                if self.tags[i] == "problem":
                    fused[i] += SECTION_BOOST
                elif self.tags[i] == "variety":
                    fused[i] -= VARIETY_PENALTY

        best = sorted(fused, key=lambda i: (-fused[i], i))[:k]
        return [SmartHit(self.index.chunks[i], round(fused[i], 5), bm25_rank.get(i),
                         dense_rank.get(i), round(float(sims[i]), 4), self.tags[i])
                for i in best]
