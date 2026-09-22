"""Stage 12 read-only exploration and grounded planning boundaries."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from openai import OpenAIError

from proofdemo.adapters.openai_exploration import LinkChoice, OpenAILinkAdvisor
from proofdemo.adapters.openai_planner import OpenAIPlanner
from proofdemo.application.exploration import ExplorationService, safe_exploration_url
from proofdemo.application.grounding import GroundingService
from proofdemo.application.jobs import JobManager, JobRecord, JobStatus
from proofdemo.domain.demo_spec import DemoSpec, LabelTarget, RoleTarget
from proofdemo.domain.exploration import ExplorationReport, ExplorationStatus
from proofdemo.domain.planning import DemoIntent
from proofdemo.ports.browser import BrowserUnavailableError
from proofdemo.ports.explorer import (
    ControlSnapshot,
    ExplorationUnavailableError,
    InvalidLinkAdvice,
    PageSnapshot,
)
from proofdemo.ports.planner import PlannerCandidate, PlannerUnavailableError

SOURCE = "https://product.example.test/"
DETAIL = "https://product.example.test/create"


class Browser:
    def __init__(self) -> None:
        self.visits: list[str] = []
        self.closed = False

    def open(self, source_url: str) -> None:
        assert source_url == SOURCE

    def visit(self, url: str, *, screenshot_path: Path, timeout_ms: int) -> PageSnapshot:
        self.visits.append(url)
        assert 0 < timeout_ms <= 15_000
        screenshot_path.write_bytes(b"image")
        if url == SOURCE:
            return PageSnapshot(
                url=url,
                title="Product",
                headings=("Welcome",),
                controls=(
                    ControlSnapshot(
                        "link",
                        "Create",
                        RoleTarget(strategy="role", role="link", name="Create"),
                        DETAIL,
                    ),
                    ControlSnapshot("link", "Delete", href=f"{SOURCE}delete/account"),
                    ControlSnapshot("link", "Remote", href="https://other.example.test/"),
                ),
            )
        return PageSnapshot(
            url=url,
            title="Create",
            headings=("Compose",),
            controls=(
                ControlSnapshot("input", "Title", LabelTarget(strategy="label", label="Title")),
                ControlSnapshot(
                    "button", "Save", RoleTarget(strategy="role", role="button", name="Save")
                ),
            ),
        )

    def close(self) -> None:
        self.closed = True


class Advisor:
    def __init__(self, choice: str | None) -> None:
        self.choice = choice
        self.candidates: tuple[str, ...] = ()

    def choose(self, intent: DemoIntent, pages: tuple, candidates: tuple[str, ...]) -> str | None:
        self.candidates = candidates
        return self.choice


def intent() -> DemoIntent:
    return DemoIntent(source_url=SOURCE, goal="Create an item")


def grounded_spec(*, target: str = "Save", navigation: str = DETAIL) -> DemoSpec:
    return DemoSpec.model_validate(
        {
            "schema_version": "1.2",
            "id": "grounded_example",
            "title": "Create an item",
            "goal": "Create one item",
            "source_url": SOURCE,
            "scenes": [
                {
                    "id": "compose",
                    "title": "Compose",
                    "goal": "Save one item",
                    "actions": [
                        {"id": "open", "type": "goto", "url": SOURCE},
                        {"id": "navigate", "type": "goto", "url": navigation},
                        {
                            "id": "title",
                            "type": "fill",
                            "target": {"strategy": "label", "label": "Title"},
                            "value": "Launch update",
                        },
                        {
                            "id": "save",
                            "type": "click",
                            "target": {"strategy": "role", "role": "button", "name": target},
                        },
                    ],
                    "assertions": [{"id": "url", "type": "url_equals", "expected_url": navigation}],
                }
            ],
        }
    )


def source_only_spec() -> DemoSpec:
    return DemoSpec.model_validate(
        {
            "schema_version": "1.2",
            "id": "source_only",
            "title": "Observe the product",
            "goal": "Show the visited page",
            "source_url": SOURCE,
            "scenes": [
                {
                    "id": "home",
                    "title": "Product home",
                    "goal": "Show the home page",
                    "actions": [{"id": "open", "type": "goto", "url": SOURCE}],
                    "assertions": [{"id": "url", "type": "url_equals", "expected_url": SOURCE}],
                }
            ],
        }
    )


@pytest.mark.parametrize(
    "candidate",
    [
        "https://other.example.test/",
        "https://product.example.test/logout",
        "https://product.example.test/delete/account",
        "https://product.example.test/report.pdf",
        "https://product.example.test/?api_key=secret",
        "https://user:password@product.example.test/",
    ],
)
def test_unsafe_links_are_never_admitted(candidate: str) -> None:
    assert safe_exploration_url(SOURCE, candidate) is None


def test_only_observed_safe_link_can_be_visited(tmp_path: Path) -> None:
    browser = Browser()
    advisor = Advisor(DETAIL)
    service = ExplorationService(browser, advisor)

    report = service.explore(intent(), tmp_path)
    path = service.write(report, tmp_path)

    assert report.status is ExplorationStatus.COMPLETE
    assert browser.visits == [SOURCE, DETAIL]
    assert browser.closed
    assert advisor.candidates == (DETAIL,)
    assert len(report.pages) == 2
    assert [control.name for control in report.pages[0].controls] == ["Create"]
    assert str(report.pages[1].discovered_from) == SOURCE
    assert ExplorationReport.model_validate_json(path.read_text()) == report
    assert "Launch update" not in path.read_text()


def test_invalid_advisor_choice_blocks_without_visiting_it(tmp_path: Path) -> None:
    browser = Browser()
    report = ExplorationService(browser, Advisor(f"{SOURCE}invented")).explore(intent(), tmp_path)

    assert report.status is ExplorationStatus.BLOCKED
    assert browser.visits == [SOURCE]
    assert report.unvisited_link_count == 1
    assert "unobserved" in report.warnings[0]


def test_invalid_structured_link_advice_is_partial_and_keeps_grounding(
    tmp_path: Path,
) -> None:
    class InvalidAdvisor:
        def choose(
            self, intent: DemoIntent, pages: tuple, candidates: tuple[str, ...]
        ) -> str | None:
            raise InvalidLinkAdvice("provider-secret-detail")

    browser = Browser()
    report = ExplorationService(browser, InvalidAdvisor()).explore(intent(), tmp_path)

    assert report.status is ExplorationStatus.PARTIAL
    assert browser.visits == [SOURCE]
    assert browser.closed
    assert report.unvisited_link_count == 1
    assert "remaining safe links were not visited" in report.warnings[0]
    assert "provider-secret-detail" not in str(report.warnings)
    assert GroundingService.assess(source_only_spec(), report).status == "GROUNDED"
    assert GroundingService.assess(grounded_spec(), report).status == "BLOCKED"


def test_link_advisor_request_failure_still_blocks_exploration(tmp_path: Path) -> None:
    class UnavailableAdvisor:
        def choose(
            self, intent: DemoIntent, pages: tuple, candidates: tuple[str, ...]
        ) -> str | None:
            raise ExplorationUnavailableError("link advisor request failed")

    browser = Browser()
    report = ExplorationService(browser, UnavailableAdvisor()).explore(intent(), tmp_path)

    assert report.status is ExplorationStatus.BLOCKED
    assert browser.visits == [SOURCE]
    assert report.unvisited_link_count == 1


def test_partial_exploration_continues_to_planning(tmp_path: Path) -> None:
    class InvalidAdvisor:
        def choose(
            self, intent: DemoIntent, pages: tuple, candidates: tuple[str, ...]
        ) -> str | None:
            raise InvalidLinkAdvice("malformed link choice")

    class PartialPlanner:
        def plan_grounded(self, intent: DemoIntent, report: ExplorationReport) -> PlannerCandidate:
            assert report.status is ExplorationStatus.PARTIAL
            assert len(report.pages) == 1
            return PlannerCandidate(spec=source_only_spec(), provider="fixture", model="fixture")

    class NoExecutionBrowser:
        def open(self, source_url: str, *, recording_dir: Path | None = None) -> None:
            raise BrowserUnavailableError("fixture execution stop")

        def close(self) -> None:
            pass

    jobs = JobManager(
        tmp_path,
        planner_factory=PartialPlanner,
        explorer_factory=Browser,
        advisor_factory=InvalidAdvisor,
        browser_factory=NoExecutionBrowser,
    )
    created = jobs.create(intent())
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job = jobs.get(created.id)
        if job is not None and job.status in {
            JobStatus.PASSED,
            JobStatus.FAILED,
            JobStatus.BLOCKED,
        }:
            break
        time.sleep(0.01)

    job = jobs.get(created.id)
    assert job is not None
    assert job.status is JobStatus.BLOCKED
    assert "Exploration could not ground" not in job.message
    assert jobs.exploration(created.id).status is ExplorationStatus.PARTIAL
    assert jobs.grounding(created.id).status == "GROUNDED"
    assert jobs.spec(created.id) == source_only_spec()


def test_budget_exhaustion_is_partial(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ExplorationService, "MAX_PAGES", 1)
    report = ExplorationService(Browser(), Advisor(DETAIL)).explore(intent(), tmp_path)

    assert report.status is ExplorationStatus.PARTIAL
    assert report.unvisited_link_count == 1


def test_missing_page_screenshot_blocks_exploration(tmp_path: Path) -> None:
    class NoScreenshot(Browser):
        def visit(self, url: str, *, screenshot_path: Path, timeout_ms: int) -> PageSnapshot:
            return PageSnapshot(url=url, title="No image", headings=(), controls=())

    report = ExplorationService(NoScreenshot(), Advisor(None)).explore(intent(), tmp_path)

    assert report.status is ExplorationStatus.BLOCKED
    assert "screenshot" in report.warnings[0]


def test_grounding_links_every_interactive_action_to_observed_control(tmp_path: Path) -> None:
    report = ExplorationService(Browser(), Advisor(DETAIL)).explore(intent(), tmp_path)
    result = GroundingService.assess(grounded_spec(), report)

    assert result.status == "GROUNDED"
    assert [item.control_id for item in result.checks] == [
        None,
        None,
        "page-2-control-1",
        "page-2-control-2",
    ]


def test_grounding_blocks_fabricated_control_and_unvisited_page(tmp_path: Path) -> None:
    report = ExplorationService(Browser(), Advisor(DETAIL)).explore(intent(), tmp_path)

    fabricated = GroundingService.assess(grounded_spec(target="Export secrets"), report)
    unvisited = GroundingService.assess(grounded_spec(navigation=f"{SOURCE}invented"), report)

    assert fabricated.status == "BLOCKED"
    assert fabricated.checks[-1].reason == "action target was not observed"
    assert unvisited.status == "BLOCKED"
    assert unvisited.checks[1].reason == "navigation page was not visited"


class FakeResponses:
    def __init__(self, parsed: object) -> None:
        self.parsed = parsed
        self.kwargs: dict[str, Any] = {}

    def parse(self, **kwargs: Any) -> SimpleNamespace:
        self.kwargs = kwargs
        return SimpleNamespace(output_parsed=self.parsed)


def test_model_link_choice_is_tool_free_and_non_persisted(tmp_path: Path) -> None:
    report = ExplorationService(Browser(), Advisor(None)).explore(intent(), tmp_path)
    client = SimpleNamespace(responses=FakeResponses(LinkChoice(url=DETAIL)))

    choice = OpenAILinkAdvisor("explicit-model", client=client).choose(
        intent(), report.pages, (DETAIL,)
    )

    assert choice == DETAIL
    assert client.responses.kwargs["text_format"] is LinkChoice
    assert client.responses.kwargs["store"] is False
    assert "tools" not in client.responses.kwargs
    assert "Launch update" not in client.responses.kwargs["input"]


def test_grounded_planner_receives_report_not_browser_authority(tmp_path: Path) -> None:
    report = ExplorationService(Browser(), Advisor(DETAIL)).explore(intent(), tmp_path)
    candidate = grounded_spec()
    client = SimpleNamespace(responses=FakeResponses(candidate))

    result = OpenAIPlanner("explicit-model", client=client).plan_grounded(intent(), report)

    assert result.spec == candidate
    assert client.responses.kwargs["text_format"] is DemoSpec
    assert client.responses.kwargs["store"] is False
    assert "tools" not in client.responses.kwargs
    assert "exploration" in client.responses.kwargs["input"]


def test_link_advisor_hides_provider_error_details() -> None:
    class FailingResponses:
        def parse(self, **kwargs: object) -> None:
            raise OpenAIError("provider-secret-detail")

    with pytest.raises(ExplorationUnavailableError, match="advisor request failed") as caught:
        advisor = OpenAILinkAdvisor(
            "explicit-model", client=SimpleNamespace(responses=FailingResponses())
        )
        advisor.choose(intent(), (), (DETAIL,))
    assert "provider-secret-detail" not in str(caught.value)


def test_missing_model_blocks_before_browser_visit(tmp_path: Path) -> None:
    browser = Browser()

    def unavailable() -> None:
        raise PlannerUnavailableError("no model configured")

    jobs = JobManager(
        tmp_path,
        planner_factory=unavailable,  # type: ignore[arg-type]
        explorer_factory=lambda: browser,
        advisor_factory=lambda: Advisor(None),
    )
    created = jobs.create(intent())
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        job = jobs.get(created.id)
        if job is not None and job.status is JobStatus.BLOCKED:
            break
        time.sleep(0.01)

    assert jobs.get(created.id).status is JobStatus.BLOCKED  # type: ignore[union-attr]
    assert browser.visits == []


def test_interrupted_exploration_recovers_as_blocked(tmp_path: Path) -> None:
    job_id = uuid4()
    directory = tmp_path / str(job_id)
    directory.mkdir()
    now = datetime.now(UTC)
    snapshot = JobRecord(
        id=job_id,
        status=JobStatus.EXPLORING,
        created_at=now,
        updated_at=now,
        message="Observing product pages",
        exploration_page_count=1,
    )
    (directory / "job.json").write_text(snapshot.model_dump_json())

    recovered = JobManager(tmp_path, planner_factory=unavailable_planner)

    assert recovered.get(job_id).status is JobStatus.BLOCKED  # type: ignore[union-attr]
    assert recovered.events_since(job_id, 0)[-1].status == "BLOCKED"


def unavailable_planner() -> None:
    raise PlannerUnavailableError("not called")
