from sqlalchemy import select
from sqlalchemy.orm import Session

from argus.db.models import Document, Source
from argus.ingest.flows import persist


def _doc(doc_id: str, source: str) -> Document:
    return Document(
        doc_id=doc_id, source=source, title=f"title {doc_id}", url=f"https://x/{doc_id}"
    )


def test_persist_inserts_docs_and_creates_graded_sources(session: Session) -> None:
    stats = persist(
        session,
        [_doc("reuters.com:1", "reuters.com"), _doc("unknown.test:1", "unknown.test")],
    )
    session.commit()

    assert stats == {"new": 2, "skipped": 0, "sources": 2}
    # Known source gets its curated Admiralty grade; unknown defaults to F.
    assert session.get(Source, "reuters.com").reliability == "B"
    assert session.get(Source, "unknown.test").reliability == "F"
    assert session.scalar(select(Document).where(Document.doc_id == "reuters.com:1")) is not None


def test_persist_is_idempotent_and_preserves_enrichment(session: Session) -> None:
    persist(session, [_doc("reuters.com:1", "reuters.com")])
    session.commit()

    # Simulate enrichment having scored the document.
    doc = session.get(Document, "reuters.com:1")
    assert doc is not None
    doc.credibility = 2
    doc.embedding = [0.5, 0.5]
    session.commit()

    # Re-ingesting the same doc_id must not re-insert or clobber enrichment.
    stats = persist(session, [_doc("reuters.com:1", "reuters.com")])
    session.commit()
    assert stats["new"] == 0 and stats["skipped"] == 1

    refreshed = session.get(Document, "reuters.com:1")
    assert refreshed is not None
    assert refreshed.credibility == 2
    assert refreshed.embedding == [0.5, 0.5]


def test_persist_dedupes_within_batch(session: Session) -> None:
    stats = persist(
        session, [_doc("reuters.com:1", "reuters.com"), _doc("reuters.com:1", "reuters.com")]
    )
    session.commit()
    assert stats["new"] == 1
