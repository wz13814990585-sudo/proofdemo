"""Unit tests for deterministic execution and verification orchestration."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from proofdemo.application.artifacts import ArtifactKind, ArtifactWriteError, ArtifactWriter
from proofdemo.application.execution import (
    ActionResultStatus,
    ArtifactPathError,
    EvidenceCapture,
    ExecutionService,
    safe_artifact_path,
)
from proofdemo.application.trace import TraceEventKind
from proofdemo.application.verification import OutcomeStatus, VerificationStatus
from proofdemo.cli import EXIT_FAILED, run
from proofdemo.domain.demo_run import DemoRunStatus
from proofdemo.domain.demo_spec import DemoSpec, ElementTarget
from proofdemo.ports.browser import (
    AppStateObservation,
    BrowserActionError,
    BrowserLogEntry,
    BrowserSessionArtifacts,
    BrowserUnavailableError,
    DownloadObservation,
)

ROOT = Path(__file__).resolve().parents[1]


def load_example() -> dict[str, Any]:
    return json.loads((ROOT / "examples" / "demo_spec.json").read_text(encoding="utf-8"))


class FakeBrowser:
    def __init__(
        self,
        *,
        startup_error: Exception | None = None,
        action_error: Exception | None = None,
        observation_error: Exception | None = None,
        visible: bool = True,
        text: str | None = "Prepare launch demo",
        download: DownloadObservation | None = None,
        fail_evidence_capture: bool = False,
    ) -> None:
        self.startup_error = startup_error
        self.action_error = action_error
        self.observation_error = observation_error
        self.visible = visible
        self.text = text
        self.download = download or DownloadObservation(
            filename="launch-plan.txt",
            completed=True,
            byte_count=20,
        )
        self.fail_evidence_capture = fail_evidence_capture
        self.recording_dir: Path | None = None
        self.calls: list[tuple[str, object]] = []
        self.closed = False

    def open(self, source_url: str, *, recording_dir: Path | None = None) -> None:
        self.calls.append(("open", source_url))
        self.recording_dir = recording_dir
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
        if self.fail_evidence_capture and path.parent.name == "evidence":
            raise BrowserActionError("evidence capture unavailable")
        path.write_bytes(b"fake png")

    def is_visible(self, target: ElementTarget, *, timeout_ms: int) -> bool:
        if self.observation_error is not None:
            raise self.observation_error
        self.calls.append(("is_visible", (target, timeout_ms)))
        return self.visible

    def text_content(self, target: ElementTarget, *, timeout_ms: int) -> str | None:
        if self.observation_error is not None:
            raise self.observation_error
        self.calls.append(("text_content", (target, timeout_ms)))
        return self.text

    def current_url(self) -> str:
        if self.observation_error is not None:
            raise self.observation_error
        return "http://127.0.0.1:4173/"

    def completed_download(self, filename: str, *, timeout_ms: int) -> DownloadObservation:
        if self.observation_error is not None:
            raise self.observation_error
        return self.download

    def application_state(self, key: str) -> AppStateObservation:
        if self.observation_error is not None:
            raise self.observation_error
        return AppStateObservation(found=True, value=1)

    def close(self) -> BrowserSessionArtifacts:
        self.closed = True
        self.calls.append(("close", None))
        video_path = None
        if self.recording_dir is not None:
            video_path = self.recording_dir / "browser.webm"
            video_path.write_bytes(b"fake webm")
        return BrowserSessionArtifacts(
            video_path=video_path,
            logs=(BrowserLogEntry(level="info", message="fixture ready"),),
        )


def test_successful_execution_is_ordered_and_verified(tmp_path: Path) -> None:
    browser = FakeBrowser()
    spec = DemoSpec.model_validate(load_example())

    report = ExecutionService(browser).execute(spec, tmp_path)

    assert report.run.status is DemoRunStatus.PASSED
    assert report.verification_status is VerificationStatus.PASSED
    assert [result.action_id for result in report.action_results] == [
        "open-todo-app",
        "enter-task-title",
        "add-task",
        "download-launch-plan",
        "capture-created-task",
    ]
    assert all(result.status is ActionResultStatus.SUCCEEDED for result in report.action_results)
    assert report.screenshot_paths == ("task-created.png",)
    assert (tmp_path / "task-created.png").is_file()
    assert browser.closed
    assert [transition.to_status for transition in report.run.transitions][-2:] == [
        DemoRunStatus.EXECUTED,
        DemoRunStatus.PASSED,
    ]
    assert report.scene_results[0].status is OutcomeStatus.PASSED
    assert len(report.scene_results[0].assertion_results) == 5
    assert "scene_results" in report.model_dump()
    assert "assertion_results" in report.model_dump()["scene_results"][0]


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
    assert report.run.status is DemoRunStatus.PASSED


def test_action_failure_is_failed_and_browser_closes(tmp_path: Path) -> None:
    browser = FakeBrowser(action_error=BrowserActionError("target is missing"))
    spec = DemoSpec.model_validate(load_example())

    report = ExecutionService(browser).execute(spec, tmp_path)

    assert report.run.status is DemoRunStatus.FAILED
    assert report.run.transitions[-1].reason == "target is missing"
    assert report.action_results[-1].action_id == "add-task"
    assert report.action_results[-1].status is ActionResultStatus.FAILED
    assert report.action_results[-1].error == "target is missing"
    assert report.scene_results[0].status is OutcomeStatus.FAILED
    assert all(
        result.status is OutcomeStatus.BLOCKED
        for result in report.scene_results[0].assertion_results
    )
    assert report.verification_status is VerificationStatus.NOT_RUN
    assert browser.closed


def test_browser_startup_failure_is_blocked_and_close_is_attempted(tmp_path: Path) -> None:
    browser = FakeBrowser(startup_error=BrowserUnavailableError("Chromium unavailable"))
    spec = DemoSpec.model_validate(load_example())

    report = ExecutionService(browser).execute(spec, tmp_path)

    assert report.run.status is DemoRunStatus.BLOCKED
    assert report.run.transitions[-1].reason == "Chromium unavailable"
    assert report.action_results == ()
    assert report.scene_results[0].status is OutcomeStatus.BLOCKED
    assert report.verification_status is VerificationStatus.NOT_RUN
    assert browser.closed


def test_false_assertion_fails_scene_and_run(tmp_path: Path) -> None:
    browser = FakeBrowser(text="A different task")
    spec = DemoSpec.model_validate(load_example())

    report = ExecutionService(browser).execute(spec, tmp_path)

    assert report.run.status is DemoRunStatus.FAILED
    assert report.verification_status is VerificationStatus.FAILED
    assert report.scene_results[0].status is OutcomeStatus.FAILED
    failed = report.scene_results[0].assertion_results[0]
    assert failed.status is OutcomeStatus.FAILED
    assert failed.evidence is not None
    assert failed.evidence.observed == "A different task"
    assert browser.closed


def test_unavailable_observation_blocks_scene_and_run(tmp_path: Path) -> None:
    browser = FakeBrowser(observation_error=BrowserUnavailableError("page crashed"))
    spec = DemoSpec.model_validate(load_example())

    report = ExecutionService(browser).execute(spec, tmp_path)

    assert report.run.status is DemoRunStatus.BLOCKED
    assert report.verification_status is VerificationStatus.BLOCKED
    assert report.scene_results[0].status is OutcomeStatus.BLOCKED
    assert report.scene_results[0].assertion_results[0].reason == "page crashed"
    assert browser.closed


def test_download_requires_expected_completed_file(tmp_path: Path) -> None:
    browser = FakeBrowser(
        download=DownloadObservation(
            filename="launch-plan.txt",
            completed=False,
            failure="download canceled",
        )
    )
    spec = DemoSpec.model_validate(load_example())

    report = ExecutionService(browser).execute(spec, tmp_path)

    download_result = next(
        result
        for result in report.scene_results[0].assertion_results
        if result.assertion_type == "download_completed"
    )
    assert download_result.status is OutcomeStatus.FAILED
    assert download_result.evidence is not None
    assert download_result.evidence.observed == {
        "filename": "launch-plan.txt",
        "completed": False,
        "byte_count": None,
        "failure": "download canceled",
    }


def test_later_scenes_are_blocked_after_verification_failure(tmp_path: Path) -> None:
    raw = load_example()
    later_scene = deepcopy(raw["scenes"][0])
    later_scene["id"] = "review_task"
    later_scene["actions"] = [{"id": "review-pause", "type": "pause", "duration_ms": 1}]
    later_scene["assertions"] = [
        {
            "id": "list-still-visible",
            "type": "element_visible",
            "target": {"strategy": "test_id", "test_id": "task-list"},
        }
    ]
    raw["scenes"].append(later_scene)
    spec = DemoSpec.model_validate(raw)

    report = ExecutionService(FakeBrowser(text="wrong task")).execute(spec, tmp_path)

    assert [result.status for result in report.scene_results] == [
        OutcomeStatus.FAILED,
        OutcomeStatus.BLOCKED,
    ]
    assert all(result.scene_id != "review_task" for result in report.action_results)
    assert report.scene_results[1].assertion_results[0].status is OutcomeStatus.BLOCKED


def test_cli_returns_failed_exit_and_writes_evidence_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(load_example()), encoding="utf-8")
    artifacts = tmp_path / "artifacts"
    monkeypatch.setattr(
        "proofdemo.cli.PlaywrightBrowser",
        lambda: FakeBrowser(text="wrong task"),
    )

    exit_code = run(["run", str(spec_path), "--artifacts", str(artifacts)])
    report = json.loads((artifacts / "execution_report.json").read_text(encoding="utf-8"))

    assert exit_code == EXIT_FAILED
    assert report["run"]["status"] == "FAILED"
    assert report["verification_status"] == "FAILED"
    assert report["scene_results"][0]["assertion_results"][0]["evidence"] == {
        "kind": "text_contains",
        "expected": "Prepare launch demo",
        "observed": "wrong task",
    }


def test_execution_bundle_trace_is_contiguous_and_omits_fill_value(tmp_path: Path) -> None:
    spec = DemoSpec.model_validate(load_example())

    bundle = ExecutionService(FakeBrowser()).execute_bundle(spec, tmp_path)

    assert [event.sequence for event in bundle.trace_events] == list(
        range(1, len(bundle.trace_events) + 1)
    )
    assert bundle.trace_events[-1].kind is TraceEventKind.RUN_TRANSITION
    assert bundle.trace_events[-1].status == "PASSED"
    action_trace = "\n".join(
        event.model_dump_json()
        for event in bundle.trace_events
        if event.kind in {TraceEventKind.ACTION_STARTED, TraceEventKind.ACTION_FINISHED}
    )
    assert "Prepare launch demo" not in action_trace
    assert any(event.kind is TraceEventKind.ASSERTION_EVALUATED for event in bundle.trace_events)
    assert len(bundle.evidence_captures) == 5


@pytest.mark.parametrize(
    ("browser", "terminal_status"),
    [
        (FakeBrowser(text="wrong task"), "FAILED"),
        (FakeBrowser(startup_error=BrowserUnavailableError("no browser")), "BLOCKED"),
    ],
)
def test_trace_order_remains_valid_on_unsuccessful_paths(
    browser: FakeBrowser, terminal_status: str, tmp_path: Path
) -> None:
    bundle = ExecutionService(browser).execute_bundle(
        DemoSpec.model_validate(load_example()),
        tmp_path,
    )

    assert [event.sequence for event in bundle.trace_events] == list(
        range(1, len(bundle.trace_events) + 1)
    )
    run_events = [
        event for event in bundle.trace_events if event.kind is TraceEventKind.RUN_TRANSITION
    ]
    assert run_events[-1].status == terminal_status


def test_evidence_capture_failure_warns_without_changing_verification(tmp_path: Path) -> None:
    bundle = ExecutionService(FakeBrowser(fail_evidence_capture=True)).execute_bundle(
        DemoSpec.model_validate(load_example()),
        tmp_path,
    )

    assert bundle.report.run.status is DemoRunStatus.PASSED
    assert bundle.report.verification_status is VerificationStatus.PASSED
    assert bundle.report.evidence_screenshot_paths == ()
    assert len(bundle.report.artifact_warnings) == 5
    assert (
        sum(event.kind is TraceEventKind.ARTIFACT_CAPTURE_FAILED for event in bundle.trace_events)
        == 5
    )


def test_artifact_writer_hashes_and_verifies_every_declared_file(tmp_path: Path) -> None:
    bundle = ExecutionService(FakeBrowser()).execute_bundle(
        DemoSpec.model_validate(load_example()),
        tmp_path,
    )

    manifest = ArtifactWriter().persist(bundle, tmp_path)

    assert (tmp_path / "execution_report.json").is_file()
    assert (tmp_path / "trace.jsonl").is_file()
    assert (tmp_path / "browser.log.jsonl").is_file()
    assert (tmp_path / "artifact_manifest.json").is_file()
    assert ArtifactWriter.verify(tmp_path, manifest) == ()
    assert {record.kind for record in manifest.artifacts} == set(ArtifactKind)
    assert len(manifest.artifacts) == 10
    assert all(len(record.sha256) == 64 for record in manifest.artifacts)
    evidence = [
        record for record in manifest.artifacts if record.kind is ArtifactKind.EVIDENCE_SCREENSHOT
    ]
    assert all(record.scene_id and record.assertion_id for record in evidence)


def test_manifest_verification_detects_changed_bytes(tmp_path: Path) -> None:
    bundle = ExecutionService(FakeBrowser()).execute_bundle(
        DemoSpec.model_validate(load_example()),
        tmp_path,
    )
    manifest = ArtifactWriter().persist(bundle, tmp_path)
    (tmp_path / "task-created.png").write_bytes(b"tampered bytes")

    errors = ArtifactWriter.verify(tmp_path, manifest)

    assert "byte count changed: task-created.png" in errors
    assert "sha256 changed: task-created.png" in errors


def test_artifact_writer_rejects_correlated_path_traversal(tmp_path: Path) -> None:
    bundle = ExecutionService(FakeBrowser()).execute_bundle(
        DemoSpec.model_validate(load_example()),
        tmp_path,
    )
    unsafe = replace(
        bundle,
        evidence_captures=(
            EvidenceCapture(
                scene_id="create_task",
                assertion_id="task-is-listed",
                path="../escape.png",
            ),
        ),
    )

    with pytest.raises(ArtifactWriteError, match="escaped requested directory"):
        ArtifactWriter().persist(unsafe, tmp_path)


def test_safe_artifact_path_rejects_traversal(tmp_path: Path) -> None:
    with pytest.raises(ArtifactPathError, match="escapes requested directory"):
        safe_artifact_path(tmp_path, "../escaped.png")


def test_safe_artifact_path_rejects_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.png"
    link = tmp_path / "capture.png"
    link.symlink_to(outside)

    with pytest.raises(ArtifactPathError, match="escapes requested directory"):
        safe_artifact_path(tmp_path, "capture.png")
