"""Operational health endpoint tests."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.routers import health
from app.services.storage import StorageService


def _payload(response) -> dict:
    return json.loads(response.body)


@pytest.mark.asyncio
async def test_readiness_reports_dependencies_and_acknowledged_local_risk(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        health, "_postgres_status", AsyncMock(return_value={"ok": True})
    )
    monkeypatch.setattr(health, "_redis_status", AsyncMock(return_value={"ok": True}))
    monkeypatch.setattr(health, "_minio_status", AsyncMock(return_value={"ok": True}))
    monkeypatch.setattr(
        health,
        "_cleanup_status",
        AsyncMock(
            return_value={"ok": True, "heartbeat": True, "backlog_current": True}
        ),
    )
    monkeypatch.setattr(health.settings, "executor_backend", "local")
    monkeypatch.setattr(health.settings, "environment", "production")
    monkeypatch.setattr(health.settings, "allow_unsafe_local_executor", True)

    response = await health.health_ready()
    payload = _payload(response)

    assert response.status_code == 200
    assert payload["status"] == "ready"
    assert payload["dependencies"]["executor"] == {
        "ok": True,
        "backend": "local",
        "unsafe_local_executor": True,
        "risk_acknowledged": True,
    }


@pytest.mark.asyncio
async def test_grpc_stub_keeps_readiness_unhealthy(monkeypatch) -> None:
    healthy = AsyncMock(return_value={"ok": True})
    monkeypatch.setattr(health, "_postgres_status", healthy)
    monkeypatch.setattr(health, "_redis_status", healthy)
    monkeypatch.setattr(health, "_minio_status", healthy)
    monkeypatch.setattr(health, "_cleanup_status", healthy)
    monkeypatch.setattr(health.settings, "executor_backend", "grpc")

    response = await health.health_ready()
    payload = _payload(response)

    assert response.status_code == 503
    assert payload["status"] == "not_ready"
    assert payload["dependencies"]["executor"]["ok"] is False


@pytest.mark.asyncio
async def test_minio_readiness_check_is_not_satisfied_by_cached_bucket_state() -> None:
    service = StorageService(client=MagicMock())
    service._bucket_ready = True
    service._run = AsyncMock(side_effect=[True, RuntimeError("minio unavailable")])

    await service.check_bucket_access()
    with pytest.raises(RuntimeError, match="unavailable"):
        await service.check_bucket_access()

    assert service._run.await_count == 2
