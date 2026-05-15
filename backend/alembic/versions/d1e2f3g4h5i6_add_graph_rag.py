"""Add GraphRAG tables (graph_nodes, graph_edges).

Revision ID: d1e2f3g4h5i6
Revises: c1d2e3f4g5h6
Create Date: 2026-05-06
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "d1e2f3g4h5i6"
down_revision = "c1d2e3f4g5h6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Ensure pgvector extension exists
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Graph nodes (entities)
    op.create_table(
        "graph_nodes",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("kb_id", UUID(as_uuid=True), sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workspace_id", UUID(as_uuid=True), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("source_doc_ids", JSONB, nullable=False, server_default="[]"),
        sa.Column("properties", JSONB, nullable=False, server_default="{}"),
        sa.Column("mention_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )

    # Add vector column separately (pgvector syntax)
    op.execute("ALTER TABLE graph_nodes ADD COLUMN IF NOT EXISTS embedding vector(1024)")

    # Indexes for graph_nodes
    op.create_index("ix_graph_nodes_kb_id", "graph_nodes", ["kb_id"])
    op.create_index("ix_graph_nodes_name", "graph_nodes", ["kb_id", "name"])
    op.create_index("ix_graph_nodes_type", "graph_nodes", ["kb_id", "entity_type"])

    # Graph edges (relationships)
    op.create_table(
        "graph_edges",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("kb_id", UUID(as_uuid=True), sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_node_id", UUID(as_uuid=True), sa.ForeignKey("graph_nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_node_id", UUID(as_uuid=True), sa.ForeignKey("graph_nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("relationship_type", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("weight", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("source_doc_ids", JSONB, nullable=False, server_default="[]"),
        sa.Column("properties", JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )

    # Indexes for graph_edges
    op.create_index("ix_graph_edges_kb_id", "graph_edges", ["kb_id"])
    op.create_index("ix_graph_edges_source", "graph_edges", ["source_node_id"])
    op.create_index("ix_graph_edges_target", "graph_edges", ["target_node_id"])
    op.create_index("ix_graph_edges_type", "graph_edges", ["kb_id", "relationship_type"])


def downgrade() -> None:
    op.drop_table("graph_edges")
    op.drop_table("graph_nodes")
