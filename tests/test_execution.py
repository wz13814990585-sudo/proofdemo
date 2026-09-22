"""Unit tests for deterministic Stage 1 execution orchestration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from proofdemo.application.execution import (
    ActionResultStatus,
    ArtifactPathError,
    ExecutionService,
    safe_artifact_path,
)
from proofdemo.domain.demo_run import DemoRunStatus
from proofdemo.domain.demo_spec import DemoSpec, ElementTarget
from proofdemo.ports.browser import BrowserActionError, BrowserUnavailableError

ROOT = Path(__file__).resolve().parents[1]


def load_example() -> dict[str, Any]:
    return json.loads((ROOT / "examples" / "demo_spec.json").read_text(encoding="utf-8"))


class FakeBrowser:
    def __init__(
        self,
        *,
        startup_error: Exception | None = None,
        action_error: Exception | None = None,
    ) -> None:
        self.startup_error = startup_error
        self.action_error = action_error
        self.calls: list[tuple[str, object]] = []
        self.closed = False

    def open(self, source_url: str) -> None:
        self.calls.append(("open", source_url))
        if self.startup_error is not None:
            raise self.startup_error

    def goto(self, url: str, *, timeout_ms: int) -> None:
        self.calls.append(("goto", (url, timeout_ms)))

    def click(self, target: ElementTarget, *, timeout_ms: int) -> None:
        self.calls.append(("click", (target, timeout_ms)))
        if self.action_error is not None:
            raise self.action_error

    def fill(self, target: ElementTarget, value: str, *, timeout_ms: int) -> None:
        self.calls.append(("fill", (target, value, timeout_ms)))

    def pause(self, duration_ms: int) -> None:
        self.calls.append(("pause", duration_ms))

    def screenshot(self, path: Path, *, full_page: bool) -> None:
        self.calls.append(("screenshot", (path, full_page)))
        path.write_bytes(b"fake png")

    def close(self) -> None:
        self.closed = True
        self.calls.append(("close", None))


def test_successful_execution_is_ordered_and_unverified(tmp_path: Path) -> None:
    browser = FakeBrowser()
    spec = DemoSpec.model_validate(load_example())

    report = ExecutionService(browser).execute(spec, tmp_path)

    assert report.run.status is DemoRunStatus.EXECUTED
    assert report.verification_status == "NOT_RUN"
    assert [result.action_id for result in report.action_results] == [
        "open-todo-app",
        "enter-task-title",
        "add-task",
        "capture-created-task",
    ]
    assert all(result.status is ActionResultStatus.SUCCEEDED for result in report.action_results)
    assert report.screenshot_paths == ("task-created.png",)
    assert (tmp_path / "task-created.png").is_file()
    assert browser.closed
    assert DemoRunStatus.PASSED not in [
        transition.to_status for transition in report.run.transitions
    ]


def test_all_typed_targets_cross_the_browser_port_unchanged(tmp_path: Path) -> None:
    raw = load_example()
    raw["scenes"][0]["actions"] = [
        raw["scenes"][0]["actions"][0],
        {
            "id": "role-target",
            "type": "click",
            "target": {"strategy": "role", "role": "button", "name": "Add task"},
        },
        {
            "id": "label-target",
            "type": "click",
            "target": {"strategy": "label", "label": "Task title"},
        },
        {
            "id": "text-target",
            "type": "click",
            "target": {"strategy": "text", "text": "Launch tasks"},
        },
        {
            "id": "test-id-target",
            "type": "click",
            "target": {"strategy": "test_id", "test_id": "task-list"},
        },
        {
            "id": "css-target",
            "type": "click",
            "target": {"strategy": "css", "selector": "#task-title"},
        },
    ]
    spec = DemoSpec.model_validate(raw)
    browser = FakeBrowser()

    report = ExecutionService(browser).execute(spec, tmp_path)

    observed_targets = [
        value[0] for name, value in browser.calls if name == "click" and isinstance(value, tuple)
    ]
    expected_targets = [action.target for action in spec.scenes[0].actions[1:]]
    assert observed_targets == expected_targets
    assert report.run.status is DemoRunStatus.EXECUTED


def test_action_failure_is_failed_and_browser_closes(tmp_path: Path) -> None:
    browser = FakeBrowser(action_error=BrowserActionError("target is missing"))
    spec = DemoSpec.model_validate(load_example())

    report = ExecutionService(browser).execute(spec, tmp_path)

    assert report.run.status is DemoRunStatus.FAILED
    assert report.run.transitions[-1].reason == "target is missing"
    assert report.action_results[-1].action_id == "add-task"
    assert report.action_results[-1].status is ActionResultStatus.FAILED
    assert report.action_results[-1].error == "target is missing"
    assert browser.closed


def test_browser_startup_failure_is_blocked_and_close_is_attempted(tmp_path: Path) -> None:
    browser = FakeBrowser(startup_error=BrowserUnavailableError("Chromium unavailable"))
    spec = DemoSpec.model_validate(load_example())

    report = ExecutionService(browser).execute(spec, tmp_path)

    assert report.run.status is DemoRunStatus.BLOCKED
    assert report.run.transitions[-1].reason == "Chromium unavailable"
    assert report.action_results == ()
    assert browser.closed


def test_safe_artifact_path_rejects_traversal(tmp_path: Path) -> None:
    with pytest.raises(ArtifactPathError, match="escapes requested directory"):
        safe_artifact_path(tmp_path, "../escaped.png")


def test_safe_artifact_path_rejects_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.png"
    link = tmp_path / "capture.png"
    link.symlink_to(outside)

    with pytest.raises(ArtifactPathError, match="escapes requested directory"):
        safe_artifact_path(tmp_path, "capture.png")
