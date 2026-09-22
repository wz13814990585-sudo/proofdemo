"""Evidence-grounded narration policy and scene-aligned audio orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from proofdemo.application.artifacts import (
    ArtifactDeclaration,
    ArtifactKind,
    ArtifactManifest,
    ArtifactRecord,
    ArtifactWriter,
)
from proofdemo.application.execution import ExecutionBundle
from proofdemo.application.rendering import VideoTimeline
from proofdemo.application.verification import AssertionResult, OutcomeStatus, VerificationStatus
from proofdemo.domain.demo_run import DemoRunStatus
from proofdemo.ports.audio import AudioInfo, AudioMixCue, AudioMixPort
from proofdemo.ports.render import MediaInfo
from proofdemo.ports.speech import SpeechPort

VOICE_DISCLOSURE: Final[Literal["AI-generated voice."]] = "AI-generated voice."
MAX_TEMPO = 2.0


class NarrationCue(BaseModel):
    """One approved spoken cue tied to verified assertion evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scene_id: str
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    text: str = Field(min_length=1, max_length=240)
    assertion_ids: tuple[str, ...] = Field(min_length=1)
    audio_path: str
    source_duration_ms: int = Field(gt=0)
    tempo: float = Field(ge=1.0, le=MAX_TEMPO)

    @model_validator(mode="after")
    def validate_range(self) -> NarrationCue:
        if self.end_ms <= self.start_ms:
            raise ValueError("narration cue end must be after its start")
        return self


class NarrationTrack(BaseModel):
    """Versioned evidence-linked narration metadata."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    run_id: str
    timeline_path: Literal["timeline.json"] = "timeline.json"
    timeline_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_video_path: Literal["demo.mp4"] = "demo.mp4"
    output_video_path: Literal["demo-narrated.mp4"] = "demo-narrated.mp4"
    provider: str
    model: str
    voice: str
    voice_disclosure: Literal["AI-generated voice."] = VOICE_DISCLOSURE
    cues: tuple[NarrationCue, ...] = Field(min_length=1)


@dataclass(frozen=True)
class NarrationResult:
    track: NarrationTrack
    output_video: MediaInfo
    output_audio: AudioInfo
    declarations: tuple[ArtifactDeclaration, ...]


@dataclass(frozen=True)
class _DraftCue:
    scene_id: str
    start_ms: int
    end_ms: int
    text: str
    assertion_id: str
    audio_path: str


class NarrationRefusedError(RuntimeError):
    """Narration input is unverified, ungrounded, or cannot fit its timeline."""


def _grounded_phrase(assertion: AssertionResult) -> str:
    phrases = {
        "download_completed": "Download verified.",
        "app_state_equals": "State verified.",
        "text_contains": "Content verified.",
        "element_visible": "Interface verified.",
        "url_equals": "Page verified.",
    }
    try:
        return phrases[assertion.assertion_type]
    except KeyError as error:
        raise NarrationRefusedError(
            f"unsupported narration evidence type: {assertion.assertion_type}"
        ) from error


def validate_narration_grounding(
    track: NarrationTrack,
    bundle: ExecutionBundle,
    timeline: VideoTimeline,
) -> None:
    """Prove every spoken cue is the exact template for passed scene evidence."""
    if [cue.scene_id for cue in track.cues] != [scene.scene_id for scene in timeline.scenes]:
        raise NarrationRefusedError("narration scenes do not match the verified timeline")
    scene_results = {scene.scene_id: scene for scene in bundle.report.scene_results}
    for index, (cue, timeline_scene) in enumerate(zip(track.cues, timeline.scenes, strict=True)):
        scene = scene_results.get(cue.scene_id)
        if scene is None or scene.status is not OutcomeStatus.PASSED:
            raise NarrationRefusedError(f"narration Scene {cue.scene_id} is not verified")
        if cue.start_ms != timeline_scene.start_ms or cue.end_ms != timeline_scene.end_ms:
            raise NarrationRefusedError(f"narration Scene {cue.scene_id} changed timeline bounds")
        passed = {
            assertion.assertion_id: assertion
            for assertion in scene.assertion_results
            if assertion.status is OutcomeStatus.PASSED and assertion.evidence is not None
        }
        if len(cue.assertion_ids) != 1 or cue.assertion_ids[0] not in passed:
            raise NarrationRefusedError(
                f"narration Scene {cue.scene_id} cites unverified assertion evidence"
            )
        phrase = _grounded_phrase(passed[cue.assertion_ids[0]])
        expected_text = f"{VOICE_DISCLOSURE} {phrase}" if index == 0 else phrase
        if cue.text != expected_text:
            raise NarrationRefusedError(
                f"narration Scene {cue.scene_id} contains an ungrounded claim"
            )


class NarrationService:
    """Create speech only from deterministic passed-assertion templates."""

    TRACK_PATH = "narration.json"
    SILENT_VIDEO_PATH = "demo.mp4"
    OUTPUT_VIDEO_PATH = "demo-narrated.mp4"

    def __init__(self, speech: SpeechPort, mixer: AudioMixPort) -> None:
        self._speech = speech
        self._mixer = mixer

    def narrate(
        self,
        bundle: ExecutionBundle,
        manifest: ArtifactManifest,
        timeline: VideoTimeline,
        artifact_dir: Path,
    ) -> NarrationResult:
        timeline_record = self._validate_inputs(bundle, manifest, timeline, artifact_dir)
        drafts = self._draft(bundle, timeline)
        created: list[Path] = []
        cues: list[NarrationCue] = []
        try:
            for draft in drafts:
                audio_path = self._contained(artifact_dir, draft.audio_path)
                self._speech.synthesize(draft.text, audio_path)
                created.append(audio_path)
                audio_info = self._mixer.probe_audio(audio_path)
                if (
                    audio_info.duration_ms <= 0
                    or audio_info.sample_rate <= 0
                    or audio_info.channels <= 0
                    or not audio_info.codec.startswith("pcm_")
                ):
                    raise NarrationRefusedError(
                        f"narration Scene {draft.scene_id} speech is not valid PCM WAV"
                    )
                slot_ms = draft.end_ms - draft.start_ms
                tempo = max(1.0, audio_info.duration_ms / slot_ms)
                if tempo > MAX_TEMPO:
                    raise NarrationRefusedError(
                        f"narration Scene {draft.scene_id} speech exceeds its scene duration"
                    )
                cues.append(
                    NarrationCue(
                        scene_id=draft.scene_id,
                        start_ms=draft.start_ms,
                        end_ms=draft.end_ms,
                        text=draft.text,
                        assertion_ids=(draft.assertion_id,),
                        audio_path=draft.audio_path,
                        source_duration_ms=audio_info.duration_ms,
                        tempo=tempo,
                    )
                )

            descriptor = self._speech.descriptor
            track = NarrationTrack(
                run_id=str(bundle.report.run.id),
                timeline_sha256=timeline_record.sha256,
                provider=descriptor.provider,
                model=descriptor.model,
                voice=descriptor.voice,
                cues=tuple(cues),
            )
            validate_narration_grounding(track, bundle, timeline)
            output_path = self._contained(artifact_dir, self.OUTPUT_VIDEO_PATH)
            self._mixer.mix(
                self._contained(artifact_dir, self.SILENT_VIDEO_PATH),
                tuple(
                    AudioMixCue(
                        source=self._contained(artifact_dir, cue.audio_path),
                        start_ms=cue.start_ms,
                        end_ms=cue.end_ms,
                        source_duration_ms=cue.source_duration_ms,
                        tempo=cue.tempo,
                    )
                    for cue in track.cues
                ),
                output_path,
                duration_ms=timeline.source_duration_ms,
            )
            created.append(output_path)
            output_video = self._mixer.probe_video(output_path)
            output_audio = self._mixer.probe_audio(output_path)
            self._validate_output(timeline, output_video, output_audio)
            track_path = self._contained(artifact_dir, self.TRACK_PATH)
            self._atomic_text(track_path, track.model_dump_json(indent=2) + "\n")
            created.append(track_path)
        except Exception:
            for path in created:
                path.unlink(missing_ok=True)
            raise

        declarations = [
            ArtifactDeclaration(path=self.TRACK_PATH, kind=ArtifactKind.NARRATION_TRACK),
            ArtifactDeclaration(path=self.OUTPUT_VIDEO_PATH, kind=ArtifactKind.NARRATED_VIDEO),
        ]
        declarations.extend(
            ArtifactDeclaration(
                path=cue.audio_path,
                kind=ArtifactKind.NARRATION_AUDIO,
                scene_id=cue.scene_id,
                assertion_id=cue.assertion_ids[0],
            )
            for cue in track.cues
        )
        return NarrationResult(
            track=track,
            output_video=output_video,
            output_audio=output_audio,
            declarations=tuple(declarations),
        )

    @staticmethod
    def _draft(bundle: ExecutionBundle, timeline: VideoTimeline) -> tuple[_DraftCue, ...]:
        scene_results = {scene.scene_id: scene for scene in bundle.report.scene_results}
        priority = {
            "download_completed": 0,
            "app_state_equals": 1,
            "text_contains": 2,
            "element_visible": 3,
            "url_equals": 4,
        }
        drafts: list[_DraftCue] = []
        for index, timeline_scene in enumerate(timeline.scenes):
            scene = scene_results[timeline_scene.scene_id]
            candidates = [
                assertion
                for assertion in scene.assertion_results
                if assertion.status is OutcomeStatus.PASSED and assertion.evidence is not None
            ]
            if not candidates:
                raise NarrationRefusedError(
                    f"narration Scene {scene.scene_id} has no passed assertion evidence"
                )
            assertion = min(candidates, key=lambda item: priority.get(item.assertion_type, 99))
            phrase = _grounded_phrase(assertion)
            text = f"{VOICE_DISCLOSURE} {phrase}" if index == 0 else phrase
            drafts.append(
                _DraftCue(
                    scene_id=scene.scene_id,
                    start_ms=timeline_scene.start_ms,
                    end_ms=timeline_scene.end_ms,
                    text=text,
                    assertion_id=assertion.assertion_id,
                    audio_path=f"narration/{scene.scene_id}.wav",
                )
            )
        return tuple(drafts)

    @staticmethod
    def _validate_inputs(
        bundle: ExecutionBundle,
        manifest: ArtifactManifest,
        timeline: VideoTimeline,
        artifact_dir: Path,
    ) -> ArtifactRecord:
        report = bundle.report
        if (
            report.run.status is not DemoRunStatus.PASSED
            or report.verification_status is not VerificationStatus.PASSED
        ):
            raise NarrationRefusedError("only a verified PASSED run can be narrated")
        if (
            manifest.run_id != str(report.run.id)
            or manifest.spec_id != report.run.spec_id
            or manifest.run_status != DemoRunStatus.PASSED.value
        ):
            raise NarrationRefusedError("artifact manifest does not belong to this run")
        integrity_errors = ArtifactWriter.verify(artifact_dir, manifest)
        if integrity_errors:
            raise NarrationRefusedError(f"artifact integrity check failed: {integrity_errors[0]}")
        timeline_record = next(
            (
                record
                for record in manifest.artifacts
                if record.kind is ArtifactKind.TIMELINE and record.path == "timeline.json"
            ),
            None,
        )
        video_record = next(
            (
                record
                for record in manifest.artifacts
                if record.kind is ArtifactKind.FINAL_VIDEO and record.path == "demo.mp4"
            ),
            None,
        )
        if timeline_record is None or video_record is None:
            raise NarrationRefusedError("Stage 4 timeline and silent video are required")
        persisted_timeline = VideoTimeline.model_validate_json(
            (artifact_dir.resolve() / timeline_record.path).read_text(encoding="utf-8")
        )
        if persisted_timeline != timeline:
            raise NarrationRefusedError("provided timeline differs from the recorded timeline")
        report_scene_ids = [scene.scene_id for scene in report.scene_results]
        if report_scene_ids != [scene.scene_id for scene in timeline.scenes]:
            raise NarrationRefusedError("timeline scenes do not match verified scene results")
        return timeline_record

    @staticmethod
    def _validate_output(
        timeline: VideoTimeline,
        video: MediaInfo,
        audio: AudioInfo,
    ) -> None:
        if video.width != 1920 or video.height != 1080 or abs(video.fps - 30.0) > 0.001:
            raise NarrationRefusedError("narrated video does not preserve 1080p at 30 fps")
        if video.codec != "h264" or audio.codec != "aac":
            raise NarrationRefusedError("narrated output must contain H.264 video and AAC audio")
        if abs(video.duration_ms - timeline.source_duration_ms) > 34:
            raise NarrationRefusedError("narrated video duration differs by more than one frame")
        if abs(audio.duration_ms - timeline.source_duration_ms) > 34:
            raise NarrationRefusedError("narrated audio duration differs by more than one frame")

    @staticmethod
    def _contained(artifact_dir: Path, relative_path: str) -> Path:
        root = artifact_dir.resolve()
        path = (root / relative_path).resolve()
        if not path.is_relative_to(root):
            raise NarrationRefusedError("narration path escaped artifact directory")
        return path

    @staticmethod
    def _atomic_text(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
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
