"""Pytest configuration and shared fixtures."""

import os
import tempfile
from pathlib import Path

# Required Settings fields (CI has no backend/.env). Force-assign so a developer
# shell env cannot leak into the suite the way setdefault would allow.
os.environ["POSTGRES_USER"] = "test"
os.environ["POSTGRES_PASSWORD"] = "test"
# Prefer IPv4 loopback — "localhost" can resolve to ::1 first on some runners.
os.environ["POSTGRES_HOST"] = "127.0.0.1"
os.environ["POSTGRES_PORT"] = "5432"
os.environ["POSTGRES_DB"] = "rootagent_test"
os.environ["REDIS_PASSWORD"] = "test"
os.environ["MINIO_ACCESS_KEY"] = "admin"
os.environ["MINIO_SECRET_KEY"] = "password123"
os.environ["JWT_SECRET"] = "test-secret-key"
os.environ["INFRA_HUB_POSTGRES_DB"] = "main_db_test"
os.environ["ENVIRONMENT"] = "test"
# Non-empty so production Settings() unit tests are not coupled to a local .env.
os.environ["LLM_API_KEY"] = "test-llm-api-key"

# Portable across macOS and Linux CI (avoid /private/tmp, which is not writable on GHA).
_log_dir = Path(tempfile.gettempdir()) / "rootagent-tests"
_log_dir.mkdir(parents=True, exist_ok=True)
os.environ["BACKEND_LOG_FILE"] = str(_log_dir / "backend.log")
