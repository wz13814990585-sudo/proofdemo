"""Product-job acceptance tests over the existing execution and render services."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from collections.abc import Iterator
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient

from proofdemo.adapters.ffmpeg_render import FFmpegRenderAdapter
from proofdemo.adapters.playwright_browser import PlaywrightBrowser
from proofdemo.api import create_app
from proofdemo.application.artifacts import ArtifactWriter
from proofdemo.application.jobs import JobBusyError, JobIntegrityError, JobManager, JobStatus
from proofdemo.config import Settings
from proofdemo.domain.demo_spec import DemoSpec, ElementTarget
from proofdemo.domain.planning import DemoIntent
from proofdemo.ports.browser import (
    AppStateObservation,
    BrowserSessionArtifacts,
    BrowserUnavailableError,
    DownloadObservation,
)
from proofdemo.ports.planner import PlannerCandidate, PlannerUnavailableError
from proofdemo.ports.render import MediaInfo, RenderSettings, RenderUnavailableError
from proofdemo.ports.video_polish import PolishRenderError

SOURCE = "https://demo.example.test/"


def make_spec(*, action: str = "Create task") -> DemoSpec:
    actions: list[dict[str, object]] = [
        {"id": "open", "type": "goto", "url": SOURCE},
        {
            "id": "act",
            "type": "click",
            "target": {"strategy": "role", "role": "button", "name": action},
        },
    ]
    if action == "credential":
        actions[1] = {
            "id": "act",
            "type": "fill",
            "target": {"strategy": "label", "label": "API key"},
            "value": "example-value",
        }
    return DemoSpec.model_validate(
        {
            "schema_version": "1.2",
            "id": "product_job_demo",
            "title": "Product job demo",
            "goal": "Show one verified action",
            "source_url": SOURCE,
            "scenes": [
                {
                    "id": "scene_one",
                    "title": "Act and verify",
                    "goal": "Verify the saved result",
                    "actions": actions,
                    "assertions": [
                        {
                            "id": "saved",
                            "type": "text_contains",
                            "target": {"strategy": "test_id", "test_id": "result"},
                            "expected_text": "Saved",
                        }
                    ],
                }
            ],
        }
    )


class Planner:
    def __init__(self, spec: DemoSpec) -> None:
        self.spec = spec

    def plan(self, intent: DemoIntent) -> PlannerCandidate:
        return PlannerCandidate(spec=self.spec, provider="fixture", model="fixture")


class Browser:
    def __init__(self) -> None:
        self.recording_dir: Path | None = None

    def open(self, source_url: str, *, recording_dir: Path | None = None) -> None:
        self.recording_dir = recording_dir

    def goto(self, url: str, *, timeout_ms: int) -> None:
        pass

    def click(self, target: ElementTarget, *, timeout_ms: int) -> None:
        pass

    def fill(self, target: ElementTarget, value: str, *, timeout_ms: int) -> None:
        pass

    def pause(self, duration_ms: int) -> None:
        pass

    def screenshot(self, path: Path, *, full_page: bool) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"preview image")

    def is_visible(self, target: ElementTarget, *, timeout_ms: int) -> bool:
        return True

    def text_content(self, target: ElementTarget, *, timeout_ms: int) -> str:
        return "Saved"

    def current_url(self) -> str:
        return SOURCE

    def completed_download(self, filename: str, *, timeout_ms: int) -> DownloadObservation:
        return DownloadObservation(filename=filename, completed=True)

    def application_state(self, key: str) -> AppStateObservation:
        return AppStateObservation(found=True, value=True)

    def close(self) -> BrowserSessionArtifacts:
        assert self.recording_dir is not None
        path = self.recording_dir / "browser.webm"
        path.write_bytes(b"fixture video")
        return BrowserSessionArtifacts(video_path=path)


class Renderer:
    def probe(self, path: Path) -> MediaInfo:
        if path.suffix == ".mp4":
            return MediaInfo(duration_ms=1000, width=1920, height=1080, fps=30, codec="h264")
        return MediaInfo(duration_ms=1000, width=1280, height=720, fps=25, codec="vp8")

    def render(self, source: Path, output: Path, settings: RenderSettings) -> None:
        assert source.is_file()
        assert settings == RenderSettings()
        output.write_bytes(b"fixture mp4")


class UnavailableBrowser(Browser):
    def open(self, source_url: str, *, recording_dir: Path | None = None) -> None:
        raise BrowserUnavailableError("Chromium unavailable")


class MismatchBrowser(Browser):
    def text_content(self, target: ElementTarget, *, timeout_ms: int) -> str:
        return "Different result"


class UnavailableRenderer(Renderer):
    def probe(self, path: Path) -> MediaInfo:
        raise RenderUnavailableError("FFmpeg unavailable")


class FailingPolisher:
    def probe(self, path: Path) -> MediaInfo:
        raise PolishRenderError("polish tool unavailable")

    def render(self, source, output, plan, artifact_dir) -> tuple[str, ...]:  # type: ignore[no-untyped-def]
        raise AssertionError("render must not start")


def manager(root: Path, spec: DemoSpec) -> JobManager:
    return JobManager(
        root,
        planner_factory=lambda: Planner(spec),
        browser_factory=Browser,
        renderer_factory=Renderer,
    )


def wait_for(manager: JobManager, job_id: UUID, expected: JobStatus, *, timeout: float = 5) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = manager.get(job_id)
        assert job is not None
        if job.status is expected:
            return
        if job.status in {JobStatus.FAILED, JobStatus.BLOCKED} and job.status is not expected:
            pytest.fail(f"job unexpectedly ended {job.status}: {job.message}")
        time.sleep(0.01)
    pytest.fail(f"job did not reach {expected}")


def test_job_creates_verified_video_and_sanitized_live_events(tmp_path: Path) -> None:
    raw = make_spec().model_dump(mode="json")
    raw["scenes"][0]["actions"].insert(
        1,
        {
            "id": "enter-title",
            "type": "fill",
            "target": {"strategy": "label", "label": "Task title"},
            "value": "demo-sentinel",
        },
    )
    jobs = manager(tmp_path, DemoSpec.model_validate(raw))
    created = jobs.create(DemoIntent(source_url=SOURCE, goal="Create and verify a task"))

    wait_for(jobs, created.id, JobStatus.PASSED)

    assert jobs.spec(created.id).id == "product_job_demo"
    assert jobs.report(created.id).verification_status == "PASSED"
    assert jobs.video_path(created.id).read_bytes() == b"fixture mp4"
    assert jobs.preview_path(created.id).read_bytes() == b"preview image"
    assert (
        ArtifactWriter.verify(tmp_path / str(created.id) / "run", jobs.manifest(created.id)) == ()
    )
    events = jobs.events_since(created.id, 0)
    assert any(event.kind == "ACTION_FINISHED" for event in events)
    assert any(event.kind == "PREVIEW_UPDATED" for event in events)
    assert [event.sequence for event in events] == list(range(1, len(events) + 1))
    assert "demo-sentinel" not in (tmp_path / str(created.id) / "events.jsonl").read_text()


def test_risky_plan_waits_for_fresh_approval(tmp_path: Path) -> None:
    jobs = manager(tmp_path, make_spec(action="Delete project"))
    created = jobs.create(DemoIntent(source_url=SOURCE, goal="Demonstrate deletion"))

    wait_for(jobs, created.id, JobStatus.AWAITING_APPROVAL)
    assert jobs.get(created.id).safety_findings  # type: ignore[union-attr]
    assert not (tmp_path / str(created.id) / "run" / "browser.webm").exists()

    jobs.approve(created.id)
    wait_for(jobs, created.id, JobStatus.PASSED)
    assessment = (tmp_path / str(created.id) / "run" / "safety_assessment.json").read_text()
    assert '"approval_acknowledged": true' in assessment


def test_credential_fill_is_blocked_without_browser(tmp_path: Path) -> None:
    jobs = manager(tmp_path, make_spec(action="credential"))
    created = jobs.create(DemoIntent(source_url=SOURCE, goal="Fill a field"))

    wait_for(jobs, created.id, JobStatus.BLOCKED)
    assert not (tmp_path / str(created.id) / "run" / "browser.webm").exists()
    assert jobs.get(created.id).safety_decision == "BLOCKED"  # type: ignore[union-attr]


def test_interrupted_approval_job_recovers_as_blocked(tmp_path: Path) -> None:
    first = manager(tmp_path, make_spec(action="Delete project"))
    created = first.create(DemoIntent(source_url=SOURCE, goal="Demonstrate deletion"))
    wait_for(first, created.id, JobStatus.AWAITING_APPROVAL)

    recovered = manager(tmp_path, make_spec())

    assert recovered.get(created.id).status is JobStatus.BLOCKED  # type: ignore[union-attr]
    assert "restart" in recovered.get(created.id).message  # type: ignore[union-attr]


def test_approval_is_bound_to_the_reviewed_spec(tmp_path: Path) -> None:
    jobs = manager(tmp_path, make_spec(action="Delete project"))
    created = jobs.create(DemoIntent(source_url=SOURCE, goal="Demonstrate deletion"))
    wait_for(jobs, created.id, JobStatus.AWAITING_APPROVAL)
    path = tmp_path / str(created.id) / "demo_spec.json"
    changed = json.loads(path.read_text(encoding="utf-8"))
    changed["scenes"][0]["actions"][1]["target"]["name"] = "Delete workspace"
    path.write_text(json.dumps(changed), encoding="utf-8")

    jobs.approve(created.id)
    wait_for(jobs, created.id, JobStatus.BLOCKED)

    assert not (tmp_path / str(created.id) / "run" / "browser.webm").exists()


def test_recovery_discards_partial_event_tail_without_losing_job(tmp_path: Path) -> None:
    first = manager(tmp_path, make_spec(action="Delete project"))
    created = first.create(DemoIntent(source_url=SOURCE, goal="Demonstrate deletion"))
    wait_for(first, created.id, JobStatus.AWAITING_APPROVAL)
    events_path = tmp_path / str(created.id) / "events.jsonl"
    with events_path.open("a", encoding="utf-8") as stream:
        stream.write('{"sequence":')

    recovered = manager(tmp_path, make_spec())

    assert recovered.get(created.id).status is JobStatus.BLOCKED  # type: ignore[union-attr]
    events = recovered.events_since(created.id, 0)
    assert events[-1].kind == "JOB_STATUS"
    assert len(events_path.read_text(encoding="utf-8").splitlines()) == len(events)


def test_single_local_job_slot_rejects_concurrent_request(tmp_path: Path) -> None:
    jobs = manager(tmp_path, make_spec(action="Delete project"))
    jobs.create(DemoIntent(source_url=SOURCE, goal="One"))
    with pytest.raises(JobBusyError):
        jobs.create(DemoIntent(source_url=SOURCE, goal="Two"))


def test_missing_planner_is_explicitly_blocked(tmp_path: Path) -> None:
    def unavailable() -> Planner:
        raise PlannerUnavailableError("no model configured")

    jobs = JobManager(tmp_path, planner_factory=unavailable)
    created = jobs.create(DemoIntent(source_url=SOURCE, goal="Create a task"))

    wait_for(jobs, created.id, JobStatus.BLOCKED)
    assert "PROOFDEMO_OPENAI_MODEL" in jobs.get(created.id).message  # type: ignore[union-attr]


def test_unavailable_browser_keeps_job_blocked_without_video(tmp_path: Path) -> None:
    jobs = JobManager(
        tmp_path,
        planner_factory=lambda: Planner(make_spec()),
        browser_factory=UnavailableBrowser,
        renderer_factory=Renderer,
    )
    created = jobs.create(DemoIntent(source_url=SOURCE, goal="Create a task"))

    wait_for(jobs, created.id, JobStatus.BLOCKED)

    assert jobs.report(created.id).run.status == "BLOCKED"
    assert not (tmp_path / str(created.id) / "run" / "demo.mp4").exists()


def test_failed_assertion_does_not_render_video(tmp_path: Path) -> None:
    jobs = JobManager(
        tmp_path,
        planner_factory=lambda: Planner(make_spec()),
        browser_factory=MismatchBrowser,
        renderer_factory=Renderer,
    )
    created = jobs.create(DemoIntent(source_url=SOURCE, goal="Create a task"))

    wait_for(jobs, created.id, JobStatus.FAILED)

    assert jobs.report(created.id).verification_status == "FAILED"
    assert not (tmp_path / str(created.id) / "run" / "demo.mp4").exists()


def test_unavailable_renderer_preserves_verified_report_but_blocks_delivery(
    tmp_path: Path,
) -> None:
    jobs = JobManager(
        tmp_path,
        planner_factory=lambda: Planner(make_spec()),
        browser_factory=Browser,
        renderer_factory=UnavailableRenderer,
    )
    created = jobs.create(DemoIntent(source_url=SOURCE, goal="Create a task"))

    wait_for(jobs, created.id, JobStatus.BLOCKED)

    assert jobs.report(created.id).verification_status == "PASSED"
    assert "FFmpeg" in jobs.get(created.id).message  # type: ignore[union-attr]
    assert not (tmp_path / str(created.id) / "run" / "demo.mp4").exists()


def test_polish_failure_keeps_verified_source_but_blocks_product_delivery(
    tmp_path: Path,
) -> None:
    jobs = JobManager(
        tmp_path,
        planner_factory=lambda: Planner(make_spec()),
        browser_factory=Browser,
        renderer_factory=Renderer,
        polisher_factory=FailingPolisher,
    )
    created = jobs.create(DemoIntent(source_url=SOURCE, goal="Create a task"))

    wait_for(jobs, created.id, JobStatus.BLOCKED)

    assert jobs.report(created.id).verification_status == "PASSED"
    assert (tmp_path / str(created.id) / "run" / "demo.mp4").exists()
    assert not (tmp_path / str(created.id) / "run" / "polished_demo.mp4").exists()
    with pytest.raises(JobIntegrityError, match="no verified final video"):
        jobs.video_path(created.id)


@pytest.mark.parametrize("target", ["demo.mp4", "timeline.json"])
def test_polish_refuses_source_or_timeline_tampering(tmp_path: Path, target: str) -> None:
    def tamper_then_polish() -> FailingPolisher:
        job_dir = next(path for path in tmp_path.iterdir() if path.is_dir())
        (job_dir / "run" / target).write_bytes(b"tampered")
        return FailingPolisher()

    jobs = JobManager(
        tmp_path,
        planner_factory=lambda: Planner(make_spec()),
        browser_factory=Browser,
        renderer_factory=Renderer,
        polisher_factory=tamper_then_polish,
    )
    created = jobs.create(DemoIntent(source_url=SOURCE, goal="Create a task"))

    wait_for(jobs, created.id, JobStatus.BLOCKED)
    assert not (tmp_path / str(created.id) / "run" / "polished_demo.mp4").exists()


def test_interrupted_polish_recovers_as_blocked(tmp_path: Path) -> None:
    first = manager(tmp_path, make_spec(action="Delete project"))
    created = first.create(DemoIntent(source_url=SOURCE, goal="Demonstrate deletion"))
    wait_for(first, created.id, JobStatus.AWAITING_APPROVAL)
    path = tmp_path / str(created.id) / "job.json"
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    snapshot["status"] = "POLISHING"
    path.write_text(json.dumps(snapshot), encoding="utf-8")

    recovered = manager(tmp_path, make_spec())

    assert recovered.get(created.id).status is JobStatus.BLOCKED  # type: ignore[union-attr]
    assert "restart" in recovered.get(created.id).message  # type: ignore[union-attr]


def test_tampered_video_cannot_be_served_as_verified(tmp_path: Path) -> None:
    jobs = manager(tmp_path, make_spec())
    created = jobs.create(DemoIntent(source_url=SOURCE, goal="Create a task"))
    wait_for(jobs, created.id, JobStatus.PASSED)
    video = tmp_path / str(created.id) / "run" / "demo.mp4"
    video.write_bytes(b"tampered")

    with pytest.raises(JobIntegrityError, match="changed"):
        jobs.video_path(created.id)
    with pytest.raises(JobIntegrityError, match="changed"):
        jobs.report(created.id)

    app = create_app(Settings(environment="test", job_root=tmp_path), jobs)

    async def check() -> None:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            assert (await client.get(f"/jobs/{created.id}/video")).status_code == 409
            assert (await client.get(f"/jobs/{created.id}/manifest")).status_code == 409

    asyncio.run(check())


def test_api_creates_job_and_serves_verified_artifacts(tmp_path: Path) -> None:
    jobs = manager(tmp_path, make_spec())
    app = create_app(Settings(environment="test", job_root=tmp_path), jobs)

    async def exercise() -> None:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/jobs",
                json={"source_url": SOURCE, "goal": "Create a task"},
                headers={"X-ProofDemo-Client": "studio"},
            )
            assert response.status_code == 202
            job_id = response.json()["id"]
            wait_for(jobs, UUID(job_id), JobStatus.PASSED)
            assert (await client.get(f"/jobs/{job_id}/spec")).status_code == 200
            assert (await client.get(f"/jobs/{job_id}/report")).json()[
                "verification_status"
            ] == "PASSED"
            assert (await client.get(f"/jobs/{job_id}/manifest")).status_code == 200
            assert (await client.get(f"/jobs/{job_id}/preview")).content == b"preview image"
            assert (await client.get(f"/jobs/{job_id}/video")).content == b"fixture mp4"
            events = await client.get(f"/jobs/{job_id}/events")
            assert "ACTION_FINISHED" in events.text
            event_log = await client.get(f"/jobs/{job_id}/event-log")
            assert any(item["kind"] == "ACTION_FINISHED" for item in event_log.json())

    asyncio.run(exercise())


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass


@pytest.fixture
def todo_url() -> Iterator[str]:
    root = Path(__file__).resolve().parents[1] / "examples" / "todo_app"
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(root)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}/"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_real_todo_job_runs_browser_verification_and_ffmpeg(todo_url: str, tmp_path: Path) -> None:
    example = Path(__file__).resolve().parents[1] / "examples" / "demo_spec.json"
    raw = json.loads(example.read_text(encoding="utf-8"))
    raw["source_url"] = todo_url
    raw["scenes"][0]["actions"][0]["url"] = todo_url
    for assertion in raw["scenes"][0]["assertions"]:
        if assertion["type"] == "url_equals":
            assertion["expected_url"] = todo_url
    spec = DemoSpec.model_validate(raw)
    jobs = JobManager(
        tmp_path,
        planner_factory=lambda: Planner(spec),
        browser_factory=PlaywrightBrowser,
        renderer_factory=FFmpegRenderAdapter,
    )
    created = jobs.create(DemoIntent(source_url=todo_url, goal="Create a launch task"))

    wait_for(jobs, created.id, JobStatus.PASSED, timeout=50)

    assert jobs.report(created.id).verification_status == "PASSED"
    assert jobs.preview_path(created.id).stat().st_size > 0
    assert jobs.video_path(created.id).stat().st_size > 0
    assert (
        ArtifactWriter.verify(tmp_path / str(created.id) / "run", jobs.manifest(created.id)) == ()
    )
