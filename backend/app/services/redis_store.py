import json
import redis
from typing import List, Optional, Dict, Set
from backend.app.models.chat import Message, Session
from backend.app.utils.logger import create_logger
from backend.app.core.config import Config
import os

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
            self.redis_client.ping()
            logger.info("Successfully connected to Redis.")
        except (redis.ConnectionError, redis.exceptions.ConnectionError) as e:
            logger.warning(
                f"Could not connect to Redis: {e}. Using fakeredis for local development."
            )
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
        logger.debug(f"Clearing session {key}")
        self.redis_client.delete(key)
        self.redis_client.delete(f"{key}:functions")

    def save_functions(self, user_id: str, session_id: str, functions: Dict[str, str]):
        """
        Save the dictionary of function names and their source code to Redis.
        """
        key = f"{self._get_session_key(user_id, session_id)}:functions"
        if functions:
            self.redis_client.hset(key, mapping=functions)
            logger.debug(f"Saved {len(functions)} functions to {key}")
        else:
            logger.debug("No functions to save")

    def get_functions(self, user_id: str, session_id: str) -> Dict[str, str]:
        """
        Retrieve all defined functions for the session.
        """
        key = f"{self._get_session_key(user_id, session_id)}:functions"
        functions = self.redis_client.hgetall(key)
        logger.debug(f"Retrieved {len(functions)} functions from {key}")
        return functions

    def save_imports(self, user_id: str, session_id: str, imports: Set[str]):
        key = f"{self._get_session_key(user_id, session_id)}:imports"
        if imports:
            self.redis_client.sadd(key, *imports)
            logger.debug(f"Saved {len(imports)} imports to {key}")
        else:
            logger.debug("No imports to save")

    def get_imports(self, user_id: str, session_id: str) -> Set[str]:
        key = f"{self._get_session_key(user_id, session_id)}:imports"
        imports = self.redis_client.smembers(key)
        logger.debug(f"Retrieved {len(imports)} imports from {key}")
        return imports
