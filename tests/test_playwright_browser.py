"""Integration tests for the real Playwright Chromium adapter."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from proofdemo.adapters.playwright_browser import PlaywrightBrowser
from proofdemo.application.execution import ExecutionService
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
    report = ExecutionService(PlaywrightBrowser()).execute(spec_for_url(todo_url), tmp_path)

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


def test_real_adapter_rejects_cross_origin_navigation(todo_url: str) -> None:
    browser = PlaywrightBrowser()
    browser.open(todo_url)
    try:
        with pytest.raises(BrowserActionError, match="leave the source origin"):
            browser.goto("https://example.com/", timeout_ms=1_000)
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
