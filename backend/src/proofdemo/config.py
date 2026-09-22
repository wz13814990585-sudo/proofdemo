"""Environment-backed application configuration."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, ValidationError
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

    app_name: str = "proofdemo-api"
    environment: Environment = "development"
    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8000, ge=1, le=65_535)
    frontend_origin: str = "http://127.0.0.1:5173"
    openai_model: str | None = None

    @classmethod
    def from_env(cls) -> Settings:
        """Load settings and expose invalid input as a stable domain error."""
        try:
            return cls()
        except ValidationError as error:
            raise ConfigurationError(str(error)) from error
