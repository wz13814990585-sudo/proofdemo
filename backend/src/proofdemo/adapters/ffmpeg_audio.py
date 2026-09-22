"""FFmpeg implementation of narration probing and scene-aligned mixing."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from proofdemo.adapters.ffmpeg_render import FFmpegRenderAdapter
from proofdemo.ports.audio import (
    AudioInfo,
    AudioMixCue,
    AudioMixError,
    AudioUnavailableError,
)
from proofdemo.ports.render import MediaInfo, RenderFailedError, RenderUnavailableError
from proofdemo.security import sanitize_diagnostic_text


class FFmpegAudioMixAdapter:
    """Probe WAV input and mix bounded cues into an existing video."""

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
        self._video_probe = FFmpegRenderAdapter(
            ffmpeg_path=self._ffmpeg,
            ffprobe_path=self._ffprobe,
            timeout_seconds=timeout_seconds,
        )

    def probe_audio(self, path: Path) -> AudioInfo:
        ffprobe = self._require_executable(self._ffprobe, "ffprobe")
        completed = self._run(
            [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=codec_name,sample_rate,channels,duration:format=duration",
                "-of",
                "json",
                str(path),
            ],
            "FFprobe audio",
        )
        try:
            payload: dict[str, Any] = json.loads(completed.stdout)
            stream = payload["streams"][0]
            duration = stream.get("duration") or payload["format"]["duration"]
            return AudioInfo(
                duration_ms=round(float(duration) * 1_000),
                sample_rate=int(stream["sample_rate"]),
                channels=int(stream["channels"]),
                codec=str(stream["codec_name"]),
            )
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise AudioMixError("FFprobe returned incomplete audio metadata") from error

    def probe_video(self, path: Path) -> MediaInfo:
        try:
            return self._video_probe.probe(path)
        except RenderUnavailableError as error:
            raise AudioUnavailableError(str(error)) from error
        except RenderFailedError as error:
            raise AudioMixError(str(error)) from error

    def mix(
        self,
        video: Path,
        cues: tuple[AudioMixCue, ...],
        output: Path,
        *,
        duration_ms: int,
    ) -> None:
        if not cues:
            raise AudioMixError("at least one narration cue is required")
        ffmpeg = self._require_executable(self._ffmpeg, "ffmpeg")
        output.parent.mkdir(parents=True, exist_ok=True)
        command = [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(video)]
        for cue in cues:
            command.extend(["-i", str(cue.source)])

        filters: list[str] = []
        labels: list[str] = []
        for index, cue in enumerate(cues, start=1):
            slot_seconds = (cue.end_ms - cue.start_ms) / 1_000
            chain = f"[{index}:a]asetpts=PTS-STARTPTS"
            if cue.tempo > 1.000001:
                chain += f",atempo={cue.tempo:.6f}"
            label = f"cue{index}"
            chain += (
                f",apad=whole_dur={slot_seconds:.6f}"
                f",atrim=duration={slot_seconds:.6f}"
                f",adelay={cue.start_ms}:all=1[{label}]"
            )
            filters.append(chain)
            labels.append(f"[{label}]")
        filters.append(
            "".join(labels)
            + f"amix=inputs={len(cues)}:duration=longest:normalize=0,"
            + f"apad=whole_dur={duration_ms / 1_000:.6f},"
            + f"atrim=duration={duration_ms / 1_000:.6f},asetpts=PTS-STARTPTS[aout]"
        )
        command.extend(
            [
                "-filter_complex",
                ";".join(filters),
                "-map",
                "0:v:0",
                "-map",
                "[aout]",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                "160k",
                "-ar",
                "48000",
                "-ac",
                "2",
                "-t",
                f"{duration_ms / 1_000:.6f}",
                "-map_metadata",
                "-1",
                "-fflags",
                "+bitexact",
                "-movflags",
                "+faststart",
                str(output),
            ]
        )
        try:
            self._run(command, "FFmpeg audio mix")
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
            raise AudioUnavailableError(f"{label} executable is unavailable") from error
        except subprocess.TimeoutExpired as error:
            raise AudioMixError(f"{label} timed out") from error
        if completed.returncode != 0:
            detail = sanitize_diagnostic_text(completed.stderr.strip(), max_length=1_000)
            raise AudioMixError(f"{label} failed: {detail or 'unknown error'}")
        return completed

    @staticmethod
    def _require_executable(path: str | None, name: str) -> str:
        if path is None:
            raise AudioUnavailableError(f"{name} executable is unavailable")
        return path
