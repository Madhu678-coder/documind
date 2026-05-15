"""Add multi_turn_enabled to eval_config

Revision ID: 0003_multi_turn_eval
Revises: 99cb697df279
Create Date: 2026-03-26
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_multi_turn_eval"
down_revision = "99cb697df279"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "eval_config",
        sa.Column(
            "multi_turn_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("eval_config", "multi_turn_enabled")
