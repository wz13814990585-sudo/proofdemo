"""Provider-scoped DeepSeek routing without real credentials or network calls."""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from openai import OpenAIError

from proofdemo.adapters import deepseek
from proofdemo.adapters.deepseek import DeepSeekLinkAdvisor, DeepSeekPlanner
from proofdemo.adapters.openai_exploration import LinkChoice
from proofdemo.application.jobs import JobManager, JobStatus
from proofdemo.cli import EXIT_BLOCKED, EXIT_EXECUTED, run
from proofdemo.config import Settings
from proofdemo.domain.demo_spec import DemoSpec
from proofdemo.domain.exploration import ExplorationReport, ExplorationStatus, PageObservation
from proofdemo.domain.planning import DemoIntent
from proofdemo.ports.planner import PlannerCandidate, PlannerUnavailableError

SOURCE = "https://product.example.test/"


def spec() -> DemoSpec:
    return DemoSpec.model_validate(
        {
            "schema_version": "1.2",
            "id": "deepseek_fixture",
            "title": "Create a task",
            "goal": "Create one task",
            "source_url": SOURCE,
            "scenes": [
                {
                    "id": "main",
                    "title": "Create task",
                    "goal": "Add one task",
                    "actions": [{"id": "open", "type": "goto", "url": SOURCE}],
                    "assertions": [
                        {
                            "id": "visible",
                            "type": "element_visible",
                            "target": {"strategy": "test_id", "test_id": "task-list"},
                        }
                    ],
                }
            ],
        }
    )


def test_deepseek_uses_only_its_scoped_key_and_fixed_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constructor_calls: list[dict[str, Any]] = []
    requests: list[dict[str, Any]] = []

    class FakeResponses:
        def parse(self, **kwargs: Any) -> SimpleNamespace:
            requests.append(kwargs)
            parsed = spec() if kwargs["text_format"] is DemoSpec else LinkChoice(url=SOURCE)
            return SimpleNamespace(output_parsed=parsed)

    def fake_client(**kwargs: Any) -> SimpleNamespace:
        constructor_calls.append(kwargs)
        return SimpleNamespace(responses=FakeResponses())

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only-deepseek-key")
    monkeypatch.setenv("OPENAI_API_KEY", "wrong-provider-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://wrong-provider.example.test")
    monkeypatch.setattr(deepseek, "OpenAI", fake_client)
    intent = DemoIntent(source_url=SOURCE, goal="Create one task")

    candidate = DeepSeekPlanner("deepseek-flash").plan(intent)
    choice = DeepSeekLinkAdvisor("deepseek-flash").choose(intent, (), (SOURCE,))

    assert candidate.provider == "deepseek"
    assert candidate.model == "deepseek-flash"
    assert candidate.spec == spec()
    assert choice == SOURCE
    assert all(call["api_key"] == "test-only-deepseek-key" for call in constructor_calls)
    assert all(call["base_url"] == "https://api.deepseek.com" for call in constructor_calls)
    assert all(call["store"] is False and "tools" not in call for call in requests)
    assert all("test-only-deepseek-key" not in str(call["input"]) for call in requests)


def test_deepseek_grounded_plan_keeps_provider_label_and_evidence_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[dict[str, Any]] = []

    class FakeResponses:
        def parse(self, **kwargs: Any) -> SimpleNamespace:
            requests.append(kwargs)
            return SimpleNamespace(output_parsed=spec())

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only-deepseek-key")
    monkeypatch.setattr(
        deepseek,
        "OpenAI",
        lambda **kwargs: SimpleNamespace(responses=FakeResponses()),
    )
    intent = DemoIntent(source_url=SOURCE, goal="Create one task")
    report = ExplorationReport(
        source_url=SOURCE,
        status=ExplorationStatus.COMPLETE,
        pages=(PageObservation(url=SOURCE, title="Tasks", headings=(), controls=()),),
        warnings=(),
        unvisited_link_count=0,
    )

    candidate = DeepSeekPlanner("deepseek-flash").plan_grounded(intent, report)

    assert candidate.provider == "deepseek"
    assert "exploration" in requests[0]["input"]
    assert requests[0]["text_format"] is DemoSpec
    assert requests[0]["store"] is False


def test_deepseek_requires_new_local_key_and_explicit_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "not-a-deepseek-key")

    with pytest.raises(PlannerUnavailableError, match="DEEPSEEK_API_KEY"):
        DeepSeekPlanner("deepseek-flash")
    with pytest.raises(PlannerUnavailableError, match="PROOFDEMO_DEEPSEEK_MODEL"):
        DeepSeekPlanner(" ")


def test_deepseek_provider_error_never_reveals_remote_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingResponses:
        def parse(self, **kwargs: Any) -> None:
            raise OpenAIError("provider-secret-detail")

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only-deepseek-key")
    monkeypatch.setattr(
        deepseek,
        "OpenAI",
        lambda **kwargs: SimpleNamespace(responses=FailingResponses()),
    )
    with pytest.raises(PlannerUnavailableError, match="planner request failed") as caught:
        DeepSeekPlanner("deepseek-flash").plan(
            DemoIntent(source_url=SOURCE, goal="Create one task")
        )
    assert "provider-secret-detail" not in str(caught.value)


def test_product_settings_route_to_deepseek_and_block_before_browser_without_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    settings = Settings(
        environment="test",
        job_root=tmp_path,
        planner_provider="deepseek",
        deepseek_model="deepseek-flash",
    )
    jobs = JobManager.from_settings(settings)
    created = jobs.create(DemoIntent(source_url=SOURCE, goal="Create one task"))
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        job = jobs.get(created.id)
        if job is not None and job.status is JobStatus.BLOCKED:
            break
        time.sleep(0.01)

    job = jobs.get(created.id)
    assert job is not None
    assert job.status is JobStatus.BLOCKED
    assert "DEEPSEEK_API_KEY" in job.message
    assert "OPENAI_API_KEY" not in job.message
    assert not (tmp_path / str(created.id) / "exploration_report.json").exists()


def test_cli_plan_uses_deepseek_only_when_selected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    chosen_models: list[str] = []

    class FakePlanner:
        def plan(self, intent: DemoIntent) -> PlannerCandidate:
            return PlannerCandidate(spec=spec(), provider="deepseek", model=chosen_models[-1])

    def fake_deepseek(model: str) -> FakePlanner:
        chosen_models.append(model)
        return FakePlanner()

    monkeypatch.setenv("PROOFDEMO_PLANNER_PROVIDER", "deepseek")
    monkeypatch.setenv("PROOFDEMO_DEEPSEEK_MODEL", "deepseek-flash")
    monkeypatch.setattr("proofdemo.cli.DeepSeekPlanner", fake_deepseek)
    monkeypatch.setattr(
        "proofdemo.cli.OpenAIPlanner",
        lambda model: (_ for _ in ()).throw(AssertionError("OpenAI must not be selected")),
    )
    output = tmp_path / "candidate.json"
    args = ["plan", SOURCE, "--goal", "Create one task", "--output", str(output)]

    assert run(args) == EXIT_EXECUTED
    assert chosen_models == ["deepseek-flash"]
    assert DemoSpec.model_validate_json(output.read_text(encoding="utf-8")) == spec()


def test_cli_plan_with_deepseek_requires_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("PROOFDEMO_PLANNER_PROVIDER", "deepseek")
    monkeypatch.delenv("PROOFDEMO_DEEPSEEK_MODEL", raising=False)
    output = tmp_path / "candidate.json"

    args = ["plan", SOURCE, "--goal", "Create one task", "--output", str(output)]

    assert run(args) == EXIT_BLOCKED
    assert "PROOFDEMO_DEEPSEEK_MODEL" in capsys.readouterr().err
    assert not output.exists()
