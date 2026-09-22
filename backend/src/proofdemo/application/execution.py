"""Deterministic action orchestration, run lifecycle, and capture coordination."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from proofdemo.application.trace import TraceEvent, TraceEventKind, TraceRecorder
from proofdemo.application.verification import (
    OutcomeStatus,
    SceneResult,
    VerificationService,
    VerificationStatus,
    unverified_scene,
)
from proofdemo.domain.demo_run import (
    DemoRun,
    DemoRunStatus,
    create_demo_run,
    transition_demo_run,
)
from proofdemo.domain.demo_spec import (
    Action,
    ClickAction,
    DemoSpec,
    FillAction,
    GotoAction,
    PauseAction,
    Scene,
    ScreenshotAction,
)
from proofdemo.ports.browser import (
    BrowserActionError,
    BrowserLogEntry,
    BrowserPort,
    BrowserSessionArtifacts,
    BrowserUnavailableError,
)


class ActionResultStatus(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class ActionResult(BaseModel):
    """Small result for one ordered browser action."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scene_id: str
    action_id: str
    action_type: str
    status: ActionResultStatus
    screenshot_path: str | None = None
    error: str | None = Field(default=None, min_length=1, max_length=2_000)

    @model_validator(mode="after")
    def validate_result(self) -> ActionResult:
        if self.status is ActionResultStatus.SUCCEEDED and self.error is not None:
            raise ValueError("successful actions cannot include an error")
        if self.status is ActionResultStatus.FAILED and self.error is None:
            raise ValueError("failed actions require an error")
        return self


class EvidenceCapture(BaseModel):
    """Correlation metadata for an automatically captured evidence screenshot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scene_id: str
    assertion_id: str
    path: str


class ExecutionReport(BaseModel):
    """Stage 3 run output with verification and persisted-artifact references."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["3.0"] = "3.0"
    run: DemoRun
    action_results: tuple[ActionResult, ...]
    scene_results: tuple[SceneResult, ...]
    screenshot_paths: tuple[str, ...]
    evidence_screenshot_paths: tuple[str, ...]
    browser_video_path: str | None
    trace_path: Literal["trace.jsonl"] = "trace.jsonl"
    browser_log_path: Literal["browser.log.jsonl"] = "browser.log.jsonl"
    artifact_manifest_path: Literal["artifact_manifest.json"] = "artifact_manifest.json"
    artifact_warnings: tuple[str, ...] = ()
    verification_status: VerificationStatus


@dataclass(frozen=True)
class ExecutionBundle:
    """In-memory facts persisted atomically by the artifact writer."""

    report: ExecutionReport
    trace_events: tuple[TraceEvent, ...]
    browser_logs: tuple[BrowserLogEntry, ...]
    evidence_captures: tuple[EvidenceCapture, ...]


class ArtifactPathError(ValueError):
    """An artifact name attempted to escape its requested directory."""


def safe_artifact_path(artifact_dir: Path, filename: str) -> Path:
    """Resolve a contained artifact path, including protection from symlinks."""
    root = artifact_dir.resolve()
    candidate = (root / filename).resolve()
    if not candidate.is_relative_to(root):
        raise ArtifactPathError(f"artifact path escapes requested directory: {filename}")
    return candidate


class ExecutionService:
    """Execute actions, coordinate verification, and capture browser evidence."""

    def __init__(
        self,
        browser: BrowserPort,
        *,
        trace_observer: Callable[[TraceEvent], None] | None = None,
        capture_live_preview: bool = False,
    ) -> None:
        self._browser = browser
        self._verifier = VerificationService(browser)
        self._trace_observer = trace_observer
        self._capture_live_preview = capture_live_preview

    def execute(self, spec: DemoSpec, artifact_dir: Path) -> ExecutionReport:
        """Execute and return the report; CLI callers should persist the full bundle."""
        return self.execute_bundle(spec, artifact_dir).report

    def execute_bundle(self, spec: DemoSpec, artifact_dir: Path) -> ExecutionBundle:
        artifact_dir.mkdir(parents=True, exist_ok=True)
        run = create_demo_run(spec.id)
        trace = TraceRecorder(run.id, spec.id, observer=self._trace_observer)
        run = self._transition(run, DemoRunStatus.VALIDATED, trace)
        run = self._transition(run, DemoRunStatus.RUNNING, trace)
        action_results: list[ActionResult] = []
        scene_results: list[SceneResult] = []
        screenshots: list[str] = []
        evidence_captures: list[EvidenceCapture] = []
        warnings: list[str] = []
        browser_logs: tuple[BrowserLogEntry, ...] = ()
        browser_video_path: str | None = None
        verification_status = VerificationStatus.NOT_RUN
        all_scenes_verified = False

        try:
            self._browser.open(str(spec.source_url), recording_dir=artifact_dir)
            for scene_index, scene in enumerate(spec.scenes):
                action_outcome = self._execute_scene_actions(
                    scene,
                    artifact_dir,
                    action_results,
                    screenshots,
                    trace,
                )
                if action_outcome is not None:
                    outcome, reason = action_outcome
                    scene_result = unverified_scene(scene, outcome, reason)
                    scene_results.append(scene_result)
                    self._record_scene_result(scene_result, trace)
                    blocked = self._append_blocked_scenes(
                        scene_results,
                        spec.scenes[scene_index + 1 :],
                        f"Not run after Scene {scene.id}: {reason}",
                    )
                    for blocked_scene in blocked:
                        self._record_scene_result(blocked_scene, trace)
                    run = self._transition(
                        run,
                        DemoRunStatus.BLOCKED
                        if outcome is OutcomeStatus.BLOCKED
                        else DemoRunStatus.FAILED,
                        trace,
                        reason=reason,
                    )
                    break

                scene_result = self._verifier.verify_scene(scene)
                scene_results.append(scene_result)
                self._record_scene_result(scene_result, trace)
                self._capture_scene_evidence(
                    scene_result,
                    artifact_dir,
                    evidence_captures,
                    warnings,
                    trace,
                )
                if scene_result.status is not OutcomeStatus.PASSED:
                    verification_status = VerificationStatus(scene_result.status.value)
                    reason = scene_result.reason or "Scene verification did not pass"
                    blocked = self._append_blocked_scenes(
                        scene_results,
                        spec.scenes[scene_index + 1 :],
                        f"Not verified after Scene {scene.id}: {reason}",
                    )
                    for blocked_scene in blocked:
                        self._record_scene_result(blocked_scene, trace)
                    run = self._transition(
                        run,
                        DemoRunStatus.BLOCKED
                        if scene_result.status is OutcomeStatus.BLOCKED
                        else DemoRunStatus.FAILED,
                        trace,
                        reason=reason,
                    )
                    break
            if run.status is DemoRunStatus.RUNNING:
                run = self._transition(run, DemoRunStatus.EXECUTED, trace)
                verification_status = VerificationStatus.PASSED
                all_scenes_verified = True
        except BrowserUnavailableError as error:
            reason = self._reason(error)
            blocked = self._append_blocked_scenes(scene_results, spec.scenes, reason)
            for blocked_scene in blocked:
                self._record_scene_result(blocked_scene, trace)
            run = self._transition(run, DemoRunStatus.BLOCKED, trace, reason=reason)
        except Exception as error:  # defensive startup boundary
            reason = f"Browser startup failed: {type(error).__name__}"
            blocked = self._append_blocked_scenes(scene_results, spec.scenes, reason)
            for blocked_scene in blocked:
                self._record_scene_result(blocked_scene, trace)
            run = self._transition(run, DemoRunStatus.BLOCKED, trace, reason=reason)
        finally:
            try:
                closed = self._browser.close()
                session = (
                    closed
                    if isinstance(closed, BrowserSessionArtifacts)
                    else BrowserSessionArtifacts()
                )
                browser_logs = session.logs
                if session.video_path is not None:
                    browser_video_path = self._relative_artifact_path(
                        artifact_dir,
                        session.video_path,
                    )
                    trace.record(
                        TraceEventKind.ARTIFACT_CAPTURED,
                        status="SUCCEEDED",
                        data={"kind": "BROWSER_VIDEO", "path": browser_video_path},
                    )
                else:
                    warning = "Browser video was not produced"
                    warnings.append(warning)
                    trace.record(
                        TraceEventKind.ARTIFACT_CAPTURE_FAILED,
                        status="FAILED",
                        data={"kind": "BROWSER_VIDEO", "reason": warning},
                    )
                trace.record(
                    TraceEventKind.BROWSER_SESSION_CLOSED,
                    status="SUCCEEDED",
                    data={"log_count": len(browser_logs)},
                )
            except Exception as error:  # closing is infrastructure, not an action
                reason = f"Browser cleanup failed: {type(error).__name__}"
                trace.record(
                    TraceEventKind.BROWSER_SESSION_CLOSED,
                    status="BLOCKED",
                    data={"reason": reason},
                )
                if run.status in {DemoRunStatus.RUNNING, DemoRunStatus.EXECUTED}:
                    run = self._transition(
                        run,
                        DemoRunStatus.BLOCKED,
                        trace,
                        reason=reason,
                    )
                    verification_status = VerificationStatus.BLOCKED

        if all_scenes_verified and run.status is DemoRunStatus.EXECUTED:
            run = self._transition(run, DemoRunStatus.PASSED, trace)

        report = ExecutionReport(
            run=run,
            action_results=tuple(action_results),
            scene_results=tuple(scene_results),
            screenshot_paths=tuple(screenshots),
            evidence_screenshot_paths=tuple(capture.path for capture in evidence_captures),
            browser_video_path=browser_video_path,
            artifact_warnings=tuple(warnings),
            verification_status=verification_status,
        )
        return ExecutionBundle(
            report=report,
            trace_events=trace.events,
            browser_logs=browser_logs,
            evidence_captures=tuple(evidence_captures),
        )

    def _execute_scene_actions(
        self,
        scene: Scene,
        artifact_dir: Path,
        results: list[ActionResult],
        screenshots: list[str],
        trace: TraceRecorder,
    ) -> tuple[OutcomeStatus, str] | None:
        for action in scene.actions:
            trace.record(
                TraceEventKind.ACTION_STARTED,
                scene_id=scene.id,
                action_id=action.id,
                data={"action_type": action.type},
            )
            try:
                screenshot_path = self._execute_action(action, artifact_dir)
            except BrowserUnavailableError as error:
                reason = self._reason(error)
                results.append(self._failed_action(scene.id, action, reason))
                self._record_action_outcome(scene.id, action, "BLOCKED", reason, trace)
                return OutcomeStatus.BLOCKED, reason
            except (BrowserActionError, ArtifactPathError) as error:
                reason = self._reason(error)
                results.append(self._failed_action(scene.id, action, reason))
                self._record_action_outcome(scene.id, action, "FAILED", reason, trace)
                return OutcomeStatus.FAILED, reason
            except Exception as error:  # defensive adapter boundary
                reason = f"Unexpected browser adapter error: {type(error).__name__}"
                results.append(self._failed_action(scene.id, action, reason))
                self._record_action_outcome(scene.id, action, "FAILED", reason, trace)
                return OutcomeStatus.FAILED, reason
            results.append(
                ActionResult(
                    scene_id=scene.id,
                    action_id=action.id,
                    action_type=action.type,
                    status=ActionResultStatus.SUCCEEDED,
                    screenshot_path=screenshot_path,
                )
            )
            data: dict[str, JsonValue] = {"action_type": action.type}
            if screenshot_path is not None:
                screenshots.append(screenshot_path)
                data["screenshot_path"] = screenshot_path
            trace.record(
                TraceEventKind.ACTION_FINISHED,
                scene_id=scene.id,
                action_id=action.id,
                status="SUCCEEDED",
                data=data,
            )
            if self._capture_live_preview:
                self._update_live_preview(artifact_dir, trace, scene.id, action.id)
        return None

    def _update_live_preview(
        self,
        artifact_dir: Path,
        trace: TraceRecorder,
        scene_id: str,
        action_id: str,
    ) -> None:
        try:
            path = safe_artifact_path(artifact_dir, "preview/latest.png")
            path.parent.mkdir(parents=True, exist_ok=True)
            self._browser.screenshot(path, full_page=False)
        except (BrowserActionError, ArtifactPathError, OSError):
            return
        trace.record(
            TraceEventKind.PREVIEW_UPDATED,
            scene_id=scene_id,
            action_id=action_id,
            status="SUCCEEDED",
        )

    def _capture_scene_evidence(
        self,
        scene: SceneResult,
        artifact_dir: Path,
        captures: list[EvidenceCapture],
        warnings: list[str],
        trace: TraceRecorder,
    ) -> None:
        for assertion in scene.assertion_results:
            if assertion.evidence is None:
                continue
            relative_path = f"evidence/{scene.scene_id}--{assertion.assertion_id}.png"
            try:
                path = safe_artifact_path(artifact_dir, relative_path)
                path.parent.mkdir(parents=True, exist_ok=True)
                self._browser.screenshot(path, full_page=False)
            except Exception as error:
                reason = f"Evidence screenshot failed: {type(error).__name__}"
                warnings.append(f"{scene.scene_id}/{assertion.assertion_id}: {reason}")
                trace.record(
                    TraceEventKind.ARTIFACT_CAPTURE_FAILED,
                    scene_id=scene.scene_id,
                    assertion_id=assertion.assertion_id,
                    status="FAILED",
                    data={"kind": "EVIDENCE_SCREENSHOT", "reason": reason},
                )
                continue
            capture = EvidenceCapture(
                scene_id=scene.scene_id,
                assertion_id=assertion.assertion_id,
                path=relative_path,
            )
            captures.append(capture)
            trace.record(
                TraceEventKind.ARTIFACT_CAPTURED,
                scene_id=scene.scene_id,
                assertion_id=assertion.assertion_id,
                status="SUCCEEDED",
                data={"kind": "EVIDENCE_SCREENSHOT", "path": relative_path},
            )

    def _execute_action(self, action: Action, artifact_dir: Path) -> str | None:
        if isinstance(action, GotoAction):
            self._browser.goto(str(action.url), timeout_ms=action.timeout_ms)
            return None
        if isinstance(action, ClickAction):
            self._browser.click(action.target, timeout_ms=action.timeout_ms)
            return None
        if isinstance(action, FillAction):
            self._browser.fill(action.target, action.value, timeout_ms=action.timeout_ms)
            return None
        if isinstance(action, PauseAction):
            self._browser.pause(action.duration_ms)
            return None
        if isinstance(action, ScreenshotAction):
            filename = f"{action.name}.png"
            path = safe_artifact_path(artifact_dir, filename)
            self._browser.screenshot(path, full_page=action.full_page)
            return filename
        raise BrowserActionError(f"Unsupported action type: {type(action).__name__}")

    @staticmethod
    def _record_action_outcome(
        scene_id: str,
        action: Action,
        status: str,
        reason: str,
        trace: TraceRecorder,
    ) -> None:
        trace.record(
            TraceEventKind.ACTION_FINISHED,
            scene_id=scene_id,
            action_id=action.id,
            status=status,
            data={"action_type": action.type, "reason": reason},
        )

    @staticmethod
    def _record_scene_result(scene: SceneResult, trace: TraceRecorder) -> None:
        for assertion in scene.assertion_results:
            data: dict[str, JsonValue] = {"assertion_type": assertion.assertion_type}
            if assertion.evidence is not None:
                data["expected"] = assertion.evidence.expected
                data["observed"] = assertion.evidence.observed
            if assertion.reason is not None:
                data["reason"] = assertion.reason
            trace.record(
                TraceEventKind.ASSERTION_EVALUATED,
                scene_id=scene.scene_id,
                assertion_id=assertion.assertion_id,
                status=assertion.status.value,
                data=data,
            )
        scene_data: dict[str, JsonValue] = {}
        if scene.reason is not None:
            scene_data["reason"] = scene.reason
        trace.record(
            TraceEventKind.SCENE_EVALUATED,
            scene_id=scene.scene_id,
            status=scene.status.value,
            data=scene_data,
        )

    @staticmethod
    def _append_blocked_scenes(
        results: list[SceneResult],
        scenes: tuple[Scene, ...],
        reason: str,
    ) -> tuple[SceneResult, ...]:
        existing = {result.scene_id for result in results}
        appended = tuple(
            unverified_scene(scene, OutcomeStatus.BLOCKED, reason)
            for scene in scenes
            if scene.id not in existing
        )
        results.extend(appended)
        return appended

    @staticmethod
    def _failed_action(scene_id: str, action: Action, reason: str) -> ActionResult:
        return ActionResult(
            scene_id=scene_id,
            action_id=action.id,
            action_type=action.type,
            status=ActionResultStatus.FAILED,
            error=reason,
        )

    @staticmethod
    def _transition(
        run: DemoRun,
        status: DemoRunStatus,
        trace: TraceRecorder,
        *,
        reason: str | None = None,
    ) -> DemoRun:
        updated = transition_demo_run(run, status, reason=reason)
        data: dict[str, JsonValue] = {"from_status": run.status.value}
        if reason is not None:
            data["reason"] = reason
        trace.record(TraceEventKind.RUN_TRANSITION, status=status.value, data=data)
        return updated

    @staticmethod
    def _relative_artifact_path(artifact_dir: Path, path: Path) -> str:
        root = artifact_dir.resolve()
        candidate = path.resolve()
        if not candidate.is_relative_to(root):
            raise ArtifactPathError("browser artifact escaped requested directory")
        return candidate.relative_to(root).as_posix()

    @staticmethod
    def _reason(error: Exception) -> str:
        return str(error).strip() or type(error).__name__
