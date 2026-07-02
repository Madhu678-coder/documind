"""Add openkb_pages table for OpenKB RAG mode.

Revision ID: g1h2i3j4k5l6
Revises: d1e2f3g4h5i6
Create Date: 2026-07-01

OpenKB is a separate RAG mode that compiles documents into a structured,
interlinked wiki with distinct page categories (summary, concept, entity,
index, exploration).  This table is completely independent of wiki_pages.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "g1h2i3j4k5l6"
down_revision: Union[str, None] = "d1e2f3g4h5i6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "openkb_pages",
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
        sa.Column("page_category", sa.Text(), nullable=False, server_default="concept"),
        sa.Column("page_type", sa.Text(), nullable=False, server_default="concept"),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
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

    op.create_index("idx_openkb_pages_kb_id", "openkb_pages", ["kb_id"])
    op.create_index("idx_openkb_pages_workspace_id", "openkb_pages", ["workspace_id"])
    op.create_index("idx_openkb_pages_kb_title", "openkb_pages", ["kb_id", "title"])
    op.create_index("idx_openkb_pages_category", "openkb_pages", ["kb_id", "page_category"])


def downgrade() -> None:
    op.drop_index("idx_openkb_pages_category", table_name="openkb_pages")
    op.drop_index("idx_openkb_pages_kb_title", table_name="openkb_pages")
    op.drop_index("idx_openkb_pages_workspace_id", table_name="openkb_pages")
    op.drop_index("idx_openkb_pages_kb_id", table_name="openkb_pages")
    op.drop_table("openkb_pages")
