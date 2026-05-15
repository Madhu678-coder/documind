"""Initial schema

Revision ID: 0001
Revises: None
Create Date: 2024-01-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, ARRAY, UUID

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable pgcrypto for gen_random_uuid()
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # 1. workspaces
    op.create_table(
        "workspaces",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("owner_id", UUID(as_uuid=True), nullable=False),
        sa.Column("settings", JSONB(), nullable=False, server_default="{}"),
    )

    # 2. users
    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=False, unique=True),
        sa.Column(
            "role",
            sa.Enum("admin", "editor", "viewer", name="userrole"),
            nullable=False,
            server_default="viewer",
        ),
        sa.Column("workspace_id", UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_users_workspace_id", "users", ["workspace_id"])

    # Add FK from workspaces.owner_id -> users.id (deferred to avoid circular dep)
    op.create_foreign_key("fk_workspaces_owner_id", "workspaces", "users", ["owner_id"], ["id"])

    # 3. knowledge_bases
    op.create_table(
        "knowledge_bases",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workspace_id", UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("settings", JSONB(), nullable=False, server_default="{}"),
    )
    op.create_index("ix_knowledge_bases_workspace_id", "knowledge_bases", ["workspace_id"])

    # 4. documents
    op.create_table(
        "documents",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workspace_id", UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("kb_id", UUID(as_uuid=True), sa.ForeignKey("knowledge_bases.id"), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("file_path", sa.String(), nullable=False),
        sa.Column("file_type", sa.String(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("uploading", "processing", "ready", "failed", name="documentstatus"),
            nullable=False,
            server_default="uploading",
        ),
        sa.Column("uploaded_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_documents_workspace_id", "documents", ["workspace_id"])
    op.create_index("ix_documents_kb_id", "documents", ["kb_id"])

    # 5. document_trees
    op.create_table(
        "document_trees",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("document_id", UUID(as_uuid=True), sa.ForeignKey("documents.id"), nullable=False, unique=True),
        sa.Column("tree_json", JSONB(), nullable=False),
        sa.Column("built_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("llm_model_used", sa.String(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("executive_summary", sa.Text(), nullable=True),
        sa.Column("key_entities", JSONB(), nullable=True),
        sa.Column("document_tags", ARRAY(sa.String()), nullable=True),
        sa.Column("complexity_score", sa.Float(), nullable=True),
    )

    # 6. chat_sessions
    op.create_table(
        "chat_sessions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workspace_id", UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("kb_id", UUID(as_uuid=True), sa.ForeignKey("knowledge_bases.id"), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_chat_sessions_workspace_id", "chat_sessions", ["workspace_id"])
    op.create_index("ix_chat_sessions_kb_id", "chat_sessions", ["kb_id"])

    # 7. chat_messages
    op.create_table(
        "chat_messages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("session_id", UUID(as_uuid=True), sa.ForeignKey("chat_sessions.id"), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("citations", JSONB(), nullable=True),
        sa.Column("reasoning_trace", JSONB(), nullable=True),
        sa.Column("node_ids_visited", ARRAY(sa.String()), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_chat_messages_session_id", "chat_messages", ["session_id"])

    # 8. document_session_links
    op.create_table(
        "document_session_links",
        sa.Column("session_id", UUID(as_uuid=True), sa.ForeignKey("chat_sessions.id"), primary_key=True),
        sa.Column("document_id", UUID(as_uuid=True), sa.ForeignKey("documents.id"), primary_key=True),
    )

    # 9. eval_results
    op.create_table(
        "eval_results",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("message_id", UUID(as_uuid=True), sa.ForeignKey("chat_messages.id"), nullable=False),
        sa.Column("document_id", UUID(as_uuid=True), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("faithfulness_score", sa.Float(), nullable=False),
        sa.Column("faithfulness_reason", sa.Text(), nullable=False),
        sa.Column("answer_relevancy_score", sa.Float(), nullable=False),
        sa.Column("contextual_precision_score", sa.Float(), nullable=False),
        sa.Column("contextual_recall_score", sa.Float(), nullable=False),
        sa.Column("hallucination_score", sa.Float(), nullable=False),
        sa.Column("overall_pass", sa.Boolean(), nullable=False),
        sa.Column("eval_model", sa.String(), nullable=False),
        sa.Column("triggered_by", sa.String(), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_eval_results_message_id", "eval_results", ["message_id"])

    # 10. eval_config
    op.create_table(
        "eval_config",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workspace_id", UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=False, unique=True),
        sa.Column("faithfulness_threshold", sa.Float(), nullable=False, server_default="0.85"),
        sa.Column("answer_relevancy_threshold", sa.Float(), nullable=False, server_default="0.80"),
        sa.Column("contextual_precision_threshold", sa.Float(), nullable=False, server_default="0.75"),
        sa.Column("contextual_recall_threshold", sa.Float(), nullable=False, server_default="0.75"),
        sa.Column("hallucination_threshold", sa.Float(), nullable=False, server_default="0.15"),
    )

    # 11. audit_logs
    op.create_table(
        "audit_logs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("resource_type", sa.String(), nullable=False),
        sa.Column("resource_id", UUID(as_uuid=True), nullable=False),
        sa.Column("metadata", JSONB(), nullable=False, server_default="{}"),
        sa.Column("timestamp", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_audit_logs_user_id", "audit_logs", ["user_id"])


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("eval_config")
    op.drop_table("eval_results")
    op.drop_table("document_session_links")
    op.drop_table("chat_messages")
    op.drop_table("chat_sessions")
    op.drop_table("document_trees")
    op.drop_table("documents")
    op.drop_table("knowledge_bases")
    op.drop_constraint("fk_workspaces_owner_id", "workspaces", type_="foreignkey")
    op.drop_table("users")
    op.drop_table("workspaces")
    op.execute("DROP TYPE IF EXISTS userrole")
    op.execute("DROP TYPE IF EXISTS documentstatus")
    op.execute("DROP EXTENSION IF EXISTS pgcrypto")
