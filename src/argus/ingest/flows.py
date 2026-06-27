"""Prefect ingestion flow — collect open-source reporting on a topic into the corpus.

    python -m argus.ingest.flows "South China Sea"

Pulls GDELT articles for the query plus the curated RSS feeds, ensures a Source row
(with its Admiralty grade) exists for every provenance label, and inserts the *new*
documents — existing ones are left untouched so a re-run never clobbers enrichment.
"""

import sys

from prefect import flow, task
from sqlalchemy import select
from sqlalchemy.orm import Session

from argus.db.base import session_scope
from argus.db.models import Document, Source
from argus.ingest.gdelt import fetch_gdelt_articles
from argus.ingest.rss import fetch_rss_documents
from argus.logging import configure_logging, get_logger
from argus.sources import grade_for, info_for

log = get_logger(__name__)


@task
def collect(query: str) -> list[Document]:
    docs = fetch_gdelt_articles(query)
    docs.extend(fetch_rss_documents())
    return docs


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


@flow(name="argus-ingest")
def ingest(query: str) -> dict[str, int]:
    docs = collect(query)
    with session_scope() as session:
        stats = persist(session, docs)
    log.info("ingest_complete", query=query, **stats)
    return stats


if __name__ == "__main__":
    configure_logging()
    topic = " ".join(sys.argv[1:]).strip() or "Singapore security"
    ingest(topic)
