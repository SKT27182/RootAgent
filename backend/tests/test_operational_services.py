from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.core.dependencies import (
    get_current_user,
    has_admin_access,
    is_infra_admin,
    is_rootagent_admin,
    require_admin,
    require_infra_admin,
)
from app.core.security import (
    create_access_token,
    decode_access_token,
    get_password_hash,
    verify_password,
)
from sqlalchemy import inspect as sa_inspect

from app.db.models import (
    Chat,
    CleanupOperation,
    CleanupState,
    User,
    UserRole,
)
from app.services.cleanup_service import (
    _remove_local_workspaces,
    cleanup_worker_is_current,
    process_next_cleanup_job,
)
from app.services.session_service import (
    delete_session,
    delete_user,
    get_owned_session,
    list_sessions,
    resolve_run_session,
)
from app.services.storage import StorageService


class ScalarResult:
    def __init__(self, *, one=None, all_values=(), first=None) -> None:
        self._one = one
        self._all = list(all_values)
        self._first = first

    def scalar_one_or_none(self):
        return self._one

    def scalars(self):
        return self

    def all(self):
        return self._all

    def first(self):
        return self._first


class FakeObjectResponse:
    def __init__(self, payload: bytes) -> None:
        self._stream = BytesIO(payload)
        self.closed = False
        self.released = False

    def read(self, size: int) -> bytes:
        return self._stream.read(size)

    def close(self) -> None:
        self.closed = True

    def release_conn(self) -> None:
        self.released = True


class FakeMinio:
    def __init__(self, *, bucket_exists: bool = False, payload: bytes = b"") -> None:
        self.exists = bucket_exists
        self.payload = payload
        self.calls: list[tuple] = []
        self.response = FakeObjectResponse(payload)

    def bucket_exists(self, bucket: str) -> bool:
        self.calls.append(("bucket_exists", bucket))
        return self.exists

    def make_bucket(self, bucket: str) -> None:
        self.calls.append(("make_bucket", bucket))
        self.exists = True

    def put_object(self, bucket, path, stream, length, *, content_type):
        self.calls.append(
            ("put_object", bucket, path, stream.read(), length, content_type)
        )

    def stat_object(self, bucket: str, path: str):
        self.calls.append(("stat_object", bucket, path))
        return SimpleNamespace(size=len(self.payload))

    def get_object(self, bucket: str, path: str):
        self.calls.append(("get_object", bucket, path))
        return self.response

    def remove_object(self, bucket: str, path: str) -> None:
        self.calls.append(("remove_object", bucket, path))


@pytest.mark.asyncio
async def test_storage_service_full_object_lifecycle() -> None:
    client = FakeMinio(payload=b"chunked payload")
    storage = StorageService(client=client)  # type: ignore[arg-type]

    assert await storage.upload_file("objects/input.csv", b"a,b\n1,2\n", "text/csv") == (
        "objects/input.csv"
    )
    await storage.ensure_bucket()  # cached branch
    stat = await storage.stat_file("objects/input.csv")
    assert stat.size == len(b"chunked payload")
    assert await storage.download_file("objects/input.csv") == b"chunked payload"
    await storage.delete_file("objects/input.csv")

    assert ("make_bucket", storage._bucket) in client.calls
    assert sum(call[0] == "bucket_exists" for call in client.calls) == 1
    assert client.response.closed is True
    assert client.response.released is True
    put = next(call for call in client.calls if call[0] == "put_object")
    assert put[3:] == (b"a,b\n1,2\n", 8, "text/csv")


@pytest.mark.asyncio
async def test_cleanup_job_success_empty_and_worker_freshness(tmp_path: Path) -> None:
    workspace_id = uuid4()
    workspace = tmp_path / str(workspace_id)
    workspace.mkdir()
    (workspace / "temporary.txt").write_text("data")
    job = SimpleNamespace(
        id=uuid4(),
        operation=CleanupOperation.SESSION,
        object_keys=["objects/a.csv"],
        redis_keys=["session:key"],
        workspace_ids=[str(workspace_id)],
        state=CleanupState.PENDING,
        attempts=0,
        next_attempt_at=datetime.now(timezone.utc),
        last_error="old",
    )
    db = AsyncMock()
    db.execute.side_effect = [ScalarResult(one=job), ScalarResult(first=None)]
    storage = SimpleNamespace(delete_file=AsyncMock())
    redis_store = SimpleNamespace(delete_keys=AsyncMock())

    with patch("app.services.cleanup_service.settings.executor_workspace_root", tmp_path):
        assert await process_next_cleanup_job(db, storage, redis_store) is True
    assert job.state is CleanupState.COMPLETE
    assert job.last_error is None
    storage.delete_file.assert_awaited_once_with("objects/a.csv")
    redis_store.delete_keys.assert_awaited_once_with(["session:key"])
    assert not workspace.exists()
    assert await cleanup_worker_is_current(db) is True

    empty_db = AsyncMock()
    empty_db.execute.return_value = ScalarResult(one=None)
    assert await process_next_cleanup_job(empty_db, storage, redis_store) is False


@pytest.mark.asyncio
async def test_cleanup_job_failure_is_retryable_and_bounded() -> None:
    job = SimpleNamespace(
        id=uuid4(),
        operation=CleanupOperation.USER,
        object_keys=["objects/fail.csv"],
        redis_keys=[],
        workspace_ids=[],
        state=CleanupState.PENDING,
        attempts=20,
        next_attempt_at=datetime.now(timezone.utc),
        last_error=None,
    )
    db = AsyncMock()
    db.execute.return_value = ScalarResult(one=job)
    storage = SimpleNamespace(
        delete_file=AsyncMock(side_effect=RuntimeError("storage unavailable"))
    )
    redis_store = SimpleNamespace(delete_keys=AsyncMock())

    assert await process_next_cleanup_job(db, storage, redis_store) is True
    assert job.state is CleanupState.FAILED
    assert job.attempts == 21
    assert job.last_error == "storage unavailable"
    delay = (job.next_attempt_at - datetime.now(timezone.utc)).total_seconds()
    assert 3590 <= delay <= 3600
    assert db.commit.await_count == 2


@pytest.mark.asyncio
async def test_remove_local_workspaces_rejects_non_uuid(tmp_path: Path) -> None:
    with patch("app.services.cleanup_service.settings.executor_workspace_root", tmp_path):
        with pytest.raises(ValueError):
            await _remove_local_workspaces(["../outside"])


def test_chat_child_relationships_use_passive_deletes() -> None:
    """DB ON DELETE CASCADE must not be undermined by ORM nullification."""
    mapper = sa_inspect(Chat)
    assert mapper.relationships["runs"].passive_deletes is True
    assert mapper.relationships["artifacts"].passive_deletes is True


@pytest.mark.asyncio
async def test_session_service_resolves_lists_and_deletes_owned_session() -> None:
    user_id = uuid4()
    session_id = uuid4()
    chat = Chat(id=uuid4(), user_id=user_id, session_id=session_id)

    db = AsyncMock()
    db.add = MagicMock()
    db.execute.side_effect = [ScalarResult(all_values=[chat]), ScalarResult(one=chat)]
    assert await list_sessions(db, user_id) == [chat]
    assert await get_owned_session(db, user_id, session_id) is chat

    existing_db = AsyncMock()
    existing_db.execute.return_value = ScalarResult(one=chat)
    assert await resolve_run_session(existing_db, user_id, session_id) is chat

    create_db = AsyncMock()
    create_db.add = MagicMock()
    created = await resolve_run_session(create_db, user_id, None)
    assert created is not None
    assert created.user_id == user_id
    create_db.add.assert_called_once_with(created)
    create_db.commit.assert_awaited_once()
    create_db.refresh.assert_awaited_once_with(created)

    run_id = uuid4()
    deletion_db = AsyncMock()
    deletion_db.execute.side_effect = [
        ScalarResult(one=chat),
        ScalarResult(all_values=[run_id]),
    ]
    storage = AsyncMock()
    storage.delete_prefix = AsyncMock(return_value=2)
    redis_store = AsyncMock()
    redis_store.delete_keys = AsyncMock()
    assert (
        await delete_session(
            deletion_db,
            user_id,
            session_id,
            storage=storage,
            redis_store=redis_store,
        )
        is True
    )
    storage.delete_prefix.assert_awaited_once_with(f"{user_id}/{chat.id}/")
    redis_store.delete_keys.assert_awaited_once_with(
        [f"session:{user_id}:{session_id}"]
    )
    deletion_db.add.assert_not_called()
    deletion_db.delete.assert_awaited_once_with(chat)
    deletion_db.commit.assert_awaited_once()
    # MinIO wipe happens before Postgres delete
    assert storage.delete_prefix.await_count == 1
    assert deletion_db.delete.await_args_list[0].args[0] is chat

    missing_db = AsyncMock()
    missing_db.execute.return_value = ScalarResult(one=None)
    assert await delete_session(missing_db, user_id, session_id) is True
    missing_db.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_session_service_deletes_user_minio_first_then_cascades() -> None:
    user = User(
        id=uuid4(),
        email="member@example.com",
        name="Member",
        hashed_password="hash",
        role=UserRole.USER,
    )
    session_ids = [uuid4(), uuid4()]
    run_ids = [uuid4()]
    db = AsyncMock()
    db.execute.side_effect = [
        ScalarResult(all_values=session_ids),
        ScalarResult(all_values=run_ids),
    ]
    storage = AsyncMock()
    storage.delete_prefix = AsyncMock(return_value=3)
    redis_store = AsyncMock()
    redis_store.delete_keys = AsyncMock()

    assert (
        await delete_user(db, user, storage=storage, redis_store=redis_store) is True
    )
    storage.delete_prefix.assert_awaited_once_with(f"{user.id}/")
    redis_store.delete_keys.assert_awaited_once_with(
        [f"session:{user.id}:{item}" for item in session_ids]
    )
    db.add.assert_not_called()
    db.delete.assert_awaited_once_with(user)
    db.commit.assert_awaited_once()


def build_user(role: UserRole) -> User:
    return User(
        id=uuid4(),
        email=f"{role.value}@example.com",
        name=role.value,
        hashed_password="hash",
        role=role,
    )


@pytest.mark.asyncio
async def test_auth_dependencies_validate_tokens_users_and_roles() -> None:
    user = build_user(UserRole.USER)
    db = AsyncMock()
    db.execute.return_value = ScalarResult(one=user)
    token = create_access_token({"sub": str(user.id)})
    assert await get_current_user(token, db) is user

    assert not has_admin_access(user)
    assert not is_rootagent_admin(user)
    assert not is_infra_admin(user)
    with pytest.raises(HTTPException) as denied:
        await require_admin(user)
    assert denied.value.status_code == 403
    with pytest.raises(HTTPException) as denied_infra:
        await require_infra_admin(user)
    assert denied_infra.value.status_code == 403

    admin = build_user(UserRole.ADMIN)
    infra = build_user(UserRole.INFRA_ADMIN)
    assert await require_admin(admin) is admin
    assert is_rootagent_admin(admin)
    assert await require_admin(infra) is infra
    assert await require_infra_admin(infra) is infra
    assert is_infra_admin(infra)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [None, {}, {"sub": "not-a-uuid"}, {"sub": str(uuid4())}],
)
async def test_current_user_rejects_invalid_identity(payload: dict | None) -> None:
    db = AsyncMock()
    db.execute.return_value = ScalarResult(one=None)
    with patch("app.core.dependencies.decode_access_token", return_value=payload):
        with pytest.raises(HTTPException) as rejected:
            await get_current_user("token", db)
    assert rejected.value.status_code == 401
    assert rejected.value.headers == {"WWW-Authenticate": "Bearer"}


def test_security_hashing_and_jwt_failure_paths() -> None:
    password = "correct horse battery staple"
    hashed = get_password_hash(password)
    assert verify_password(password, hashed)
    assert not verify_password("wrong", hashed)

    token = create_access_token({"sub": str(uuid4())})
    assert decode_access_token(token)["sub"]
    assert decode_access_token(token + "tampered") is None
