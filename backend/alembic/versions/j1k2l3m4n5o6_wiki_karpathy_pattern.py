"""Add Karpathy wiki pattern support — connection/qa/index/log page types.

Revision ID: j1k2l3m4n5o6
Revises: i1j2k3l4m5n6
Create Date: 2026-07-01

No schema changes required — the wiki_pages table already has all needed columns:
  - page_type TEXT: extended to accept "connection" | "qa" | "index" | "log"
  - content TEXT: stores YAML frontmatter embedded at top
  - source_doc_ids JSONB: tracks source documents
  - related_titles ARRAY: tracks cross-page links

This migration creates indexes to speed up lookups on the new page types.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision: str = "j1k2l3m4n5o6"
down_revision: str = "i1j2k3l4m5n6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Index for fast lookup of structural pages (index/log) per KB
    op.create_index(
        "ix_wiki_pages_kb_page_type",
        "wiki_pages",
        ["kb_id", "page_type"],
        unique=False,
    )
    # Index for fast title lookup per KB (used by merge logic and lint)
    op.create_index(
        "ix_wiki_pages_kb_title",
        "wiki_pages",
        ["kb_id", "title"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_wiki_pages_kb_title", table_name="wiki_pages")
    op.drop_index("ix_wiki_pages_kb_page_type", table_name="wiki_pages")
