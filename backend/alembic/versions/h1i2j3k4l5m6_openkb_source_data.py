"""Add source_data and doc_type columns to openkb_pages.

source_data  — per-page JSON content for long (PageIndex) documents.
doc_type     — "short" | "pageindex".

Revision ID: h1i2j3k4l5m6
Revises: g1h2i3j4k5l6
Create Date: 2026-07-01
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "h1i2j3k4l5m6"
down_revision: Union[str, None] = "g1h2i3j4k5l6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "openkb_pages",
        sa.Column("doc_type", sa.Text(), nullable=True, server_default="short"),
    )
    op.add_column(
        "openkb_pages",
        sa.Column("source_data", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("openkb_pages", "source_data")
    op.drop_column("openkb_pages", "doc_type")
