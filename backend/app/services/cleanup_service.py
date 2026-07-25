"""Retryable processing for durable external-resource cleanup jobs."""

import asyncio
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import Chat, CleanupJob, CleanupState
from app.services import session_service
from app.services.storage import StorageService, get_storage_service
from app.services.redis_store import RedisStore, get_redis_store
from app.utils.logger import create_logger
from app.core.metrics import CLEANUP_RETRIES

logger = create_logger(__name__)
MAX_CLEANUP_BACKOFF_SECONDS = 3600


async def reconcile_pending_session_deletion(
    db: AsyncSession, redis_store: RedisStore | None = None
) -> bool:
    """Delete one pending chat once no live run owns its Redis lock."""
    redis_store = redis_store or get_redis_store()
    result = await db.execute(
        select(Chat)
        .where(Chat.deletion_requested_at.is_not(None))
        .order_by(Chat.deletion_requested_at)
        .limit(50)
    )
    for chat in result.scalars().all():
        token = await redis_store.acquire_run_lock(
            str(chat.user_id), str(chat.session_id)
        )
        if token is None:
            continue
        try:
            await session_service.delete_session(db, chat.user_id, chat.session_id)
        finally:
            await redis_store.release_run_lock(
                str(chat.user_id), str(chat.session_id), token
            )
        return True
    return False


async def _remove_local_workspaces(workspace_ids: list[str]) -> None:
    """Remove only UUID-named directories contained by the configured workspace root."""

    root = Path(settings.executor_workspace_root).resolve()
    for raw_workspace_id in workspace_ids:
        workspace_id = uuid.UUID(raw_workspace_id)
        candidate = (root / str(workspace_id)).resolve()
        candidate.relative_to(root)
        await asyncio.to_thread(shutil.rmtree, candidate, True)


async def process_next_cleanup_job(
    db: AsyncSession,
    storage: StorageService | None = None,
    redis_store: RedisStore | None = None,
) -> bool:
    """Claim and process one cleanup job; return whether a job was available."""
    storage = storage or get_storage_service()
    redis_store = redis_store or get_redis_store()
    now = datetime.now(timezone.utc)
    stale_cutoff = now - timedelta(seconds=120)
    result = await db.execute(
        select(CleanupJob)
        .where(
            or_(
                and_(
                    CleanupJob.state.in_(
                        [CleanupState.PENDING, CleanupState.FAILED]
                    ),
                    CleanupJob.next_attempt_at <= now,
                ),
                and_(
                    CleanupJob.state == CleanupState.RUNNING,
                    CleanupJob.updated_at < stale_cutoff,
                ),
            )
        )
        .order_by(CleanupJob.next_attempt_at, CleanupJob.created_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    job = result.scalar_one_or_none()
    if job is None:
        return False

    job.state = CleanupState.RUNNING
    job.attempts += 1
    await db.commit()
    try:
        for object_key in job.object_keys:
            await storage.delete_file(object_key)
        await redis_store.delete_keys(job.redis_keys)
        if settings.executor_backend == "local":
            await _remove_local_workspaces(job.workspace_ids)
    except Exception as exc:
        CLEANUP_RETRIES.labels(job.operation.value).inc()
        delay = min(5 * (2 ** max(job.attempts - 1, 0)), MAX_CLEANUP_BACKOFF_SECONDS)
        job.state = CleanupState.FAILED
        job.next_attempt_at = now + timedelta(seconds=delay)
        job.last_error = str(exc)[:2000]
        logger.warning("Cleanup job %s failed; retry in %ss", job.id, delay)
    else:
        job.state = CleanupState.COMPLETE
        job.last_error = None
    await db.commit()
    return True


async def cleanup_worker_is_current(db: AsyncSession, *, max_age_seconds: int = 120) -> bool:
    """Report whether cleanup is making progress or has no runnable backlog."""
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=max_age_seconds)
    result = await db.execute(
        select(CleanupJob.id).where(
            or_(
                CleanupJob.state.in_([CleanupState.PENDING, CleanupState.FAILED]),
                (CleanupJob.state == CleanupState.RUNNING)
                & (CleanupJob.updated_at < cutoff),
            )
        )
    )
    return result.first() is None
