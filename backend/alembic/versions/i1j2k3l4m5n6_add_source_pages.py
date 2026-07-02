"""Add source_pages column to document_trees for per-page content storage.

source_pages stores the per-page JSON from PageIndex extraction:
  [{"page": 1, "content": "...", "images": [...], "word_count": N, "headings": [...]}, ...]

This enables page-range retrieval at query time — the key capability that
separates the real PageIndex algorithm from simple tree navigation over
embedded node text.

Revision ID: i1j2k3l4m5n6
Revises: h1i2j3k4l5m6
Create Date: 2026-07-01
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "i1j2k3l4m5n6"
down_revision: Union[str, None] = "h1i2j3k4l5m6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "document_trees",
        sa.Column("source_pages", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "document_trees",
        sa.Column("page_count", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("document_trees", "page_count")
    op.drop_column("document_trees", "source_pages")
