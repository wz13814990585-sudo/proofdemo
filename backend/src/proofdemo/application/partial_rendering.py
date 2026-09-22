"""Verified baseline/repaired scene selection and partial video composition."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from proofdemo.application.artifacts import (
    ArtifactDeclaration,
    ArtifactKind,
    ArtifactManifest,
    ArtifactRecord,
    ArtifactWriter,
)
from proofdemo.application.execution import ExecutionBundle, ExecutionReport
from proofdemo.application.rendering import VideoTimeline
from proofdemo.application.verification import VerificationStatus
from proofdemo.domain.demo_run import DemoRunStatus
from proofdemo.domain.demo_spec import DemoSpec
from proofdemo.domain.repair import SceneRepairProposal
from proofdemo.ports.partial_render import PartialRenderPort, VideoSegment
from proofdemo.ports.render import MediaInfo, RenderSettings


class PartialScene(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scene_id: str
    source: Literal["baseline", "repaired"]
    source_video_path: str
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_start_ms: int = Field(ge=0)
    source_end_ms: int = Field(gt=0)
    output_start_ms: int = Field(ge=0)
    output_end_ms: int = Field(gt=0)


class PartialRenderPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    baseline_run_id: str
    repaired_run_id: str
    repaired_scene_id: str
    output_video_path: Literal["demo-repaired.mp4"] = "demo-repaired.mp4"
    output_duration_ms: int = Field(gt=0)
    scenes: tuple[PartialScene, ...] = Field(min_length=1)


@dataclass(frozen=True)
class PartialRenderResult:
    plan: PartialRenderPlan
    output_info: MediaInfo
    declarations: tuple[ArtifactDeclaration, ...]


@dataclass(frozen=True)
class RepairExecutionContext:
    baseline_dir: Path
    baseline_spec: DemoSpec
    proposal: SceneRepairProposal


class PartialRenderRefusedError(RuntimeError):
    """Partial composition inputs are unverified, inconsistent, or tampered."""


class PartialRenderService:
    PLAN_PATH = "partial_render.json"
    OUTPUT_PATH = "demo-repaired.mp4"

    def __init__(self, renderer: PartialRenderPort) -> None:
        self._renderer = renderer

    def compose(
        self,
        context: RepairExecutionContext,
        repaired_spec: DemoSpec,
        repaired_bundle: ExecutionBundle,
        repaired_manifest: ArtifactManifest,
        repaired_timeline: VideoTimeline,
        artifact_dir: Path,
    ) -> PartialRenderResult:
        self._validate_repaired(
            context,
            repaired_spec,
            repaired_bundle,
            repaired_manifest,
            artifact_dir,
        )
        baseline_manifest = self._load_manifest(context.baseline_dir)
        baseline_report = self._load_report(context.baseline_dir)
        baseline_timeline = self._load_timeline(context.baseline_dir)
        integrity_errors = ArtifactWriter.verify(context.baseline_dir, baseline_manifest)
        if integrity_errors:
            raise PartialRenderRefusedError(
                f"baseline artifact integrity failed: {integrity_errors[0]}"
            )
        if (
            baseline_report.run.status is not DemoRunStatus.PASSED
            or baseline_report.verification_status is not VerificationStatus.PASSED
            or baseline_report.run.spec_id != context.baseline_spec.id
        ):
            raise PartialRenderRefusedError("baseline run is not a matching verified success")

        baseline_ids = [scene.scene_id for scene in baseline_timeline.scenes]
        repaired_ids = [scene.scene_id for scene in repaired_timeline.scenes]
        spec_ids = [scene.id for scene in repaired_spec.scenes]
        if baseline_ids != repaired_ids or repaired_ids != spec_ids:
            raise PartialRenderRefusedError("baseline and repaired scene sets do not match")

        baseline_video = self._record(
            baseline_manifest,
            ArtifactKind.FINAL_VIDEO,
            "demo.mp4",
        )
        repaired_video = self._record(
            repaired_manifest,
            ArtifactKind.FINAL_VIDEO,
            "demo.mp4",
        )
        baseline_path = self._contained(context.baseline_dir, baseline_video.path)
        repaired_path = self._contained(artifact_dir, repaired_video.path)
        baseline_by_id = {scene.scene_id: scene for scene in baseline_timeline.scenes}
        repaired_by_id = {scene.scene_id: scene for scene in repaired_timeline.scenes}

        segments: list[VideoSegment] = []
        scenes: list[PartialScene] = []
        output_cursor = 0
        for scene_id in spec_ids:
            use_repaired = scene_id == context.proposal.scene_id
            timeline_scene = repaired_by_id[scene_id] if use_repaired else baseline_by_id[scene_id]
            record = repaired_video if use_repaired else baseline_video
            source_path = repaired_path if use_repaired else baseline_path
            duration = timeline_scene.end_ms - timeline_scene.start_ms
            segments.append(
                VideoSegment(
                    source=source_path,
                    start_ms=timeline_scene.start_ms,
                    end_ms=timeline_scene.end_ms,
                )
            )
            scenes.append(
                PartialScene(
                    scene_id=scene_id,
                    source="repaired" if use_repaired else "baseline",
                    source_video_path=record.path,
                    source_sha256=record.sha256,
                    source_start_ms=timeline_scene.start_ms,
                    source_end_ms=timeline_scene.end_ms,
                    output_start_ms=output_cursor,
                    output_end_ms=output_cursor + duration,
                )
            )
            output_cursor += duration

        plan = PartialRenderPlan(
            baseline_run_id=str(baseline_report.run.id),
            repaired_run_id=str(repaired_bundle.report.run.id),
            repaired_scene_id=context.proposal.scene_id,
            output_duration_ms=output_cursor,
            scenes=tuple(scenes),
        )
        output = self._contained(artifact_dir, self.OUTPUT_PATH)
        self._renderer.render_segments(tuple(segments), output, RenderSettings())
        try:
            output_info = self._renderer.probe(output)
            self._validate_output(plan, output_info)
            self._atomic_text(
                self._contained(artifact_dir, self.PLAN_PATH),
                plan.model_dump_json(indent=2) + "\n",
            )
        except Exception:
            output.unlink(missing_ok=True)
            raise
        return PartialRenderResult(
            plan=plan,
            output_info=output_info,
            declarations=(
                ArtifactDeclaration(
                    path=self.PLAN_PATH,
                    kind=ArtifactKind.PARTIAL_RENDER_PLAN,
                    scene_id=context.proposal.scene_id,
                ),
                ArtifactDeclaration(
                    path=self.OUTPUT_PATH,
                    kind=ArtifactKind.REPAIRED_VIDEO,
                    scene_id=context.proposal.scene_id,
                ),
            ),
        )

    @staticmethod
    def _validate_repaired(
        context: RepairExecutionContext,
        repaired_spec: DemoSpec,
        bundle: ExecutionBundle,
        manifest: ArtifactManifest,
        artifact_dir: Path,
    ) -> None:
        if (
            bundle.report.run.status is not DemoRunStatus.PASSED
            or bundle.report.verification_status is not VerificationStatus.PASSED
        ):
            raise PartialRenderRefusedError("repaired run must be fully verified PASSED")
        integrity_errors = ArtifactWriter.verify(artifact_dir, manifest)
        if integrity_errors:
            raise PartialRenderRefusedError(
                f"repaired artifact integrity failed: {integrity_errors[0]}"
            )
        baseline_scenes = {scene.id: scene for scene in context.baseline_spec.scenes}
        repaired_scenes = {scene.id: scene for scene in repaired_spec.scenes}
        if baseline_scenes.keys() != repaired_scenes.keys():
            raise PartialRenderRefusedError("repair changed the DemoSpec scene set")
        for scene_id, baseline_scene in baseline_scenes.items():
            if (
                scene_id != context.proposal.scene_id
                and repaired_scenes[scene_id] != baseline_scene
            ):
                raise PartialRenderRefusedError("repair changed a non-invalidated Scene")

    @staticmethod
    def _load_manifest(directory: Path) -> ArtifactManifest:
        try:
            return ArtifactManifest.model_validate_json(
                (directory / "artifact_manifest.json").read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as error:
            raise PartialRenderRefusedError("baseline manifest is missing or invalid") from error

    @staticmethod
    def _load_report(directory: Path) -> ExecutionReport:
        try:
            return ExecutionReport.model_validate_json(
                (directory / "execution_report.json").read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as error:
            raise PartialRenderRefusedError("baseline report is missing or invalid") from error

    @staticmethod
    def _load_timeline(directory: Path) -> VideoTimeline:
        try:
            return VideoTimeline.model_validate_json(
                (directory / "timeline.json").read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as error:
            raise PartialRenderRefusedError("baseline timeline is missing or invalid") from error

    @staticmethod
    def _record(
        manifest: ArtifactManifest,
        kind: ArtifactKind,
        path: str,
    ) -> ArtifactRecord:
        record = next(
            (item for item in manifest.artifacts if item.kind is kind and item.path == path),
            None,
        )
        if record is None:
            raise PartialRenderRefusedError(f"required video artifact is missing: {path}")
        return record

    @staticmethod
    def _validate_output(plan: PartialRenderPlan, output: MediaInfo) -> None:
        if output.width != 1920 or output.height != 1080:
            raise PartialRenderRefusedError("repaired video is not 1920x1080")
        if abs(output.fps - 30.0) > 0.001 or output.codec != "h264":
            raise PartialRenderRefusedError("repaired video must be H.264 at 30 fps")
        if abs(output.duration_ms - plan.output_duration_ms) > 34:
            raise PartialRenderRefusedError(
                "repaired video duration differs by more than one frame"
            )

    @staticmethod
    def _contained(directory: Path, relative_path: str) -> Path:
        root = directory.resolve()
        path = (root / relative_path).resolve()
        if not path.is_relative_to(root):
            raise PartialRenderRefusedError("partial render path escaped artifact directory")
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
