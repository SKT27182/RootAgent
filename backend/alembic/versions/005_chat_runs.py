"""Durable, idempotent chat runs.

Revision ID: 005
Revises: 004
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    run_status = postgresql.ENUM(
        "running", "completed", "failed", name="chatrunstatus", create_type=False
    )
    run_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "chat_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chat_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("query_digest", sa.String(length=64), nullable=False),
        sa.Column("status", run_status, nullable=False),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("final_answer", sa.Text(), nullable=True),
        sa.Column("message_id", sa.String(length=64), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.String(length=512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "request_id", name="uq_chat_runs_user_request"),
    )
    op.create_index(
        "ix_chat_runs_chat_created",
        "chat_runs",
        ["chat_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_chat_runs_user_status",
        "chat_runs",
        ["user_id", "status"],
        unique=False,
    )
    op.create_index(
        "uq_chat_runs_active_chat",
        "chat_runs",
        ["chat_id"],
        unique=True,
        postgresql_where=sa.text("status = 'running'"),
    )
    op.add_column(
        "artifacts",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_artifacts_run_id_chat_runs",
        "artifacts",
        "chat_runs",
        ["run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_artifacts_run_id", "artifacts", ["run_id"], unique=False)
    op.create_unique_constraint(
        "uq_artifacts_run_sha256", "artifacts", ["run_id", "sha256"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_artifacts_run_sha256", "artifacts", type_="unique")
    op.drop_index("ix_artifacts_run_id", table_name="artifacts")
    op.drop_constraint(
        "fk_artifacts_run_id_chat_runs", "artifacts", type_="foreignkey"
    )
    op.drop_column("artifacts", "run_id")
    op.drop_index("uq_chat_runs_active_chat", table_name="chat_runs")
    op.drop_index("ix_chat_runs_user_status", table_name="chat_runs")
    op.drop_index("ix_chat_runs_chat_created", table_name="chat_runs")
    op.drop_table("chat_runs")
    op.execute("DROP TYPE IF EXISTS chatrunstatus")
