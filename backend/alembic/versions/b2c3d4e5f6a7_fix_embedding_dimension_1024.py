"""fix embedding vector dimension to 1024 (Titan Embed v2 max)

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-04-07 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op


revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop the 1536-dim column and recreate as 1024
    # (pgvector does not support ALTER COLUMN for vector type dimension changes)
    op.execute("ALTER TABLE document_chunks DROP COLUMN IF EXISTS embedding")
    op.execute("ALTER TABLE document_chunks ADD COLUMN embedding vector(1024)")


def downgrade() -> None:
    op.execute("ALTER TABLE document_chunks DROP COLUMN IF EXISTS embedding")
    op.execute("ALTER TABLE document_chunks ADD COLUMN embedding vector(1536)")
