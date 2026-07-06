"""Event deduplication — cluster documents that report the same happening.

Single-pass greedy clustering over normalised embeddings within a time window: two
documents join the same event if their embeddings are similar enough AND they were
published close together. The number of *distinct sources* in a cluster is the
corroboration signal that drives each member document's Admiralty credibility.
"""

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
from numpy.typing import NDArray
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from argus.db.models import Document, Event, EventDocument
from argus.nlp.embed import Vector
from argus.nlp.reliability import credibility_from_corroboration

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _normalize(v: NDArray[Any]) -> Vector:
    norm = float(np.linalg.norm(v))
    result = v / norm if norm else v
    return np.asarray(result, dtype=np.float32)


def cluster_documents(
    embeddings: Vector,
    times: list[datetime | None],
    threshold: float,
    window: timedelta,
) -> list[list[int]]:
    """Greedily group document rows into event clusters; returns member-index lists.

    Documents are processed oldest-first. A document joins the most-similar existing
    cluster whose centroid cosine >= `threshold` and whose representative time is
    within `window` (the time gate is skipped when either timestamp is missing);
    otherwise it starts a new cluster.
    """
    n = len(times)
    order = sorted(range(n), key=lambda i: (times[i] is None, times[i] or _EPOCH))

    centroids: list[Vector] = []
    members: list[list[int]] = []
    rep_times: list[datetime | None] = []

    for i in order:
        vec = _normalize(embeddings[i])
        best, best_sim = -1, threshold
        for c, centroid in enumerate(centroids):
            sim = float(np.dot(vec, centroid))
            if sim < best_sim:
                continue
            t_i, t_c = times[i], rep_times[c]
            if t_i is not None and t_c is not None and abs(t_i - t_c) > window:
                continue
            best, best_sim = c, sim
        if best >= 0:
            members[best].append(i)
            k = len(members[best])
            centroids[best] = _normalize(centroids[best] * (k - 1) / k + vec / k)
        else:
            centroids.append(vec)
            members.append([i])
            rep_times.append(times[i])
    return members


def _event_id(doc_ids: list[str]) -> str:
    digest = hashlib.sha256("|".join(sorted(doc_ids)).encode()).hexdigest()
    return f"evt:{digest[:21]}"


def rebuild_events(session: Session, threshold: float, window: timedelta) -> int:
    """Recluster all embedded documents into events and (re)score credibility.

    Rebuilt from scratch each run (events are a derived view). Also writes each
    document's Admiralty credibility from its cluster's distinct-source count.
    """
    from argus.nlp.contest import framing_divergence  # local: contest imports events._normalize

    docs = list(session.scalars(select(Document).where(Document.embedding.is_not(None))).all())
    # Defensive: drop rows whose embedding is empty at the Python level (a stored JSON
    # `null` passes the SQL filter) — one bad row must not crash the whole rebuild.
    docs = [d for d in docs if d.embedding]
    if not docs:
        return 0
    embeddings = np.asarray([d.embedding for d in docs], dtype=np.float32)
    clusters = cluster_documents(embeddings, [d.published for d in docs], threshold, window)

    session.execute(delete(EventDocument))
    session.execute(delete(Event))
    session.flush()

    for member_idx in clusters:
        member_docs = [docs[i] for i in member_idx]
        doc_ids = [d.doc_id for d in member_docs]
        sources = {d.source for d in member_docs}
        published = [d.published for d in member_docs if d.published]
        representative = member_docs[0]
        event_id = _event_id(doc_ids)
        # Contested-event signal: how divergently the member sources frame the same event.
        divergence = framing_divergence(embeddings[member_idx]) if len(member_idx) > 1 else 0.0
        session.add(
            Event(
                event_id=event_id,
                title=representative.title,
                summary=representative.summary,
                occurred=min(published) if published else None,
                doc_count=len(doc_ids),
                source_count=len(sources),
                divergence=divergence,
            )
        )
        credibility = credibility_from_corroboration(len(sources))
        for doc in member_docs:
            doc.credibility = credibility
            session.add(EventDocument(event_id=event_id, doc_id=doc.doc_id))
    session.flush()
    return len(clusters)
