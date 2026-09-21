"""Environment-backed application configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal, cast

Environment = Literal["development", "test", "production"]


class ConfigurationError(ValueError):
    """Raised when environment configuration is invalid."""


@dataclass(frozen=True, slots=True)
class Settings:
    """Safe, non-secret settings shared by API entry points."""

    app_name: str = "proofdemo-api"
    environment: Environment = "development"
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    frontend_origin: str = "http://localhost:5173"

    @classmethod
    def from_env(cls) -> Settings:
        """Read settings from the process environment and validate them."""
        raw_environment = os.getenv("PROOFDEMO_ENVIRONMENT", "development")
        if raw_environment not in {"development", "test", "production"}:
            raise ConfigurationError(
                "PROOFDEMO_ENVIRONMENT must be development, test, or production"
            )

        raw_port = os.getenv("PROOFDEMO_API_PORT", "8000")
        try:
            port = int(raw_port)
        except ValueError as error:
            raise ConfigurationError("PROOFDEMO_API_PORT must be an integer") from error
        if not 1 <= port <= 65_535:
            raise ConfigurationError("PROOFDEMO_API_PORT must be between 1 and 65535")

        return cls(
            environment=cast(Environment, raw_environment),
            api_host=os.getenv("PROOFDEMO_API_HOST", "127.0.0.1"),
            api_port=port,
            frontend_origin=os.getenv("PROOFDEMO_FRONTEND_ORIGIN", "http://localhost:5173"),
        )
