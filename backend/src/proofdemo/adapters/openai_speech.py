"""OpenAI speech adapter for approved narration text."""

from __future__ import annotations

from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from openai import OpenAI, OpenAIError

from proofdemo.ports.speech import (
    SpeechDescriptor,
    SpeechPort,
    SpeechSynthesisError,
    SpeechUnavailableError,
)


class OpenAISpeechAdapter(SpeechPort):
    """Synthesize one approved cue to WAV without authoring its claims."""

    def __init__(self, model: str, voice: str, *, client: Any | None = None) -> None:
        if not model.strip() or not voice.strip():
            raise SpeechUnavailableError("explicit OpenAI speech model and voice are required")
        self._descriptor = SpeechDescriptor(provider="openai", model=model, voice=voice)
        try:
            self._client = client or OpenAI()
        except OpenAIError as error:
            raise SpeechUnavailableError(
                "OpenAI speech client configuration is unavailable"
            ) from error

    @property
    def descriptor(self) -> SpeechDescriptor:
        return self._descriptor

    def synthesize(self, text: str, output: Path) -> None:
        if not text or len(text) > 4_096:
            raise SpeechSynthesisError("approved narration text must contain 1 to 4096 characters")
        output.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            dir=output.parent,
            prefix=f".{output.stem}.",
            suffix=".wav",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
        try:
            with self._client.audio.speech.with_streaming_response.create(
                model=self._descriptor.model,
                voice=self._descriptor.voice,
                input=text,
                response_format="wav",
            ) as response:
                response.stream_to_file(temporary_path)
            if not temporary_path.is_file() or temporary_path.stat().st_size == 0:
                raise SpeechSynthesisError("speech provider produced an empty WAV file")
            temporary_path.replace(output)
        except SpeechSynthesisError:
            temporary_path.unlink(missing_ok=True)
            raise
        except OpenAIError as error:
            temporary_path.unlink(missing_ok=True)
            raise SpeechSynthesisError("OpenAI speech request failed") from error
        except OSError as error:
            temporary_path.unlink(missing_ok=True)
            raise SpeechSynthesisError("speech WAV could not be published") from error
