import json
from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import JWTError, jwt
import bcrypt
import redis.asyncio as redis
from backend.app.core.config import Config
from backend.app.models.user import User, UserCreate, TokenData
from backend.app.utils.logger import create_logger

logger = create_logger(__name__, level=Config.LOG_LEVEL)


class AuthService:
    def __init__(
        self,
        host: str = Config.REDIS_HOST,
        port: int = Config.REDIS_PORT,
        password: Optional[str] = Config.REDIS_PASSWORD,
        ssl: bool = Config.REDIS_SSL,
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
            logger.info("AuthService Redis client initialized.")
        except Exception as e:
            logger.error(f"Failed to initialize AuthService Redis: {e}")
            self.redis_client = None

    def _get_user_key(self, username: str) -> str:
        """Get Redis key for user by username"""
        return f"user:auth:{username}"

    def _get_user_by_id_key(self, user_id: str) -> str:
        """Get Redis key for user by id mapping"""
        return f"user:id:{user_id}"

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """Verify a plain password against a hashed one"""
        return bcrypt.checkpw(
            plain_password.encode("utf-8"), hashed_password.encode("utf-8")
        )

    def hash_password(self, password: str) -> str:
        """Hash a password using bcrypt"""
        salt = bcrypt.gensalt()
        return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")

    def create_access_token(self, user_id: str, username: str) -> str:
        """Create a JWT access token"""
        expire = datetime.now(timezone.utc) + timedelta(
            hours=Config.JWT_EXPIRATION_HOURS
        )
        to_encode = {"sub": user_id, "username": username, "exp": expire}
        return jwt.encode(
            to_encode, Config.JWT_SECRET_KEY, algorithm=Config.JWT_ALGORITHM
        )

    def decode_token(self, token: str) -> Optional[TokenData]:
        """Decode and validate a JWT token"""
        try:
            payload = jwt.decode(
                token, Config.JWT_SECRET_KEY, algorithms=[Config.JWT_ALGORITHM]
            )
            user_id: str = payload.get("sub")
            username: str = payload.get("username")
            if user_id is None or username is None:
                return None
            return TokenData(user_id=user_id, username=username)
        except JWTError as e:
            logger.debug(f"JWT decode error: {e}")
            return None

    async def get_user_by_username(self, username: str) -> Optional[User]:
        """Retrieve a user by username from Redis"""
        key = self._get_user_key(username)
        user_data = await self.redis_client.get(key)
        if user_data:
            return User(**json.loads(user_data))
        return None

    async def get_user_by_id(self, user_id: str) -> Optional[User]:
        """Retrieve a user by user_id from Redis"""
        # First get username from user_id mapping
        key = self._get_user_by_id_key(user_id)
        username = await self.redis_client.get(key)
        if username:
            return await self.get_user_by_username(username)
        return None

    async def create_user(self, user_data: UserCreate) -> Optional[User]:
        """Create a new user and store in Redis"""
        # Check if username already exists
        existing_user = await self.get_user_by_username(user_data.username)
        if existing_user:
            logger.warning(f"Username {user_data.username} already exists")
            return None

        # Create user with hashed password
        user = User(
            username=user_data.username,
            email=user_data.email,
            hashed_password=self.hash_password(user_data.password),
        )

        # Store user data
        key = self._get_user_key(user.username)
        await self.redis_client.set(key, user.model_dump_json())

        # Store user_id -> username mapping for reverse lookup
        id_key = self._get_user_by_id_key(user.user_id)
        await self.redis_client.set(id_key, user.username)

        logger.info(f"Created new user: {user.username} with id: {user.user_id}")
        return user

    async def authenticate_user(self, username: str, password: str) -> Optional[User]:
        """Authenticate a user by username and password"""
        user = await self.get_user_by_username(username)
        if not user:
            logger.debug(f"User not found: {username}")
            return None
        if not self.verify_password(password, user.hashed_password):
            logger.debug(f"Invalid password for user: {username}")
            return None
        return user
