"""Enrichment pass over the corpus.

    python -m argus.nlp.enrich

For documents not yet enriched: compute and store a dense embedding, extract entities
into the entity graph. Then (re)cluster *all* embedded documents into events and score
each document's Admiralty credibility from its cluster's distinct-source corroboration.
Idempotent: embedding/entity work touches only un-enriched documents; event clustering
is a full rebuild of a derived view.
"""

from collections import Counter
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from argus.config import get_settings
from argus.db.base import session_scope
from argus.db.models import Document, DocumentEntity, Entity
from argus.logging import configure_logging, get_logger
from argus.nlp.embed import embed_texts
from argus.nlp.events import as_utc, rebuild_events
from argus.nlp.extract import entity_id, extract_entities

log = get_logger(__name__)


def _doc_text(doc: Document) -> str:
    return f"{doc.title}. {doc.summary}" if doc.summary else doc.title


def _now() -> datetime:
    return datetime.now().astimezone()


def _embed_pending(session: Session, pending: list[Document]) -> None:
    vectors = embed_texts([_doc_text(d) for d in pending])
    stamp = _now()
    for doc, vec in zip(pending, vectors, strict=True):
        doc.embedding = vec.tolist()
        doc.enriched_at = stamp


def _extract_pending(session: Session, pending: list[Document]) -> int:
    edges = 0
    for doc in pending:
        counts = Counter(extract_entities(_doc_text(doc)))
        for (name, etype), count in counts.items():
            eid = entity_id(name, etype)
            # NB: don't pass first_seen/last_seen into the merged Entity — merge copies
            # the constructor's values onto the existing row, which would clobber the
            # running min/max with the *current* doc's date (or None). The span is owned
            # solely by the comparisons below.
            entity = session.merge(Entity(entity_id=eid, name=name, type=etype))
            entity.mentions = (entity.mentions or 0) + count
            # as_utc on both sides: a persisted (SQLite-naive) span must compare cleanly
            # against a freshly-ingested (aware) publish time mid-collect-on-demand.
            pub = as_utc(doc.published)
            if pub is not None:
                first, last = as_utc(entity.first_seen), as_utc(entity.last_seen)
                if first is None or pub < first:
                    entity.first_seen = pub
                if last is None or pub > last:
                    entity.last_seen = pub
            session.merge(DocumentEntity(doc_id=doc.doc_id, entity_id=eid, count=count))
            edges += 1
    return edges


def run(session: Session) -> dict[str, int]:
    """Enrich the corpus on a given session (testable; no engine of its own)."""
    settings = get_settings()
    pending = list(session.scalars(select(Document).where(Document.embedding.is_(None))).all())
    if pending:
        _embed_pending(session, pending)
        session.flush()
        edges = _extract_pending(session, pending)
    else:
        edges = 0
    n_events = rebuild_events(
        session,
        settings.event_dedup_threshold,
        timedelta(days=settings.event_window_days),
    )
    stats = {"embedded": len(pending), "entity_edges": edges, "events": n_events}
    log.info("enrich_complete", **stats)
    return stats


def enrich() -> dict[str, int]:
    with session_scope() as session:
        return run(session)


if __name__ == "__main__":
    configure_logging()
    enrich()
