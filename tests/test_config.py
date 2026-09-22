"""Tests for deterministic environment and .env configuration."""

from pathlib import Path

import pytest

from proofdemo.config import ConfigurationError, Settings

ENVIRONMENT_VARIABLES = (
    "PROOFDEMO_APP_NAME",
    "PROOFDEMO_ENVIRONMENT",
    "PROOFDEMO_API_HOST",
    "PROOFDEMO_API_PORT",
    "PROOFDEMO_FRONTEND_ORIGIN",
)


def clear_proofdemo_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENVIRONMENT_VARIABLES:
        monkeypatch.delenv(name, raising=False)


def test_settings_read_namespaced_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROOFDEMO_ENVIRONMENT", "test")
    monkeypatch.setenv("PROOFDEMO_API_HOST", "0.0.0.0")
    monkeypatch.setenv("PROOFDEMO_API_PORT", "9000")
    monkeypatch.setenv("PROOFDEMO_FRONTEND_ORIGIN", "http://127.0.0.1:4173")

    settings = Settings.from_env()

    assert settings.environment == "test"
    assert settings.api_host == "0.0.0.0"
    assert settings.api_port == 9000
    assert settings.frontend_origin == "http://127.0.0.1:4173"


def test_settings_load_dotenv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    clear_proofdemo_environment(monkeypatch)
    (tmp_path / ".env").write_text(
        "PROOFDEMO_ENVIRONMENT=test\nPROOFDEMO_API_PORT=9100\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    settings = Settings.from_env()

    assert settings.environment == "test"
    assert settings.api_port == 9100


def test_real_environment_takes_precedence_over_dotenv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clear_proofdemo_environment(monkeypatch)
    (tmp_path / ".env").write_text("PROOFDEMO_API_PORT=9100\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PROOFDEMO_API_PORT", "9200")

    assert Settings.from_env().api_port == 9200


@pytest.mark.parametrize("value", ["abc", "0", "65536"])
def test_settings_reject_invalid_port(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("PROOFDEMO_API_PORT", value)

    with pytest.raises(ConfigurationError, match="api_port"):
        Settings.from_env()
