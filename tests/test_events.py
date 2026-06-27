from datetime import UTC, datetime, timedelta

import numpy as np
from sqlalchemy.orm import Session

from argus.db.models import Document, Event, Source
from argus.nlp.events import cluster_documents, rebuild_events

_T = datetime(2026, 6, 20, tzinfo=UTC)


def test_cluster_groups_similar_within_window() -> None:
    emb = np.asarray([[1.0, 0.0], [0.99, 0.14], [0.0, 1.0]], dtype=np.float32)
    clusters = cluster_documents(emb, [_T, _T, _T], threshold=0.78, window=timedelta(days=3))
    assert sorted(sorted(c) for c in clusters) == [[0, 1], [2]]


def test_cluster_time_gate_splits_identical_but_distant() -> None:
    emb = np.asarray([[1.0, 0.0], [1.0, 0.0]], dtype=np.float32)
    times = [datetime(2026, 6, 1, tzinfo=UTC), datetime(2026, 6, 20, tzinfo=UTC)]
    clusters = cluster_documents(emb, times, threshold=0.78, window=timedelta(days=3))
    assert sorted(sorted(c) for c in clusters) == [[0], [1]]


def test_rebuild_events_clusters_and_scores_credibility(session: Session) -> None:
    for label in ("reuters.com", "bbc-world", "apnews.com"):
        session.add(Source(label=label, reliability="B"))
    session.add(
        Document(doc_id="a", source="reuters.com", title="x", embedding=[1.0, 0.0], published=_T)
    )
    session.add(
        Document(doc_id="b", source="bbc-world", title="x", embedding=[1.0, 0.0], published=_T)
    )
    session.add(
        Document(doc_id="c", source="apnews.com", title="y", embedding=[0.0, 1.0], published=_T)
    )
    session.flush()

    n = rebuild_events(session, threshold=0.78, window=timedelta(days=3))
    assert n == 2
    assert session.query(Event).count() == 2
    # a + b corroborate (2 distinct sources) -> credibility 3; c is single-source -> 4
    assert session.get(Document, "a").credibility == 3
    assert session.get(Document, "b").credibility == 3
    assert session.get(Document, "c").credibility == 4


def test_rebuild_events_empty_corpus(session: Session) -> None:
    assert rebuild_events(session, threshold=0.78, window=timedelta(days=3)) == 0
