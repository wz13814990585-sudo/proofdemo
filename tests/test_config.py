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
    "PROOFDEMO_OPENAI_MODEL",
    "PROOFDEMO_OPENAI_TTS_MODEL",
    "PROOFDEMO_OPENAI_TTS_VOICE",
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


def test_settings_read_explicit_planner_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROOFDEMO_OPENAI_MODEL", "account-supported-model")

    assert Settings.from_env().openai_model == "account-supported-model"


def test_settings_read_explicit_speech_model_and_voice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PROOFDEMO_OPENAI_TTS_MODEL", "account-supported-tts")
    monkeypatch.setenv("PROOFDEMO_OPENAI_TTS_VOICE", "approved-voice")

    settings = Settings.from_env()

    assert settings.openai_tts_model == "account-supported-tts"
    assert settings.openai_tts_voice == "approved-voice"


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


@pytest.mark.parametrize(
    "origin",
    [
        "*",
        "https://user:secret@example.com",
        "https://example.com/path",
        "https://example.com:99999",
        "https://example.com ",
        "ftp://example.com",
    ],
)
def test_settings_reject_invalid_frontend_origin(origin: str) -> None:
    with pytest.raises(ValueError, match="frontend_origin"):
        Settings(frontend_origin=origin)


def test_production_requires_https_frontend_origin() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        Settings(environment="production", frontend_origin="http://demo.example.com")


def test_provider_settings_normalize_blank_values() -> None:
    settings = Settings(openai_model=" ", openai_tts_model="", openai_tts_voice="  ")

    assert settings.openai_model is None
    assert settings.openai_tts_model is None
    assert settings.openai_tts_voice is None
