"""Browser acceptance for the real React workbench against a controlled API contract."""

from __future__ import annotations

import os
import socket
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import pytest
from playwright.sync_api import Route, sync_playwright

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def vite_url() -> Iterator[str]:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    vite = ROOT / "frontend" / "node_modules" / ".bin" / "vite"
    if not vite.is_file():
        pytest.skip("frontend dependencies are not installed")
    environment = os.environ.copy()
    environment["VITE_API_BASE_URL"] = "http://127.0.0.1:8000"
    process = subprocess.Popen(
        [str(vite), "--host", "127.0.0.1", "--port", str(port), "--strictPort"],
        cwd=ROOT / "frontend",
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if process.poll() is not None:
                pytest.fail("Vite server exited before it became ready")
            try:
                with urlopen(url, timeout=1) as response:
                    if response.status == 200:
                        break
            except (URLError, TimeoutError):
                time.sleep(0.1)
        else:
            pytest.fail("Vite server did not become ready")
        yield url
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def test_workbench_submits_intent_and_renders_verified_result(vite_url: str) -> None:
    job_id = "d1a9716f-4266-43cc-965d-90239fcab783"
    job = {
        "id": job_id,
        "status": "PASSED",
        "message": "Verified demo video is ready",
        "spec_id": "ui_demo",
        "run_status": "PASSED",
        "safety_findings": [],
        "preview_revision": 0,
        "exploration_status": "COMPLETE",
        "exploration_page_count": 1,
        "grounding_status": "GROUNDED",
    }
    spec = {
        "id": "ui_demo",
        "title": "Create a task",
        "goal": "Show task creation",
        "source_url": "https://product.example.test/",
        "scenes": [
            {
                "id": "create_task",
                "title": "Create the task",
                "goal": "Add a task",
                "actions": [{"id": "open", "type": "goto"}],
                "assertions": [{"id": "visible", "type": "element_visible"}],
            }
        ],
    }
    report = {
        "verification_status": "PASSED",
        "scene_results": [
            {
                "scene_id": "create_task",
                "status": "PASSED",
                "assertion_results": [
                    {
                        "assertion_id": "visible",
                        "status": "PASSED",
                        "evidence": {"kind": "element_visible", "expected": True, "observed": True},
                    }
                ],
            }
        ],
        "artifact_warnings": [],
    }
    cors = {
        "Access-Control-Allow-Origin": vite_url,
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, X-ProofDemo-Client",
    }
    submitted: list[dict[str, object]] = []
    page_errors: list[str] = []

    def fulfill(route: Route) -> None:
        request = route.request
        path = request.url.split("http://127.0.0.1:8000", 1)[-1]
        if request.method == "OPTIONS":
            route.fulfill(status=204, headers=cors)
            return
        if path == "/jobs" and request.method == "POST":
            assert request.headers["x-proofdemo-client"] == "studio"
            submitted.append(request.post_data_json)
            body: object = job
        elif path == "/health":
            body = {"version": "1.0.0"}
        elif path == f"/jobs/{job_id}":
            body = job
        elif path == f"/jobs/{job_id}/spec":
            body = spec
        elif path == f"/jobs/{job_id}/exploration":
            body = {
                "status": "COMPLETE",
                "warnings": [],
                "unvisited_link_count": 0,
                "pages": [
                    {
                        "url": "https://product.example.test/",
                        "title": "Product home",
                        "headings": ["Get started"],
                        "controls": [
                            {
                                "id": "page-1-control-1",
                                "kind": "button",
                                "name": "Create task",
                                "href": None,
                                "target": {
                                    "strategy": "role",
                                    "role": "button",
                                    "name": "Create task",
                                },
                            }
                        ],
                    }
                ],
            }
        elif path == f"/jobs/{job_id}/grounding":
            body = {
                "status": "GROUNDED",
                "checks": [
                    {
                        "scene_id": "create_task",
                        "action_id": "open",
                        "status": "GROUNDED",
                        "page_index": 1,
                        "control_id": None,
                        "reason": None,
                    }
                ],
            }
        elif path.startswith(f"/jobs/{job_id}/exploration-preview"):
            route.fulfill(status=200, headers={**cors, "Content-Type": "image/png"}, body=b"")
            return
        elif path == f"/jobs/{job_id}/report":
            body = report
        elif path == f"/jobs/{job_id}/manifest":
            body = {"artifacts": [{"kind": "FINAL_VIDEO", "path": "demo.mp4"}]}
        elif path == f"/jobs/{job_id}/event-log":
            body = [
                {
                    "sequence": 1,
                    "kind": "JOB_STATUS",
                    "status": "PASSED",
                    "message": "Verified demo video is ready",
                    "scene_id": None,
                    "action_id": None,
                    "assertion_id": None,
                }
            ]
        elif path == f"/jobs/{job_id}/video":
            route.fulfill(status=200, headers={**cors, "Content-Type": "video/mp4"}, body=b"")
            return
        else:
            route.fulfill(status=404, headers=cors, body="not found")
            return
        route.fulfill(status=200, headers={**cors, "Content-Type": "application/json"}, json=body)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.route("http://127.0.0.1:8000/**", fulfill)
        page.goto(vite_url)
        page.locator("#url").fill("https://product.example.test/")
        page.locator("#goal").fill("Create a task")
        page.locator("#audience").fill("Product team")
        page.locator("#language").select_option("en")
        page.locator("#duration").select_option("90")
        page.locator("button.primary-button").click()
        page.locator("video").wait_for(timeout=10_000)
        page.get_by_role("tab", name="探索").click()
        page.get_by_text("Product home").wait_for(timeout=10_000)
        assert page.get_by_text("计划证据覆盖").count() == 1
        page.get_by_role("tab", name="验证").click()
        page.get_by_text("visible", exact=True).wait_for(timeout=10_000)

        assert page.locator(".job-state").inner_text() == "PASSED"
        assert page.locator(".verification-card").count() == 1
        assert page.locator(".event-item").count() == 1
        assert submitted[0]["source_url"] == "https://product.example.test/"
        assert submitted[0]["goal"] == "Create a task"
        assert submitted[0]["audience"] == "Product team"
        assert submitted[0]["language"] == "en"
        assert submitted[0]["approximate_duration_seconds"] == 90
        assert page_errors == []
        browser.close()
