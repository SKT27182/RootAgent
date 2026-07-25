"""Durable cleanup worker for MinIO, Redis, and future workspace resources."""

from __future__ import annotations

import asyncio
import signal
from contextlib import suppress

from app.core.config import settings
from app.db.postgres import async_session_maker, close_db
from app.services.cleanup_service import (
    process_next_cleanup_job,
    reconcile_pending_session_deletion,
)
from app.services.redis_store import get_redis_store
from app.utils.logger import create_logger

logger = create_logger(__name__, level=settings.log_level)


async def run_worker() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_name in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            loop.add_signal_handler(signal_name, stop.set)

    redis_store = get_redis_store()
    logger.info("Cleanup worker started")
    try:
        while not stop.is_set():
            try:
                await redis_store.redis_client.set(
                    "cleanup-worker:heartbeat", "ok", ex=60
                )
                async with async_session_maker() as db:
                    reconciled = await reconcile_pending_session_deletion(
                        db, redis_store=redis_store
                    )
                    processed = reconciled or await process_next_cleanup_job(
                        db, redis_store=redis_store
                    )
            except Exception:
                logger.exception("Cleanup worker iteration failed")
                processed = False

            if not processed:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=5)
                except TimeoutError:
                    pass
    finally:
        await redis_store.close()
        await close_db()
        logger.info("Cleanup worker stopped")


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
