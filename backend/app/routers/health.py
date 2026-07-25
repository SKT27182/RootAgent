"""Process liveness and dependency-aware readiness endpoints."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from fastapi import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text

from app.core.config import settings
from app.db.postgres import async_session_maker
from app.services.cleanup_service import cleanup_worker_is_current
from app.services.redis_store import get_redis_store
from app.services.storage import get_storage_service
from app.utils.logger import create_logger
from app.core.metrics import READINESS_FAILURES

router = APIRouter(tags=["Health"])
logger = create_logger(__name__, level=settings.log_level)
READINESS_TIMEOUT_SECONDS = 3.0


@router.get("/health/live")
@router.get("/health")
async def health_live() -> dict[str, str]:
    return {"status": "ok"}


async def _postgres_status() -> dict[str, Any]:
    async with async_session_maker() as db:
        await db.execute(text("SELECT 1"))
        result = await db.execute(text("SELECT version_num FROM alembic_version"))
        current = result.scalar_one_or_none()
    backend_dir = Path(__file__).resolve().parents[2]
    config = Config(str(backend_dir / "alembic.ini"))
    # alembic.ini uses a backend-relative script_location, while local uvicorn
    # is launched from the repository root. Resolve it explicitly so readiness
    # is independent of the process working directory.
    config.set_main_option("script_location", str(backend_dir / "alembic"))
    head = ScriptDirectory.from_config(config).get_current_head()
    return {"ok": current == head, "current_revision": current, "head_revision": head}


async def _redis_status() -> dict[str, Any]:
    store = get_redis_store()
    pong = await store.redis_client.ping()
    return {"ok": bool(pong)}


async def _cleanup_status() -> dict[str, Any]:
    store = get_redis_store()
    heartbeat = await store.redis_client.get("cleanup-worker:heartbeat")
    async with async_session_maker() as db:
        backlog_current = await cleanup_worker_is_current(db)
    return {
        "ok": heartbeat == "ok" and backlog_current,
        "heartbeat": heartbeat == "ok",
        "backlog_current": backlog_current,
    }


async def _minio_status() -> dict[str, Any]:
    storage = get_storage_service()
    await storage.ensure_bucket()
    await storage.check_bucket_access()
    return {"ok": True, "bucket": settings.minio_bucket}


async def _bounded(check) -> dict[str, Any]:
    try:
        return await asyncio.wait_for(check(), timeout=READINESS_TIMEOUT_SECONDS)
    except Exception as exc:
        logger.warning("Readiness dependency failed: %s", type(exc).__name__)
        return {"ok": False, "error": type(exc).__name__}


@router.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@router.get("/health/ready")
async def health_ready() -> JSONResponse:
    postgres, redis, minio, cleanup = await asyncio.gather(
        _bounded(_postgres_status),
        _bounded(_redis_status),
        _bounded(_minio_status),
        _bounded(_cleanup_status),
    )
    executor = {
        "ok": settings.executor_backend == "local",
        "backend": settings.executor_backend,
        "unsafe_local_executor": settings.executor_backend == "local",
        "risk_acknowledged": (
            settings.executor_backend != "local"
            or settings.allow_unsafe_local_executor
            or settings.environment != "production"
        ),
    }
    for dependency, result in (
        ("postgres", postgres),
        ("redis", redis),
        ("minio", minio),
        ("cleanup_worker", cleanup),
        ("executor", executor),
    ):
        if not result.get("ok"):
            READINESS_FAILURES.labels(dependency).inc()
    ready = all(
        [
            bool(postgres.get("ok")),
            bool(redis.get("ok")),
            bool(minio.get("ok")),
            bool(cleanup.get("ok")),
            bool(executor.get("ok")),
            bool(executor.get("risk_acknowledged")),
        ]
    )
    payload = {
        "status": "ready" if ready else "not_ready",
        "dependencies": {
            "postgres": postgres,
            "redis": redis,
            "minio": minio,
            "cleanup_worker": cleanup,
            "executor": executor,
        },
    }
    return JSONResponse(payload, status_code=200 if ready else 503)
