import os
from dotenv import load_dotenv
from backend.app.utils.logger import create_logger

# Load environment variables from .env file
load_dotenv()
DEFAULT_MODEL_NAME = "gemini/gemini-2.5-flash"

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

    # Logging
    LOG_LEVEL = os.environ.get("LOG_LEVEL", "debug")

    # Redis
    REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
    REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))
    REDIS_PASSWORD = os.environ.get("REDIS_PASSWORD")
    REDIS_SSL = os.environ.get("REDIS_SSL", "false").lower() == "true"

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
