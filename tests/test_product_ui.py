"""Browser acceptance for the real React workbench against a controlled API contract."""

from __future__ import annotations

import os
import socket
import subprocess
import threading
import time
from collections.abc import Iterator
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen
from uuid import UUID

import pytest
from playwright.sync_api import Route, sync_playwright
from uvicorn import Config, Server

from proofdemo.adapters.ffmpeg_polish import FFmpegVideoPolisher
from proofdemo.adapters.playwright_explorer import PlaywrightExplorer
from proofdemo.api import create_app
from proofdemo.application.artifacts import ArtifactWriter
from proofdemo.application.jobs import JobManager, JobStatus
from proofdemo.config import Settings
from proofdemo.domain.demo_spec import DemoSpec
from proofdemo.domain.exploration import ExplorationReport
from proofdemo.domain.planning import DemoIntent
from proofdemo.ports.planner import PlannerCandidate

ROOT = Path(__file__).resolve().parents[1]


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def wait_for_http(url: str, *, timeout: float = 20) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except (URLError, TimeoutError):
            time.sleep(0.1)
    pytest.fail(f"HTTP server did not become ready: {url}")


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass


class TodoLinkAdvisor:
    def choose(self, intent: DemoIntent, pages: tuple, candidates: tuple[str, ...]) -> str | None:
        return None


class TodoGroundedPlanner:
    def plan(self, intent: DemoIntent) -> PlannerCandidate:
        raise AssertionError("the product job must use its exploration report")

    def plan_grounded(self, intent: DemoIntent, report: ExplorationReport) -> PlannerCandidate:
        assert len(report.pages) == 1
        assert str(report.pages[0].url) == str(intent.source_url)
        spec = DemoSpec.model_validate(
            {
                "schema_version": "1.2",
                "id": "ui_full_stack",
                "title": "Create a task",
                "goal": intent.goal,
                "source_url": str(intent.source_url),
                "scenes": [
                    {
                        "id": "create_task",
                        "title": "Create and verify a task",
                        "goal": intent.goal,
                        "actions": [
                            {"id": "open", "type": "goto", "url": str(intent.source_url)},
                            {
                                "id": "title",
                                "type": "fill",
                                "target": {"strategy": "label", "label": "Task title"},
                                "value": "Launch update",
                            },
                            {
                                "id": "add",
                                "type": "click",
                                "target": {
                                    "strategy": "role",
                                    "role": "button",
                                    "name": "Add task",
                                },
                            },
                        ],
                        "assertions": [
                            {
                                "id": "created",
                                "type": "text_contains",
                                "target": {"strategy": "test_id", "test_id": "task-list"},
                                "expected_text": "Launch update",
                            }
                        ],
                    }
                ],
            }
        )
        return PlannerCandidate(spec=spec, provider="fixture", model="fixture")


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
        "video_kind": "POLISHED_VIDEO",
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
            body = {"artifacts": [{"kind": "POLISHED_VIDEO", "path": "polished_demo.mp4"}]}
        elif path == f"/jobs/{job_id}/polish-plan":
            body = {
                "output_duration_ms": 2800,
                "warnings": [],
                "scenes": [
                    {
                        "scene_id": "create_task",
                        "title": "Create the task",
                        "display_start_ms": 0,
                        "display_end_ms": 2800,
                        "passed_assertions": 1,
                    }
                ],
                "focus_cues": [{"scene_id": "create_task", "action_id": "open", "kind": "click"}],
            }
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
        assert page.locator(".verification-card").count() == 1
        page.get_by_role("tab", name="视频编辑").click()
        page.get_by_text("1 个真实目标镜头").wait_for(timeout=10_000)
        page.get_by_text("click · open").wait_for(timeout=10_000)

        assert page.locator(".job-state").inner_text() == "PASSED"
        assert page.locator(".panel-title").get_by_text("润色版").count() == 1
        assert page.locator(".event-item").count() == 1
        assert submitted[0]["source_url"] == "https://product.example.test/"
        assert submitted[0]["goal"] == "Create a task"
        assert submitted[0]["audience"] == "Product team"
        assert submitted[0]["language"] == "en"
        assert submitted[0]["approximate_duration_seconds"] == 90
        assert page_errors == []
        browser.close()


@pytest.fixture
def full_stack(tmp_path: Path) -> Iterator[tuple[str, str, JobManager]]:
    vite = ROOT / "frontend" / "node_modules" / ".bin" / "vite"
    if not vite.is_file():
        pytest.skip("frontend dependencies are not installed")
    todo = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        partial(QuietHandler, directory=str(ROOT / "examples" / "todo_app")),
    )
    todo_thread = threading.Thread(target=todo.serve_forever, daemon=True)
    todo_thread.start()
    todo_host, todo_port = todo.server_address
    todo_url = f"http://{todo_host}:{todo_port}/"
    api_port, vite_port = free_port(), free_port()
    api_url = f"http://127.0.0.1:{api_port}"
    vite_url = f"http://127.0.0.1:{vite_port}"
    jobs = JobManager(
        tmp_path / "jobs",
        planner_factory=TodoGroundedPlanner,
        explorer_factory=PlaywrightExplorer,
        advisor_factory=TodoLinkAdvisor,
        polisher_factory=FFmpegVideoPolisher,
    )
    settings = Settings(environment="test", job_root=tmp_path / "jobs", frontend_origin=vite_url)
    server = Server(
        Config(create_app(settings, jobs), host="127.0.0.1", port=api_port, log_level="error")
    )
    api_thread = threading.Thread(target=server.run, daemon=True)
    api_thread.start()
    environment = os.environ.copy()
    environment["VITE_API_BASE_URL"] = api_url
    process = subprocess.Popen(
        [str(vite), "--host", "127.0.0.1", "--port", str(vite_port), "--strictPort"],
        cwd=ROOT / "frontend",
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        wait_for_http(f"{api_url}/health")
        wait_for_http(vite_url)
        yield vite_url, todo_url, jobs
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        server.should_exit = True
        api_thread.join(timeout=5)
        todo.shutdown()
        todo.server_close()
        todo_thread.join(timeout=5)


def test_workbench_generates_polished_video_through_real_local_stack(
    full_stack: tuple[str, str, JobManager],
) -> None:
    vite_url, todo_url, jobs = full_stack
    page_errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.goto(vite_url)
        page.locator("#url").fill(todo_url)
        page.locator("#goal").fill("Create and verify one task")
        page.locator("button.primary-button").click()
        page.wait_for_function(
            "() => ['PASSED', 'FAILED', 'BLOCKED'].includes("
            "document.querySelector('.job-state')?.textContent?.trim())",
            timeout=90_000,
        )
        assert page.locator(".job-state").inner_text() == "PASSED"
        page.locator("video").wait_for(timeout=90_000)
        page.get_by_role("tab", name="探索").click()
        page.get_by_text("计划证据覆盖").wait_for(timeout=10_000)
        page.get_by_role("tab", name="验证").click()
        page.get_by_text("created", exact=True).wait_for(timeout=10_000)
        page.get_by_role("tab", name="视频编辑").click()
        page.get_by_text("真实目标镜头").wait_for(timeout=10_000)
        video_url = page.locator("video").get_attribute("src")
        assert video_url is not None
        job_id = UUID(video_url.split("/jobs/", 1)[1].split("/", 1)[0])
        job = jobs.get(job_id)
        assert job is not None
        assert job.status is JobStatus.PASSED
        assert job.video_kind == "POLISHED_VIDEO"
        assert jobs.video_path(job.id).stat().st_size > 0
        assert ArtifactWriter.verify(jobs.video_path(job.id).parent, jobs.manifest(job.id)) == ()
        assert page_errors == []
        browser.close()
