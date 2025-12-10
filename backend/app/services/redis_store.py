import json
import redis
from typing import List, Optional
from backend.app.models.chat import Message, Session
from backend.app.utils.logger import create_logger
from backend.app.core.config import Config
import os

logger = create_logger(__name__, level=Config.LOG_LEVEL)

class RedisStore:
    def __init__(self, host: str = "localhost", port: int = 6379, db: int = 0):
        try:
            logger.info(f"Connecting to Redis at {host}:{port}, db={db}")
            self.redis_client = redis.Redis(host=host, port=port, db=db, decode_responses=True)
            self.redis_client.ping()
            logger.info("Successfully connected to Redis.")
        except (redis.ConnectionError, redis.exceptions.ConnectionError):
            logger.warning("Could not connect to real Redis. Using fakeredis for local development.")
            import fakeredis
            self.redis_client = fakeredis.FakeRedis(decode_responses=True)

    def _get_session_key(self, user_id: str, session_id: str) -> str:
        return f"session:{user_id}:{session_id}"

    def save_message(self, user_id: str, session_id: str, message: Message):
        key = self._get_session_key(user_id, session_id)
        logger.debug(f"Saving message to {key}: {message.message_id}")
        self.redis_client.rpush(key, message.model_dump_json())

    def get_session_history(self, user_id: str, session_id: str) -> List[Message]:
        key = self._get_session_key(user_id, session_id)
        logger.debug(f"Retrieving history for {key}")
        messages_json = self.redis_client.lrange(key, 0, -1)
        return [Message(**json.loads(msg)) for msg in messages_json]

    def clear_session(self, user_id: str, session_id: str):
        key = self._get_session_key(user_id, session_id)
        logger.info(f"Clearing session {key}")
        self.redis_client.delete(key)
