"""Evidence-derived edit plan and guarded polished-video publication."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Literal, cast

from proofdemo.application.artifacts import (
    ArtifactDeclaration,
    ArtifactKind,
    ArtifactManifest,
    ArtifactWriter,
)
from proofdemo.application.execution import (
    ActionResultStatus,
    ExecutionBundle,
    safe_artifact_path,
)
from proofdemo.application.rendering import VideoTimeline
from proofdemo.application.trace import TraceEventKind
from proofdemo.application.verification import OutcomeStatus, VerificationStatus
from proofdemo.domain.demo_run import DemoRunStatus
from proofdemo.domain.demo_spec import DemoSpec
from proofdemo.domain.video_polish import (
    CaptionCue,
    CaptionTrack,
    FocusCue,
    PolishScene,
    VideoPolishPlan,
)
from proofdemo.ports.render import MediaInfo
from proofdemo.ports.video_polish import VideoPolishPort


class VideoPolishRefusedError(RuntimeError):
    """The source lacks verified, intact, or time-aligned evidence."""


@dataclass(frozen=True)
class VideoPolishResult:
    plan: VideoPolishPlan
    output_info: MediaInfo
    declarations: tuple[ArtifactDeclaration, ...]


class VideoPolishService:
    PLAN_PATH = "polish_plan.json"
    CAPTIONS_PATH = "polish_captions.json"
    OUTPUT_PATH = "polished_demo.mp4"
    HOLD_MS = 800
    MAX_SCENES = 12
    MAX_CUES = 24

    def __init__(self, polisher: VideoPolishPort) -> None:
        self._polisher = polisher

    def polish(
        self,
        spec: DemoSpec,
        bundle: ExecutionBundle,
        timeline: VideoTimeline,
        manifest: ArtifactManifest,
        artifact_dir: Path,
    ) -> VideoPolishResult:
        report = bundle.report
        if (
            report.run.status is not DemoRunStatus.PASSED
            or report.verification_status is not VerificationStatus.PASSED
            or any(scene.status is not OutcomeStatus.PASSED for scene in report.scene_results)
        ):
            raise VideoPolishRefusedError("only a fully verified run can be polished")
        if len(spec.scenes) > self.MAX_SCENES:
            raise VideoPolishRefusedError("video polish supports at most 12 scenes")
        if spec.id != report.run.spec_id or len(spec.scenes) != len(timeline.scenes):
            raise VideoPolishRefusedError("specification and timeline identities differ")
        problems = ArtifactWriter.verify(artifact_dir, manifest)
        if problems:
            raise VideoPolishRefusedError(f"source artifact integrity failed: {problems[0]}")
        source_record = next(
            (
                record
                for record in manifest.artifacts
                if record.kind is ArtifactKind.FINAL_VIDEO and record.path == "demo.mp4"
            ),
            None,
        )
        timeline_record = next(
            (
                record
                for record in manifest.artifacts
                if record.kind is ArtifactKind.TIMELINE and record.path == "timeline.json"
            ),
            None,
        )
        if source_record is None or timeline_record is None:
            raise VideoPolishRefusedError("verified source video or timeline is absent")
        persisted_timeline = VideoTimeline.model_validate_json(
            safe_artifact_path(artifact_dir, timeline_record.path).read_bytes()
        )
        if persisted_timeline != timeline:
            raise VideoPolishRefusedError("timeline changed after composition")
        source = safe_artifact_path(artifact_dir, source_record.path)
        source_info = self._polisher.probe(source)
        if (
            source_info.width != 1920
            or source_info.height != 1080
            or abs(source_info.fps - 30.0) > 0.001
            or source_info.codec != "h264"
            or abs(source_info.duration_ms - timeline.source_duration_ms) > 34
        ):
            raise VideoPolishRefusedError("basic video does not match its verified timeline")
        plan = self.build_plan(
            spec,
            bundle,
            timeline,
            source_info.duration_ms,
            source_sha256=source_record.sha256,
            timeline_sha256=timeline_record.sha256,
        )
        output = safe_artifact_path(artifact_dir, self.OUTPUT_PATH)
        try:
            overlays = self._polisher.render(source, output, plan, artifact_dir)
            output_info = self._polisher.probe(output)
            if (
                output_info.width != 1920
                or output_info.height != 1080
                or abs(output_info.fps - 30.0) > 0.001
                or output_info.codec != "h264"
                or abs(output_info.duration_ms - plan.output_duration_ms) > 70
            ):
                raise VideoPolishRefusedError("polished video properties do not match the plan")
            self._atomic_text(
                safe_artifact_path(artifact_dir, self.PLAN_PATH),
                plan.model_dump_json(indent=2) + "\n",
            )
            captions = self.caption_track(plan)
            self._atomic_text(
                safe_artifact_path(artifact_dir, self.CAPTIONS_PATH),
                captions.model_dump_json(indent=2) + "\n",
            )
        except Exception:
            output.unlink(missing_ok=True)
            raise
        return VideoPolishResult(
            plan=plan,
            output_info=output_info,
            declarations=(
                ArtifactDeclaration(path=self.PLAN_PATH, kind=ArtifactKind.POLISH_PLAN),
                ArtifactDeclaration(path=self.CAPTIONS_PATH, kind=ArtifactKind.POLISH_CAPTIONS),
                *(
                    ArtifactDeclaration(path=path, kind=ArtifactKind.POLISH_OVERLAY)
                    for path in overlays
                ),
                ArtifactDeclaration(path=self.OUTPUT_PATH, kind=ArtifactKind.POLISHED_VIDEO),
            ),
        )

    @classmethod
    def build_plan(
        cls,
        spec: DemoSpec,
        bundle: ExecutionBundle,
        timeline: VideoTimeline,
        source_duration_ms: int,
        *,
        source_sha256: str,
        timeline_sha256: str,
    ) -> VideoPolishPlan:
        if len(spec.scenes) != len(timeline.scenes):
            raise VideoPolishRefusedError("scene and timeline counts differ")
        scene_count = len(spec.scenes)
        if source_duration_ms < scene_count:
            raise VideoPolishRefusedError("video is too short for scene presentation")
        boundaries = [0]
        for index, item in enumerate(timeline.scenes[1:], start=1):
            raw = round(item.start_ms / timeline.source_duration_ms * source_duration_ms)
            boundaries.append(
                min(source_duration_ms - (scene_count - index), max(boundaries[-1] + 1, raw))
            )
        boundaries.append(source_duration_ms)
        scenes: list[PolishScene] = []
        for index, (spec_scene, timeline_scene, result) in enumerate(
            zip(spec.scenes, timeline.scenes, bundle.report.scene_results, strict=True)
        ):
            if spec_scene.id != timeline_scene.scene_id or result.scene_id != spec_scene.id:
                raise VideoPolishRefusedError("scene order differs from verified timeline")
            passed = sum(item.status is OutcomeStatus.PASSED for item in result.assertion_results)
            if passed != len(result.assertion_results) or passed < 1:
                raise VideoPolishRefusedError("scene lacks fully passed assertions")
            scenes.append(
                PolishScene(
                    scene_id=spec_scene.id,
                    title=spec_scene.title,
                    source_start_ms=boundaries[index],
                    source_end_ms=boundaries[index + 1],
                    display_start_ms=boundaries[index] + cls.HOLD_MS * index,
                    display_end_ms=boundaries[index + 1] + cls.HOLD_MS * (index + 1),
                    passed_assertions=passed,
                )
            )
        first = next(
            (event for event in bundle.trace_events if event.kind is TraceEventKind.ACTION_STARTED),
            None,
        )
        last = next(
            (
                event
                for event in reversed(bundle.trace_events)
                if event.kind is TraceEventKind.SCENE_EVALUATED
            ),
            None,
        )
        if first is None or last is None:
            raise VideoPolishRefusedError("verified action timing is absent")
        elapsed_ms = max(1, round((last.occurred_at - first.occurred_at).total_seconds() * 1000))
        succeeded = {
            (result.scene_id, result.action_id)
            for result in bundle.report.action_results
            if result.status is ActionResultStatus.SUCCEEDED
        }
        candidates: list[tuple[int, str, str, Literal["click", "fill"], float, float]] = []
        by_scene = {scene.scene_id: (index, scene) for index, scene in enumerate(scenes)}
        for event in bundle.trace_events:
            if (
                event.kind is not TraceEventKind.ACTION_STARTED
                or event.scene_id is None
                or event.action_id is None
                or (event.scene_id, event.action_id) not in succeeded
                or event.data.get("action_type") not in {"click", "fill"}
            ):
                continue
            x, y = event.data.get("focus_x"), event.data.get("focus_y")
            if (
                isinstance(x, bool)
                or isinstance(y, bool)
                or not isinstance(x, (int, float))
                or not isinstance(y, (int, float))
                or not isfinite(x)
                or not isfinite(y)
                or not (0 <= x <= 1 and 0 <= y <= 1)
            ):
                continue
            relative_ms = round((event.occurred_at - first.occurred_at).total_seconds() * 1000)
            source_ms = round(relative_ms / elapsed_ms * source_duration_ms)
            _index, observed_scene = by_scene[event.scene_id]
            source_ms = min(
                observed_scene.source_end_ms,
                max(observed_scene.source_start_ms, source_ms),
            )
            action_kind = cast(Literal["click", "fill"], event.data["action_type"])
            candidates.append(
                (source_ms, event.scene_id, event.action_id, action_kind, float(x), float(y))
            )
        cues: list[FocusCue] = []
        warnings: list[str] = []
        previous: tuple[float, float] | None = None
        for index, scene in enumerate(scenes):
            scoped = [item for item in candidates if item[1] == scene.scene_id]
            # Prefer a real click over a nearby fill; both refer to observed geometry.
            scoped.sort(key=lambda item: (item[3] != "click", item[0]))
            for source_ms, scene_id, action_id, kind, x, y in scoped:
                if len(cues) >= cls.MAX_CUES:
                    warnings.append("Additional visual focus cues were omitted by budget")
                    break
                action_ms = source_ms + cls.HOLD_MS * index
                if any(abs(action_ms - prior.action_ms) < 900 for prior in cues):
                    continue
                cursor_start = max(scene.display_start_ms, action_ms - 300)
                zoom_start = action_ms + 150
                zoom_end = min(scene.display_end_ms - 160, zoom_start + 900)
                if zoom_end - zoom_start < 200:
                    continue
                from_x, from_y = previous or (x, y)
                cues.append(
                    FocusCue(
                        scene_id=scene_id,
                        action_id=action_id,
                        kind=kind,
                        from_x=from_x,
                        from_y=from_y,
                        x=x,
                        y=y,
                        cursor_start_ms=cursor_start,
                        source_action_ms=source_ms,
                        action_ms=action_ms,
                        zoom_start_ms=zoom_start,
                        zoom_end_ms=zoom_end,
                    )
                )
                previous = (x, y)
            if len(cues) >= cls.MAX_CUES:
                break
        if not cues:
            warnings.append("No reliable action geometry; static framing was preserved")
        return VideoPolishPlan(
            source_sha256=source_sha256,
            timeline_sha256=timeline_sha256,
            source_duration_ms=source_duration_ms,
            output_duration_ms=source_duration_ms + cls.HOLD_MS * scene_count,
            scenes=tuple(scenes),
            focus_cues=tuple(sorted(cues, key=lambda cue: cue.action_ms)),
            warnings=tuple(dict.fromkeys(warnings))[:20],
        )

    @staticmethod
    def caption_track(plan: VideoPolishPlan) -> CaptionTrack:
        cues: list[CaptionCue] = []
        for scene in plan.scenes:
            cues.append(
                CaptionCue(
                    scene_id=scene.scene_id,
                    kind="scene_title",
                    start_ms=scene.display_start_ms,
                    end_ms=scene.display_end_ms,
                    text=scene.title,
                )
            )
            cues.append(
                CaptionCue(
                    scene_id=scene.scene_id,
                    kind="verified_result",
                    start_ms=scene.display_end_ms - scene.hold_ms,
                    end_ms=scene.display_end_ms,
                    text=f"{scene.passed_assertions} assertion(s) passed",
                )
            )
        return CaptionTrack(cues=tuple(cues))

    @staticmethod
    def _atomic_text(path: Path, content: str) -> None:
        with NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as temporary:
            temporary.write(content)
            temporary.flush()
            Path(temporary.name).replace(path)
