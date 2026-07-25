from __future__ import annotations

import json
from datetime import datetime, timezone
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import BaseModel

from app.agent.llm import LLMClient
from app.db.models import (
    Artifact,
    ArtifactSource,
    Chat,
    User,
    UserRole,
)
from app.routers import artifacts as artifact_routes
from app.routers import auth as auth_routes
from app.schemas.auth import PasswordChange, ProfileUpdate, UserRegister
from app.services import artifact_service
from app.services.redis_store import RateLimitResult


class ScalarResult:
    def __init__(self, *, one=None, all_values=()) -> None:
        self._one = one
        self._all = list(all_values)

    def scalar_one_or_none(self):
        return self._one

    def scalars(self):
        return self

    def all(self):
        return self._all


def user() -> User:
    return User(
        id=uuid4(),
        email="person@example.com",
        name="Person",
        hashed_password="hashed",
        role=UserRole.USER,
    )


def artifact(owner: User, chat: Chat, *, content_type: str = "text/csv") -> Artifact:
    item = Artifact(
        id=uuid4(),
        user_id=owner.id,
        chat_id=chat.id,
        filename="report.csv",
        content_type=content_type,
        storage_path=f"{owner.id}/{chat.id}/{uuid4()}",
        file_size=8,
        sha256="a" * 64,
        source=ArtifactSource.UPLOAD,
    )
    item.created_at = datetime.now(timezone.utc)
    return item


@pytest.mark.asyncio
async def test_artifact_service_create_list_get_and_response_metadata() -> None:
    owner = user()
    session_id = uuid4()
    chat = Chat(id=uuid4(), user_id=owner.id, session_id=session_id)
    db = AsyncMock()
    db.add = MagicMock()
    db.execute.side_effect = [ScalarResult(one=chat), ScalarResult(one=None)]
    storage = SimpleNamespace(upload_stream=AsyncMock(), delete_file=AsyncMock())

    created = await artifact_service.create_artifact_from_stream(
        db,
        owner,
        session_id,
        "../../quarterly.csv",
        "text/csv",
        BytesIO(b"a,b\n1,2\n"),
        8,
        "b" * 64,
        storage=storage,
    )
    assert created.filename == "quarterly.csv"
    assert created.storage_path == f"{owner.id}/{chat.id}/upload/{created.id}"
    created.created_at = datetime.now(timezone.utc)
    storage.upload_stream.assert_awaited_once()
    db.add.assert_called_once_with(created)
    db.commit.assert_awaited_once()

    db.execute.side_effect = [
        ScalarResult(one=chat),
        ScalarResult(all_values=[created]),
        ScalarResult(one=created),
    ]
    assert await artifact_service.list_artifacts_for_chat(db, owner, session_id) == [
        created
    ]
    assert (
        await artifact_service.get_artifact_for_user(
            db, owner, session_id, created.id
        )
        is created
    )
    metadata = artifact_service.to_artifact_response(created, session_id)
    assert metadata.content_url.endswith(f"/{created.id}/content")
    assert metadata.preview_url.endswith(f"/{created.id}/preview")
    assert artifact_service.to_artifact_event_metadata(created, session_id).id == (
        created.id
    )


@pytest.mark.asyncio
async def test_artifact_service_rolls_back_metadata_and_uploaded_object() -> None:
    owner = user()
    chat = Chat(id=uuid4(), user_id=owner.id, session_id=uuid4())
    db = AsyncMock()
    db.add = MagicMock()
    db.execute.side_effect = [ScalarResult(one=chat), ScalarResult(one=None)]
    db.commit.side_effect = RuntimeError("database unavailable")
    storage = SimpleNamespace(upload_stream=AsyncMock(), delete_file=AsyncMock())

    with pytest.raises(RuntimeError, match="database unavailable"):
        await artifact_service.create_artifact_from_stream(
            db,
            owner,
            chat.session_id,
            "report.csv",
            "text/csv",
            BytesIO(b"a\n1\n"),
            4,
            "a" * 64,
            storage=storage,
        )
    db.rollback.assert_awaited_once()
    storage.delete_file.assert_awaited_once()


@pytest.mark.asyncio
async def test_artifact_service_generated_bytes_and_idempotent_cleanup() -> None:
    owner = user()
    chat = Chat(id=uuid4(), user_id=owner.id, session_id=uuid4())
    stored = artifact(owner, chat)
    db = AsyncMock()
    db.add = MagicMock()
    storage = SimpleNamespace(delete_file=AsyncMock())

    with patch(
        "app.services.artifact_service.create_artifact_from_stream",
        new=AsyncMock(return_value=stored),
    ) as creator:
        assert (
            await artifact_service.create_artifact(
                db,
                owner,
                chat.session_id,
                "table.csv",
                "text/csv",
                b"a\n1\n",
                source=ArtifactSource.GENERATED,
                storage=storage,
            )
            is stored
        )
    assert creator.await_args.kwargs["source"] is ArtifactSource.GENERATED
    assert creator.await_args.args[7]

    with patch(
        "app.services.artifact_service.get_artifact_for_user",
        new=AsyncMock(side_effect=[stored, None]),
    ):
        assert await artifact_service.delete_artifact(
            db, owner, chat.session_id, stored.id, storage
        )
        storage.delete_file.assert_awaited_once_with(stored.storage_path)
        db.delete.assert_awaited_once_with(stored)
        db.commit.assert_awaited()
        assert await artifact_service.delete_artifact(
            db, owner, chat.session_id, stored.id, storage
        )
    assert db.delete.await_count == 1


@pytest.mark.asyncio
async def test_artifact_service_keeps_row_when_minio_delete_fails() -> None:
    owner = user()
    chat = Chat(id=uuid4(), user_id=owner.id, session_id=uuid4())
    stored = artifact(owner, chat)
    db = AsyncMock()
    storage = SimpleNamespace(
        delete_file=AsyncMock(side_effect=RuntimeError("minio offline"))
    )
    with patch(
        "app.services.artifact_service.get_artifact_for_user",
        new=AsyncMock(return_value=stored),
    ):
        with pytest.raises(RuntimeError, match="minio offline"):
            await artifact_service.delete_artifact(
                db, owner, chat.session_id, stored.id, storage
            )
    db.delete.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_artifact_routes_stream_list_get_delete_and_content_disposition() -> None:
    owner = user()
    session_id = uuid4()
    chat = Chat(id=uuid4(), user_id=owner.id, session_id=session_id)
    stored = artifact(owner, chat)
    stream = iter(())

    assert "filename*=UTF-8''" in artifact_routes._content_disposition(
        'résumé "Q1".csv', attachment=True
    )
    assert artifact_routes._content_disposition("資料.csv", attachment=False).startswith(
        'inline; filename=".csv"'
    )

    with patch.object(
        artifact_service,
        "list_artifacts_for_chat",
        new=AsyncMock(return_value=[stored]),
    ), patch.object(
        artifact_service,
        "get_artifact_for_user",
        new=AsyncMock(return_value=stored),
    ), patch.object(
        artifact_service, "delete_artifact", new=AsyncMock(return_value=True)
    ), patch(
        "app.routers.artifacts.get_storage_service",
        return_value=SimpleNamespace(open_download=AsyncMock(return_value=stream)),
    ):
        listed = await artifact_routes.list_artifacts(session_id, owner, AsyncMock())
        fetched = await artifact_routes.get_artifact(
            session_id, stored.id, owner, AsyncMock()
        )
        response = await artifact_routes.download_artifact(
            session_id, stored.id, owner, AsyncMock()
        )
        await artifact_routes.delete_artifact_route(
            session_id, stored.id, owner, AsyncMock()
        )

    assert listed[0].id == stored.id
    assert fetched.id == stored.id
    assert response.headers["content-disposition"].startswith("attachment")
    assert response.headers["x-content-type-options"] == "nosniff"

    with patch.object(
        artifact_service,
        "get_artifact_for_user",
        new=AsyncMock(return_value=None),
    ):
        with pytest.raises(HTTPException) as missing:
            await artifact_routes.get_artifact(session_id, stored.id, owner, AsyncMock())
    assert missing.value.status_code == 404


def request(ip: str = "203.0.113.7"):
    return SimpleNamespace(client=SimpleNamespace(host=ip))


@pytest.mark.asyncio
async def test_auth_routes_register_login_ticket_profile_and_password() -> None:
    db = AsyncMock()
    db.add = MagicMock()
    db.execute.return_value = ScalarResult(one=None)
    redis = SimpleNamespace(
        check_rate_limit=AsyncMock(return_value=RateLimitResult(True, 1, 0)),
        issue_ws_ticket=AsyncMock(return_value=("ticket-value", 30)),
    )

    with patch("app.routers.auth.get_password_hash", return_value="hash"):
        registered = await auth_routes.register(
            UserRegister(
                email="new@example.com", name=" New User ", password="secret123"
            ),
            request(),
            db,
            redis,
        )
    assert registered.name == "New User"
    assert registered.role is UserRole.USER

    with patch(
        "app.routers.auth.authenticate_user",
        new=AsyncMock(return_value=registered),
    ), patch("app.routers.auth.create_access_token", return_value="jwt"):
        token = await auth_routes.login(
            SimpleNamespace(username=registered.email, password="secret123"),
            request(),
            db,
            redis,
        )
    assert token.access_token == "jwt"
    ticket = await auth_routes.create_ws_ticket(registered, redis)
    assert ticket.ticket == "ticket-value"
    assert await auth_routes.get_me(registered) is registered

    updated = await auth_routes.update_profile(
        ProfileUpdate(name=" Updated Name "), registered, db
    )
    assert updated.name == "Updated Name"
    with patch("app.routers.auth.verify_password", return_value=True), patch(
        "app.routers.auth.get_password_hash", return_value="new-hash"
    ):
        await auth_routes.change_password(
            PasswordChange(current_password="old-password", new_password="new-password"),
            registered,
            db,
        )
    assert registered.hashed_password == "new-hash"


@pytest.mark.asyncio
async def test_auth_routes_reject_duplicates_bad_login_limits_and_linked_updates() -> None:
    owner = user()
    db = AsyncMock()
    db.execute.return_value = ScalarResult(one=owner)
    allowed = SimpleNamespace(
        check_rate_limit=AsyncMock(return_value=RateLimitResult(True, 1, 0))
    )
    with pytest.raises(HTTPException) as duplicate:
        await auth_routes.register(
            UserRegister(email=owner.email, name="Name", password="secret123"),
            request(),
            db,
            allowed,
        )
    assert duplicate.value.status_code == 400

    limited = SimpleNamespace(
        check_rate_limit=AsyncMock(return_value=RateLimitResult(False, 10, 17))
    )
    with pytest.raises(HTTPException) as rate_limited:
        await auth_routes._enforce_rate_limit(
            limited, namespace="login", identity="ip", limit=10, window_seconds=60
        )
    assert rate_limited.value.headers == {"Retry-After": "17"}

    with patch(
        "app.routers.auth.authenticate_user", new=AsyncMock(return_value=None)
    ):
        with pytest.raises(HTTPException) as bad_login:
            await auth_routes.login(
                SimpleNamespace(username=owner.email, password="wrong"),
                request(),
                db,
                allowed,
            )
    assert bad_login.value.status_code == 401

    owner.infra_hub_user_id = 1
    with pytest.raises(HTTPException) as linked_profile:
        await auth_routes.update_profile(ProfileUpdate(name="Other"), owner, db)
    with pytest.raises(HTTPException) as linked_password:
        await auth_routes.change_password(
            PasswordChange(current_password="old-password", new_password="new-password"),
            owner,
            db,
        )
    assert linked_profile.value.status_code == linked_password.value.status_code == 403


class Answer(BaseModel):
    value: int


def llm_response(content: str):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


@pytest.mark.asyncio
async def test_llm_client_parses_plain_json_markdown_models_and_streams() -> None:
    client = LLMClient(model="test-model", api_key="test-key")
    completion = AsyncMock(
        side_effect=[
            llm_response("plain text"),
            llm_response(json.dumps({"value": 4})),
            llm_response('```json\n{"value": 5}\n```'),
            llm_response('```json\n{"legacy": true}\n```'),
        ]
    )
    with patch("app.agent.llm.acompletion", completion):
        assert await client.agenerate([]) == "plain text"
        assert await client.agenerate([], Answer) == Answer(value=4)
        assert await client.agenerate([], Answer) == Answer(value=5)
        assert await client.agenerate([], {"type": "object"}) == {"legacy": True}

    async def chunks():
        yield SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content="one"))]
        )
        yield SimpleNamespace(choices=[])
        yield SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content="two"))]
        )

    with patch("app.agent.llm.acompletion", new=AsyncMock(return_value=chunks())):
        assert [part async for part in client.astream([])] == ["one", "two"]


@pytest.mark.asyncio
async def test_llm_client_wraps_generation_and_stream_errors() -> None:
    client = LLMClient(model="test-model", api_key="test-key")
    with patch(
        "app.agent.llm.acompletion", new=AsyncMock(side_effect=ValueError("offline"))
    ):
        with pytest.raises(RuntimeError, match="offline"):
            await client.agenerate([])
        with pytest.raises(RuntimeError, match="offline"):
            async for _ in client.astream([]):
                pass
