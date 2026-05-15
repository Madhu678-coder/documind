"""Add wiki_pages table for Wiki RAG mode.

Revision ID: c1d2e3f4g5h6
Revises: b2c3d4e5f6a7
Create Date: 2026-04-08 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c1d2e3f4g5h6"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "wiki_pages",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "kb_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("page_type", sa.Text(), nullable=False, server_default="general"),
        sa.Column("source_doc_ids", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column(
            "related_titles",
            postgresql.ARRAY(sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("llm_model_used", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("idx_wiki_pages_kb_id", "wiki_pages", ["kb_id"])
    op.create_index("idx_wiki_pages_workspace_id", "wiki_pages", ["workspace_id"])
    # Composite index for kb+title lookups (used for merge key matching)
    op.create_index("idx_wiki_pages_kb_title", "wiki_pages", ["kb_id", "title"])


def downgrade() -> None:
    op.drop_index("idx_wiki_pages_kb_title", table_name="wiki_pages")
    op.drop_index("idx_wiki_pages_workspace_id", table_name="wiki_pages")
    op.drop_index("idx_wiki_pages_kb_id", table_name="wiki_pages")
    op.drop_table("wiki_pages")
