"""add vector rag support

Revision ID: a1b2c3d4e5f6
Revises: 0004
Create Date: 2026-04-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Create document_chunks table
    op.create_table(
        'document_chunks',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('document_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('kb_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('workspace_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('chunk_index', sa.Integer(), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('char_start', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('char_end', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('page_number', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('parent_chunk_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('chunk_metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('NOW()')),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['kb_id'], ['knowledge_bases.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['parent_chunk_id'], ['document_chunks.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )

    # Add vector column via raw SQL (SQLAlchemy has no native vector type)
    op.execute("ALTER TABLE document_chunks ADD COLUMN embedding vector(1536)")

    # Indexes for document_chunks
    op.execute("CREATE INDEX ON document_chunks (kb_id, workspace_id)")
    op.execute("CREATE INDEX ON document_chunks (document_id)")
    op.execute("CREATE INDEX ON document_chunks USING GIN (to_tsvector('english', text))")

    # Create model_provider_configs table
    op.create_table(
        'model_provider_configs',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('workspace_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('provider_type', sa.String(), nullable=False),
        sa.Column('provider_name', sa.String(), nullable=False),
        sa.Column('model_id', sa.String(), nullable=False),
        sa.Column('api_key', sa.String(), nullable=True),
        sa.Column('region', sa.String(), nullable=True),
        sa.Column('extra_config', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),
        sa.Column('is_default', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('NOW()')),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.execute("CREATE INDEX ON model_provider_configs (workspace_id, provider_type)")


def downgrade() -> None:
    op.drop_table('model_provider_configs')
    op.drop_table('document_chunks')
    op.execute("DROP EXTENSION IF EXISTS vector")
