"""Tests for deterministic environment configuration."""

import pytest

from proofdemo.config import ConfigurationError, Settings


def test_settings_read_namespaced_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROOFDEMO_ENVIRONMENT", "test")
    monkeypatch.setenv("PROOFDEMO_API_HOST", "0.0.0.0")
    monkeypatch.setenv("PROOFDEMO_API_PORT", "9000")
    monkeypatch.setenv("PROOFDEMO_FRONTEND_ORIGIN", "http://localhost:4173")

    settings = Settings.from_env()

    assert settings.environment == "test"
    assert settings.api_host == "0.0.0.0"
    assert settings.api_port == 9000
    assert settings.frontend_origin == "http://localhost:4173"


@pytest.mark.parametrize("value", ["abc", "0", "65536"])
def test_settings_reject_invalid_port(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("PROOFDEMO_API_PORT", value)

    with pytest.raises(ConfigurationError, match="PROOFDEMO_API_PORT"):
        Settings.from_env()
