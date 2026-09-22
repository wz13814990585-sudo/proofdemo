"""Application-owned boundary for verified video-segment concatenation."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from proofdemo.ports.render import MediaInfo, RenderSettings


@dataclass(frozen=True)
class VideoSegment:
    source: Path
    start_ms: int
    end_ms: int


class PartialRenderPort(Protocol):
    def probe(self, path: Path) -> MediaInfo:
        """Read video stream properties."""

    def render_segments(
        self,
        segments: tuple[VideoSegment, ...],
        output: Path,
        settings: RenderSettings,
    ) -> None:
        """Concatenate ordered source ranges into a silent video."""
