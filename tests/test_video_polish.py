"""Stage 13 deterministic video presentation contract and real media smoke."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from proofdemo.adapters.ffmpeg_polish import FFmpegVideoPolisher
from proofdemo.domain.video_polish import FocusCue, PolishScene, VideoPolishPlan


def one_scene_plan() -> VideoPolishPlan:
    return VideoPolishPlan(
        source_sha256="a" * 64,
        timeline_sha256="b" * 64,
        source_duration_ms=2_000,
        output_duration_ms=2_800,
        scenes=(
            PolishScene(
                scene_id="main",
                title="Create a task",
                source_start_ms=0,
                source_end_ms=2_000,
                display_start_ms=0,
                display_end_ms=2_800,
                passed_assertions=2,
            ),
        ),
        focus_cues=(
            FocusCue(
                scene_id="main",
                action_id="click",
                kind="click",
                from_x=0.2,
                from_y=0.7,
                x=0.7,
                y=0.4,
                cursor_start_ms=700,
                source_action_ms=1_000,
                action_ms=1_000,
                zoom_start_ms=1_150,
                zoom_end_ms=2_050,
            ),
        ),
        warnings=(),
    )


def two_scene_plan() -> VideoPolishPlan:
    return VideoPolishPlan(
        source_sha256="a" * 64,
        timeline_sha256="b" * 64,
        source_duration_ms=2_000,
        output_duration_ms=3_600,
        scenes=(
            PolishScene(
                scene_id="one",
                title="First step",
                source_start_ms=0,
                source_end_ms=1_000,
                display_start_ms=0,
                display_end_ms=1_800,
                passed_assertions=1,
            ),
            PolishScene(
                scene_id="two",
                title="Second step",
                source_start_ms=1_000,
                source_end_ms=2_000,
                display_start_ms=1_800,
                display_end_ms=3_600,
                passed_assertions=1,
            ),
        ),
        focus_cues=(),
        warnings=("No reliable action geometry; static framing was preserved",),
    )


def _frame(path: Path, at_seconds: float, *, scale: bool = False) -> bytes:
    command = [
        shutil.which("ffmpeg") or "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{at_seconds:.3f}",
        "-i",
        str(path),
    ]
    if scale:
        command.extend(["-vf", "scale=1920:1080"])
    command.extend(["-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"])
    return subprocess.run(command, check=True, capture_output=True, timeout=30).stdout


def _pixel(frame: bytes, x: int, y: int) -> tuple[int, int, int]:
    start = (y * 1920 + x) * 3
    return tuple(frame[start : start + 3])  # type: ignore[return-value]


def _distance(left: tuple[int, ...], right: tuple[int, ...]) -> int:
    return sum(abs(a - b) for a, b in zip(left, right, strict=True))


@pytest.mark.parametrize("plan", [one_scene_plan(), two_scene_plan()])
def test_real_ffmpeg_polish_renders_assets_and_longer_video(
    tmp_path: Path, plan: VideoPolishPlan
) -> None:
    executable = shutil.which("ffmpeg")
    if executable is None:
        pytest.skip("FFmpeg is unavailable")
    source = tmp_path / "source.mp4"
    output = tmp_path / "polished_demo.mp4"
    subprocess.run(
        [
            executable,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=640x360:rate=30",
            "-t",
            "2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-threads",
            "1",
            str(source),
        ],
        check=True,
        timeout=30,
    )
    renderer = FFmpegVideoPolisher(timeout_seconds=90)

    assets = renderer.render(source, output, plan, tmp_path)
    result = renderer.probe(output)

    assert result.width == 1920 and result.height == 1080
    assert result.codec == "h264"
    assert abs(result.duration_ms - plan.output_duration_ms) <= 70
    assert len(assets) == len(plan.scenes) * 2 + (1 if plan.focus_cues else 0)
    assert all((tmp_path / asset).stat().st_size > 0 for asset in assets)
    if plan.focus_cues:
        base_early = _frame(source, 0.5, scale=True)
        output_early = _frame(output, 0.5)
        assert _distance(_pixel(base_early, 100, 950), _pixel(output_early, 100, 950)) > 80
        base_cursor = _frame(source, 1.05, scale=True)
        output_cursor = _frame(output, 1.05)
        assert _distance(_pixel(base_cursor, 1340, 432), _pixel(output_cursor, 1340, 432)) > 80
        base_zoom = _frame(source, 1.6, scale=True)
        output_zoom = _frame(output, 1.6)
        assert _distance(_pixel(base_zoom, 500, 250), _pixel(output_zoom, 500, 250)) > 80
        end_card = _frame(output, 2.35)
        assert _distance(_pixel(base_zoom, 1510, 120), _pixel(end_card, 1510, 120)) > 80
    else:
        transition = _frame(output, 1.8)
        assert max(_pixel(transition, 1_000, 500)) < 45


def test_untrusted_caption_text_cannot_enter_ffmpeg_filter_syntax() -> None:
    payload = "'};movie=/private/secret.mp4;{<script>alert(1)</script>"
    raw = two_scene_plan().model_dump(mode="json")
    raw["scenes"][0]["title"] = payload
    plan = VideoPolishPlan.model_validate(raw)

    graph = FFmpegVideoPolisher.build_filter(
        plan,
        (
            "polish/caption-01.png",
            "polish/caption-02.png",
            "polish/verified-01.png",
            "polish/verified-02.png",
        ),
    )

    assert payload not in graph
    assert "movie=" not in graph


def test_polish_plan_rejects_out_of_scene_visual_cue() -> None:
    raw = one_scene_plan().model_dump(mode="json")
    raw["focus_cues"][0]["zoom_end_ms"] = 3_000
    with pytest.raises(ValidationError, match="inside its verified scene"):
        VideoPolishPlan.model_validate(raw)
