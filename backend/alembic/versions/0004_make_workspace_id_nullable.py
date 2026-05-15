"""make workspace_id nullable

Revision ID: 0004
Revises: 0003_multi_turn_eval
Create Date: 2026-03-26 13:05:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0004'
down_revision = '0003_multi_turn_eval'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Make workspace_id nullable to allow creating user before workspace
    op.alter_column('users', 'workspace_id',
                    existing_type=sa.UUID(),
                    nullable=True)


def downgrade() -> None:
    # Make workspace_id not nullable again
    op.alter_column('users', 'workspace_id',
                    existing_type=sa.UUID(),
                    nullable=False)
