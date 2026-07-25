"""
RootAgent Backend - Core Configuration

All environment variables are loaded here. Other modules import settings
from this file - never use os.getenv() directly elsewhere.
"""

import json
import math
import os
import tempfile
import ipaddress
from collections import Counter
from pathlib import Path
from typing import Literal, Optional
from urllib.parse import parse_qs, urlparse

from pydantic import Field, field_validator, model_validator
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
        populate_by_name=True,
    )

    # PostgreSQL
    postgres_user: str = Field(description="PostgreSQL user")
    postgres_password: str = Field(description="PostgreSQL password")
    postgres_host: str = Field(default="127.0.0.1")
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
    redis_host: str = Field(default="127.0.0.1")
    redis_port: int = Field(default=63791)
    redis_password: str = Field(description="Redis password (match infra-hub REDIS_PASSWORD)")
    redis_ssl: bool = Field(default=False)
    session_ttl_seconds: int = Field(default=172800)
    ws_ticket_ttl_seconds: int = Field(default=30, ge=1, le=300)
    run_lock_ttl_seconds: int = Field(default=3600, ge=30, le=7200)

    # Abuse controls
    login_rate_limit: int = Field(default=10, ge=1)
    login_rate_window_seconds: int = Field(default=60, ge=1)
    registration_rate_limit: int = Field(default=5, ge=1)
    registration_rate_window_seconds: int = Field(default=3600, ge=1)
    chat_rate_limit: int = Field(default=10, ge=1)
    chat_rate_window_seconds: int = Field(default=60, ge=1)
    upload_rate_limit: int = Field(default=20, ge=1)
    upload_rate_window_seconds: int = Field(default=3600, ge=1)

    # MinIO
    minio_endpoint: str = Field(default="127.0.0.1:9000")
    minio_access_key: str = Field(description="MinIO access key")
    minio_secret_key: str = Field(description="MinIO secret key")
    minio_bucket: str = Field(default="rootagent")
    minio_secure: bool = Field(default=False)
    storage_threadpool_workers: int = Field(default=4, ge=1, le=32)
    storage_stream_chunk_bytes: int = Field(default=1024 * 1024, ge=64 * 1024)

    # File validation and generated-output quotas
    max_upload_bytes: int = Field(default=50 * 1024 * 1024, ge=1)
    upload_spool_bytes: int = Field(default=8 * 1024 * 1024, ge=1)
    max_xlsx_entries: int = Field(default=10_000, ge=1)
    max_xlsx_expanded_bytes: int = Field(default=500 * 1024 * 1024, ge=1)
    max_xlsx_compression_ratio: int = Field(default=100, ge=1)
    max_png_pixels: int = Field(default=40_000_000, ge=1)
    max_generated_file_bytes: int = Field(default=50 * 1024 * 1024, ge=1)
    max_generated_run_bytes: int = Field(default=100 * 1024 * 1024, ge=1)
    max_generated_files_per_run: int = Field(default=20, ge=1)
    max_artifact_parsed_cells: int = Field(default=1_000_000, ge=1)

    # JWT
    jwt_secret: str = Field(description="JWT signing secret")
    jwt_algorithm: str = Field(default="HS256")
    jwt_expire_minutes: int = Field(default=1440)

    # Swagger docs (HTTP Basic); set both in .env to enable
    swagger_username: Optional[str] = Field(default=None)
    swagger_password: Optional[str] = Field(default=None)

    # LLM
    llm_api_key: str = Field(default="", alias="LLM_API_KEY")
    llm_model: str = Field(default=DEFAULT_MODEL_NAME, alias="LLM_MODEL")
    tavily_api_key: Optional[str] = Field(default=None, alias="TAVILY_API_KEY")

    # App
    environment: Literal["development", "test", "production"] = Field(
        default="development"
    )
    debug: bool = Field(default=True)
    api_port: int = Field(default=8890)
    app_public_url: Optional[str] = Field(default=None)
    app_public_host: Optional[str] = Field(default=None)
    service_public_host: str = Field(default="localhost")
    cors_origins: str = Field(
        default="http://localhost:5145,http://127.0.0.1:5145",
    )
    trusted_proxy_ips: str = Field(default="")
    log_level: str = Field(default="INFO")
    sql_echo: bool = Field(
        default=False,
        description=(
            "Log SQL statements via the app logger (colored). "
            "Also enabled automatically when LOG_LEVEL=DEBUG. "
            "Never uses SQLAlchemy engine echo= (avoids duplicate white logs)."
        ),
    )
    executor_backend: Literal["local", "grpc"] = Field(default="local")
    allow_unsafe_local_executor: bool = Field(default=False)
    executor_workspace_root: str = Field(
        default_factory=lambda: str(Path(tempfile.gettempdir()) / "rootagent-workspaces")
    )
    executor_default_deadline_seconds: float = Field(default=120.0, gt=0)
    executor_stdout_max_bytes: int = Field(default=64 * 1024, ge=0)
    executor_stderr_max_bytes: int = Field(default=64 * 1024, ge=0)

    # Future isolated runtime.  The current gRPC backend validates these settings
    # but intentionally remains unavailable until generated clients and contract
    # tests are introduced.
    grpc_executor_target: str = Field(default="")
    grpc_executor_tls: bool = Field(default=True)
    grpc_executor_ca_cert: Optional[str] = Field(default=None)
    grpc_executor_client_cert: Optional[str] = Field(default=None)
    grpc_executor_client_key: Optional[str] = Field(default=None)
    grpc_executor_auth_token: Optional[str] = Field(default=None)

    @field_validator("trusted_proxy_ips")
    @classmethod
    def validate_trusted_proxy_ips(cls, value: str) -> str:
        for item in value.split(","):
            item = item.strip()
            if item:
                ipaddress.ip_network(item, strict=False)
        return value

    @model_validator(mode="after")
    def apply_public_app_settings(self) -> "Settings":
        if self.app_public_host:
            self.service_public_host = self.app_public_host
        elif self.app_public_url:
            hostname = urlparse(self.app_public_url).hostname
            if hostname:
                self.service_public_host = hostname
        return self

    @model_validator(mode="after")
    def validate_executor_settings(self) -> "Settings":
        if self.executor_backend != "grpc":
            return self
        if not self.grpc_executor_target.strip():
            raise ValueError("GRPC_EXECUTOR_TARGET is required for the gRPC backend")
        if bool(self.grpc_executor_client_cert) != bool(
            self.grpc_executor_client_key
        ):
            raise ValueError(
                "GRPC_EXECUTOR_CLIENT_CERT and GRPC_EXECUTOR_CLIENT_KEY "
                "must be set together"
            )
        return self

    @model_validator(mode="after")
    def validate_production_settings(self) -> "Settings":
        """Reject development defaults and unsafe implicit choices in production."""
        if self.environment != "production":
            return self

        errors: list[str] = []
        placeholders = {
            "",
            "change-me",
            "change-me-in-production",
            "password",
            "password123",
            "secret",
            "test",
            "test-secret-key",
        }

        def is_placeholder(value: str | None) -> bool:
            return value is None or value.strip().lower() in placeholders

        def entropy_bits(value: str) -> float:
            counts = Counter(value.encode("utf-8"))
            length = sum(counts.values())
            return sum(
                -(count / length) * math.log2(count / length) * length
                for count in counts.values()
            )

        if self.debug:
            errors.append("DEBUG must be false")
        if self.jwt_algorithm not in {"HS256", "HS384", "HS512"}:
            errors.append("JWT_ALGORITHM must be HS256, HS384, or HS512")
        jwt_minimum = {"HS256": 32, "HS384": 48, "HS512": 64}.get(
            self.jwt_algorithm, 64
        )
        if is_placeholder(self.jwt_secret) or len(
            self.jwt_secret.encode("utf-8")
        ) < jwt_minimum or entropy_bits(self.jwt_secret) < 128:
            errors.append(
                "JWT_SECRET must be non-placeholder, sufficiently diverse, and at "
                f"least {jwt_minimum} bytes"
            )

        required_secrets = {
            "POSTGRES_PASSWORD": self.postgres_password,
            "REDIS_PASSWORD": self.redis_password,
            "MINIO_ACCESS_KEY": self.minio_access_key,
            "MINIO_SECRET_KEY": self.minio_secret_key,
            "LLM_API_KEY": self.llm_api_key,
        }
        for name, value in required_secrets.items():
            if is_placeholder(value):
                errors.append(f"{name} must be configured with a non-placeholder value")

        origins = self.cors_origins_list
        if not origins or "*" in origins:
            errors.append("CORS_ORIGINS must contain explicit production origins")
        if any(
            urlparse(origin).hostname in {"localhost", "127.0.0.1"}
            for origin in origins
        ):
            errors.append("CORS_ORIGINS must not contain localhost in production")
        if any(urlparse(origin).scheme != "https" for origin in origins):
            errors.append("CORS_ORIGINS must contain only https origins in production")
        if not self.trusted_proxy_networks:
            errors.append("TRUSTED_PROXY_IPS must identify the central proxy")
        if not self.app_public_url or urlparse(self.app_public_url).scheme != "https":
            errors.append("APP_PUBLIC_URL must be an https URL")
        local_hosts = {"localhost", "127.0.0.1", "::1"}
        postgres = urlparse(self.postgres_url or "")
        postgres_tls = parse_qs(postgres.query).get("ssl", []) + parse_qs(
            postgres.query
        ).get("sslmode", [])
        if (
            postgres.scheme != "postgresql+asyncpg"
            or postgres.hostname in local_hosts
            or not any(value in {"require", "verify-ca", "verify-full"} for value in postgres_tls)
        ):
            errors.append("POSTGRES_URL must use asyncpg, a non-local host, and required TLS")
        infra_postgres = urlparse(self.infra_hub_postgres_url or "")
        infra_tls = parse_qs(infra_postgres.query).get("sslmode", [])
        if (
            infra_postgres.scheme != "postgresql"
            or infra_postgres.hostname in local_hosts
            or not any(
                value in {"require", "verify-ca", "verify-full"}
                for value in infra_tls
            )
        ):
            errors.append(
                "INFRA_HUB_POSTGRES_URL must use a non-local host and required TLS"
            )
        if self.redis_host in local_hosts:
            errors.append("REDIS_HOST must not be local in production")
        if not self.redis_ssl:
            errors.append("REDIS_SSL must be true in production")
        minio_host = urlparse(f"//{self.minio_endpoint}").hostname
        if minio_host in local_hosts:
            errors.append("MINIO_ENDPOINT must not be local in production")
        if not self.minio_secure:
            errors.append("MINIO_SECURE must be true in production")
        if self.executor_backend == "local" and not self.allow_unsafe_local_executor:
            errors.append(
                "ALLOW_UNSAFE_LOCAL_EXECUTOR=true is required for the local executor"
            )
        if self.executor_backend == "grpc" and not self.grpc_executor_tls:
            errors.append("GRPC_EXECUTOR_TLS must be true in production")

        if errors:
            raise ValueError("Invalid production configuration: " + "; ".join(errors))
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

    @property
    def trusted_proxy_networks(self) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
        networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
        for value in self.trusted_proxy_ips.split(","):
            value = value.strip()
            if value:
                networks.append(ipaddress.ip_network(value, strict=False))
        return networks

    def validate_llm(self) -> None:
        if not self.llm_api_key:
            return
        if "gemini" in self.llm_model.lower():
            os.environ["GEMINI_API_KEY"] = self.llm_api_key


settings = Settings()
settings.validate_llm()

# Backward-compatible Config alias for gradual migration
Config = settings
