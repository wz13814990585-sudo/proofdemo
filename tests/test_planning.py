"""Tests for bounded Stage 5 planning and provider isolation."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from openai import OpenAIError
from pydantic import ValidationError

from proofdemo.adapters.openai_planner import OpenAIPlanner
from proofdemo.application.planning import InvalidPlannerCandidate, PlanningService
from proofdemo.cli import EXIT_BLOCKED, EXIT_EXECUTED, run
from proofdemo.domain.demo_spec import DemoSpec
from proofdemo.domain.planning import DemoIntent
from proofdemo.ports.planner import (
    PlannerCandidate,
    PlannerResponseError,
    PlannerUnavailableError,
)

ROOT = Path(__file__).resolve().parents[1]


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


class FakePlanner:
    def __init__(self, spec: DemoSpec) -> None:
        self.spec = spec
        self.calls: list[DemoIntent] = []

    def plan(self, intent: DemoIntent) -> PlannerCandidate:
        self.calls.append(intent)
        return PlannerCandidate(spec=self.spec, provider="fake", model="fixture-model")


class FakeResponses:
    def __init__(self, parsed: object) -> None:
        self.parsed = parsed
        self.kwargs: dict[str, object] = {}

    def parse(self, **kwargs: object) -> SimpleNamespace:
        self.kwargs = kwargs
        return SimpleNamespace(output_parsed=self.parsed)


class FakeClient:
    def __init__(self, parsed: object) -> None:
        self.responses = FakeResponses(parsed)


def test_planning_service_returns_review_required_validated_spec() -> None:
    intent = DemoIntent(
        source_url="https://app.example.test/todos",
        goal="Create a launch task",
    )
    planner = FakePlanner(spec_for_url("https://app.example.test/todos"))

    result = PlanningService(planner).plan(intent)

    assert result.requires_review is True
    assert result.spec.schema_version == "1.2"
    assert result.spec.scenes[0].actions[0].type == "goto"
    assert result.spec.scenes[0].assertions
    assert result.provider == "fake"
    assert planner.calls == [intent]


def test_planning_service_rejects_candidate_that_changes_origin() -> None:
    intent = DemoIntent(source_url="https://app.example.test/", goal="Create a task")
    planner = FakePlanner(spec_for_url("https://attacker.example.test/"))

    with pytest.raises(InvalidPlannerCandidate, match="changed the requested source origin"):
        PlanningService(planner).plan(intent)


def test_demo_intent_rejects_embedded_credentials() -> None:
    with pytest.raises(ValidationError, match="embedded credentials"):
        DemoIntent(
            source_url="https://user:secret@app.example.test/",
            goal="Create a task",
        )


def test_openai_adapter_uses_one_tool_free_non_persisted_structured_call() -> None:
    spec = spec_for_url("https://app.example.test/")
    client = FakeClient(spec)
    intent = DemoIntent(source_url="https://app.example.test/", goal="Create a task")

    candidate = OpenAIPlanner("explicit-model", client=client).plan(intent)

    assert candidate.spec == spec
    assert candidate.model == "explicit-model"
    assert client.responses.kwargs["model"] == "explicit-model"
    assert client.responses.kwargs["text_format"] is DemoSpec
    assert client.responses.kwargs["store"] is False
    assert "tools" not in client.responses.kwargs
    assert "Create a task" in str(client.responses.kwargs["input"])


def test_openai_adapter_rejects_refusal_or_missing_structured_output() -> None:
    intent = DemoIntent(source_url="https://app.example.test/", goal="Create a task")

    with pytest.raises(PlannerResponseError, match="no structured DemoSpec"):
        OpenAIPlanner("explicit-model", client=FakeClient(None)).plan(intent)


def test_openai_adapter_requires_explicit_model() -> None:
    with pytest.raises(PlannerUnavailableError, match="explicit"):
        OpenAIPlanner(" ", client=FakeClient(None))


def test_openai_adapter_hides_provider_error_details() -> None:
    class FailingResponses:
        def parse(self, **kwargs: object) -> None:
            raise OpenAIError("provider-secret-detail")

    intent = DemoIntent(source_url="https://app.example.test/", goal="Create a task")
    client = SimpleNamespace(responses=FailingResponses())

    with pytest.raises(PlannerUnavailableError, match="request failed") as captured:
        OpenAIPlanner("explicit-model", client=client).plan(intent)

    assert "provider-secret-detail" not in str(captured.value)


def test_plan_cli_requires_model_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PROOFDEMO_OPENAI_MODEL", raising=False)
    output = tmp_path / "candidate.json"

    exit_code = run(
        [
            "plan",
            "https://app.example.test/",
            "--goal",
            "Create a task",
            "--output",
            str(output),
        ]
    )

    assert exit_code == EXIT_BLOCKED
    assert not output.exists()


def test_plan_cli_writes_candidate_without_automatic_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    planner = FakePlanner(spec_for_url("https://app.example.test/"))
    monkeypatch.setattr("proofdemo.cli.OpenAIPlanner", lambda model: planner)
    monkeypatch.setattr(
        "proofdemo.cli.ExecutionService",
        lambda browser: (_ for _ in ()).throw(AssertionError("must not execute")),
    )
    output = tmp_path / "candidate.json"

    exit_code = run(
        [
            "plan",
            "https://app.example.test/",
            "--goal",
            "Create a task",
            "--model",
            "explicit-model",
            "--output",
            str(output),
        ]
    )

    assert exit_code == EXIT_EXECUTED
    assert DemoSpec.model_validate_json(output.read_text(encoding="utf-8")) == planner.spec
