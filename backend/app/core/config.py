"""
RootAgent Backend - Core Configuration

All environment variables are loaded here. Other modules import settings
from this file - never use os.getenv() directly elsewhere.
"""

import json
import os
from typing import Optional
from urllib.parse import urlparse

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_MODEL_NAME = "openrouter/amazon/nova-2-lite-v1:free"


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=("backend/.env", ".env", "../.env", "/app/.env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        protected_namespaces=("settings_",),
    )

    # PostgreSQL
    postgres_user: str = Field(description="PostgreSQL user")
    postgres_password: str = Field(description="PostgreSQL password")
    postgres_host: str = Field(default="localhost")
    postgres_port: int = Field(default=5432)
    postgres_db: str = Field(default="rootagent")
    postgres_url: Optional[str] = Field(default=None)

    # infra-hub main_db (read-only for admin auth; credentials never stored in rootagent)
    infra_hub_postgres_db: str = Field(default="main_db")
    infra_hub_postgres_url: Optional[str] = Field(default=None)

    @model_validator(mode="after")
    def assemble_postgres_urls(self) -> "Settings":
        if not self.postgres_url:
            self.postgres_url = (
                f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}@"
                f"{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
            )
        if not self.infra_hub_postgres_url:
            self.infra_hub_postgres_url = (
                f"postgresql://{self.postgres_user}:{self.postgres_password}@"
                f"{self.postgres_host}:{self.postgres_port}/{self.infra_hub_postgres_db}"
            )
        return self

    # Redis
    redis_host: str = Field(default="localhost")
    redis_port: int = Field(default=6379)
    redis_password: Optional[str] = Field(default=None)
    redis_ssl: bool = Field(default=False)
    session_ttl_seconds: int = Field(default=172800)

    # MinIO
    minio_endpoint: str = Field(default="localhost:9000")
    minio_access_key: str = Field(description="MinIO access key")
    minio_secret_key: str = Field(description="MinIO secret key")
    minio_bucket: str = Field(default="rootagent")
    minio_secure: bool = Field(default=False)

    # JWT
    jwt_secret: str = Field(description="JWT signing secret")
    jwt_algorithm: str = Field(default="HS256")
    jwt_expire_minutes: int = Field(default=1440)

    # Swagger
    swagger_username: Optional[str] = Field(default=None)
    swagger_password: Optional[str] = Field(default=None)

    # LLM
    llm_api_key: str = Field(default="", alias="LLM_API_KEY")
    llm_model: str = Field(default=DEFAULT_MODEL_NAME, alias="LLM_MODEL")
    tavily_api_key: Optional[str] = Field(default=None, alias="TAVILY_API_KEY")

    # App
    debug: bool = Field(default=True)
    api_port: int = Field(default=8890)
    app_public_url: Optional[str] = Field(default=None)
    app_public_host: Optional[str] = Field(default=None)
    service_public_host: str = Field(default="localhost")
    cors_origins: str = Field(
        default="http://localhost:5145,http://127.0.0.1:5145",
    )
    log_level: str = Field(default="INFO")

    @model_validator(mode="after")
    def apply_public_app_settings(self) -> "Settings":
        if self.app_public_host:
            self.service_public_host = self.app_public_host
        elif self.app_public_url:
            hostname = urlparse(self.app_public_url).hostname
            if hostname:
                self.service_public_host = hostname
        return self

    @property
    def cors_origins_list(self) -> list[str]:
        raw = self.cors_origins.strip()
        if not raw:
            origins: list[str] = []
        elif raw.startswith("["):
            parsed = json.loads(raw)
            if not isinstance(parsed, list):
                raise ValueError("CORS_ORIGINS JSON value must be a list")
            origins = [str(item).strip() for item in parsed if str(item).strip()]
        else:
            origins = [origin.strip() for origin in raw.split(",") if origin.strip()]

        if self.app_public_url:
            public_origin = self.app_public_url.rstrip("/")
            if public_origin not in origins:
                origins.append(public_origin)
        return origins

    def validate_llm(self) -> None:
        if not self.llm_api_key:
            return
        if "gemini" in self.llm_model.lower():
            os.environ["GEMINI_API_KEY"] = self.llm_api_key


settings = Settings()
settings.validate_llm()

# Backward-compatible Config alias for gradual migration
Config = settings
