"""Create app database if missing, then run Alembic migrations."""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path


async def _ensure_db() -> None:
    from app.db.postgres import ensure_database_exists

    await ensure_database_exists()


def main() -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    try:
        asyncio.run(_ensure_db())
    except Exception as exc:
        print(f"Failed to ensure database exists: {exc}", file=sys.stderr)
        print(
            "Check POSTGRES_* in backend/.env match infra-hub. "
            "If they already match, the persisted PostgreSQL role may have been "
            "initialized with an older password. Reconcile that role before "
            "deleting shared infra data.",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"],
        cwd=backend_dir,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
