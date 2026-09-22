"""Provider-isolation tests for Stage 6 speech synthesis."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from openai import OpenAIError

from proofdemo.adapters.openai_speech import OpenAISpeechAdapter
from proofdemo.ports.speech import SpeechSynthesisError, SpeechUnavailableError


class FakeSpeechResponse:
    def __enter__(self) -> FakeSpeechResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def stream_to_file(self, path: Path) -> None:
        path.write_bytes(b"RIFF fake wav")


class FakeSpeechCreate:
    def __init__(self) -> None:
        self.kwargs: dict[str, object] = {}

    def create(self, **kwargs: object) -> FakeSpeechResponse:
        self.kwargs = kwargs
        return FakeSpeechResponse()


def fake_client(create: object) -> SimpleNamespace:
    return SimpleNamespace(
        audio=SimpleNamespace(
            speech=SimpleNamespace(with_streaming_response=create),
        )
    )


def test_openai_speech_uses_explicit_model_voice_and_wav(tmp_path: Path) -> None:
    create = FakeSpeechCreate()
    adapter = OpenAISpeechAdapter(
        "explicit-tts-model",
        "explicit-voice",
        client=fake_client(create),
    )
    output = tmp_path / "scene.wav"

    adapter.synthesize("Approved evidence text.", output)

    assert output.read_bytes() == b"RIFF fake wav"
    assert adapter.descriptor.provider == "openai"
    assert create.kwargs == {
        "model": "explicit-tts-model",
        "voice": "explicit-voice",
        "input": "Approved evidence text.",
        "response_format": "wav",
    }
    assert list(tmp_path.iterdir()) == [output]


def test_openai_speech_requires_explicit_model_and_voice() -> None:
    with pytest.raises(SpeechUnavailableError, match="explicit"):
        OpenAISpeechAdapter("", "voice", client=object())
    with pytest.raises(SpeechUnavailableError, match="explicit"):
        OpenAISpeechAdapter("model", " ", client=object())


def test_openai_speech_hides_provider_error_and_preserves_existing_output(
    tmp_path: Path,
) -> None:
    class FailingCreate:
        def create(self, **kwargs: object) -> None:
            raise OpenAIError("secret provider detail")

    output = tmp_path / "scene.wav"
    output.write_bytes(b"previous audio")
    adapter = OpenAISpeechAdapter(
        "explicit-model",
        "explicit-voice",
        client=fake_client(FailingCreate()),
    )

    with pytest.raises(SpeechSynthesisError, match="request failed") as captured:
        adapter.synthesize("Approved text.", output)

    assert "secret provider detail" not in str(captured.value)
    assert output.read_bytes() == b"previous audio"
    assert list(tmp_path.iterdir()) == [output]
