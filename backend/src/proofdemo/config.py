"""Environment-backed application configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "test", "production"]


class ConfigurationError(ValueError):
    """Raised when environment configuration is invalid."""


class Settings(BaseSettings):
    """Validated settings loaded from .env and the process environment."""

    model_config = SettingsConfigDict(
        env_prefix="PROOFDEMO_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    app_name: str = Field(default="proofdemo-api", min_length=1, max_length=100)
    environment: Environment = "development"
    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8000, ge=1, le=65_535)
    frontend_origin: str = "http://127.0.0.1:5173"
    job_root: Path = Path("artifacts/jobs")
    planner_provider: Literal["openai", "deepseek"] = "openai"
    openai_model: str | None = None
    deepseek_model: str | None = None
    openai_tts_model: str | None = None
    openai_tts_voice: str | None = None

    @field_validator("api_host")
    @classmethod
    def validate_local_api_host(cls, value: str) -> str:
        if value not in {"127.0.0.1", "::1", "localhost"}:
            raise ValueError("unauthenticated job API must bind to a loopback host")
        return value

    @field_validator("frontend_origin")
    @classmethod
    def validate_frontend_origin(cls, value: str) -> str:
        parsed = urlsplit(value)
        try:
            _ = parsed.port
        except ValueError as error:
            raise ValueError("frontend_origin must use a valid port") from error
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname is None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or "*" in value
            or any(character.isspace() for character in value)
        ):
            raise ValueError("frontend_origin must be one credential-free HTTP(S) origin")
        return value.rstrip("/")

    @field_validator("openai_model", "deepseek_model", "openai_tts_model", "openai_tts_voice")
    @classmethod
    def normalize_optional_provider_setting(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def validate_production_transport(self) -> Settings:
        if self.environment == "production" and not self.frontend_origin.startswith("https://"):
            raise ValueError("production frontend_origin must use HTTPS")
        return self

    @classmethod
    def from_env(cls) -> Settings:
        """Load settings and expose invalid input as a stable domain error."""
        try:
            return cls()
        except ValidationError as error:
            raise ConfigurationError(str(error)) from error
