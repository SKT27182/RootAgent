"""Async SQLAlchemy engine and session management."""

from collections.abc import AsyncGenerator

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.sql import text

from app.core.config import settings
from app.utils.logger import create_logger

logger = create_logger(__name__)

engine = create_async_engine(
    settings.postgres_url,
    echo=settings.debug,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    pass


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """Ensure database exists. Schema is managed by Alembic migrations."""
    await ensure_database_exists()
    logger.info("Database ready (run `make db-migrate` to apply schema)")


async def close_db() -> None:
    await engine.dispose()
    logger.info("Database connections closed")


async def ensure_database_exists() -> None:
    db_url = make_url(settings.postgres_url)
    if not db_url.drivername.startswith("postgresql") or not db_url.database:
        return

    target_database = db_url.database
    admin_url = db_url.set(database="postgres")
    admin_engine = create_async_engine(
        admin_url,
        echo=settings.debug,
        isolation_level="AUTOCOMMIT",
        pool_pre_ping=True,
    )

    try:
        async with admin_engine.connect() as conn:
            result = await conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :db_name"),
                {"db_name": target_database},
            )
            if result.scalar() is not None:
                return
            escaped_database = target_database.replace('"', '""')
            await conn.execute(text(f'CREATE DATABASE "{escaped_database}"'))
            logger.info(f"Created database: {target_database}")
    finally:
        await admin_engine.dispose()
