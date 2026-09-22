"""Deterministic action orchestration and run lifecycle."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

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
from proofdemo.ports.browser import BrowserActionError, BrowserPort, BrowserUnavailableError


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


class ExecutionReport(BaseModel):
    """Stage 2 run output with deterministic scene and assertion evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["2.0"] = "2.0"
    run: DemoRun
    action_results: tuple[ActionResult, ...]
    scene_results: tuple[SceneResult, ...]
    screenshot_paths: tuple[str, ...]
    verification_status: VerificationStatus


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
    """Execute scene actions and coordinate the separate verifier."""

    def __init__(self, browser: BrowserPort) -> None:
        self._browser = browser
        self._verifier = VerificationService(browser)

    def execute(self, spec: DemoSpec, artifact_dir: Path) -> ExecutionReport:
        artifact_dir.mkdir(parents=True, exist_ok=True)
        run = create_demo_run(spec.id)
        run = transition_demo_run(run, DemoRunStatus.VALIDATED)
        run = transition_demo_run(run, DemoRunStatus.RUNNING)
        action_results: list[ActionResult] = []
        scene_results: list[SceneResult] = []
        screenshots: list[str] = []
        verification_status = VerificationStatus.NOT_RUN
        all_scenes_verified = False

        try:
            self._browser.open(str(spec.source_url))
            for scene_index, scene in enumerate(spec.scenes):
                action_outcome = self._execute_scene_actions(
                    scene,
                    artifact_dir,
                    action_results,
                    screenshots,
                )
                if action_outcome is not None:
                    outcome, reason = action_outcome
                    scene_results.append(unverified_scene(scene, outcome, reason))
                    self._append_blocked_scenes(
                        scene_results,
                        spec.scenes[scene_index + 1 :],
                        f"Not run after Scene {scene.id}: {reason}",
                    )
                    run = transition_demo_run(
                        run,
                        DemoRunStatus.BLOCKED
                        if outcome is OutcomeStatus.BLOCKED
                        else DemoRunStatus.FAILED,
                        reason=reason,
                    )
                    break

                scene_result = self._verifier.verify_scene(scene)
                scene_results.append(scene_result)
                if scene_result.status is not OutcomeStatus.PASSED:
                    verification_status = VerificationStatus(scene_result.status.value)
                    reason = scene_result.reason or "Scene verification did not pass"
                    self._append_blocked_scenes(
                        scene_results,
                        spec.scenes[scene_index + 1 :],
                        f"Not verified after Scene {scene.id}: {reason}",
                    )
                    run = transition_demo_run(
                        run,
                        DemoRunStatus.BLOCKED
                        if scene_result.status is OutcomeStatus.BLOCKED
                        else DemoRunStatus.FAILED,
                        reason=reason,
                    )
                    break
            if run.status is DemoRunStatus.RUNNING:
                run = transition_demo_run(run, DemoRunStatus.EXECUTED)
                verification_status = VerificationStatus.PASSED
                all_scenes_verified = True
        except BrowserUnavailableError as error:
            reason = self._reason(error)
            self._append_blocked_scenes(scene_results, spec.scenes, reason)
            run = transition_demo_run(run, DemoRunStatus.BLOCKED, reason=reason)
        except Exception as error:  # defensive startup boundary
            reason = f"Browser startup failed: {type(error).__name__}"
            self._append_blocked_scenes(scene_results, spec.scenes, reason)
            run = transition_demo_run(run, DemoRunStatus.BLOCKED, reason=reason)
        finally:
            try:
                self._browser.close()
            except Exception as error:  # closing is infrastructure, not an action
                if run.status in {DemoRunStatus.RUNNING, DemoRunStatus.EXECUTED}:
                    reason = f"Browser cleanup failed: {type(error).__name__}"
                    run = transition_demo_run(run, DemoRunStatus.BLOCKED, reason=reason)
                    verification_status = VerificationStatus.BLOCKED

        if all_scenes_verified and run.status is DemoRunStatus.EXECUTED:
            run = transition_demo_run(run, DemoRunStatus.PASSED)

        return ExecutionReport(
            run=run,
            action_results=tuple(action_results),
            scene_results=tuple(scene_results),
            screenshot_paths=tuple(screenshots),
            verification_status=verification_status,
        )

    def _execute_scene_actions(
        self,
        scene: Scene,
        artifact_dir: Path,
        results: list[ActionResult],
        screenshots: list[str],
    ) -> tuple[OutcomeStatus, str] | None:
        for action in scene.actions:
            try:
                screenshot_path = self._execute_action(action, artifact_dir)
            except BrowserUnavailableError as error:
                reason = self._reason(error)
                results.append(self._failed_action(scene.id, action, reason))
                return OutcomeStatus.BLOCKED, reason
            except (BrowserActionError, ArtifactPathError) as error:
                reason = self._reason(error)
                results.append(self._failed_action(scene.id, action, reason))
                return OutcomeStatus.FAILED, reason
            except Exception as error:  # defensive adapter boundary
                reason = f"Unexpected browser adapter error: {type(error).__name__}"
                results.append(self._failed_action(scene.id, action, reason))
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
            if screenshot_path is not None:
                screenshots.append(screenshot_path)
        return None

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
    def _append_blocked_scenes(
        results: list[SceneResult],
        scenes: tuple[Scene, ...],
        reason: str,
    ) -> None:
        existing = {result.scene_id for result in results}
        results.extend(
            unverified_scene(scene, OutcomeStatus.BLOCKED, reason)
            for scene in scenes
            if scene.id not in existing
        )

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
    def _reason(error: Exception) -> str:
        return str(error).strip() or type(error).__name__
