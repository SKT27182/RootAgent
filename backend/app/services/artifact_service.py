"""Artifact lifecycle: Postgres metadata + MinIO objects."""

import base64
import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Artifact, ArtifactSource, Chat, User, UserRole
from app.services.storage import StorageService, get_storage_service
from app.utils.logger import create_logger

logger = create_logger(__name__)


def _storage_path(user_id: uuid.UUID, chat_id: uuid.UUID, artifact_id: uuid.UUID, filename: str) -> str:
    safe_name = filename.replace("/", "_")
    return f"{user_id}/{chat_id}/{artifact_id}/{safe_name}"


async def get_or_create_chat(
    db: AsyncSession,
    user_id: uuid.UUID,
    session_id: str,
) -> Chat:
    result = await db.execute(
        select(Chat).where(Chat.session_id == session_id, Chat.user_id == user_id)
    )
    chat = result.scalar_one_or_none()
    if chat:
        return chat
    chat = Chat(user_id=user_id, session_id=session_id)
    db.add(chat)
    await db.flush()
    return chat


def user_can_access_artifact(user: User, artifact: Artifact) -> bool:
    if user.role in (UserRole.ADMIN, UserRole.INFRA_ADMIN):
        return True
    return artifact.user_id == user.id


async def create_artifact(
    db: AsyncSession,
    user: User,
    session_id: str,
    filename: str,
    content_type: str,
    data: bytes,
    source: ArtifactSource = ArtifactSource.UPLOAD,
    storage: StorageService | None = None,
) -> Artifact:
    storage = storage or get_storage_service()
    chat = await get_or_create_chat(db, user.id, session_id)
    artifact_id = uuid.uuid4()
    path = _storage_path(user.id, chat.id, artifact_id, filename)

    try:
        storage.upload_file(path, data, content_type=content_type)
    except Exception:
        raise

    artifact = Artifact(
        id=artifact_id,
        user_id=user.id,
        chat_id=chat.id,
        filename=filename,
        content_type=content_type,
        storage_path=path,
        file_size=len(data),
        source=source,
    )
    db.add(artifact)
    try:
        await db.commit()
        await db.refresh(artifact)
    except Exception:
        await db.rollback()
        try:
            storage.delete_file(path)
        except Exception as cleanup_err:
            logger.warning(f"Failed to cleanup MinIO object after DB error: {cleanup_err}")
        raise
    return artifact


async def list_artifacts_for_chat(
    db: AsyncSession,
    user: User,
    session_id: str,
) -> list[Artifact]:
    result = await db.execute(
        select(Chat).where(Chat.session_id == session_id, Chat.user_id == user.id)
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
    session_id: str,
    artifact_id: uuid.UUID,
) -> Artifact | None:
    result = await db.execute(
        select(Artifact)
        .join(Chat, Artifact.chat_id == Chat.id)
        .where(
            Artifact.id == artifact_id,
            Chat.session_id == session_id,
        )
    )
    artifact = result.scalar_one_or_none()
    if artifact is None:
        return None
    if not user_can_access_artifact(user, artifact):
        return None
    return artifact


_IMAGE_DATA_URI = re.compile(
    r"data:image/(?P<fmt>[a-zA-Z0-9+.-]+);base64,(?P<data>[A-Za-z0-9+/=\s]+)"
)


async def save_generated_images_from_text(
    db: AsyncSession,
    user: User,
    session_id: str,
    text: str,
) -> list[Artifact]:
    """Persist inline base64 images from agent output as generated artifacts."""
    saved: list[Artifact] = []
    for idx, match in enumerate(_IMAGE_DATA_URI.finditer(text)):
        fmt = match.group("fmt").split("+")[0]
        raw = match.group("data").replace("\n", "")
        try:
            data = base64.b64decode(raw, validate=True)
        except Exception:
            continue
        filename = f"generated_{idx + 1}.{fmt}"
        content_type = f"image/{fmt}"
        artifact = await create_artifact(
            db=db,
            user=user,
            session_id=session_id,
            filename=filename,
            content_type=content_type,
            data=data,
            source=ArtifactSource.GENERATED,
        )
        saved.append(artifact)
    return saved


async def delete_artifact(
    db: AsyncSession,
    user: User,
    session_id: str,
    artifact_id: uuid.UUID,
    storage: StorageService | None = None,
) -> bool:
    storage = storage or get_storage_service()
    artifact = await get_artifact_for_user(db, user, session_id, artifact_id)
    if artifact is None:
        return False

    path = artifact.storage_path
    await db.delete(artifact)
    await db.commit()
    try:
        storage.delete_file(path)
    except Exception as e:
        logger.warning(f"MinIO delete failed for {path}: {e}")
    return True
