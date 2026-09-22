"""Provider isolation and real media tests for Stage 9 repair."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from openai import OpenAIError

from proofdemo.adapters.ffmpeg_partial import FFmpegPartialRenderAdapter
from proofdemo.adapters.openai_repair import OpenAIRepairAdapter
from proofdemo.domain.demo_spec import DemoSpec, RoleTarget
from proofdemo.domain.repair import (
    RepairFindingContext,
    RepairRequest,
    SceneRepairProposal,
    TargetReplacement,
)
from proofdemo.ports.partial_render import VideoSegment
from proofdemo.ports.render import RenderSettings, RenderUnavailableError
from proofdemo.ports.repair import RepairResponseError, RepairUnavailableError

ROOT = Path(__file__).resolve().parents[1]
FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")


class FakeResponses:
    def __init__(self, parsed: object) -> None:
        self.parsed = parsed
        self.kwargs: dict[str, object] = {}

    def parse(self, **kwargs: object) -> SimpleNamespace:
        self.kwargs = kwargs
        return SimpleNamespace(output_parsed=self.parsed)


def repair_request_and_proposal() -> tuple[RepairRequest, SceneRepairProposal]:
    spec = DemoSpec.model_validate_json(
        (ROOT / "examples" / "demo_spec.json").read_text(encoding="utf-8")
    )
    recipe_id = uuid4()
    proposal = SceneRepairProposal(
        source_recipe_id=recipe_id,
        source_spec_sha256="a" * 64,
        scene_id="create_task",
        diagnostic_categories=("SELECTOR_BROKEN",),
        replacements=(
            TargetReplacement(
                entity="action",
                entity_id="add-task",
                target=RoleTarget(strategy="role", role="button", name="Create task"),
            ),
        ),
        rationale="Use the reviewed current accessible name.",
    )
    request = RepairRequest(
        recipe_id=recipe_id,
        spec_sha256="a" * 64,
        scene=spec.scenes[0],
        findings=(
            RepairFindingContext(
                category="SELECTOR_BROKEN",
                action_id="add-task",
                description="target not actionable",
            ),
        ),
        user_hint="The button is now named Create task.",
    )
    return request, proposal


def test_openai_repair_uses_one_tool_free_structured_call() -> None:
    request, proposal = repair_request_and_proposal()
    responses = FakeResponses(proposal)
    client = SimpleNamespace(responses=responses)

    candidate = OpenAIRepairAdapter("explicit-model", client=client).propose(request)

    assert candidate.proposal == proposal
    assert responses.kwargs["model"] == "explicit-model"
    assert responses.kwargs["text_format"] is SceneRepairProposal
    assert responses.kwargs["store"] is False
    assert "tools" not in responses.kwargs
    payload = json.loads(str(responses.kwargs["input"]))
    assert payload["user_hint"] == "The button is now named Create task."


def test_openai_repair_requires_model_and_hides_provider_errors() -> None:
    request, _ = repair_request_and_proposal()
    with pytest.raises(RepairUnavailableError, match="explicit"):
        OpenAIRepairAdapter(" ", client=object())

    class FailingResponses:
        def parse(self, **kwargs: object) -> None:
            raise OpenAIError("secret provider detail")

    with pytest.raises(RepairUnavailableError, match="request failed") as captured:
        OpenAIRepairAdapter(
            "explicit-model",
            client=SimpleNamespace(responses=FailingResponses()),
        ).propose(request)
    assert "secret provider detail" not in str(captured.value)

    with pytest.raises(RepairResponseError, match="no structured proposal"):
        OpenAIRepairAdapter(
            "explicit-model",
            client=SimpleNamespace(responses=FakeResponses(None)),
        ).propose(request)


def _color_video(path: Path, color: str) -> None:
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
            f"color=c={color}:s=1920x1080:r=30:d=1",
            "-an",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-threads",
            "1",
            str(path),
        ],
        check=True,
    )


@pytest.mark.skipif(not FFMPEG or not FFPROBE, reason="FFmpeg runtime unavailable")
def test_ffmpeg_partial_renderer_concatenates_selected_ranges(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.mp4"
    repaired = tmp_path / "repaired.mp4"
    output = tmp_path / "partial.mp4"
    _color_video(baseline, "red")
    _color_video(repaired, "blue")
    adapter = FFmpegPartialRenderAdapter(ffmpeg_path=FFMPEG, ffprobe_path=FFPROBE)

    adapter.render_segments(
        (
            VideoSegment(source=baseline, start_ms=0, end_ms=500),
            VideoSegment(source=repaired, start_ms=500, end_ms=1_000),
        ),
        output,
        RenderSettings(),
    )
    info = adapter.probe(output)

    assert info.width == 1920
    assert info.height == 1080
    assert info.fps == pytest.approx(30.0)
    assert info.codec == "h264"
    assert info.duration_ms == pytest.approx(1_000, abs=34)


def test_ffmpeg_partial_renderer_reports_missing_runtime(tmp_path: Path) -> None:
    adapter = FFmpegPartialRenderAdapter(ffmpeg_path="/definitely/missing/ffmpeg")

    with pytest.raises(RenderUnavailableError, match="unavailable"):
        adapter.render_segments(
            (VideoSegment(source=tmp_path / "source.mp4", start_ms=0, end_ms=1),),
            tmp_path / "output.mp4",
            RenderSettings(),
        )
