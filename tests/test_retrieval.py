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
