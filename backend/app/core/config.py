import os
from dotenv import load_dotenv
from backend.app.utils.logger import create_logger

from pathlib import Path

# Load environment variables from .env file
load_dotenv()
DEFAULT_MODEL_NAME = "openrouter/amazon/nova-2-lite-v1:free"

logger = create_logger(__name__, level=os.environ.get("LOG_LEVEL", "debug"))


class Config:
    # API Keys
    # Prioritize generic LLM_API_KEY, then specific provider keys
    LLM_API_KEY = (
        os.environ.get("LLM_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
        or os.environ.get("HF_API_KEY")
    )

    # Model Defaults
    DEFAULT_MODEL = os.environ.get("LLM_MODEL", DEFAULT_MODEL_NAME)

    # Tavily API Key
    TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY")

    # Logging
    LOG_LEVEL = os.environ.get("LOG_LEVEL", "debug")

    # Redis
    REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
    REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))
    REDIS_PASSWORD = os.environ.get("REDIS_PASSWORD")
    REDIS_SSL = os.environ.get("REDIS_SSL", "false").lower() == "true"
    SESSION_TTL_SECONDS = int(os.environ.get("SESSION_TTL_SECONDS", 172800))  # 2 days

    # Executor Settings
    USE_CONTAINERIZED_EXECUTOR = (
        os.environ.get("USE_CONTAINERIZED_EXECUTOR", "false").lower() == "true"
    )
    EXECUTOR_URL = os.environ.get("EXECUTOR_URL", "http://localhost:8001")

    # JWT Settings
    JWT_SECRET_KEY = os.environ.get(
        "JWT_SECRET_KEY", "your-super-secret-key-change-in-production"
    )
    JWT_ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")
    JWT_EXPIRATION_HOURS = int(os.environ.get("JWT_EXPIRATION_HOURS", 24))

    SWAGGER_USERNAME = os.environ.get("SWAGGER_USERNAME")
    SWAGGER_PASSWORD = os.environ.get("SWAGGER_PASSWORD")

    # Validation
    @classmethod
    def validate(cls):
        if not cls.LLM_API_KEY:
            logger.warning("No LLM_API_KEY or provider key found.")

        # Ensure GEMINI_API_KEY is set for LiteLLM if we have a key and using Gemini
        if cls.LLM_API_KEY and "gemini" in cls.DEFAULT_MODEL.lower():
            os.environ["GEMINI_API_KEY"] = cls.LLM_API_KEY


# Run validation on import
Config.validate()
