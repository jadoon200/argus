import numpy as np

from argus.nlp.retrieval import RetrievedDoc, hybrid_search


def test_lexical_only_when_no_query_embedding() -> None:
    docs = [
        RetrievedDoc("d1", "naval patrols increase in disputed waters"),
        RetrievedDoc("d2", "central bank raises interest rates"),
    ]
    res = hybrid_search("naval patrol waters", docs, query_embedding=None, top_k=2)
    assert res[0][0] == "d1"


def test_dense_signal_breaks_lexical_tie() -> None:
    docs = [
        RetrievedDoc("d1", "report one", embedding=[1.0, 0.0]),
        RetrievedDoc("d2", "report two", embedding=[0.0, 1.0]),
    ]
    q = np.asarray([0.0, 1.0], dtype=np.float32)
    res = hybrid_search("report", docs, query_embedding=q, top_k=2)
    assert res[0][0] == "d2"  # equal lexically; dense favours d2


def test_missing_embeddings_fall_back_to_lexical() -> None:
    docs = [
        RetrievedDoc("d1", "typhoon makes landfall", embedding=None),
        RetrievedDoc("d2", "summit communique released", embedding=None),
    ]
    q = np.asarray([1.0, 0.0], dtype=np.float32)  # no doc embeddings -> dense skipped
    res = hybrid_search("typhoon landfall", docs, query_embedding=q, top_k=1)
    assert res[0][0] == "d1"


def test_empty_corpus() -> None:
    assert hybrid_search("anything", [], None) == []


def test_gold_set_saturates_lexical_retrieval() -> None:
    """Guards the claim in docs/EVAL.md that the ablation is unanswered.

    BM25 alone already ranks a relevant document first for every gold query, so the gold set
    cannot separate BM25 / dense / RRF — the retrieval table records that the retriever
    clears the fixture, not that fusion helps. If a future gold set stops saturating (a
    lexical miss appears), this fails, and the EVAL claim must be revisited rather than
    silently carried forward. Embedding-free: it asserts the *lexical* ceiling.
    """
    from argus.eval.goldset import CORPUS, QUERIES
    from argus.nlp.retrieval import RetrievedDoc, hybrid_search

    docs = [RetrievedDoc(d.doc_id, f"{d.title}. {d.summary}", embedding=None) for d in CORPUS]
    misses = [
        q.query
        for q in QUERIES
        if hybrid_search(q.query, docs, query_embedding=None, top_k=1)[0][0] not in q.relevant_ids
    ]
    assert not misses, (
        "BM25 no longer tops every gold query, so the gold set can now discriminate "
        f"between rankers — re-run scripts/eval_retrieval.py and update docs/EVAL.md: {misses}"
    )
