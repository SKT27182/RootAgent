"""Postgres-authoritative chat session lifecycle."""

from __future__ import annotations

import asyncio
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import Chat, ChatRun, User
from app.services.artifact_service import chat_storage_prefix, user_storage_prefix
from app.services.redis_store import RedisStore, get_redis_store
from app.services.storage import StorageService, get_storage_service
from app.utils.logger import create_logger

logger = create_logger(__name__)


class SessionBusyError(RuntimeError):
    """Raised when deletion would race an active durable chat run."""


async def list_sessions(db: AsyncSession, user_id: uuid.UUID) -> list[Chat]:
    result = await db.execute(
        select(Chat)
        .where(Chat.user_id == user_id)
        .order_by(Chat.updated_at.desc(), Chat.created_at.desc())
    )
    return list(result.scalars().all())


async def get_owned_session(
    db: AsyncSession, user_id: uuid.UUID, session_id: uuid.UUID
) -> Chat | None:
    result = await db.execute(
        select(Chat).where(Chat.user_id == user_id, Chat.session_id == session_id)
    )
    return result.scalar_one_or_none()


async def resolve_run_session(
    db: AsyncSession,
    user_id: uuid.UUID,
    requested_session_id: uuid.UUID | None,
) -> Chat | None:
    """Create a server-issued session, or resolve an existing owned session."""
    if requested_session_id is not None:
        return await get_owned_session(db, user_id, requested_session_id)
    chat = Chat(user_id=user_id, session_id=uuid.uuid4())
    db.add(chat)
    await db.commit()
    await db.refresh(chat)
    return chat


async def _remove_local_workspaces(workspace_ids: list[str]) -> None:
    """Remove only UUID-named directories contained by the configured workspace root."""
    if settings.executor_backend != "local" or not workspace_ids:
        return
    root = Path(settings.executor_workspace_root).resolve()
    for raw_workspace_id in workspace_ids:
        workspace_id = uuid.UUID(raw_workspace_id)
        candidate = (root / str(workspace_id)).resolve()
        candidate.relative_to(root)
        await asyncio.to_thread(shutil.rmtree, candidate, True)


async def delete_session(
    db: AsyncSession,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    *,
    storage: StorageService | None = None,
    redis_store: RedisStore | None = None,
) -> bool:
    """Wipe MinIO/Redis/workspaces first, then DELETE chat (DB cascades children).

    Order matters: external bytes and session history are removed before the
    Postgres chat row so ON DELETE CASCADE can drop chat_runs and artifacts
    without leaving orphaned objects behind.
    """
    chat = await get_owned_session(db, user_id, session_id)
    if chat is None:
        return True

    storage = storage or get_storage_service()
    redis_store = redis_store or get_redis_store()

    result = await db.execute(select(ChatRun.id).where(ChatRun.chat_id == chat.id))
    workspace_ids = [str(item) for item in result.scalars().all()]

    # 1) MinIO — every object under this chat
    await storage.delete_prefix(chat_storage_prefix(user_id, chat.id))
    # 2) Redis history for this session
    await redis_store.delete_keys([f"session:{user_id}:{session_id}"])
    # 3) Local executor workspaces for runs of this chat
    await _remove_local_workspaces(workspace_ids)
    # 4) Postgres last — CASCADE removes chat_runs + artifacts
    await db.delete(chat)
    await db.commit()
    logger.info(
        "Deleted chat session=%s chat_id=%s user=%s (cascaded runs/artifacts)",
        session_id,
        chat.id,
        user_id,
    )
    return True


async def request_session_deletion(db: AsyncSession, chat: Chat) -> None:
    """Durably mark a chat for deletion after its current run releases the lock."""
    if chat.deletion_requested_at is None:
        chat.deletion_requested_at = datetime.now(timezone.utc)
        await db.commit()


async def delete_user(
    db: AsyncSession,
    user: User,
    *,
    storage: StorageService | None = None,
    redis_store: RedisStore | None = None,
) -> bool:
    """Wipe all user external resources, then DELETE user (cascades chats/runs/artifacts)."""
    storage = storage or get_storage_service()
    redis_store = redis_store or get_redis_store()

    result = await db.execute(select(Chat.session_id).where(Chat.user_id == user.id))
    session_ids = list(result.scalars().all())
    result = await db.execute(select(ChatRun.id).where(ChatRun.user_id == user.id))
    workspace_ids = [str(item) for item in result.scalars().all()]

    await storage.delete_prefix(user_storage_prefix(user.id))
    await redis_store.delete_keys(
        [f"session:{user.id}:{session_id}" for session_id in session_ids]
    )
    await _remove_local_workspaces(workspace_ids)
    await db.delete(user)
    await db.commit()
    logger.info("Deleted user=%s (cascaded chats/runs/artifacts)", user.id)
    return True
