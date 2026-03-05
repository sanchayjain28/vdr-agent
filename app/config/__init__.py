from __future__ import annotations

import json
import logging
import os
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from pydantic import Field, model_validator
from pydantic.fields import FieldInfo
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource


# Only load .env files if required values are missing from the environment.
def _load_dotenv_if_needed() -> None:
    local_mode = os.getenv("VDR_AGENT_ENV", "").strip().lower() == "local"
    if local_mode:
        try:  # pragma: no cover - optional dependency
            from dotenv import load_dotenv

            # Always hydrate from .env.local first in local mode without overriding explicit env.
            load_dotenv(dotenv_path=Path(".env.local"), override=False)
            # Then allow a plain .env for any other defaults.
            load_dotenv(override=False)
        except Exception:
            pass

    required_keys = (
        "VDR_AGENT_DB_HOST",
        "VDR_AGENT_DB_NAME",
        "VDR_AGENT_DB_USER",
        "AWS_BEARER_TOKEN_BEDROCK",
        "AWS_REGION",
    )

    def _missing() -> bool:
        for key in required_keys:
            val = os.getenv(key)
            if val is None or val == "" or val == "changeme":
                return True
        return False

    try:  # pragma: no cover - optional dependency
        if _missing() and not local_mode:
            from dotenv import load_dotenv

            # Prefer real environment variables; fill only missing keys from local files.
            load_dotenv(dotenv_path=Path(".env.local"), override=False)
            load_dotenv(override=False)
    except Exception:
        # Best-effort; skip if dotenv is unavailable.
        pass


logger = logging.getLogger(__name__)
LOCAL_ENV_VAR = "VDR_AGENT_ENV"
LOCAL_ENV_VALUE = "local"
DEFAULT_SECRET_NAME = "dev/vdr-agent"
SECRET_NAME_ENV = "VDR_AGENT_AWS_SECRET_NAME"
SECRET_REGION_ENV = "AWS_REGION"
SECRET_KEY_TO_FIELD = {
    "VDR_AGENT_DB_PASSWORD": "db_password",
    "AWS_BEARER_TOKEN_BEDROCK": "aws_bearer_token_bedrock",
}
SECRET_ENV_EXPORTS = ("AWS_BEARER_TOKEN_BEDROCK", "VDR_AGENT_DB_PASSWORD")
MAX_SECRET_RETRIES = 3
SECRET_RETRY_INITIAL_DELAY = 1.0


def _load_aws_secret(secret_name: str) -> dict[str, str]:
    """Fetch and cache the AWS Secrets Manager payload."""

    region = os.getenv(SECRET_REGION_ENV)

    if not region:
        # Silently skip AWS secrets if region not configured (local dev mode)
        return {}

    session = boto3.session.Session(region_name=region)
    response: dict[str, Any] | None = None
    delay = SECRET_RETRY_INITIAL_DELAY
    for attempt in range(MAX_SECRET_RETRIES):
        try:
            client = session.client("secretsmanager")
            response = client.get_secret_value(SecretId=secret_name)
            break
        except (BotoCoreError, ClientError) as exc:  # pragma: no cover - network/infra failure
            if attempt == MAX_SECRET_RETRIES - 1:
                logger.debug(
                    "Unable to fetch AWS secret %s after %s attempts: %s",
                    secret_name,
                    MAX_SECRET_RETRIES,
                    exc,
                )
                return {}
            time.sleep(delay)
            delay *= 2

    if response is None:
        logger.debug("Unable to fetch AWS secret %s", secret_name)
        return {}

    secret_string = response.get("SecretString")
    if not secret_string:
        logger.debug("AWS secret %s missing SecretString", secret_name)
        return {}

    try:
        payload = json.loads(secret_string)
    except json.JSONDecodeError:
        logger.debug("AWS secret %s contains invalid JSON", secret_name)
        return {}

    if not isinstance(payload, dict):
        logger.debug("AWS secret %s payload is not a JSON object", secret_name)
        return {}

    cleaned = {key: str(value) for key, value in payload.items() if value is not None}
    return cleaned


def _export_secret_env_vars(secret_values: dict[str, str]) -> None:
    """Populate env vars that other components expect (e.g., Bedrock token)."""

    for key in SECRET_ENV_EXPORTS:
        if key in secret_values:
            existing = os.getenv(key)
            if existing in (None, "", "changeme"):
                os.environ[key] = secret_values[key]


def _load_and_export_secret(secret_name: str) -> dict[str, str]:
    secret_values = _load_aws_secret(secret_name)
    if secret_values:
        _export_secret_env_vars(secret_values)
    return secret_values


def _bootstrap_config_sources() -> None:
    """Ensure secrets are consulted before falling back to env files."""

    initial_secret_name = os.getenv(SECRET_NAME_ENV, DEFAULT_SECRET_NAME)
    secrets = _load_and_export_secret(initial_secret_name)

    _load_dotenv_if_needed()

    post_env_secret_name = os.getenv(SECRET_NAME_ENV, initial_secret_name)
    if not secrets or post_env_secret_name != initial_secret_name:
        secrets = _load_and_export_secret(post_env_secret_name)


_bootstrap_config_sources()


class AwsSecretsSettingsSource(PydanticBaseSettingsSource):
    """Custom settings source that pulls values from AWS Secrets Manager."""

    def __init__(self, settings_cls: type[BaseSettings]):
        super().__init__(settings_cls)
        self._cached_values: dict[str, str] | None = None

    def __call__(self) -> dict[str, Any]:
        return self._load()

    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        data = self._load()
        if field_name not in data:
            return None, field_name, False
        return data[field_name], field_name, False

    def _load(self) -> dict[str, str]:
        if self._cached_values is not None:
            return self._cached_values

        secret_name = os.getenv(SECRET_NAME_ENV, DEFAULT_SECRET_NAME)
        secret_values = _load_aws_secret(secret_name)
        if not secret_values:
            self._cached_values = {}
            return self._cached_values

        _export_secret_env_vars(secret_values)

        mapped: dict[str, Any] = {}
        for secret_key, field_name in SECRET_KEY_TO_FIELD.items():
            if secret_key in secret_values:
                mapped[field_name] = secret_values[secret_key]
        self._cached_values = mapped
        return self._cached_values


class Settings(BaseSettings):
    """VDR Agent application settings."""

    env: str = Field(
        default="local",
        description="Deployment environment: local | staging | production",
    )
    db_host: str = Field(
        description="PostgreSQL server hostname — required: set VDR_AGENT_DB_HOST",
    )
    db_port: int = Field(
        default=5432,
        description="PostgreSQL server port",
    )
    db_name: str = Field(
        description="PostgreSQL database name — required: set VDR_AGENT_DB_NAME",
    )
    db_user: str = Field(
        description="PostgreSQL user name — required: set VDR_AGENT_DB_USER",
    )
    db_password: str | None = Field(
        default=None,
        description="PostgreSQL user password",
    )
    aws_bearer_token_bedrock: str | None = Field(
        default=None,
        description="AWS Bedrock bearer token",
    )
    aws_region: str = Field(
        default="us-east-1",
        validation_alias="AWS_REGION",
        description="AWS region",
    )
    log_level: str = Field(
        default="INFO",
        description="Root logging level",
    )
    bedrock_model: str = Field(
        default="global.anthropic.claude-sonnet-4-5-20250929-v1:0",
        description="AWS Bedrock model ID for Claude — override with VDR_AGENT_BEDROCK_MODEL",
    )
    bedrock_max_tokens: int = Field(
        default=4096,
        description="Max tokens for Bedrock Claude responses — override with VDR_AGENT_BEDROCK_MAX_TOKENS",
    )
    bedrock_max_concurrent: int = Field(
        default=10,
        description="Max concurrent Bedrock API calls (semaphore) — override with VDR_AGENT_BEDROCK_MAX_CONCURRENT",
    )
    bedrock_embedding_model: str = Field(
        default="cohere.embed-english-v3",
        description="AWS Bedrock embedding model ID for Cohere — override with VDR_AGENT_BEDROCK_EMBEDDING_MODEL",
    )
    poll_interval_seconds: int = Field(
        default=10,
        description="Poll loop sleep interval in seconds — override with VDR_AGENT_POLL_INTERVAL_SECONDS",
    )
    poll_batch_size: int = Field(
        default=5,
        description="Max documents per poll batch — override with VDR_AGENT_POLL_BATCH_SIZE",
    )
    stale_lock_threshold_minutes: int = Field(
        default=30,
        description="Minutes before a processing row is considered stale — override with VDR_AGENT_STALE_LOCK_THRESHOLD_MINUTES",
    )
    summary_section_size: int = Field(
        default=5,
        description="Number of embedding chunks per summary section — override with VDR_AGENT_SUMMARY_SECTION_SIZE",
    )
    cors_origins: list[str] = Field(
        default_factory=lambda: ["*"],
        description="Allowed CORS origins",
    )

    model_config = {
        "env_prefix": "VDR_AGENT_",
        "extra": "ignore",
        "populate_by_name": True,
    }

    @model_validator(mode="after")
    def _validate_required(self) -> "Settings":
        missing = []
        if not self.db_host:
            missing.append("VDR_AGENT_DB_HOST")
        if not self.db_name:
            missing.append("VDR_AGENT_DB_NAME")
        if not self.db_user:
            missing.append("VDR_AGENT_DB_USER")
        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")
        return self

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type["Settings"],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ):
        aws_source = AwsSecretsSettingsSource(settings_cls)
        return (
            init_settings,
            aws_source,
            env_settings,
            dotenv_settings,
            file_secret_settings,
        )


@lru_cache(maxsize=1)
def _get_cached_settings() -> Settings:
    return Settings()


def get_settings(**overrides: Any) -> Settings:
    """Return cached settings instance, allowing overrides for tests."""

    base = _get_cached_settings()
    if not overrides:
        return base
    merged = base.model_dump()
    merged.update(
        {key: value for key, value in overrides.items() if value is not None}
    )
    return Settings(**merged)


def provide_settings() -> Settings:
    """FastAPI dependency wrapper that avoids forcing query parameters."""

    return get_settings()
