"""Authoritative UUID sessions, artifact metadata, and cleanup jobs.

Revision ID: 004
Revises: 003
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    artifact_output_kind = postgresql.ENUM(
        "png", "csv", "xlsx", name="artifactoutputkind", create_type=False
    )
    cleanup_operation = postgresql.ENUM(
        "artifact", "session", "user", name="cleanupoperation", create_type=False
    )
    cleanup_state = postgresql.ENUM(
        "pending",
        "running",
        "complete",
        "failed",
        name="cleanupstate",
        create_type=False,
    )
    artifact_output_kind.create(op.get_bind(), checkfirst=True)
    cleanup_operation.create(op.get_bind(), checkfirst=True)
    cleanup_state.create(op.get_bind(), checkfirst=True)

    op.drop_index("ix_chats_session_id", table_name="chats")
    op.alter_column(
        "chats",
        "session_id",
        existing_type=sa.String(length=64),
        type_=postgresql.UUID(as_uuid=True),
        postgresql_using="session_id::uuid",
        nullable=False,
    )
    op.create_unique_constraint(
        "uq_chats_user_session", "chats", ["user_id", "session_id"]
    )
    op.create_index(
        "ix_chats_user_updated", "chats", ["user_id", "updated_at"], unique=False
    )

    op.add_column(
        "artifacts", sa.Column("sha256", sa.String(length=64), nullable=False)
    )
    op.add_column(
        "artifacts", sa.Column("output_kind", artifact_output_kind, nullable=True)
    )
    op.add_column("artifacts", sa.Column("width", sa.Integer(), nullable=True))
    op.add_column("artifacts", sa.Column("height", sa.Integer(), nullable=True))
    op.create_index(
        "ix_artifacts_chat_source_created",
        "artifacts",
        ["chat_id", "source", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_artifacts_user_created",
        "artifacts",
        ["user_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "cleanup_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("operation", cleanup_operation, nullable=False),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "object_keys",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "workspace_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "redis_keys",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "state",
            cleanup_state,
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_cleanup_jobs_state_next_attempt",
        "cleanup_jobs",
        ["state", "next_attempt_at"],
        unique=False,
    )
    op.create_index(
        "ix_cleanup_jobs_user_created",
        "cleanup_jobs",
        ["user_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_cleanup_jobs_user_created", table_name="cleanup_jobs")
    op.drop_index("ix_cleanup_jobs_state_next_attempt", table_name="cleanup_jobs")
    op.drop_table("cleanup_jobs")

    op.drop_index("ix_artifacts_user_created", table_name="artifacts")
    op.drop_index("ix_artifacts_chat_source_created", table_name="artifacts")
    op.drop_column("artifacts", "height")
    op.drop_column("artifacts", "width")
    op.drop_column("artifacts", "output_kind")
    op.drop_column("artifacts", "sha256")

    op.drop_index("ix_chats_user_updated", table_name="chats")
    op.drop_constraint("uq_chats_user_session", "chats", type_="unique")
    op.alter_column(
        "chats",
        "session_id",
        existing_type=postgresql.UUID(as_uuid=True),
        type_=sa.String(length=64),
        postgresql_using="session_id::text",
        nullable=False,
    )
    op.create_index("ix_chats_session_id", "chats", ["session_id"], unique=True)

    op.execute("DROP TYPE IF EXISTS cleanupstate")
    op.execute("DROP TYPE IF EXISTS cleanupoperation")
    op.execute("DROP TYPE IF EXISTS artifactoutputkind")
