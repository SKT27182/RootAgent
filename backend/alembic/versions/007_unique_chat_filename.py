"""Enforce unique artifact filenames per chat.

Revision ID: 007
Revises: 006
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "007"
down_revision: str | None = "006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Keep the newest row per (chat_id, filename); drop older duplicates.
    op.execute(
        sa.text(
            """
            DELETE FROM artifacts AS older
            USING artifacts AS newer
            WHERE older.chat_id = newer.chat_id
              AND older.filename = newer.filename
              AND (
                older.created_at < newer.created_at
                OR (
                  older.created_at = newer.created_at
                  AND older.id < newer.id
                )
              )
            """
        )
    )
    op.create_unique_constraint(
        "uq_artifacts_chat_filename",
        "artifacts",
        ["chat_id", "filename"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_artifacts_chat_filename", "artifacts", type_="unique")
