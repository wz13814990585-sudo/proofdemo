"""Real local FFmpeg checks for Stage 6 narration mixing."""

from __future__ import annotations

import math
import shutil
import struct
import subprocess
import wave
from pathlib import Path

import pytest

from proofdemo.adapters.ffmpeg_audio import FFmpegAudioMixAdapter
from proofdemo.ports.audio import AudioMixCue, AudioUnavailableError

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")


def _write_tone(path: Path, *, duration_ms: int = 400) -> None:
    sample_rate = 24_000
    frame_count = round(duration_ms / 1_000 * sample_rate)
    with wave.open(str(path), "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(sample_rate)
        target.writeframes(
            b"".join(
                struct.pack("<h", round(5_000 * math.sin(2 * math.pi * 440 * i / sample_rate)))
                for i in range(frame_count)
            )
        )


@pytest.mark.skipif(not FFMPEG or not FFPROBE, reason="FFmpeg runtime unavailable")
def test_ffmpeg_mixer_preserves_video_and_adds_aligned_aac(tmp_path: Path) -> None:
    video = tmp_path / "silent.mp4"
    speech = tmp_path / "speech.wav"
    output = tmp_path / "narrated.mp4"
    subprocess.run(
        [
            FFMPEG or "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=1920x1080:r=30:d=2",
            "-an",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-threads",
            "1",
            str(video),
        ],
        check=True,
    )
    _write_tone(speech)
    mixer = FFmpegAudioMixAdapter(ffmpeg_path=FFMPEG, ffprobe_path=FFPROBE)

    mixer.mix(
        video,
        (
            AudioMixCue(
                source=speech,
                start_ms=500,
                end_ms=1_500,
                source_duration_ms=400,
                tempo=1.0,
            ),
        ),
        output,
        duration_ms=2_000,
    )

    video_info = mixer.probe_video(output)
    audio_info = mixer.probe_audio(output)
    assert video_info.width == 1920
    assert video_info.height == 1080
    assert video_info.fps == pytest.approx(30.0)
    assert video_info.codec == "h264"
    assert video_info.duration_ms == pytest.approx(2_000, abs=34)
    assert audio_info.codec == "aac"
    assert audio_info.sample_rate == 48_000
    assert audio_info.channels == 2
    assert audio_info.duration_ms == pytest.approx(2_000, abs=34)


def test_ffmpeg_audio_adapter_reports_missing_runtime(tmp_path: Path) -> None:
    mixer = FFmpegAudioMixAdapter(ffprobe_path="/definitely/missing/ffprobe")

    with pytest.raises(AudioUnavailableError, match="unavailable"):
        mixer.probe_audio(tmp_path / "missing.wav")
