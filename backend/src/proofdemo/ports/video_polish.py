"""Media-only port for the optional, verified video presentation layer."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from proofdemo.domain.video_polish import VideoPolishPlan
from proofdemo.ports.render import MediaInfo


class PolishUnavailableError(RuntimeError):
    """Required offline graphics or media runtime is unavailable."""


class PolishRenderError(RuntimeError):
    """A presentation render failed without changing verification truth."""


class VideoPolishPort(Protocol):
    def probe(self, path: Path) -> MediaInfo:
        """Read video metadata without changing it."""

    def render(
        self,
        source: Path,
        output: Path,
        plan: VideoPolishPlan,
        artifact_dir: Path,
    ) -> tuple[str, ...]:
        """Render the verified source and return generated overlay paths."""
