import json
import hashlib
import secrets
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import List, Optional

import redis.asyncio as redis

from app.core.config import settings
from app.models.chat import Message
from app.utils.logger import create_logger

logger = create_logger(__name__, level=settings.log_level)


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    remaining: int
    retry_after_seconds: int


_RATE_LIMIT_SCRIPT = """
local now_ms = tonumber(ARGV[1])
local window_ms = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
redis.call('ZREMRANGEBYSCORE', KEYS[1], 0, now_ms - window_ms)
local count = redis.call('ZCARD', KEYS[1])
local allowed = 0
if count < limit then
    redis.call('ZADD', KEYS[1], now_ms, ARGV[4])
    count = count + 1
    allowed = 1
end
redis.call('PEXPIRE', KEYS[1], window_ms)
local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
local retry_ms = window_ms
if oldest[2] then
    retry_ms = math.max(1, window_ms - (now_ms - tonumber(oldest[2])))
end
return {allowed, count, retry_ms}
"""

_RELEASE_LOCK_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""

_RENEW_LOCK_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('EXPIRE', KEYS[1], ARGV[2])
end
return 0
"""


class RedisStore:
    def __init__(
        self,
        host: str = settings.redis_host,
        port: int = settings.redis_port,
        password: Optional[str] = settings.redis_password,
        ssl: bool = settings.redis_ssl,
        db: int = 0,
    ):
        self.redis_client = redis.Redis(
            host=host,
            port=port,
            db=db,
            password=password,
            ssl=ssl,
            decode_responses=True,
        )
        logger.info("Redis client initialized.")

    def _get_session_key(self, user_id: str, session_id: str) -> str:
        return f"session:{user_id}:{session_id}"

    async def save_message(self, user_id: str, session_id: str, message: Message):
        key = self._get_session_key(user_id, session_id)
        async with self.redis_client.pipeline(transaction=True) as pipeline:
            await pipeline.rpush(key, message.model_dump_json())
            await pipeline.expire(key, settings.session_ttl_seconds)
            await pipeline.execute()

    async def get_session_history(
        self,
        user_id: str,
        session_id: str,
        last_n: int = 10,
    ) -> List[Message]:
        key = self._get_session_key(user_id, session_id)
        messages_json = await self.redis_client.lrange(key, 0, -1)
        messages: list[Message] = []
        for raw_message in messages_json:
            data = json.loads(raw_message)
            # Compatibility for pre-upgrade Redis history. The optional reasoning
            # concept is removed from the current model, but old entries may live
            # until their activity-refreshed TTL expires.
            if isinstance(data, dict):
                data.pop("is_reasoning", None)
            messages.append(Message.model_validate(data))

        if last_n == -1:
            return messages

        last_n += 1
        user_count = 0
        start_idx = 0

        for i in range(len(messages) - 1, -1, -1):
            if messages[i].step_kind == "user":
                user_count += 1
                if user_count == last_n:
                    start_idx = i
                    break

        while start_idx < len(messages) and not (
            messages[start_idx].step_kind == "user"
        ):
            start_idx += 1

        if start_idx >= len(messages):
            return []

        return messages[start_idx:]

    async def delete_session(self, user_id: str, session_id: str) -> bool:
        key = self._get_session_key(user_id, session_id)
        deleted = await self.redis_client.delete(key)
        return deleted > 0

    async def delete_keys(self, keys: list[str]) -> None:
        if keys:
            await self.redis_client.delete(*keys)

    async def delete_message(
        self, user_id: str, session_id: str, message_id: str
    ) -> bool:
        key = self._get_session_key(user_id, session_id)
        messages_json = await self.redis_client.lrange(key, 0, -1)
        for msg_json in messages_json:
            msg_data = json.loads(msg_json)
            if msg_data.get("message_id") == message_id:
                await self.redis_client.lrem(key, 1, msg_json)
                return True
        return False

    async def check_rate_limit(
        self,
        namespace: str,
        identity: str,
        *,
        limit: int,
        window_seconds: int,
    ) -> RateLimitResult:
        identity_digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        now_ms = int(time.time() * 1000)
        key = f"rate:{namespace}:{identity_digest}"
        member = f"{now_ms}:{secrets.token_urlsafe(8)}"
        allowed, count, retry_ms = await self.redis_client.eval(
            _RATE_LIMIT_SCRIPT,
            1,
            key,
            now_ms,
            window_seconds * 1000,
            limit,
            member,
        )
        allowed = bool(int(allowed))
        count = int(count)
        retry_after_seconds = max(1, (int(retry_ms) + 999) // 1000)
        return RateLimitResult(
            allowed=allowed,
            remaining=max(0, limit - count),
            retry_after_seconds=retry_after_seconds,
        )

    async def issue_ws_ticket(self, user_id: str) -> tuple[str, int]:
        ttl = settings.ws_ticket_ttl_seconds
        for _ in range(3):
            ticket = secrets.token_urlsafe(32)
            ticket_digest = hashlib.sha256(ticket.encode("utf-8")).hexdigest()
            created = await self.redis_client.set(
                f"ws-ticket:{ticket_digest}",
                user_id,
                ex=ttl,
                nx=True,
            )
            if created:
                return ticket, ttl
        raise RuntimeError("Could not allocate WebSocket ticket")

    async def consume_ws_ticket(self, ticket: str) -> str | None:
        if not ticket or len(ticket) > 256:
            return None
        ticket_digest = hashlib.sha256(ticket.encode("utf-8")).hexdigest()
        value = await self.redis_client.getdel(f"ws-ticket:{ticket_digest}")
        return str(value) if value else None

    async def acquire_run_lock(self, user_id: str, session_id: str) -> str | None:
        token = secrets.token_urlsafe(24)
        acquired = await self.redis_client.set(
            f"run-lock:{user_id}:{session_id}",
            token,
            ex=settings.run_lock_ttl_seconds,
            nx=True,
        )
        return token if acquired else None

    async def release_run_lock(
        self, user_id: str, session_id: str, token: str
    ) -> None:
        await self.redis_client.eval(
            _RELEASE_LOCK_SCRIPT,
            1,
            f"run-lock:{user_id}:{session_id}",
            token,
        )

    async def renew_run_lock(
        self, user_id: str, session_id: str, token: str
    ) -> bool:
        renewed = await self.redis_client.eval(
            _RENEW_LOCK_SCRIPT,
            1,
            f"run-lock:{user_id}:{session_id}",
            token,
            settings.run_lock_ttl_seconds,
        )
        return bool(renewed)

    async def close(self) -> None:
        await self.redis_client.aclose()


@lru_cache
def get_redis_store() -> RedisStore:
    return RedisStore()
