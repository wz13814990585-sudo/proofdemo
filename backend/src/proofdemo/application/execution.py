"""Deterministic orchestration for Stage 1 browser actions."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

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
    ScreenshotAction,
)
from proofdemo.ports.browser import BrowserActionError, BrowserPort, BrowserUnavailableError


class ActionResultStatus(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class ActionResult(BaseModel):
    """Small Stage 1 result for one ordered browser action."""

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
    """Stage 1 output; deliberately contains no assertion results."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    run: DemoRun
    action_results: tuple[ActionResult, ...]
    screenshot_paths: tuple[str, ...]
    verification_status: Literal["NOT_RUN"] = "NOT_RUN"


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
    """Execute actions in order while preserving run-state semantics."""

    def __init__(self, browser: BrowserPort) -> None:
        self._browser = browser

    def execute(self, spec: DemoSpec, artifact_dir: Path) -> ExecutionReport:
        artifact_dir.mkdir(parents=True, exist_ok=True)
        run = create_demo_run(spec.id)
        run = transition_demo_run(run, DemoRunStatus.VALIDATED)
        run = transition_demo_run(run, DemoRunStatus.RUNNING)
        results: list[ActionResult] = []
        screenshots: list[str] = []

        try:
            self._browser.open(str(spec.source_url))
            for scene in spec.scenes:
                for action in scene.actions:
                    try:
                        screenshot_path = self._execute_action(action, artifact_dir)
                    except BrowserUnavailableError as error:
                        reason = self._reason(error)
                        results.append(self._failed_result(scene.id, action, reason))
                        run = transition_demo_run(run, DemoRunStatus.BLOCKED, reason=reason)
                        break
                    except (BrowserActionError, ArtifactPathError) as error:
                        reason = self._reason(error)
                        results.append(self._failed_result(scene.id, action, reason))
                        run = transition_demo_run(run, DemoRunStatus.FAILED, reason=reason)
                        break
                    except Exception as error:  # defensive adapter boundary
                        reason = f"Unexpected browser adapter error: {type(error).__name__}"
                        results.append(self._failed_result(scene.id, action, reason))
                        run = transition_demo_run(run, DemoRunStatus.FAILED, reason=reason)
                        break
                    else:
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
                if run.status is not DemoRunStatus.RUNNING:
                    break
            if run.status is DemoRunStatus.RUNNING:
                run = transition_demo_run(run, DemoRunStatus.EXECUTED)
        except BrowserUnavailableError as error:
            run = transition_demo_run(
                run,
                DemoRunStatus.BLOCKED,
                reason=self._reason(error),
            )
        except Exception as error:  # defensive startup boundary
            run = transition_demo_run(
                run,
                DemoRunStatus.BLOCKED,
                reason=f"Browser startup failed: {type(error).__name__}",
            )
        finally:
            try:
                self._browser.close()
            except Exception as error:  # closing is infrastructure, not an action
                if run.status in {DemoRunStatus.RUNNING, DemoRunStatus.EXECUTED}:
                    run = transition_demo_run(
                        run,
                        DemoRunStatus.BLOCKED,
                        reason=f"Browser cleanup failed: {type(error).__name__}",
                    )

        return ExecutionReport(
            run=run,
            action_results=tuple(results),
            screenshot_paths=tuple(screenshots),
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
    def _failed_result(scene_id: str, action: Action, reason: str) -> ActionResult:
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
