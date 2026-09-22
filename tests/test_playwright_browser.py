"""Integration tests for the real Playwright Chromium adapter."""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Iterator
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Error as PlaywrightError

from proofdemo.adapters.ffmpeg_render import FFmpegRenderAdapter
from proofdemo.adapters.playwright_browser import PlaywrightBrowser
from proofdemo.application.artifacts import ArtifactKind, ArtifactManifest, ArtifactWriter
from proofdemo.application.execution import ExecutionService
from proofdemo.application.rendering import CompositionService
from proofdemo.application.trace import TraceEventKind
from proofdemo.cli import EXIT_EXECUTED, run
from proofdemo.domain.demo_run import DemoRunStatus
from proofdemo.domain.demo_spec import (
    CssTarget,
    DemoSpec,
    LabelTarget,
    RoleTarget,
    TextTarget,
)
from proofdemo.domain.demo_spec import (
    TestIdTarget as ByTestIdTarget,
)
from proofdemo.ports.browser import BrowserActionError

ROOT = Path(__file__).resolve().parents[1]
TODO_APP = ROOT / "examples" / "todo_app"


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass


@pytest.fixture
def todo_url() -> Iterator[str]:
    handler = partial(QuietHandler, directory=str(TODO_APP))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield f"http://{host}:{port}/"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.fixture
def new_tab_url(tmp_path: Path) -> Iterator[str]:
    root = tmp_path / "new-tab-site"
    root.mkdir()
    (root / "index.html").write_text(
        """<!doctype html><html><body>
        <a href="/h5.html" id="scripted-popup">Open H5 games</a>
        <a href="https://example.com/" target="_blank">Leave site</a>
        <script>
        document.addEventListener('click', event => {
          const link = event.target.closest('#scripted-popup');
          if (link) {
            event.preventDefault();
            window.open(link.href, '_blank');
          }
        });
        </script>
        </body></html>""",
        encoding="utf-8",
    )
    (root / "h5.html").write_text(
        "<!doctype html><html><body><h1>H5 games</h1></body></html>",
        encoding="utf-8",
    )
    handler = partial(QuietHandler, directory=str(root))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield f"http://{host}:{port}/"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def spec_for_url(url: str) -> DemoSpec:
    raw: dict[str, Any] = json.loads(
        (ROOT / "examples" / "demo_spec.json").read_text(encoding="utf-8")
    )
    raw["source_url"] = url
    raw["scenes"][0]["actions"][0]["url"] = url
    url_assertion = next(
        item for item in raw["scenes"][0]["assertions"] if item["type"] == "url_equals"
    )
    url_assertion["expected_url"] = url
    return DemoSpec.model_validate(raw)


def test_real_chromium_executes_example_and_captures_screenshot(
    todo_url: str, tmp_path: Path
) -> None:
    bundle = ExecutionService(PlaywrightBrowser()).execute_bundle(spec_for_url(todo_url), tmp_path)
    report = bundle.report

    assert report.run.status is DemoRunStatus.PASSED
    assert report.verification_status == "PASSED"
    assert [result.action_type for result in report.action_results] == [
        "goto",
        "fill",
        "click",
        "click",
        "screenshot",
    ]
    assert [result.status for result in report.scene_results[0].assertion_results] == [
        "PASSED",
        "PASSED",
        "PASSED",
        "PASSED",
        "PASSED",
    ]
    assert (tmp_path / "task-created.png").stat().st_size > 0
    assert len(report.evidence_screenshot_paths) == 5
    assert all((tmp_path / path).stat().st_size > 0 for path in report.evidence_screenshot_paths)
    assert report.browser_video_path == "browser.webm"
    assert (tmp_path / "browser.webm").stat().st_size > 0
    assert list(tmp_path.glob("*.webm")) == [tmp_path / "browser.webm"]
    focus_events = [
        event
        for event in bundle.trace_events
        if event.kind is TraceEventKind.ACTION_STARTED and "focus_x" in event.data
    ]
    assert {event.data["action_type"] for event in focus_events} >= {"fill", "click"}
    assert all(0 <= event.data["focus_x"] <= 1 for event in focus_events)

    writer = ArtifactWriter()
    source_manifest = writer.persist(bundle, tmp_path)
    service = CompositionService(FFmpegRenderAdapter())
    first = service.compose(bundle, source_manifest, tmp_path)
    final_manifest = writer.persist(
        bundle,
        tmp_path,
        extra_artifacts=first.declarations,
    )
    first_digest = hashlib.sha256((tmp_path / "demo.mp4").read_bytes()).hexdigest()
    service.compose(bundle, final_manifest, tmp_path)
    second_digest = hashlib.sha256((tmp_path / "demo.mp4").read_bytes()).hexdigest()

    assert first.output_info.width == 1920
    assert first.output_info.height == 1080
    assert first.output_info.fps == pytest.approx(30.0)
    assert first.output_info.codec == "h264"
    assert first_digest == second_digest
    assert ArtifactWriter.verify(tmp_path, final_manifest) == ()
    assert {ArtifactKind.TIMELINE, ArtifactKind.FINAL_VIDEO}.issubset(
        {record.kind for record in final_manifest.artifacts}
    )


def test_real_cli_replays_recipe_with_fresh_verified_run(
    todo_url: str,
    tmp_path: Path,
) -> None:
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(spec_for_url(todo_url).model_dump_json(), encoding="utf-8")
    source_dir = tmp_path / "source"
    replay_dir = tmp_path / "replay"

    first_exit = run(["run", str(spec_path), "--artifacts", str(source_dir)])
    first_report = json.loads((source_dir / "execution_report.json").read_text(encoding="utf-8"))
    replay_exit = run(
        [
            "replay",
            str(source_dir / "demo_recipe.json"),
            "--artifacts",
            str(replay_dir),
        ]
    )
    replay_report = json.loads((replay_dir / "execution_report.json").read_text(encoding="utf-8"))
    preflight = json.loads((replay_dir / "replay_preflight.json").read_text(encoding="utf-8"))
    change_report = json.loads((replay_dir / "ui_change_report.json").read_text(encoding="utf-8"))
    replay_manifest = ArtifactManifest.model_validate_json(
        (replay_dir / "artifact_manifest.json").read_text(encoding="utf-8")
    )

    assert first_exit == EXIT_EXECUTED
    assert replay_exit == EXIT_EXECUTED
    assert first_report["run"]["status"] == "PASSED"
    assert replay_report["run"]["status"] == "PASSED"
    assert replay_report["run"]["id"] != first_report["run"]["id"]
    assert preflight["status"] == "COMPATIBLE"
    assert preflight["source_run_id"] == first_report["run"]["id"]
    assert change_report["status"] == "UNCHANGED"
    assert change_report["findings"] == []
    assert ArtifactWriter.verify(replay_dir, replay_manifest) == ()
    assert {
        ArtifactKind.REPLAY_PREFLIGHT,
        ArtifactKind.UI_CHANGE_REPORT,
        ArtifactKind.DEMO_RECIPE,
    }.issubset({record.kind for record in replay_manifest.artifacts})


def test_real_adapter_maps_every_typed_locator(todo_url: str) -> None:
    browser = PlaywrightBrowser()
    browser.open(todo_url)
    try:
        browser.goto(todo_url, timeout_ms=5_000)
        browser.fill(
            LabelTarget(strategy="label", label="Task title"),
            "Prepare launch demo",
            timeout_ms=1_000,
        )
        browser.fill(
            CssTarget(strategy="css", selector="#task-title"),
            "Prepare launch demo",
            timeout_ms=1_000,
        )
        browser.click(
            RoleTarget(strategy="role", role="button", name="Add task"),
            timeout_ms=1_000,
        )
        browser.click(
            TextTarget(strategy="text", text="Prepare launch demo"),
            timeout_ms=1_000,
        )
        browser.click(
            ByTestIdTarget(strategy="test_id", test_id="task-list"),
            timeout_ms=1_000,
        )
    finally:
        browser.close()


def test_real_adapter_reports_missing_target(todo_url: str) -> None:
    browser = PlaywrightBrowser()
    browser.open(todo_url)
    try:
        browser.goto(todo_url, timeout_ms=5_000)
        with pytest.raises(BrowserActionError, match="not actionable"):
            browser.click(
                ByTestIdTarget(strategy="test_id", test_id="does-not-exist"),
                timeout_ms=50,
            )
    finally:
        browser.close()


def test_fill_error_never_echoes_the_fill_value(monkeypatch: pytest.MonkeyPatch) -> None:
    class FailingLocator:
        def fill(self, value: str, *, timeout: int) -> None:
            raise PlaywrightError(f"fill call included {value}")

    browser = PlaywrightBrowser()
    monkeypatch.setattr(browser, "_locator", lambda target: FailingLocator())

    with pytest.raises(BrowserActionError) as captured:
        browser.fill(
            LabelTarget(strategy="label", label="Task title"), "demo-sentinel", timeout_ms=10
        )

    assert "demo-sentinel" not in str(captured.value)


def test_real_adapter_rejects_cross_origin_navigation(todo_url: str) -> None:
    browser = PlaywrightBrowser()
    browser.open(todo_url)
    try:
        with pytest.raises(BrowserActionError, match="leave the source origin"):
            browser.goto("https://example.com/", timeout_ms=1_000)
    finally:
        browser.close()


def test_real_adapter_keeps_same_origin_new_tab_link_in_recorded_page(
    new_tab_url: str, tmp_path: Path
) -> None:
    browser = PlaywrightBrowser()
    browser.open(new_tab_url, recording_dir=tmp_path)
    try:
        browser.goto(new_tab_url, timeout_ms=5_000)
        browser.click(
            RoleTarget(strategy="role", role="link", name="Open H5 games"),
            timeout_ms=5_000,
        )

        assert browser.current_url() == f"{new_tab_url}h5.html"
        assert browser.is_visible(
            RoleTarget(strategy="role", role="heading", name="H5 games"),
            timeout_ms=1_000,
        )
    finally:
        artifacts = browser.close()

    assert artifacts.video_path == tmp_path / "browser.webm"
    assert artifacts.video_path.stat().st_size > 0
    assert list(tmp_path.glob("*.webm")) == [tmp_path / "browser.webm"]


def test_real_adapter_still_blocks_cross_origin_new_tab_link(new_tab_url: str) -> None:
    browser = PlaywrightBrowser()
    browser.open(new_tab_url)
    try:
        browser.goto(new_tab_url, timeout_ms=5_000)
        with pytest.raises(BrowserActionError):
            browser.click(
                RoleTarget(strategy="role", role="link", name="Leave site"),
                timeout_ms=5_000,
            )
        assert browser.current_url() == new_tab_url
    finally:
        browser.close()


def test_real_video_finalizes_after_action_failure(todo_url: str, tmp_path: Path) -> None:
    raw: dict[str, Any] = json.loads(
        (ROOT / "examples" / "demo_spec.json").read_text(encoding="utf-8")
    )
    raw["source_url"] = todo_url
    raw["scenes"][0]["actions"][0]["url"] = todo_url
    raw["scenes"][0]["actions"][2]["target"]["name"] = "Missing button"
    raw["scenes"][0]["actions"][2]["timeout_ms"] = 100
    url_assertion = next(
        item for item in raw["scenes"][0]["assertions"] if item["type"] == "url_equals"
    )
    url_assertion["expected_url"] = todo_url
    spec = DemoSpec.model_validate(raw)

    report = ExecutionService(PlaywrightBrowser()).execute(spec, tmp_path)

    assert report.run.status is DemoRunStatus.FAILED
    assert report.browser_video_path == "browser.webm"
    assert (tmp_path / "browser.webm").stat().st_size > 0
