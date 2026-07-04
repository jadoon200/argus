"""events: framing-divergence (contested-event) signal

Revision ID: 0003_event_divergence
Revises: 0002_brief_tradecraft
Create Date: 2026-07-05

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_event_divergence"
down_revision: str | None = "0002_brief_tradecraft"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("events", sa.Column("divergence", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("events", "divergence")
