import json
import time
from typing import List, Optional

import redis.asyncio as redis

from app.core.config import settings
from app.models.chat import Message
from app.utils.logger import create_logger

logger = create_logger(__name__, level=settings.log_level)


class RedisStore:
    def __init__(
        self,
        host: str = settings.redis_host,
        port: int = settings.redis_port,
        password: Optional[str] = settings.redis_password,
        ssl: bool = settings.redis_ssl,
        db: int = 0,
    ):
        try:
            self.redis_client = redis.Redis(
                host=host,
                port=port,
                db=db,
                password=password,
                ssl=ssl,
                decode_responses=True,
            )
            logger.info("Redis client initialized.")
        except Exception as e:
            logger.warning(f"Could not connect to Redis: {e}. Using fakeredis.")
            try:
                from fakeredis import aioredis

                self.redis_client = aioredis.FakeRedis(decode_responses=True)
            except ImportError:
                logger.error("fakeredis.aioredis not found")
                self.redis_client = None

    def _get_session_key(self, user_id: str, session_id: str) -> str:
        return f"session:{user_id}:{session_id}"

    async def save_message(self, user_id: str, session_id: str, message: Message):
        key = self._get_session_key(user_id, session_id)
        await self.redis_client.rpush(key, message.model_dump_json())

    async def get_session_history(
        self,
        user_id: str,
        session_id: str,
        include_reasoning: bool = False,
        last_n: int = 10,
    ) -> List[Message]:
        key = self._get_session_key(user_id, session_id)
        messages_json = await self.redis_client.lrange(key, 0, -1)
        messages = [Message(**json.loads(msg)) for msg in messages_json]

        if last_n == -1:
            if include_reasoning:
                return messages
            return [m for m in messages if not m.is_reasoning]

        last_n += 1
        user_count = 0
        start_idx = 0

        for i in range(len(messages) - 1, -1, -1):
            if messages[i].role == "user" and not messages[i].is_reasoning:
                user_count += 1
                if user_count == last_n:
                    start_idx = i
                    break

        while start_idx < len(messages) and not (
            messages[start_idx].role == "user" and not messages[start_idx].is_reasoning
        ):
            start_idx += 1

        if start_idx >= len(messages):
            return []

        window = messages[start_idx:]
        if not include_reasoning:
            window = [m for m in window if not m.is_reasoning]
        return window

    async def delete_session(self, user_id: str, session_id: str) -> bool:
        key = self._get_session_key(user_id, session_id)
        deleted = await self.redis_client.delete(key)
        await self.redis_client.zrem(f"user:{user_id}:sessions", session_id)
        return deleted > 0

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

    async def add_user_session(self, user_id: str, session_id: str):
        user_sessions_key = f"user:{user_id}:sessions"
        session_key = self._get_session_key(user_id, session_id)

        key_type = await self.redis_client.type(user_sessions_key)
        if key_type == "set":
            old_sessions = await self.redis_client.smembers(user_sessions_key)
            await self.redis_client.delete(user_sessions_key)
            if old_sessions:
                await self.redis_client.zadd(
                    user_sessions_key, {s: 0 for s in old_sessions}
                )

        score = await self.redis_client.zscore(user_sessions_key, session_id)
        is_new = score is None
        await self.redis_client.zadd(user_sessions_key, {session_id: time.time()})

        if is_new:
            ttl = settings.session_ttl_seconds
            await self.redis_client.expire(session_key, ttl)
            logger.info(f"Created new session {session_id} with {ttl}s TTL")

    async def get_user_sessions(self, user_id: str) -> List[str]:
        key = f"user:{user_id}:sessions"
        key_type = await self.redis_client.type(key)
        if key_type == "set":
            sessions = await self.redis_client.smembers(key)
            return list(sessions)
        return await self.redis_client.zrevrange(key, 0, -1)
