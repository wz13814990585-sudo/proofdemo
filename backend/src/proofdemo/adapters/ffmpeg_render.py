"""FFmpeg implementation of deterministic basic video composition."""

from __future__ import annotations

import json
import shutil
import subprocess
from fractions import Fraction
from pathlib import Path
from typing import Any

from proofdemo.ports.render import (
    MediaInfo,
    RenderFailedError,
    RenderSettings,
    RenderUnavailableError,
)
from proofdemo.security import sanitize_diagnostic_text


class FFmpegRenderAdapter:
    """Probe and encode video through explicit, shell-free FFmpeg commands."""

    def __init__(
        self,
        *,
        ffmpeg_path: str | None = None,
        ffprobe_path: str | None = None,
        timeout_seconds: int = 120,
    ) -> None:
        self._ffmpeg = ffmpeg_path or shutil.which("ffmpeg")
        self._ffprobe = ffprobe_path or shutil.which("ffprobe")
        self._timeout_seconds = timeout_seconds

    def probe(self, path: Path) -> MediaInfo:
        ffprobe = self._require_executable(self._ffprobe, "ffprobe")
        command = [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,width,height,avg_frame_rate,duration:format=duration",
            "-of",
            "json",
            str(path),
        ]
        completed = self._run(command, "FFprobe")
        try:
            payload: dict[str, Any] = json.loads(completed.stdout)
            stream = payload["streams"][0]
            duration_value = stream.get("duration") or payload["format"]["duration"]
            fps = float(Fraction(stream["avg_frame_rate"]))
            duration_ms = round(float(duration_value) * 1_000)
            return MediaInfo(
                duration_ms=duration_ms,
                width=int(stream["width"]),
                height=int(stream["height"]),
                fps=fps,
                codec=str(stream["codec_name"]),
            )
        except (KeyError, IndexError, TypeError, ValueError, ZeroDivisionError) as error:
            raise RenderFailedError("FFprobe returned incomplete video metadata") from error

    def render(self, source: Path, output: Path, settings: RenderSettings) -> None:
        ffmpeg = self._require_executable(self._ffmpeg, "ffmpeg")
        output.parent.mkdir(parents=True, exist_ok=True)
        video_filter = (
            f"scale={settings.width}:{settings.height}:"
            "force_original_aspect_ratio=decrease:flags=lanczos,"
            f"pad={settings.width}:{settings.height}:(ow-iw)/2:(oh-ih)/2:color=0x0b1020,"
            f"fps={settings.fps}"
        )
        command = [
            ffmpeg,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            "-map",
            "0:v:0",
            "-vf",
            video_filter,
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
        try:
            self._run(command, "FFmpeg")
        except Exception:
            output.unlink(missing_ok=True)
            raise

    def _run(self, command: list[str], label: str) -> subprocess.CompletedProcess[str]:
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds,
            )
        except FileNotFoundError as error:
            raise RenderUnavailableError(f"{label} executable is unavailable") from error
        except subprocess.TimeoutExpired as error:
            raise RenderFailedError(f"{label} timed out") from error
        if completed.returncode != 0:
            detail = sanitize_diagnostic_text(completed.stderr.strip(), max_length=1_000)
            raise RenderFailedError(f"{label} failed: {detail or 'unknown error'}")
        return completed

    @staticmethod
    def _require_executable(path: str | None, name: str) -> str:
        if path is None:
            raise RenderUnavailableError(f"{name} executable is unavailable")
        return path
