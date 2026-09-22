"""Real Chromium and FFmpeg acceptance for two structurally different sites."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from collections.abc import Iterator
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from proofdemo.adapters.ffmpeg_polish import FFmpegVideoPolisher
from proofdemo.adapters.playwright_explorer import PlaywrightExplorer
from proofdemo.api import create_app
from proofdemo.application.jobs import JobIntegrityError, JobManager, JobStatus
from proofdemo.config import Settings
from proofdemo.domain.demo_spec import DemoSpec
from proofdemo.domain.exploration import ExplorationReport
from proofdemo.domain.planning import DemoIntent
from proofdemo.ports.planner import PlannerCandidate

ROOT = Path(__file__).resolve().parents[1]


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass


@pytest.fixture(params=["todo_app", "notes_app"])
def local_site(request: pytest.FixtureRequest) -> Iterator[tuple[str, str]]:
    name = str(request.param)
    handler = partial(QuietHandler, directory=str(ROOT / "examples" / name))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield name, f"http://{host}:{port}/"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


class LinkAdvisor:
    def choose(self, intent: DemoIntent, pages: tuple, candidates: tuple[str, ...]) -> str | None:
        return next((url for url in candidates if url.endswith("compose.html")), None)


class GroundedFixturePlanner:
    def __init__(self, name: str) -> None:
        self.name = name
        self.seen_report: ExplorationReport | None = None

    def plan(self, intent: DemoIntent) -> PlannerCandidate:
        raise AssertionError("product workflow must use grounded planning")

    def plan_grounded(self, intent: DemoIntent, report: ExplorationReport) -> PlannerCandidate:
        self.seen_report = report
        source = str(intent.source_url)
        if self.name == "notes_app":
            assert len(report.pages) == 2
            actions: list[dict[str, object]] = [
                {"id": "open", "type": "goto", "url": source},
                {
                    "id": "navigate",
                    "type": "click",
                    "target": {"strategy": "role", "role": "link", "name": "Write a note"},
                },
                {
                    "id": "title",
                    "type": "fill",
                    "target": {"strategy": "label", "label": "Note title"},
                    "value": "Sprint status",
                },
                {
                    "id": "publish",
                    "type": "click",
                    "target": {"strategy": "role", "role": "button", "name": "Publish note"},
                },
            ]
            target = "published-note"
            expected = "Sprint status"
        else:
            assert len(report.pages) == 1
            actions = [
                {"id": "open", "type": "goto", "url": source},
                {
                    "id": "title",
                    "type": "fill",
                    "target": {"strategy": "label", "label": "Task title"},
                    "value": "Launch update",
                },
                {
                    "id": "add",
                    "type": "click",
                    "target": {"strategy": "role", "role": "button", "name": "Add task"},
                },
            ]
            target = "task-list"
            expected = "Launch update"
        spec = DemoSpec.model_validate(
            {
                "schema_version": "1.2",
                "id": "grounded_fixture",
                "title": "Grounded fixture demo",
                "goal": intent.goal,
                "source_url": source,
                "scenes": [
                    {
                        "id": "main",
                        "title": "Create and verify",
                        "goal": intent.goal,
                        "actions": actions,
                        "assertions": [
                            {
                                "id": "created",
                                "type": "text_contains",
                                "target": {"strategy": "test_id", "test_id": target},
                                "expected_text": expected,
                            }
                        ],
                    }
                ],
            }
        )
        return PlannerCandidate(spec=spec, provider="fixture", model="fixture")


def test_grounded_job_reaches_verified_video_on_distinct_sites(
    local_site: tuple[str, str], tmp_path: Path
) -> None:
    name, url = local_site
    planner = GroundedFixturePlanner(name)
    jobs = JobManager(
        tmp_path,
        planner_factory=lambda: planner,
        explorer_factory=PlaywrightExplorer,
        advisor_factory=LinkAdvisor,
    )
    created = jobs.create(DemoIntent(source_url=url, goal="Create one item and verify it"))
    deadline = time.monotonic() + 45
    approved = False
    while time.monotonic() < deadline:
        job = jobs.get(created.id)
        assert job is not None
        if job.status is JobStatus.AWAITING_APPROVAL and not approved:
            assert job.safety_findings
            jobs.approve(created.id)
            approved = True
        if job.status in {JobStatus.PASSED, JobStatus.FAILED, JobStatus.BLOCKED}:
            break
        time.sleep(0.05)
    job = jobs.get(created.id)
    assert job is not None
    assert job.status is JobStatus.PASSED, job.message
    assert planner.seen_report is not None
    assert job.exploration_status in {"COMPLETE", "PARTIAL"}
    assert jobs.grounding(created.id).status == "GROUNDED"
    assert jobs.report(created.id).verification_status == "PASSED"
    assert jobs.video_path(created.id).stat().st_size > 0
    assert jobs.exploration_preview_path(created.id).stat().st_size > 0
    assert any(event.kind == "PAGE_OBSERVED" for event in jobs.events_since(created.id, 0))

    async def read_api() -> tuple[int, int, int]:
        app = create_app(Settings(environment="test", job_root=tmp_path), jobs)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            exploration = await client.get(f"/jobs/{created.id}/exploration")
            grounding = await client.get(f"/jobs/{created.id}/grounding")
            preview = await client.get(f"/jobs/{created.id}/exploration-preview")
        return exploration.status_code, grounding.status_code, preview.status_code

    assert asyncio.run(read_api()) == (200, 200, 200)

    preview_path = jobs.exploration_preview_path(created.id)
    preview_path.write_bytes(b"tampered preview")
    with pytest.raises(JobIntegrityError, match="preview changed"):
        jobs.exploration_preview_path(created.id)


def test_changed_exploration_report_blocks_approved_execution(
    local_site: tuple[str, str], tmp_path: Path
) -> None:
    name, url = local_site
    if name != "notes_app":
        return
    jobs = JobManager(
        tmp_path,
        planner_factory=lambda: GroundedFixturePlanner(name),
        explorer_factory=PlaywrightExplorer,
        advisor_factory=LinkAdvisor,
    )
    created = jobs.create(DemoIntent(source_url=url, goal="Publish a note"))
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        current = jobs.get(created.id)
        assert current is not None
        if current.status is JobStatus.AWAITING_APPROVAL:
            break
        if current.status is JobStatus.BLOCKED:
            pytest.fail(current.message)
        time.sleep(0.05)
    else:
        pytest.fail("approval state not reached")

    report_path = tmp_path / str(created.id) / "exploration_report.json"
    report_path.write_text("{}", encoding="utf-8")
    jobs.approve(created.id)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        current = jobs.get(created.id)
        if current is not None and current.status is JobStatus.BLOCKED:
            break
        time.sleep(0.05)
    assert jobs.get(created.id).status is JobStatus.BLOCKED  # type: ignore[union-attr]
    assert not (tmp_path / str(created.id) / "run" / "browser.webm").exists()


def test_product_job_delivers_polished_video_after_verified_render(
    local_site: tuple[str, str], tmp_path: Path
) -> None:
    name, url = local_site
    jobs = JobManager(
        tmp_path,
        planner_factory=lambda: GroundedFixturePlanner(name),
        explorer_factory=PlaywrightExplorer,
        advisor_factory=LinkAdvisor,
        polisher_factory=FFmpegVideoPolisher,
    )
    created = jobs.create(DemoIntent(source_url=url, goal="Create one item and verify it"))
    deadline = time.monotonic() + 90
    approved = False
    while time.monotonic() < deadline:
        job = jobs.get(created.id)
        assert job is not None
        if job.status is JobStatus.AWAITING_APPROVAL and not approved:
            jobs.approve(created.id)
            approved = True
        if job.status in {JobStatus.PASSED, JobStatus.FAILED, JobStatus.BLOCKED}:
            break
        time.sleep(0.05)
    job = jobs.get(created.id)
    assert job is not None
    assert job.status is JobStatus.PASSED, job.message
    assert job.video_kind == "POLISHED_VIDEO"
    assert jobs.video_path(created.id).name == "polished_demo.mp4"
    assert (tmp_path / str(created.id) / "run" / "demo.mp4").is_file()
    assert (tmp_path / str(created.id) / "run" / "polish_captions.json").is_file()
    polish_plan = json.loads((tmp_path / str(created.id) / "run" / "polish_plan.json").read_text())
    assert polish_plan["focus_cues"]
    app = create_app(Settings(environment="test", job_root=tmp_path), jobs)

    async def check_plan_api() -> None:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/jobs/{created.id}/polish-plan")
            assert response.status_code == 200
            assert response.json()["source_sha256"] == polish_plan["source_sha256"]

    asyncio.run(check_plan_api())
    plan_path = tmp_path / str(created.id) / "run" / "polish_plan.json"
    plan_path.write_bytes(b"tampered")

    async def check_tamper_gate() -> None:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            assert (await client.get(f"/jobs/{created.id}/polish-plan")).status_code == 409
            assert (await client.get(f"/jobs/{created.id}/video")).status_code == 409

    asyncio.run(check_tamper_gate())
