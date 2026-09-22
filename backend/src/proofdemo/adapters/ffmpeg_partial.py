"""FFmpeg adapter for verified partial scene composition."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from proofdemo.adapters.ffmpeg_render import FFmpegRenderAdapter
from proofdemo.ports.partial_render import VideoSegment
from proofdemo.ports.render import (
    MediaInfo,
    RenderFailedError,
    RenderSettings,
    RenderUnavailableError,
)
from proofdemo.security import sanitize_diagnostic_text


class FFmpegPartialRenderAdapter:
    """Trim and concatenate selected verified scene ranges."""

    def __init__(
        self,
        *,
        ffmpeg_path: str | None = None,
        ffprobe_path: str | None = None,
        timeout_seconds: int = 120,
    ) -> None:
        self._ffmpeg = ffmpeg_path or shutil.which("ffmpeg")
        self._timeout_seconds = timeout_seconds
        self._probe = FFmpegRenderAdapter(
            ffmpeg_path=self._ffmpeg,
            ffprobe_path=ffprobe_path,
            timeout_seconds=timeout_seconds,
        )

    def probe(self, path: Path) -> MediaInfo:
        return self._probe.probe(path)

    def render_segments(
        self,
        segments: tuple[VideoSegment, ...],
        output: Path,
        settings: RenderSettings,
    ) -> None:
        if not segments:
            raise RenderFailedError("partial render requires at least one segment")
        ffmpeg = self._ffmpeg
        if ffmpeg is None:
            raise RenderUnavailableError("ffmpeg executable is unavailable")
        sources: list[Path] = []
        source_indexes: dict[Path, int] = {}
        for segment in segments:
            resolved = segment.source.resolve()
            if resolved not in source_indexes:
                source_indexes[resolved] = len(sources)
                sources.append(resolved)
        command = [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y"]
        for source in sources:
            command.extend(["-i", str(source)])
        filters: list[str] = []
        labels: list[str] = []
        for index, segment in enumerate(segments):
            source_index = source_indexes[segment.source.resolve()]
            label = f"segment{index}"
            filters.append(
                f"[{source_index}:v]trim=start={segment.start_ms / 1_000:.6f}:"
                f"end={segment.end_ms / 1_000:.6f},setpts=PTS-STARTPTS[{label}]"
            )
            labels.append(f"[{label}]")
        filters.append(
            "".join(labels)
            + f"concat=n={len(segments)}:v=1:a=0,fps={settings.fps},format=yuv420p[outv]"
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        command.extend(
            [
                "-filter_complex",
                ";".join(filters),
                "-map",
                "[outv]",
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "18",
                "-pix_fmt",
                "yuv420p",
                "-threads",
                "1",
                "-map_metadata",
                "-1",
                "-fflags",
                "+bitexact",
                "-flags:v",
                "+bitexact",
                "-movflags",
                "+faststart",
                str(output),
            ]
        )
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds,
            )
        except FileNotFoundError as error:
            output.unlink(missing_ok=True)
            raise RenderUnavailableError("ffmpeg executable is unavailable") from error
        except subprocess.TimeoutExpired as error:
            output.unlink(missing_ok=True)
            raise RenderFailedError("partial FFmpeg render timed out") from error
        if completed.returncode != 0:
            output.unlink(missing_ok=True)
            detail = sanitize_diagnostic_text(completed.stderr.strip(), max_length=1_000)
            raise RenderFailedError(f"partial FFmpeg render failed: {detail or 'unknown error'}")
