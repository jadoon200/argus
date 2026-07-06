"""Narrative watch — cluster documents into narratives and score coordination.

    python -m argus.narrative.run    # make narratives

A full rebuild of a derived view: cluster embedded documents into narratives (shared
framing), then score each on its coordination signal (synchronization x low-reliability
share) for an analyst to review.
"""

import hashlib
from datetime import timedelta
from typing import Any

import numpy as np
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from argus.config import get_settings
from argus.db.base import session_scope
from argus.db.models import Document, Narrative, NarrativeDocument, Source
from argus.logging import configure_logging, get_logger
from argus.narrative.cluster import cluster_narratives
from argus.narrative.coordination import coordination_score
from argus.nlp.disarm import DisarmMapper
from argus.nlp.embed import Vector

log = get_logger(__name__)


def _narrative_id(doc_ids: list[str]) -> str:
    digest = hashlib.sha256("|".join(sorted(doc_ids)).encode()).hexdigest()
    return f"nar:{digest[:21]}"


def _disarm_tags(
    mapper: DisarmMapper | None, centroid: Vector, top_k: int, threshold: float
) -> list[dict[str, Any]] | None:
    """DISARM techniques the narrative centroid resembles ([] -> None). Never raises: a
    tagging failure (model load, dim mismatch) must not break the whole narrative rebuild."""
    if mapper is None:
        return None
    try:
        matches = mapper.map_vector(centroid, top_k=top_k, threshold=threshold)
    except Exception as exc:  # advisory enrichment: degrade to no tags, never break the rebuild
        log.warning("disarm_tagging_failed", error=str(exc))
        return None
    return [m.as_dict() for m in matches] or None


def rebuild_narratives(
    session: Session,
    threshold: float,
    min_size: int,
    window: timedelta,
    mapper: DisarmMapper | None = None,
    disarm_top_k: int = 3,
    disarm_threshold: float = 0.28,
) -> int:
    docs = list(session.scalars(select(Document).where(Document.embedding.is_not(None))).all())
    if not docs:
        return 0
    embeddings = np.asarray([d.embedding for d in docs], dtype=np.float32)
    clusters = cluster_narratives(embeddings, threshold, min_size)
    reliability = {s.label: s.reliability for s in session.scalars(select(Source)).all()}

    session.execute(delete(NarrativeDocument))
    session.execute(delete(Narrative))
    session.flush()

    for member_idx in clusters:
        member_docs = [docs[i] for i in member_idx]
        doc_ids = [d.doc_id for d in member_docs]
        times = [d.published for d in member_docs]
        published = [t for t in times if t is not None]
        coordination = coordination_score(
            times, [reliability.get(d.source, "F") for d in member_docs], window
        )
        centroid = embeddings[member_idx].mean(axis=0)
        disarm = _disarm_tags(mapper, centroid, disarm_top_k, disarm_threshold)
        representative = member_docs[0]
        narrative_id = _narrative_id(doc_ids)
        session.add(
            Narrative(
                narrative_id=narrative_id,
                label=representative.title,
                summary=representative.summary,
                doc_count=len(doc_ids),
                source_count=len({d.source for d in member_docs}),
                coordination=coordination,
                disarm=disarm,
                first_seen=min(published) if published else None,
                last_seen=max(published) if published else None,
            )
        )
        for doc_id in doc_ids:
            session.add(NarrativeDocument(narrative_id=narrative_id, doc_id=doc_id))
    session.flush()
    return len(clusters)


def refresh(session: Session) -> int:
    """Rebuild the narrative view with settings-configured knobs + DISARM tagging — the
    one entry point shared by `make narratives`, collect-on-demand, and the hydration
    backfill, so every path produces the same view."""
    settings = get_settings()
    return rebuild_narratives(
        session,
        settings.narrative_threshold,
        settings.narrative_min_cluster_size,
        timedelta(hours=settings.coordination_window_hours),
        mapper=DisarmMapper(),  # tag each narrative with DISARM techniques (real encoder)
        disarm_top_k=settings.disarm_top_k,
        disarm_threshold=settings.disarm_threshold,
    )


def main() -> None:
    configure_logging()
    with session_scope() as session:
        count = refresh(session)
    log.info("narratives_rebuilt", narratives=count)


if __name__ == "__main__":
    main()
