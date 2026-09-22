"""Application-owned boundary for deterministic video probing and rendering."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class RenderUnavailableError(RuntimeError):
    """The configured media runtime is unavailable."""


class RenderFailedError(RuntimeError):
    """Media probing or encoding failed deterministically."""


@dataclass(frozen=True)
class MediaInfo:
    duration_ms: int
    width: int
    height: int
    fps: float
    codec: str


@dataclass(frozen=True)
class RenderSettings:
    width: int = 1920
    height: int = 1080
    fps: int = 30


class RenderPort(Protocol):
    def probe(self, path: Path) -> MediaInfo:
        """Read deterministic media properties for one video file."""

    def render(self, source: Path, output: Path, settings: RenderSettings) -> None:
        """Encode one source recording with fixed composition settings."""
