"""briefs: persist the structured tradecraft sections

Key Assumptions Check, Indicators & Warnings, framed hypotheses, the ACH scoring
matrix, the credible alternative, intelligence gaps, and the red-team answer — so
the dashboard renders the full intelligence product instead of a text blob.

Revision ID: 0002_brief_tradecraft
Revises: 0001_initial
Create Date: 2026-06-28

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_brief_tradecraft"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSON_COLUMNS = ("key_assumptions", "indicators", "hypotheses", "ach_ranking")
_TEXT_COLUMNS = ("alternatives", "gaps", "critique_response")


def upgrade() -> None:
    for name in _JSON_COLUMNS:
        op.add_column("briefs", sa.Column(name, sa.JSON(), nullable=True))
    for name in _TEXT_COLUMNS:
        op.add_column("briefs", sa.Column(name, sa.Text(), nullable=True))


def downgrade() -> None:
    for name in reversed(_TEXT_COLUMNS + _JSON_COLUMNS):
        op.drop_column("briefs", name)
