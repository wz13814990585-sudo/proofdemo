"""Focused tests for Stage 4 media runtime failures and timeline invariants."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from proofdemo.adapters.ffmpeg_render import FFmpegRenderAdapter
from proofdemo.application.rendering import TimelineScene, VideoTimeline
from proofdemo.ports.render import RenderUnavailableError


def test_timeline_rejects_gaps_between_scenes() -> None:
    with pytest.raises(ValidationError, match="contiguous"):
        VideoTimeline(
            source_video_path="browser.webm",
            source_sha256="a" * 64,
            source_duration_ms=1_000,
            scenes=(
                TimelineScene(scene_id="first", start_ms=0, end_ms=400),
                TimelineScene(scene_id="second", start_ms=500, end_ms=1_000),
            ),
        )


def test_ffmpeg_adapter_reports_missing_runtime_as_unavailable(tmp_path: Path) -> None:
    adapter = FFmpegRenderAdapter(ffprobe_path="/definitely/missing/ffprobe")

    with pytest.raises(RenderUnavailableError, match="unavailable"):
        adapter.probe(tmp_path / "missing.webm")
