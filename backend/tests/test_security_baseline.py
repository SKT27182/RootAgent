import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from starlette.requests import Request

from app.core.config import Settings, settings
from app.models.chat import ChatRequest
from app.schemas.auth import ProfileUpdate, UserRegister
from app.routers.admin import AdminCreateUser
from app.routers.chat import _origin_is_allowed, websocket_endpoint
from app.routers.auth import _client_ip
from app.services.redis_store import RedisStore


def test_chat_request_rejects_legacy_or_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        ChatRequest(
            query="analyze",
            request_id=uuid.uuid4(),
            user_id="caller-controlled",
        )

    with pytest.raises(ValidationError):
        ChatRequest(
            query="analyze",
            request_id=uuid.uuid4(),
            images=["data:image/png;base64,AAAA"],
        )

    with pytest.raises(ValidationError):
        ChatRequest(
            query="analyze",
            request_id=uuid.uuid4(),
            include_reasoning=True,
        )


def test_chat_request_requires_uuid_ids_and_enforces_bounds() -> None:
    with pytest.raises(ValidationError):
        ChatRequest(query="analyze", request_id="not-a-uuid")

    with pytest.raises(ValidationError):
        ChatRequest(query="   ", request_id=uuid.uuid4())

    with pytest.raises(ValidationError):
        ChatRequest(
            query="analyze",
            request_id=uuid.uuid4(),
            artifact_ids=[uuid.uuid4()],
        )


@pytest.mark.parametrize(
    "schema,payload",
    [
        (
            UserRegister,
            {"email": "user@example.com", "name": "   ", "password": "password1"},
        ),
        (ProfileUpdate, {"name": "   "}),
        (
            AdminCreateUser,
            {"email": "user@example.com", "name": "   ", "password": "password1"},
        ),
    ],
)
def test_auth_names_reject_whitespace(schema, payload) -> None:
    with pytest.raises(ValidationError, match="name must not be blank"):
        schema.model_validate(payload)


@pytest.mark.asyncio
async def test_save_message_refreshes_history_ttl() -> None:
    client = MagicMock()
    pipeline = MagicMock()
    pipeline.rpush = AsyncMock(return_value=pipeline)
    pipeline.expire = AsyncMock(return_value=pipeline)
    pipeline.execute = AsyncMock(return_value=[1, True])
    client.pipeline.return_value.__aenter__ = AsyncMock(return_value=pipeline)
    client.pipeline.return_value.__aexit__ = AsyncMock(return_value=None)
    store = RedisStore.__new__(RedisStore)
    store.redis_client = client

    from app.models.chat import Message

    await store.save_message("user", "session", Message(role="user", content="hi"))

    pipeline.rpush.assert_awaited_once()
    pipeline.expire.assert_awaited_once()
    pipeline.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_history_accepts_legacy_reasoning_flag_without_exposing_it() -> None:
    client = MagicMock()
    client.lrange = AsyncMock(
        return_value=[
            '{"role":"assistant","content":"trace","step_kind":"tool",'
            '"is_reasoning":true}'
        ]
    )
    store = RedisStore.__new__(RedisStore)
    store.redis_client = client

    history = await store.get_session_history("user", "session", last_n=-1)

    assert len(history) == 1
    assert history[0].step_kind == "tool"
    assert "is_reasoning" not in history[0].model_dump()


@pytest.mark.asyncio
async def test_rate_limit_result_and_single_use_ticket() -> None:
    client = MagicMock()
    client.eval = AsyncMock(return_value=[1, 3, 42_000])
    client.set = AsyncMock(return_value=True)
    client.getdel = AsyncMock(side_effect=[str(uuid.uuid4()), None])
    store = RedisStore.__new__(RedisStore)
    store.redis_client = client

    result = await store.check_rate_limit(
        "login", "127.0.0.1", limit=3, window_seconds=60
    )
    assert result.allowed is True
    assert result.remaining == 0
    assert result.retry_after_seconds == 42

    ticket, ttl = await store.issue_ws_ticket("user-id")
    assert ticket
    assert ttl == 30
    assert await store.consume_ws_ticket(ticket) is not None
    assert await store.consume_ws_ticket(ticket) is None
    assert client.getdel.await_count == 2


@pytest.mark.asyncio
async def test_run_lock_renewal_is_token_scoped() -> None:
    client = MagicMock()
    client.eval = AsyncMock(side_effect=[1, 0])
    store = RedisStore.__new__(RedisStore)
    store.redis_client = client

    assert await store.renew_run_lock("user", "session", "owner-token") is True
    assert await store.renew_run_lock("user", "session", "stale-token") is False
    assert client.eval.await_count == 2


def test_websocket_origin_must_be_explicitly_allowed() -> None:
    assert _origin_is_allowed("http://localhost:5145") is True
    assert _origin_is_allowed("https://attacker.invalid") is False
    assert _origin_is_allowed(None) is False


def test_forwarded_ip_is_used_only_for_a_configured_proxy(monkeypatch) -> None:
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/auth/login",
        "headers": [(b"x-forwarded-for", b"203.0.113.5, 10.0.0.2")],
        "client": ("10.0.0.2", 1234),
        "server": ("rootagent", 443),
        "scheme": "https",
        "query_string": b"",
    }
    monkeypatch.setattr(settings, "trusted_proxy_ips", "10.0.0.0/8")
    assert _client_ip(Request(scope)) == "203.0.113.5"

    monkeypatch.setattr(settings, "trusted_proxy_ips", "192.168.0.0/16")
    assert _client_ip(Request(scope)) == "10.0.0.2"


@pytest.mark.asyncio
async def test_websocket_rejects_origin_before_consuming_ticket() -> None:
    websocket = MagicMock()
    websocket.headers = {"origin": "https://attacker.invalid"}
    websocket.close = AsyncMock()
    store = MagicMock()
    store.consume_ws_ticket = AsyncMock()

    await websocket_endpoint(websocket, store, "ticket")

    websocket.close.assert_awaited_once()
    store.consume_ws_ticket.assert_not_awaited()


@pytest.mark.asyncio
async def test_websocket_rejects_invalid_ticket_before_accept() -> None:
    websocket = MagicMock()
    websocket.headers = {"origin": "http://localhost:5145"}
    websocket.close = AsyncMock()
    websocket.accept = AsyncMock()
    store = MagicMock()
    store.consume_ws_ticket = AsyncMock(return_value=None)

    await websocket_endpoint(websocket, store, "invalid")

    websocket.close.assert_awaited_once()
    websocket.accept.assert_not_awaited()


def test_production_settings_reject_unsafe_local_executor() -> None:
    common = {
        "_env_file": None,
        "environment": "production",
        "debug": False,
        "postgres_user": "rootagent",
        "postgres_password": "a-real-postgres-password",
        "postgres_host": "postgres.internal",
        "postgres_url": (
            "postgresql+asyncpg://rootagent:a-real-postgres-password@"
            "postgres.internal/rootagent?ssl=require"
        ),
        "infra_hub_postgres_url": (
            "postgresql://rootagent:a-real-postgres-password@"
            "postgres.internal/main_db?sslmode=require"
        ),
        "redis_password": "a-real-redis-password",
        "redis_host": "redis.internal",
        "redis_ssl": True,
        "minio_access_key": "rootagent-access",
        "minio_secret_key": "a-real-minio-secret",
        "minio_endpoint": "minio.internal:9000",
        "minio_secure": True,
        "jwt_secret": "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMN",
        "llm_api_key": "a-real-llm-key",
        "app_public_url": "https://rootagent.example.com",
        "cors_origins": "https://rootagent.example.com",
        "trusted_proxy_ips": "10.0.0.0/8",
        "executor_backend": "local",
    }
    with pytest.raises(ValidationError, match="ALLOW_UNSAFE_LOCAL_EXECUTOR"):
        Settings(**common, allow_unsafe_local_executor=False)

    configured = Settings(**common, allow_unsafe_local_executor=True)
    assert configured.environment == "production"

    with pytest.raises(ValidationError, match="sufficiently diverse"):
        Settings(
            **{**common, "jwt_secret": "x" * 64},
            allow_unsafe_local_executor=True,
        )


@pytest.mark.asyncio
async def test_http_errors_include_correlation_id() -> None:
    from app.main import app

    supplied = str(uuid.uuid4())
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/route-that-does-not-exist",
            headers={"X-Correlation-ID": supplied},
        )

    assert response.status_code == 404
    assert response.headers["X-Correlation-ID"] == supplied
    assert response.json()["correlation_id"] == supplied
