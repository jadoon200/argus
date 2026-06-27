"""initial schema: sources, documents, entities, events, narratives, briefs

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-27

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sources",
        sa.Column("label", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("kind", sa.String(32), nullable=True),
        sa.Column("reliability", sa.String(1), nullable=False, server_default="F"),
        sa.Column("homepage", sa.String(2048), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
    )

    op.create_table(
        "documents",
        sa.Column("doc_id", sa.String(255), primary_key=True),
        sa.Column("source", sa.String(64), sa.ForeignKey("sources.label"), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("url", sa.String(2048), nullable=True),
        sa.Column("language", sa.String(16), nullable=True),
        sa.Column("country", sa.String(64), nullable=True),
        sa.Column("published", sa.DateTime(timezone=True), nullable=True),
        sa.Column("credibility", sa.Integer(), nullable=True),
        sa.Column("embedding", sa.JSON(), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=True),
        sa.Column("raw", sa.JSON(), nullable=True),
        sa.Column("enriched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_documents_source", "documents", ["source"])
    op.create_index("ix_documents_published", "documents", ["published"])

    op.create_table(
        "entities",
        sa.Column("entity_id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(512), nullable=False),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("mentions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_entities_name", "entities", ["name"])
    op.create_index("ix_entities_type", "entities", ["type"])

    op.create_table(
        "document_entities",
        sa.Column("doc_id", sa.String(255), sa.ForeignKey("documents.doc_id"), primary_key=True),
        sa.Column(
            "entity_id", sa.String(64), sa.ForeignKey("entities.entity_id"), primary_key=True
        ),
        sa.Column("count", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index("ix_document_entities_entity_id", "document_entities", ["entity_id"])

    op.create_table(
        "events",
        sa.Column("event_id", sa.String(64), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("location", sa.String(255), nullable=True),
        sa.Column("occurred", sa.DateTime(timezone=True), nullable=True),
        sa.Column("doc_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_events_occurred", "events", ["occurred"])

    op.create_table(
        "event_documents",
        sa.Column("event_id", sa.String(64), sa.ForeignKey("events.event_id"), primary_key=True),
        sa.Column("doc_id", sa.String(255), sa.ForeignKey("documents.doc_id"), primary_key=True),
    )

    op.create_table(
        "narratives",
        sa.Column("narrative_id", sa.String(64), primary_key=True),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("doc_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("coordination", sa.Float(), nullable=True),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "narrative_documents",
        sa.Column(
            "narrative_id",
            sa.String(64),
            sa.ForeignKey("narratives.narrative_id"),
            primary_key=True,
        ),
        sa.Column("doc_id", sa.String(255), sa.ForeignKey("documents.doc_id"), primary_key=True),
    )

    op.create_table(
        "briefs",
        sa.Column("brief_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("key_judgments", sa.JSON(), nullable=True),
        sa.Column("citations", sa.JSON(), nullable=True),
        sa.Column("confidence", sa.String(16), nullable=True),
        sa.Column("backend", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("briefs")
    op.drop_table("narrative_documents")
    op.drop_table("narratives")
    op.drop_table("event_documents")
    op.drop_table("events")
    op.drop_index("ix_document_entities_entity_id", table_name="document_entities")
    op.drop_table("document_entities")
    op.drop_index("ix_entities_type", table_name="entities")
    op.drop_index("ix_entities_name", table_name="entities")
    op.drop_table("entities")
    op.drop_index("ix_documents_published", table_name="documents")
    op.drop_index("ix_documents_source", table_name="documents")
    op.drop_table("documents")
    op.drop_table("sources")
