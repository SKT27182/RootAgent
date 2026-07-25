"""Artifact lifecycle: authoritative Postgres metadata plus durable object cleanup."""

from __future__ import annotations

import hashlib
import uuid
from io import BytesIO
from typing import BinaryIO

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Artifact,
    ArtifactOutputKind,
    ArtifactSource,
    Chat,
    User,
)
from app.models.chat import ArtifactEventMetadata
from app.schemas.artifact import ArtifactResponse
from app.services.file_validation import (
    PNG_MEDIA_TYPE,
    sanitize_display_filename,
    validate_and_reencode_png,
)
from app.services.storage import StorageService, get_storage_service
from app.utils.logger import create_logger

logger = create_logger(__name__)


class DuplicateArtifactFilenameError(ValueError):
    """Raised when a chat already has an artifact with the same display filename."""

    def __init__(self, filename: str) -> None:
        self.filename = filename
        super().__init__(
            f"An artifact named '{filename}' already exists in this chat. "
            "Choose a different name."
        )


def _session_uuid(session_id: uuid.UUID | str) -> uuid.UUID:
    return session_id if isinstance(session_id, uuid.UUID) else uuid.UUID(session_id)


def storage_path(
    user_id: uuid.UUID,
    chat_id: uuid.UUID,
    artifact_id: uuid.UUID,
    *,
    source: ArtifactSource = ArtifactSource.UPLOAD,
) -> str:
    """Build an internal key exclusively from server-owned UUIDs.

    Layout:
      {user_id}/{chat_id}/upload/{artifact_id}
      {user_id}/{chat_id}/generated/{artifact_id}
    """
    kind = "upload" if source == ArtifactSource.UPLOAD else "generated"
    return f"{user_id}/{chat_id}/{kind}/{artifact_id}"


def chat_storage_prefix(user_id: uuid.UUID, chat_id: uuid.UUID) -> str:
    """Prefix covering every MinIO object for one chat."""
    return f"{user_id}/{chat_id}/"


def user_storage_prefix(user_id: uuid.UUID) -> str:
    """Prefix covering every MinIO object for one user."""
    return f"{user_id}/"


def to_artifact_response(
    artifact: Artifact, session_id: uuid.UUID
) -> ArtifactResponse:
    """Build complete authenticated artifact metadata for HTTP or run events."""
    content_url = f"/artifacts/{session_id}/{artifact.id}/content"
    return ArtifactResponse(
        id=artifact.id,
        chat_id=artifact.chat_id,
        filename=artifact.filename,
        content_type=artifact.content_type,
        file_size=artifact.file_size,
        sha256=artifact.sha256,
        source=artifact.source,
        output_kind=artifact.output_kind,
        width=artifact.width,
        height=artifact.height,
        created_at=artifact.created_at,
        content_url=content_url,
        download_url=f"/artifacts/{session_id}/{artifact.id}/download",
        preview_url=f"/artifacts/{session_id}/{artifact.id}/preview",
    )


def to_artifact_event_metadata(
    artifact: Artifact, session_id: uuid.UUID
) -> ArtifactEventMetadata:
    """Build the bounded artifact model carried by the run event protocol."""
    response = to_artifact_response(artifact, session_id)
    return ArtifactEventMetadata.model_validate(response.model_dump())


async def get_owned_chat(
    db: AsyncSession,
    user_id: uuid.UUID,
    session_id: uuid.UUID | str,
) -> Chat:
    session_uuid = _session_uuid(session_id)
    result = await db.execute(
        select(Chat).where(
            Chat.session_id == session_uuid,
            Chat.user_id == user_id,
        )
    )
    chat = result.scalar_one_or_none()
    if chat is None:
        raise ValueError("Session not found")
    return chat


def user_can_access_artifact(user: User, artifact: Artifact) -> bool:
    return artifact.user_id == user.id


async def create_artifact_from_stream(
    db: AsyncSession,
    user: User,
    session_id: uuid.UUID | str,
    filename: str,
    content_type: str,
    stream: BinaryIO,
    file_size: int,
    sha256: str,
    *,
    source: ArtifactSource = ArtifactSource.UPLOAD,
    output_kind: ArtifactOutputKind | None = None,
    width: int | None = None,
    height: int | None = None,
    storage: StorageService | None = None,
) -> Artifact:
    storage = storage or get_storage_service()
    chat = await get_owned_chat(db, user.id, session_id)
    safe_filename = sanitize_display_filename(filename, fallback=str(uuid.uuid4()))
    existing = await db.execute(
        select(Artifact.id).where(
            Artifact.chat_id == chat.id,
            Artifact.filename == safe_filename,
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise DuplicateArtifactFilenameError(safe_filename)

    artifact_id = uuid.uuid4()
    object_key = storage_path(user.id, chat.id, artifact_id, source=source)

    stream.seek(0)
    await storage.upload_stream(object_key, stream, file_size, content_type)

    artifact = Artifact(
        id=artifact_id,
        user_id=user.id,
        chat_id=chat.id,
        filename=safe_filename,
        content_type=content_type,
        storage_path=object_key,
        file_size=file_size,
        sha256=sha256,
        source=source,
        output_kind=output_kind,
        width=width,
        height=height,
    )
    db.add(artifact)
    try:
        await db.commit()
        await db.refresh(artifact)
    except Exception:
        await db.rollback()
        try:
            await storage.delete_file(object_key)
        except Exception:
            logger.warning(
                "Failed to remove uploaded object after metadata rollback: %s",
                object_key,
                exc_info=True,
            )
        raise
    return artifact


async def create_artifact(
    db: AsyncSession,
    user: User,
    session_id: uuid.UUID | str,
    filename: str,
    content_type: str,
    data: bytes,
    source: ArtifactSource = ArtifactSource.UPLOAD,
    storage: StorageService | None = None,
) -> Artifact:
    """Compatibility entry point for generated byte artifacts."""
    output_kind: ArtifactOutputKind | None = None
    width: int | None = None
    height: int | None = None
    if source == ArtifactSource.GENERATED and content_type == PNG_MEDIA_TYPE:
        png = validate_and_reencode_png(data)
        data = png.data
        width, height = png.width, png.height
        output_kind = ArtifactOutputKind.PNG
        digest = png.sha256
    else:
        digest = hashlib.sha256(data).hexdigest()

    return await create_artifact_from_stream(
        db,
        user,
        session_id,
        filename,
        content_type,
        BytesIO(data),
        len(data),
        digest,
        source=source,
        output_kind=output_kind,
        width=width,
        height=height,
        storage=storage,
    )


async def list_artifacts_for_chat(
    db: AsyncSession,
    user: User,
    session_id: uuid.UUID | str,
) -> list[Artifact]:
    result = await db.execute(
        select(Chat).where(
            Chat.session_id == _session_uuid(session_id),
            Chat.user_id == user.id,
        )
    )
    chat = result.scalar_one_or_none()
    if not chat:
        return []

    result = await db.execute(
        select(Artifact)
        .where(Artifact.chat_id == chat.id)
        .order_by(Artifact.created_at.desc())
    )
    return list(result.scalars().all())


async def get_artifact_for_user(
    db: AsyncSession,
    user: User,
    session_id: uuid.UUID | str,
    artifact_id: uuid.UUID,
) -> Artifact | None:
    result = await db.execute(
        select(Artifact)
        .join(Chat, Artifact.chat_id == Chat.id)
        .where(
            Artifact.id == artifact_id,
            Chat.session_id == _session_uuid(session_id),
            Chat.user_id == user.id,
            Artifact.user_id == user.id,
        )
    )
    artifact = result.scalar_one_or_none()
    if artifact is None or not user_can_access_artifact(user, artifact):
        return None
    return artifact


async def delete_artifact(
    db: AsyncSession,
    user: User,
    session_id: uuid.UUID | str,
    artifact_id: uuid.UUID,
    storage: StorageService | None = None,
) -> bool:
    """Wipe MinIO object first, then DELETE the artifact row.

    Missing artifacts are treated as already deleted (idempotent). If MinIO
    deletion fails, the Postgres row is left intact so the client can retry.
    """
    storage = storage or get_storage_service()
    artifact = await get_artifact_for_user(db, user, session_id, artifact_id)
    if artifact is None:
        return True

    object_key = artifact.storage_path
    await storage.delete_file(object_key)
    await db.delete(artifact)
    await db.commit()
    logger.info(
        "Deleted artifact=%s chat=%s user=%s key=%s",
        artifact_id,
        artifact.chat_id,
        user.id,
        object_key,
    )
    return True
