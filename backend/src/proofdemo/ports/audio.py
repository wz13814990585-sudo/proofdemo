"""Application-owned boundary for narration audio probing and mixing."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from proofdemo.ports.render import MediaInfo


class AudioUnavailableError(RuntimeError):
    """The configured audio runtime is unavailable."""


class AudioMixError(RuntimeError):
    """Audio probing or mixing failed deterministically."""


@dataclass(frozen=True)
class AudioInfo:
    duration_ms: int
    sample_rate: int
    channels: int
    codec: str


@dataclass(frozen=True)
class AudioMixCue:
    source: Path
    start_ms: int
    end_ms: int
    source_duration_ms: int
    tempo: float


class AudioMixPort(Protocol):
    def probe_audio(self, path: Path) -> AudioInfo:
        """Read audio stream properties."""

    def probe_video(self, path: Path) -> MediaInfo:
        """Read video stream properties."""

    def mix(
        self,
        video: Path,
        cues: tuple[AudioMixCue, ...],
        output: Path,
        *,
        duration_ms: int,
    ) -> None:
        """Align speech cues to video while preserving the video stream."""
