"""Measure Layer 2a retrieval on the gold set: BM25 vs dense vs RRF.

`docs/EVAL.md` carried `TBD` for every retrieval number since the milestone landed. This
scores the three rankers over the same labelled queries so the ablation answers a real
question — does fusing actually beat either half, or is the hybrid decoration?

**Cut-off honesty.** The gold corpus is 20 documents, so `Recall@20` is 1.0 by construction
and `Recall@10` only asks whether a relevant document reached the top half. Neither
separates a good ranker from a poor one here, so they are reported but marked
uninformative, and the operating metrics are `Recall@1/3/5` and MRR — matching how the
fixture was actually designed ("the corpus is large enough that recall@3 can fail").

Run locally, where the full embedding model is present:

    PYTHONPATH=src python scripts/eval_retrieval.py
"""

from __future__ import annotations

import numpy as np

from argus.eval.goldset import CORPUS, QUERIES
from argus.eval.metrics import recall_at_k, reciprocal_rank
from argus.nlp.embed import embed_texts
from argus.nlp.retrieval import RetrievedDoc, hybrid_search

CUTOFFS = (1, 3, 5, 10, 20)
# Cut-offs at or above the corpus size cannot discriminate — flagged rather than dropped, so
# the table shows why the numbers the doc originally asked for are not the ones to read.
INFORMATIVE = tuple(k for k in CUTOFFS if k < len(CORPUS))


def _rank_dense(query_vec: np.ndarray, doc_ids: list[str], doc_vecs: np.ndarray) -> list[str]:
    """Pure dense ranking — cosine over normalised vectors, best first."""
    sims = doc_vecs @ query_vec
    order = np.argsort(-sims, kind="stable")
    return [doc_ids[i] for i in order]


def _rank_bm25(query: str, docs: list[RetrievedDoc]) -> list[str]:
    """Pure lexical ranking: hybrid_search with no query embedding is BM25 alone."""
    ranked = hybrid_search(query, docs, query_embedding=None, top_k=len(docs))
    return [doc_id for doc_id, _ in ranked]


def _rank_rrf(query: str, docs: list[RetrievedDoc], query_vec: np.ndarray) -> list[str]:
    ranked = hybrid_search(query, docs, query_embedding=query_vec, top_k=len(docs))
    return [doc_id for doc_id, _ in ranked]


def main() -> None:
    doc_ids = [d.doc_id for d in CORPUS]
    texts = [f"{d.title}. {d.summary}" for d in CORPUS]
    text_by_id = dict(zip(doc_ids, texts, strict=True))

    print(f"embedding {len(CORPUS)} gold documents + {len(QUERIES)} queries…")
    doc_vecs = embed_texts(texts)
    query_vecs = embed_texts([q.query for q in QUERIES])

    plain = [RetrievedDoc(d, text_by_id[d], embedding=None) for d in doc_ids]
    embedded = [
        RetrievedDoc(d, text_by_id[d], embedding=doc_vecs[i]) for i, d in enumerate(doc_ids)
    ]

    rankers = {
        "BM25 only": lambda q, qv: _rank_bm25(q.query, plain),
        "Dense only": lambda q, qv: _rank_dense(qv, doc_ids, doc_vecs),
        "RRF hybrid": lambda q, qv: _rank_rrf(q.query, embedded, qv),
    }

    results: dict[str, dict[str, float]] = {}
    for name, rank in rankers.items():
        recalls: dict[int, list[float]] = {k: [] for k in CUTOFFS}
        rrs: list[float] = []
        for q, qv in zip(QUERIES, query_vecs, strict=True):
            ranked = rank(q, qv)
            for k in CUTOFFS:
                recalls[k].append(recall_at_k(ranked, q.relevant_ids, k))
            rrs.append(reciprocal_rank(ranked, q.relevant_ids))
        results[name] = {
            **{f"R@{k}": float(np.mean(recalls[k])) for k in CUTOFFS},
            "MRR": float(np.mean(rrs)),
        }

    header = "| Ranker | " + " | ".join(f"R@{k}" for k in INFORMATIVE) + " | MRR |"
    print()
    print(f"Gold set: {len(CORPUS)} documents, {len(QUERIES)} labelled queries")
    print(header)
    print("|---" * (len(INFORMATIVE) + 2) + "|")
    for name, scores in results.items():
        cells = " | ".join(f"{scores[f'R@{k}']:.3f}" for k in INFORMATIVE)
        print(f"| {name} | {cells} | {scores['MRR']:.3f} |")

    uninformative = [k for k in CUTOFFS if k not in INFORMATIVE]
    if uninformative:
        print()
        for k in uninformative:
            vals = {name: scores[f"R@{k}"] for name, scores in results.items()}
            flat = len(set(round(v, 6) for v in vals.values())) == 1
            print(
                f"R@{k}: {', '.join(f'{n} {v:.3f}' for n, v in vals.items())}"
                f"{'  — identical across rankers; cut-off >= corpus size' if flat else ''}"
            )


if __name__ == "__main__":
    main()
