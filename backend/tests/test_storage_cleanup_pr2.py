"""PR 2 contracts for safe artifact identity and durable session cleanup."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.db.models import (
    ArtifactOutputKind,
    ArtifactSource,
    CleanupJob,
    CleanupOperation,
    CleanupState,
)
from app.routers.artifacts import _to_response
from app.services.artifact_service import storage_path
from app.services.cleanup_service import (
    _remove_local_workspaces,
    process_next_cleanup_job,
    reconcile_pending_session_deletion,
)
from app.services.file_validation import sanitize_display_filename
from app.services.session_service import delete_session, request_session_deletion


def _scalar_result(value) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _scalars_result(values: list[str]) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = values
    return result


def test_display_filename_is_sanitized_but_storage_key_uses_only_uuids() -> None:
    user_id = uuid.uuid4()
    chat_id = uuid.uuid4()
    artifact_id = uuid.uuid4()

    assert sanitize_display_filename("../../Quarterly <report>? .csv") == (
        "Quarterly _report_ .csv"
    )
    assert sanitize_display_filename("..\\evil/../../report.csv") == "report.csv"
    assert sanitize_display_filename("   ") == "upload"

    key = storage_path(user_id, chat_id, artifact_id)
    assert key == f"{user_id}/{chat_id}/upload/{artifact_id}"
    assert "report" not in key
    assert ".." not in key
    generated = storage_path(
        user_id, chat_id, artifact_id, source=ArtifactSource.GENERATED
    )
    assert generated == f"{user_id}/{chat_id}/generated/{artifact_id}"
    assert "/runs/" not in generated


def test_artifact_response_uses_relative_authenticated_content_routes() -> None:
    session_id = uuid.uuid4()
    artifact_id = uuid.uuid4()
    artifact = MagicMock(
        id=artifact_id,
        chat_id=uuid.uuid4(),
        filename="table.csv",
        content_type="text/csv",
        file_size=12,
        sha256="a" * 64,
        source=ArtifactSource.GENERATED,
        output_kind=ArtifactOutputKind.CSV,
        width=None,
        height=None,
        created_at=datetime.now(timezone.utc),
    )

    response = _to_response(artifact, session_id)

    expected_base = f"/artifacts/{session_id}/{artifact_id}"
    assert response.content_url == f"{expected_base}/content"
    assert response.preview_url == f"{expected_base}/preview"
    assert response.download_url == f"{expected_base}/download"
    assert not response.content_url.startswith(("http://", "https://"))
    assert "X-Amz-" not in response.content_url


@pytest.mark.asyncio
async def test_session_delete_wipes_minio_then_deletes_chat() -> None:
    user_id = uuid.uuid4()
    session_id = uuid.uuid4()
    chat = MagicMock(id=uuid.uuid4(), user_id=user_id, session_id=session_id)
    run_id = uuid.uuid4()
    db = MagicMock()
    db.execute = AsyncMock(
        side_effect=[
            _scalar_result(chat),
            _scalars_result([run_id]),
            _scalar_result(None),
        ]
    )
    db.delete = AsyncMock()
    db.commit = AsyncMock()
    storage = MagicMock()
    storage.delete_prefix = AsyncMock(return_value=2)
    redis_store = MagicMock()
    redis_store.delete_keys = AsyncMock()

    assert (
        await delete_session(
            db, user_id, session_id, storage=storage, redis_store=redis_store
        )
        is True
    )
    assert (
        await delete_session(
            db, user_id, session_id, storage=storage, redis_store=redis_store
        )
        is True
    )

    storage.delete_prefix.assert_awaited_once_with(f"{user_id}/{chat.id}/")
    redis_store.delete_keys.assert_awaited_once_with(
        [f"session:{user_id}:{session_id}"]
    )
    db.add.assert_not_called()
    db.delete.assert_awaited_once_with(chat)
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_session_delete_uses_external_lock_as_liveness_authority() -> None:
    user_id = uuid.uuid4()
    session_id = uuid.uuid4()
    chat = MagicMock(id=uuid.uuid4(), user_id=user_id, session_id=session_id)
    db = MagicMock()
    db.execute = AsyncMock(
        side_effect=[_scalar_result(chat), _scalars_result([])]
    )
    db.delete = AsyncMock()
    db.commit = AsyncMock()
    storage = MagicMock()
    storage.delete_prefix = AsyncMock(return_value=0)
    redis_store = MagicMock()
    redis_store.delete_keys = AsyncMock()

    assert (
        await delete_session(
            db, user_id, session_id, storage=storage, redis_store=redis_store
        )
        is True
    )
    db.delete.assert_awaited_once_with(chat)


@pytest.mark.asyncio
async def test_pending_session_deletion_is_marked_once() -> None:
    chat = MagicMock(deletion_requested_at=None)
    db = MagicMock()
    db.commit = AsyncMock()

    await request_session_deletion(db, chat)
    first_requested_at = chat.deletion_requested_at
    await request_session_deletion(db, chat)

    assert first_requested_at is not None
    assert chat.deletion_requested_at == first_requested_at
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_pending_session_reconciliation_waits_for_lock_then_deletes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid.uuid4()
    session_id = uuid.uuid4()
    blocked = MagicMock(user_id=user_id, session_id=uuid.uuid4())
    ready = MagicMock(user_id=user_id, session_id=session_id)
    db = MagicMock()
    db.execute = AsyncMock(return_value=_scalars_result([blocked, ready]))
    redis_store = MagicMock()
    redis_store.acquire_run_lock = AsyncMock(side_effect=[None, "lock-token"])
    redis_store.release_run_lock = AsyncMock()
    delete = AsyncMock(return_value=True)
    monkeypatch.setattr("app.services.cleanup_service.session_service.delete_session", delete)

    assert await reconcile_pending_session_deletion(db, redis_store) is True

    delete.assert_awaited_once_with(db, user_id, session_id)
    redis_store.release_run_lock.assert_awaited_once_with(
        str(user_id), str(session_id), "lock-token"
    )


@pytest.mark.asyncio
async def test_local_workspace_cleanup_is_uuid_scoped(tmp_path, monkeypatch) -> None:
    workspace_id = uuid.uuid4()
    workspace = tmp_path / str(workspace_id)
    workspace.mkdir()
    (workspace / "staged.csv").write_text("value\n1\n")
    monkeypatch.setattr(
        "app.services.cleanup_service.settings.executor_workspace_root", str(tmp_path)
    )

    await _remove_local_workspaces([str(workspace_id)])

    assert not workspace.exists()
    with pytest.raises(ValueError):
        await _remove_local_workspaces(["../outside"])


@pytest.mark.asyncio
async def test_cleanup_retry_counts_attempt_and_schedules_backoff() -> None:
    job = SimpleNamespace(
        id=uuid.uuid4(),
        operation=CleanupOperation.SESSION,
        state=CleanupState.PENDING,
        attempts=0,
        object_keys=["object-key"],
        redis_keys=["redis-key"],
        workspace_ids=[],
        next_attempt_at=datetime.now(timezone.utc),
        last_error=None,
    )
    db = MagicMock()
    db.execute = AsyncMock(return_value=_scalar_result(job))
    db.commit = AsyncMock()
    storage = MagicMock()
    storage.delete_file = AsyncMock(side_effect=RuntimeError("storage unavailable"))
    redis_store = MagicMock()
    redis_store.delete_keys = AsyncMock()

    assert await process_next_cleanup_job(db, storage, redis_store) is True

    assert job.state is CleanupState.FAILED
    assert job.attempts == 1
    assert job.next_attempt_at > datetime.now(timezone.utc)
    assert job.last_error == "storage unavailable"
    assert db.commit.await_count == 2
