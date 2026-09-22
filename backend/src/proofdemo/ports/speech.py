"""Application-owned boundary for text-to-speech synthesis."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class SpeechUnavailableError(RuntimeError):
    """Speech configuration or provider infrastructure is unavailable."""


class SpeechSynthesisError(RuntimeError):
    """The provider could not produce a valid speech artifact."""


@dataclass(frozen=True)
class SpeechDescriptor:
    provider: str
    model: str
    voice: str


class SpeechPort(Protocol):
    @property
    def descriptor(self) -> SpeechDescriptor:
        """Return non-secret provider provenance for generated speech."""

    def synthesize(self, text: str, output: Path) -> None:
        """Atomically synthesize approved text as a WAV file."""
