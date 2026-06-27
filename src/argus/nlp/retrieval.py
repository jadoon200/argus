"""Hybrid retrieval — BM25 lexical + dense semantic, fused by Reciprocal Rank Fusion.

RRF combines the two rankings without needing their scores to be comparable: a
document's fused score is sum over rankers of 1 / (k + rank). Dense is used only when
both the query and the document carry an embedding, so retrieval still works (lexical
only) before enrichment or in a no-model/offline run.
"""

import re
from dataclasses import dataclass

import numpy as np
from rank_bm25 import BM25Okapi

from argus.nlp.embed import Vector

_TOKEN_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class RetrievedDoc:
    doc_id: str
    text: str
    embedding: list[float] | None = None


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _ranks(scores: list[float]) -> dict[int, int]:
    """1-based competition rank per index (highest score = rank 1).

    Equal scores share the same (minimum) rank, so a tie in one ranker contributes
    equally to RRF and lets the *other* ranker break it — without this, BM25's
    index-order tiebreak would silently cancel the dense signal.
    """
    order = sorted(range(len(scores)), key=lambda i: -scores[i])
    ranks: dict[int, int] = {}
    prev_score: float | None = None
    prev_rank = 0
    for position, idx in enumerate(order, start=1):
        if prev_score is not None and scores[idx] == prev_score:
            ranks[idx] = prev_rank
        else:
            ranks[idx] = position
            prev_rank, prev_score = position, scores[idx]
    return ranks


def _cosine(a: Vector, b: Vector) -> float:
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    return float(np.dot(a, b) / (na * nb)) if na and nb else 0.0


def hybrid_search(
    query: str,
    docs: list[RetrievedDoc],
    query_embedding: Vector | None = None,
    top_k: int = 10,
    rrf_k: int = 60,
) -> list[tuple[str, float]]:
    """Return up to `top_k` (doc_id, fused_score) pairs, best first."""
    if not docs:
        return []

    bm25 = BM25Okapi([_tokenize(d.text) for d in docs])
    bm25_ranks = _ranks([float(s) for s in bm25.get_scores(_tokenize(query))])

    dense_ranks: dict[int, int] = {}
    if query_embedding is not None:
        idx = [i for i, d in enumerate(docs) if d.embedding is not None]
        if idx:
            sims = [
                _cosine(query_embedding, np.asarray(docs[i].embedding, dtype=np.float32))
                for i in idx
            ]
            local = _ranks(sims)
            dense_ranks = {idx[j]: local[j] for j in range(len(idx))}

    fused: dict[str, float] = {}
    for i, doc in enumerate(docs):
        score = 1.0 / (rrf_k + bm25_ranks[i])
        if i in dense_ranks:
            score += 1.0 / (rrf_k + dense_ranks[i])
        fused[doc.doc_id] = score

    ranked = sorted(fused.items(), key=lambda kv: (-kv[1], kv[0]))
    return ranked[:top_k]


def best_score_possible(rrf_k: int = 60) -> float:
    """Max attainable fused score (rank 1 in both rankers) — for normalising display."""
    return 2.0 / (rrf_k + 1)
