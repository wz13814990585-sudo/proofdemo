"""Deterministic trace-to-timeline policy and verified video composition."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from proofdemo.application.artifacts import (
    ArtifactDeclaration,
    ArtifactKind,
    ArtifactManifest,
    ArtifactWriter,
)
from proofdemo.application.execution import ExecutionBundle
from proofdemo.application.trace import TraceEvent, TraceEventKind
from proofdemo.application.verification import OutcomeStatus, VerificationStatus
from proofdemo.domain.demo_run import DemoRunStatus
from proofdemo.ports.render import MediaInfo, RenderPort, RenderSettings


class TimelineScene(BaseModel):
    """One verified scene's contiguous range in the source recording."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scene_id: str
    status: Literal["PASSED"] = "PASSED"
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_range(self) -> TimelineScene:
        if self.end_ms <= self.start_ms:
            raise ValueError("timeline scene end must be after its start")
        return self


class VideoTimeline(BaseModel):
    """Versioned deterministic mapping from verified trace to source time."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    source_video_path: str
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_duration_ms: int = Field(gt=0)
    output_width: Literal[1920] = 1920
    output_height: Literal[1080] = 1080
    output_fps: Literal[30] = 30
    scenes: tuple[TimelineScene, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_coverage(self) -> VideoTimeline:
        if self.scenes[0].start_ms != 0:
            raise ValueError("timeline must start at zero")
        if self.scenes[-1].end_ms != self.source_duration_ms:
            raise ValueError("timeline must cover the complete source duration")
        for previous, current in zip(self.scenes, self.scenes[1:], strict=False):
            if previous.end_ms != current.start_ms:
                raise ValueError("timeline scenes must be contiguous and non-overlapping")
        return self


@dataclass(frozen=True)
class CompositionResult:
    timeline: VideoTimeline
    output_info: MediaInfo
    declarations: tuple[ArtifactDeclaration, ...]


class CompositionRefusedError(RuntimeError):
    """Composition input is unverified, incomplete, or fails integrity checks."""


class CompositionService:
    """Own timeline policy while delegating media mechanics to a render port."""

    TIMELINE_PATH = "timeline.json"
    OUTPUT_PATH = "demo.mp4"

    def __init__(self, renderer: RenderPort) -> None:
        self._renderer = renderer

    def compose(
        self,
        bundle: ExecutionBundle,
        manifest: ArtifactManifest,
        artifact_dir: Path,
    ) -> CompositionResult:
        report = bundle.report
        if (
            report.run.status is not DemoRunStatus.PASSED
            or report.verification_status is not VerificationStatus.PASSED
        ):
            raise CompositionRefusedError("only a verified PASSED run can be composed")
        integrity_errors = ArtifactWriter.verify(artifact_dir, manifest)
        if integrity_errors:
            raise CompositionRefusedError(f"artifact integrity check failed: {integrity_errors[0]}")
        if report.browser_video_path is None:
            raise CompositionRefusedError("verified run has no browser video")

        source_record = next(
            (
                record
                for record in manifest.artifacts
                if record.kind is ArtifactKind.BROWSER_VIDEO
                and record.path == report.browser_video_path
            ),
            None,
        )
        if source_record is None:
            raise CompositionRefusedError("browser video is absent from artifact manifest")

        source = self._contained(artifact_dir, report.browser_video_path)
        source_info = self._renderer.probe(source)
        timeline = self._build_timeline(
            bundle,
            source_info,
            source_sha256=source_record.sha256,
        )
        output = self._contained(artifact_dir, self.OUTPUT_PATH)
        self._renderer.render(source, output, RenderSettings())
        try:
            output_info = self._renderer.probe(output)
            self._validate_output(source_info, output_info)
            self._atomic_text(
                self._contained(artifact_dir, self.TIMELINE_PATH),
                timeline.model_dump_json(indent=2) + "\n",
            )
        except Exception:
            output.unlink(missing_ok=True)
            raise

        return CompositionResult(
            timeline=timeline,
            output_info=output_info,
            declarations=(
                ArtifactDeclaration(path=self.TIMELINE_PATH, kind=ArtifactKind.TIMELINE),
                ArtifactDeclaration(path=self.OUTPUT_PATH, kind=ArtifactKind.FINAL_VIDEO),
            ),
        )

    @staticmethod
    def _build_timeline(
        bundle: ExecutionBundle,
        source_info: MediaInfo,
        *,
        source_sha256: str,
    ) -> VideoTimeline:
        scene_results = bundle.report.scene_results
        if any(scene.status is not OutcomeStatus.PASSED for scene in scene_results):
            raise CompositionRefusedError("timeline contains an unverified scene")
        if source_info.duration_ms < len(scene_results):
            raise CompositionRefusedError("source video is too short for verified scenes")

        starts: list[TraceEvent] = []
        ends: list[TraceEvent] = []
        for scene in scene_results:
            start = next(
                (
                    event
                    for event in bundle.trace_events
                    if event.kind is TraceEventKind.ACTION_STARTED
                    and event.scene_id == scene.scene_id
                ),
                None,
            )
            end = next(
                (
                    event
                    for event in reversed(bundle.trace_events)
                    if event.kind is TraceEventKind.SCENE_EVALUATED
                    and event.scene_id == scene.scene_id
                ),
                None,
            )
            if start is None or end is None or end.occurred_at < start.occurred_at:
                raise CompositionRefusedError(
                    f"trace lacks a valid range for Scene {scene.scene_id}"
                )
            starts.append(start)
            ends.append(end)

        trace_start = starts[0].occurred_at
        trace_end = ends[-1].occurred_at
        elapsed_ms = max(1, round((trace_end - trace_start).total_seconds() * 1_000))
        boundaries = [0]
        scene_count = len(scene_results)
        for index, event in enumerate(starts[1:], start=1):
            relative_ms = max(
                0,
                round((event.occurred_at - trace_start).total_seconds() * 1_000),
            )
            scaled = round(relative_ms / elapsed_ms * source_info.duration_ms)
            minimum = boundaries[-1] + 1
            maximum = source_info.duration_ms - (scene_count - index)
            boundaries.append(min(maximum, max(minimum, scaled)))
        boundaries.append(source_info.duration_ms)

        scenes = tuple(
            TimelineScene(
                scene_id=scene.scene_id,
                start_ms=boundaries[index],
                end_ms=boundaries[index + 1],
            )
            for index, scene in enumerate(scene_results)
        )
        return VideoTimeline(
            source_video_path=bundle.report.browser_video_path or "",
            source_sha256=source_sha256,
            source_duration_ms=source_info.duration_ms,
            scenes=scenes,
        )

    @staticmethod
    def _validate_output(source: MediaInfo, output: MediaInfo) -> None:
        if output.width != 1920 or output.height != 1080:
            raise CompositionRefusedError("rendered video is not 1920x1080")
        if abs(output.fps - 30.0) > 0.001:
            raise CompositionRefusedError("rendered video is not 30 fps")
        if output.codec != "h264":
            raise CompositionRefusedError("rendered video is not H.264")
        if abs(output.duration_ms - source.duration_ms) > 34:
            raise CompositionRefusedError("rendered duration differs by more than one frame")

    @staticmethod
    def _contained(artifact_dir: Path, relative_path: str) -> Path:
        root = artifact_dir.resolve()
        path = (root / relative_path).resolve()
        if not path.is_relative_to(root):
            raise CompositionRefusedError("composition path escaped artifact directory")
        return path

    @staticmethod
    def _atomic_text(path: Path, content: str) -> None:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as temporary:
            temporary.write(content)
            temporary.flush()
            temporary_path = Path(temporary.name)
        temporary_path.replace(path)
