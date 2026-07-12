"""Idempotent persistence for ingested documents — Prefect-free.

`persist`/`ensure_sources` are plain DB operations, not orchestration. Keeping them out of
`flows.py` (which imports Prefect) means the collect-on-demand path — and therefore the slim
API image — can persist documents without pulling the whole Prefect stack. `flows.py`
re-exports both for backward compatibility.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from argus.db.models import Document, Source
from argus.sources import grade_for, info_for


def ensure_sources(session: Session, labels: set[str]) -> None:
    """Upsert a Source row (name/kind/Admiralty grade) for each provenance label."""
    for label in labels:
        info = info_for(label)
        session.merge(
            Source(
                label=label,
                name=info.name if info else None,
                kind=info.kind if info else None,
                reliability=grade_for(label),
            )
        )
    session.flush()  # satisfy the Document.source FK before inserting documents


def persist(session: Session, docs: list[Document]) -> dict[str, int]:
    """Insert new documents only; preserve existing rows (and their enrichment)."""
    incoming = {d.doc_id: d for d in docs}  # de-dupe within the batch
    ensure_sources(session, {d.source for d in incoming.values()})
    existing = set(
        session.scalars(select(Document.doc_id).where(Document.doc_id.in_(incoming))).all()
    )
    new_docs = [d for doc_id, d in incoming.items() if doc_id not in existing]
    session.add_all(new_docs)
    return {
        "new": len(new_docs),
        "skipped": len(existing),
        "sources": len({d.source for d in incoming.values()}),
    }
