from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from argus.db.base import Base

# JSONB on Postgres, plain JSON elsewhere (keeps unit tests runnable on SQLite).
JsonType = JSON().with_variant(postgresql.JSONB(), "postgresql")


def _now() -> datetime:
    return datetime.now().astimezone()


class Source(Base):
    """An open-source publisher with a curated NATO-Admiralty reliability rating.

    `reliability` is the Admiralty source-reliability grade A-F (A = completely
    reliable ... F = cannot be judged), assigned from the transparent per-source
    map in `nlp/reliability.py` -- shown to the analyst, never hidden.
    """

    __tablename__ = "sources"

    label: Mapped[str] = mapped_column(
        String(64), primary_key=True
    )  # provenance key, e.g. "bbc-world"
    name: Mapped[str | None] = mapped_column(String(255))
    kind: Mapped[str | None] = mapped_column(
        String(32)
    )  # wire|broadcaster|state|advisory|aggregator|other
    reliability: Mapped[str] = mapped_column(String(1), default="F")
    homepage: Mapped[str | None] = mapped_column(String(2048))
    notes: Mapped[str | None] = mapped_column(Text())


class Document(Base):
    """An ingested open-source item — a GDELT article or an RSS entry."""

    __tablename__ = "documents"

    doc_id: Mapped[str] = mapped_column(String(255), primary_key=True)  # "<source>:<hash>"
    source: Mapped[str] = mapped_column(ForeignKey("sources.label"), index=True)
    title: Mapped[str] = mapped_column(Text())
    summary: Mapped[str | None] = mapped_column(Text())
    url: Mapped[str | None] = mapped_column(String(2048))
    language: Mapped[str | None] = mapped_column(String(16))
    country: Mapped[str | None] = mapped_column(String(64))
    published: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    # NATO Admiralty information credibility 1 (confirmed) .. 6 (cannot be judged),
    # derived from corroboration at enrichment time; null until scored.
    credibility: Mapped[int | None] = mapped_column(Integer())
    # Cached dense embedding (list[float]) for retrieval/clustering; stored in-DB so
    # the SQLite test path needs no vector extension.
    embedding: Mapped[list[float] | None] = mapped_column(JsonType)
    tags: Mapped[list[str] | None] = mapped_column(JsonType)
    raw: Mapped[dict[str, Any] | None] = mapped_column(JsonType)
    enriched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Entity(Base):
    """A normalized entity (person/org/place/event) extracted from documents."""

    __tablename__ = "entities"

    entity_id: Mapped[str] = mapped_column(
        String(64), primary_key=True
    )  # hash(type, normalized name)
    name: Mapped[str] = mapped_column(String(512), index=True)
    type: Mapped[str] = mapped_column(String(32), index=True)  # PERSON|ORG|GPE|EVENT|...
    mentions: Mapped[int] = mapped_column(Integer(), default=0)
    first_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DocumentEntity(Base):
    """Edge: a document mentions an entity (with a per-document mention count)."""

    __tablename__ = "document_entities"

    doc_id: Mapped[str] = mapped_column(ForeignKey("documents.doc_id"), primary_key=True)
    entity_id: Mapped[str] = mapped_column(
        ForeignKey("entities.entity_id"), primary_key=True, index=True
    )
    count: Mapped[int] = mapped_column(Integer(), default=1)


class Event(Base):
    """A deduplicated event — a cluster of documents reporting the same happening.

    `source_count` is the number of *independent* sources reporting it; it drives the
    Admiralty information-credibility score assigned to the member documents.
    """

    __tablename__ = "events"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(Text())
    summary: Mapped[str | None] = mapped_column(Text())
    location: Mapped[str | None] = mapped_column(String(255))
    occurred: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    doc_count: Mapped[int] = mapped_column(Integer(), default=0)
    source_count: Mapped[int] = mapped_column(Integer(), default=0)
    # Framing divergence in [0,1] — how differently the member sources frame the same
    # event (contested-event signal, the inverse of narrative coordination). See nlp/contest.py.
    divergence: Mapped[float | None] = mapped_column(Float())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class EventDocument(Base):
    """Membership edge between an event and a document."""

    __tablename__ = "event_documents"

    event_id: Mapped[str] = mapped_column(ForeignKey("events.event_id"), primary_key=True)
    doc_id: Mapped[str] = mapped_column(ForeignKey("documents.doc_id"), primary_key=True)


class Narrative(Base):
    """A cluster of documents pushing a similar claim/narrative (Layer 2b).

    `coordination` in [0,1] measures how synchronized/concentrated the pushing is —
    a human-review signal, never an automated verdict.
    """

    __tablename__ = "narratives"

    narrative_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str] = mapped_column(Text())
    summary: Mapped[str | None] = mapped_column(Text())
    doc_count: Mapped[int] = mapped_column(Integer(), default=0)
    source_count: Mapped[int] = mapped_column(Integer(), default=0)
    coordination: Mapped[float | None] = mapped_column(Float())
    # DISARM influence-ops techniques the narrative's framing resembles (advisory, human-review):
    # list of {technique_id, name, phase, score}. See nlp/disarm.py. Symmetric to SENTINEL ATT&CK.
    disarm: Mapped[list[dict[str, Any]] | None] = mapped_column(JsonType)
    first_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class NarrativeDocument(Base):
    """Membership edge between a narrative and a document."""

    __tablename__ = "narrative_documents"

    narrative_id: Mapped[str] = mapped_column(
        ForeignKey("narratives.narrative_id"), primary_key=True
    )
    doc_id: Mapped[str] = mapped_column(ForeignKey("documents.doc_id"), primary_key=True)


class Brief(Base):
    """A generated, cited intelligence brief (cached for the dashboard).

    `citations` holds the `doc_id`s referenced inline in `body`; every one must
    resolve to a real Document — the eval harness enforces this.
    """

    __tablename__ = "briefs"

    brief_id: Mapped[int] = mapped_column(Integer(), primary_key=True, autoincrement=True)
    query: Mapped[str] = mapped_column(Text())
    body: Mapped[str] = mapped_column(Text())
    key_judgments: Mapped[list[str] | None] = mapped_column(JsonType)
    citations: Mapped[list[str] | None] = mapped_column(JsonType)  # doc_ids
    confidence: Mapped[str | None] = mapped_column(String(16))  # low|moderate|high
    # Structured Analytic Technique sections (see agent/schemas.py Finding) — persisted
    # so the dashboard renders the full intelligence product, not a text blob.
    key_assumptions: Mapped[list[str] | None] = mapped_column(JsonType)  # Key Assumptions Check
    indicators: Mapped[list[str] | None] = mapped_column(JsonType)  # Indicators & Warnings
    hypotheses: Mapped[list[str] | None] = mapped_column(JsonType)  # competing hypotheses framed
    # ACH scoring matrix rows: {hypothesis, inconsistency, consistent, inconsistent}.
    ach_ranking: Mapped[list[dict[str, Any]] | None] = mapped_column(JsonType)
    alternatives: Mapped[str | None] = mapped_column(Text())  # most credible alternative
    gaps: Mapped[str | None] = mapped_column(Text())  # intelligence gaps
    critique_response: Mapped[str | None] = mapped_column(Text())  # answer to the red team
    backend: Mapped[str | None] = mapped_column(String(32))  # which LLM backend produced it
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
