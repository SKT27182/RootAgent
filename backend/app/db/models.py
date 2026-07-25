"""SQLAlchemy models for RootAgent."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.postgres import Base


class UserRole(str, enum.Enum):
    """INFRA_ADMIN: main_db.users (infra-hub). ADMIN: RootAgent-only. USER: standard."""

    INFRA_ADMIN = "INFRA_ADMIN"
    ADMIN = "ADMIN"
    USER = "USER"


class ArtifactSource(str, enum.Enum):
    UPLOAD = "upload"
    GENERATED = "generated"


class ArtifactOutputKind(str, enum.Enum):
    PNG = "png"
    CSV = "csv"
    XLSX = "xlsx"


class CleanupOperation(str, enum.Enum):
    ARTIFACT = "artifact"
    SESSION = "session"
    USER = "user"


class CleanupState(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"


class ChatRunStatus(str, enum.Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


def _enum_values(enum_type: type[enum.Enum]) -> list[str]:
    return [str(member.value) for member in enum_type]


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole), default=UserRole.USER, nullable=False
    )
    infra_hub_user_id: Mapped[int | None] = mapped_column(
        nullable=True, unique=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    chats: Mapped[list["Chat"]] = relationship(
        back_populates="user", passive_deletes=True
    )
    artifacts: Mapped[list["Artifact"]] = relationship(
        back_populates="user", passive_deletes=True
    )
    chat_runs: Mapped[list["ChatRun"]] = relationship(
        back_populates="user", passive_deletes=True
    )

class Chat(Base):
    """User-owned conversation. Deleting a chat cascades to runs and artifacts.

    Application code must wipe MinIO/Redis/workspaces before DELETE so cascades
    only remove Postgres rows after external resources are gone.
    """
    __tablename__ = "chats"
    __table_args__ = (
        UniqueConstraint("user_id", "session_id", name="uq_chats_user_session"),
        Index("ix_chats_user_updated", "user_id", "updated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    deletion_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    user: Mapped["User"] = relationship(back_populates="chats")
    artifacts: Mapped[list["Artifact"]] = relationship(
        back_populates="chat", passive_deletes=True
    )
    runs: Mapped[list["ChatRun"]] = relationship(
        back_populates="chat", passive_deletes=True
    )


class ChatRun(Base):
    """Durable idempotency and recovery record for one chat execution."""

    __tablename__ = "chat_runs"
    __table_args__ = (
        UniqueConstraint("user_id", "request_id", name="uq_chat_runs_user_request"),
        Index("ix_chat_runs_chat_created", "chat_id", "created_at"),
        Index("ix_chat_runs_user_status", "user_id", "status"),
        Index(
            "uq_chat_runs_active_chat",
            "chat_id",
            unique=True,
            postgresql_where=text("status = 'running'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    chat_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chats.id", ondelete="CASCADE"), nullable=False
    )
    request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    query_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[ChatRunStatus] = mapped_column(
        Enum(ChatRunStatus, name="chatrunstatus", values_callable=_enum_values),
        default=ChatRunStatus.RUNNING,
        nullable=False,
    )
    correlation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    final_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    message_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user: Mapped["User"] = relationship(back_populates="chat_runs")
    chat: Mapped["Chat"] = relationship(back_populates="runs")
    generated_artifacts: Mapped[list["Artifact"]] = relationship(back_populates="run")


class Artifact(Base):
    __tablename__ = "artifacts"
    __table_args__ = (
        Index("ix_artifacts_user_chat", "user_id", "chat_id"),
        Index("ix_artifacts_chat_source_created", "chat_id", "source", "created_at"),
        Index("ix_artifacts_user_created", "user_id", "created_at"),
        UniqueConstraint("run_id", "sha256", name="uq_artifacts_run_sha256"),
        UniqueConstraint("chat_id", "filename", name="uq_artifacts_chat_filename"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    chat_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chats.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chat_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(1024), unique=True, nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[ArtifactSource] = mapped_column(
        Enum(
            ArtifactSource,
            name="artifactsource",
            values_callable=_enum_values,
        ),
        default=ArtifactSource.UPLOAD,
        nullable=False,
    )
    output_kind: Mapped[ArtifactOutputKind | None] = mapped_column(
        Enum(
            ArtifactOutputKind,
            name="artifactoutputkind",
            values_callable=_enum_values,
        ),
        nullable=True,
    )
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="artifacts")
    chat: Mapped["Chat"] = relationship(back_populates="artifacts")
    run: Mapped["ChatRun | None"] = relationship(
        back_populates="generated_artifacts",
        passive_deletes=True,
    )


class CleanupJob(Base):
    """Durable record for eventually consistent external-resource cleanup."""

    __tablename__ = "cleanup_jobs"
    __table_args__ = (
        Index("ix_cleanup_jobs_state_next_attempt", "state", "next_attempt_at"),
        Index("ix_cleanup_jobs_user_created", "user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    operation: Mapped[CleanupOperation] = mapped_column(
        Enum(
            CleanupOperation,
            name="cleanupoperation",
            values_callable=_enum_values,
        ),
        nullable=False,
    )
    subject_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    object_keys: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    redis_keys: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    workspace_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    state: Mapped[CleanupState] = mapped_column(
        Enum(CleanupState, name="cleanupstate", values_callable=_enum_values),
        default=CleanupState.PENDING,
        nullable=False,
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
