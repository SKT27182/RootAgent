"""Add durable pending chat deletion state.

Revision ID: 006
Revises: 005
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "006"
down_revision: str | None = "005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "chats",
        sa.Column("deletion_requested_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_chats_deletion_requested_at", "chats", ["deletion_requested_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_chats_deletion_requested_at", table_name="chats")
    op.drop_column("chats", "deletion_requested_at")
