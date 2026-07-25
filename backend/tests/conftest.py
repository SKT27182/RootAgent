"""Pytest configuration and shared fixtures."""

import os

# Set required settings before app modules load
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("POSTGRES_DB", "rootagent_test")
os.environ.setdefault("REDIS_PASSWORD", "test")
os.environ.setdefault("MINIO_ACCESS_KEY", "admin")
os.environ.setdefault("MINIO_SECRET_KEY", "password123")
os.environ.setdefault("JWT_SECRET", "test-secret-key")
os.environ.setdefault("INFRA_HUB_POSTGRES_DB", "main_db_test")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("BACKEND_LOG_FILE", "/private/tmp/rootagent-tests.log")
