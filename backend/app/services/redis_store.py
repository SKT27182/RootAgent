import json
import redis.asyncio as redis
from typing import List, Optional, Dict, Set
from backend.app.models.chat import Message, Session
from backend.app.utils.logger import create_logger
from backend.app.core.config import Config

logger = create_logger(__name__, level=Config.LOG_LEVEL)


class RedisStore:
    def __init__(
        self,
        host: str = Config.REDIS_HOST,
        port: int = Config.REDIS_PORT,
        password: Optional[str] = Config.REDIS_PASSWORD,
        ssl: bool = Config.REDIS_SSL,
        db: int = 0,
    ):
        try:
            logger.debug(f"Connecting to Redis at {host}:{port}, db={db}, ssl={ssl}")
            self.redis_client = redis.Redis(
                host=host,
                port=port,
                db=db,
                password=password,
                ssl=ssl,
                decode_responses=True,
            )
            # Ping is awaitable, but we can't await in init easily without a factory or start hook.
            # We will skip ping in init for now, or just assume connection.
            # Alternatively we could use a connect method, but for simplicity we rely on lazy connection or future errors.
            logger.info("Redis client initialized.")
        except Exception as e:
            logger.warning(
                f"Could not connect to Redis: {e}. Using fakeredis for local development."
            )
            # Fakeredis async support? It exists but might be tricky.
            # For now, let's assume real redis or fail gracefully if needed.
            # If fakeredis is needed, we need `fakeredis.aioredis`.
            try:
                from fakeredis import aioredis

                self.redis_client = aioredis.FakeRedis(decode_responses=True)
            except ImportError:
                logger.error("fakeredis.aioredis not found, RedisStore invalid.")
                self.redis_client = None

    def _get_session_key(self, user_id: str, session_id: str) -> str:
        return f"session:{user_id}:{session_id}"

    async def save_message(self, user_id: str, session_id: str, message: Message):
        key = self._get_session_key(user_id, session_id)
        logger.debug(f"Saving message to {key}: {message.message_id}")
        await self.redis_client.rpush(key, message.model_dump_json())

    async def get_session_history(
        self, user_id: str, session_id: str, include_reasoning: bool = False
    ) -> List[Message]:
        key = self._get_session_key(user_id, session_id)
        logger.debug(
            f"Retrieving history for {key}, include_reasoning={include_reasoning}"
        )
        messages_json = await self.redis_client.lrange(key, 0, -1)
        messages = [Message(**json.loads(msg)) for msg in messages_json]

        if not include_reasoning:
            messages = [msg for msg in messages if not msg.is_reasoning]

        return messages

    async def clear_session(self, user_id: str, session_id: str):
        key = self._get_session_key(user_id, session_id)
        logger.debug(f"Clearing session {key}")
        await self.redis_client.delete(key)
        await self.redis_client.delete(f"{key}:functions")

    async def delete_session(self, user_id: str, session_id: str) -> bool:
        """
        Completely delete a session and remove it from user's session list.
        Returns True if session existed and was deleted.
        """
        key = self._get_session_key(user_id, session_id)
        logger.debug(f"Deleting session {key}")

        # Delete session messages
        deleted = await self.redis_client.delete(key)
        # Delete associated functions and imports
        await self.redis_client.delete(f"{key}:functions")
        await self.redis_client.delete(f"{key}:imports")
        # Remove from user's session list
        await self.redis_client.srem(f"user:{user_id}:sessions", session_id)

        return deleted > 0

    async def delete_message(
        self, user_id: str, session_id: str, message_id: str
    ) -> bool:
        """
        Delete a specific message by message_id from a session.
        Returns True if message was found and deleted.
        """
        key = self._get_session_key(user_id, session_id)
        logger.debug(f"Deleting message {message_id} from {key}")

        # Get all messages
        messages_json = await self.redis_client.lrange(key, 0, -1)

        # Find and remove the target message
        for msg_json in messages_json:
            msg_data = json.loads(msg_json)
            if msg_data.get("message_id") == message_id:
                # Remove from list (removes first occurrence)
                await self.redis_client.lrem(key, 1, msg_json)
                logger.debug(f"Deleted message {message_id} from session {session_id}")
                return True

        logger.debug(f"Message {message_id} not found in session {session_id}")
        return False

    async def save_functions(
        self, user_id: str, session_id: str, functions: Dict[str, str]
    ):
        """
        Save the dictionary of function names and their source code to Redis.
        """
        key = f"{self._get_session_key(user_id, session_id)}:functions"
        if functions:
            await self.redis_client.hset(key, mapping=functions)
            logger.debug(f"Saved {len(functions)} functions to {key}")
        else:
            logger.debug("No functions to save")

    async def get_functions(self, user_id: str, session_id: str) -> Dict[str, str]:
        """
        Retrieve all defined functions for the session.
        """
        key = f"{self._get_session_key(user_id, session_id)}:functions"
        functions = await self.redis_client.hgetall(key)
        logger.debug(f"Retrieved {len(functions)} functions from {key}")
        return functions

    async def save_imports(self, user_id: str, session_id: str, imports: Set[str]):
        key = f"{self._get_session_key(user_id, session_id)}:imports"
        if imports:
            await self.redis_client.sadd(key, *imports)
            logger.debug(f"Saved {len(imports)} imports to {key}")
        else:
            logger.debug("No imports to save")

    async def get_imports(self, user_id: str, session_id: str) -> Set[str]:
        key = f"{self._get_session_key(user_id, session_id)}:imports"
        imports = await self.redis_client.smembers(key)
        logger.debug(f"Retrieved {len(imports)} imports from {key}")
        return imports

    async def add_user_session(self, user_id: str, session_id: str):
        key = f"user:{user_id}:sessions"
        await self.redis_client.sadd(key, session_id)
        logger.debug(f"Added session {session_id} to user {user_id}")

    async def get_user_sessions(self, user_id: str) -> List[str]:
        key = f"user:{user_id}:sessions"
        sessions = await self.redis_client.smembers(key)
        logger.debug(f"Retrieved {len(sessions)} sessions for user {user_id}")
        return list(sessions)

    async def get_all_users(self) -> List[str]:
        """
        Get all users who have sessions stored.
        Internal method - not exposed via API.
        """
        users = set()
        # Scan for keys matching pattern user:*:sessions
        async for key in self.redis_client.scan_iter(match="user:*:sessions"):
            # Extract user_id from key format: user:{user_id}:sessions
            parts = key.split(":")
            if len(parts) == 3:
                users.add(parts[1])
        logger.debug(f"Found {len(users)} users")
        return list(users)
