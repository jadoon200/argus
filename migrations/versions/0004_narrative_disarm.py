"""narratives: DISARM influence-ops technique tags

Revision ID: 0004_narrative_disarm
Revises: 0003_event_divergence
Create Date: 2026-07-05

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_narrative_disarm"
down_revision: str | None = "0003_event_divergence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# JSONB on Postgres, plain JSON elsewhere — mirrors the models' JsonType.
_JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.add_column("narratives", sa.Column("disarm", _JSON, nullable=True))


def downgrade() -> None:
    op.drop_column("narratives", "disarm")
