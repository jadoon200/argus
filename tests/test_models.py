from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from argus.db.models import Document, Source


def test_source_and_document_roundtrip(session: Session) -> None:
    session.add(Source(label="bbc-world", name="BBC World", kind="broadcaster", reliability="B"))
    session.add(
        Document(
            doc_id="bbc-world:abc123",
            source="bbc-world",
            title="Test headline",
            summary="A short summary.",
            url="https://example.com/a",
            language="en",
            published=datetime(2026, 6, 20).astimezone(),
            tags=["world", "test"],
        )
    )
    session.commit()

    doc = session.scalar(select(Document).where(Document.doc_id == "bbc-world:abc123"))
    assert doc is not None
    assert doc.source == "bbc-world"
    assert doc.tags == ["world", "test"]
    # credibility/embedding are unset until enrichment runs
    assert doc.credibility is None
    assert doc.embedding is None
    # ingested_at default is populated
    assert doc.ingested_at is not None


def test_json_columns_store_lists_and_dicts(session: Session) -> None:
    session.add(Source(label="gdelt", reliability="F"))
    session.add(
        Document(
            doc_id="gdelt:xyz",
            source="gdelt",
            title="Embedding doc",
            embedding=[0.1, 0.2, 0.3],
            raw={"domain": "example.com", "lang": "English"},
        )
    )
    session.commit()

    doc = session.get(Document, "gdelt:xyz")
    assert doc is not None
    assert doc.embedding == [0.1, 0.2, 0.3]
    assert doc.raw == {"domain": "example.com", "lang": "English"}
