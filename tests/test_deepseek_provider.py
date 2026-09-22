"""Provider-scoped DeepSeek routing without real credentials or network calls."""

from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from httpx import Client, MockTransport, Request, Response
from openai import BadRequestError, OpenAI, OpenAIError

from proofdemo.adapters import deepseek
from proofdemo.adapters.deepseek import (
    DeepSeekIncompleteCandidateError,
    DeepSeekInvalidCandidateError,
    DeepSeekLinkAdvisor,
    DeepSeekPlanner,
)
from proofdemo.adapters.openai_exploration import LinkChoice
from proofdemo.application.jobs import JobManager, JobStatus
from proofdemo.cli import EXIT_BLOCKED, EXIT_EXECUTED, run
from proofdemo.config import Settings
from proofdemo.domain.demo_spec import DemoSpec, RoleTarget
from proofdemo.domain.exploration import (
    ExplorationReport,
    ExplorationStatus,
    ObservedControl,
    PageObservation,
)
from proofdemo.domain.planning import DemoIntent
from proofdemo.ports.explorer import InvalidLinkAdvice
from proofdemo.ports.planner import (
    PlannerCandidate,
    PlannerResponseError,
    PlannerUnavailableError,
)

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
        def create(self, **kwargs: Any) -> SimpleNamespace:
            requests.append(kwargs)
            output = spec() if len(requests) == 1 else LinkChoice(url=SOURCE)
            return SimpleNamespace(status="completed", output_text=output.model_dump_json())

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
    assert all(call["text"] == {"format": {"type": "json_object"}} for call in requests)
    assert all(call["reasoning"] == {"effort": "none"} for call in requests)
    assert all("test-only-deepseek-key" not in str(call["input"]) for call in requests)
    assert "DemoSpec JSON Schema" in requests[0]["instructions"]
    assert "DemoSpec JSON Schema" not in requests[1]["instructions"]
    assert "LinkChoice JSON Schema" in requests[1]["instructions"]
    assert json.loads(requests[1]["instructions"].splitlines()[-1]) == LinkChoice.model_json_schema(
        mode="validation"
    )


@pytest.mark.parametrize(
    ("output", "expected"),
    [('{"url":null}', None), ('{"url":"https://product.example.test/"}', SOURCE)],
)
def test_deepseek_link_advisor_accepts_only_structured_choices(
    monkeypatch: pytest.MonkeyPatch, output: str, expected: str | None
) -> None:
    class FakeResponses:
        def create(self, **kwargs: Any) -> SimpleNamespace:
            return SimpleNamespace(status="completed", output_text=output)

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only-deepseek-key")
    monkeypatch.setattr(
        deepseek, "OpenAI", lambda **kwargs: SimpleNamespace(responses=FakeResponses())
    )

    choice = DeepSeekLinkAdvisor("deepseek-flash").choose(
        DemoIntent(source_url=SOURCE, goal="Create one task"), (), (SOURCE,)
    )

    assert choice == expected


@pytest.mark.parametrize("output", ['"https://product.example.test/"', "{}", '{"url":42}'])
def test_deepseek_link_advisor_rejects_malformed_choice_without_echoing_it(
    monkeypatch: pytest.MonkeyPatch, output: str
) -> None:
    class FakeResponses:
        def create(self, **kwargs: Any) -> SimpleNamespace:
            return SimpleNamespace(status="completed", output_text=output)

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only-deepseek-key")
    monkeypatch.setattr(
        deepseek, "OpenAI", lambda **kwargs: SimpleNamespace(responses=FakeResponses())
    )

    with pytest.raises(InvalidLinkAdvice, match="invalid LinkChoice object") as caught:
        DeepSeekLinkAdvisor("deepseek-flash").choose(
            DemoIntent(source_url=SOURCE, goal="Create one task"), (), (SOURCE,)
        )
    assert output not in str(caught.value)


def test_deepseek_grounded_plan_keeps_provider_label_and_evidence_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[dict[str, Any]] = []

    class FakeResponses:
        def create(self, **kwargs: Any) -> SimpleNamespace:
            requests.append(kwargs)
            return SimpleNamespace(status="completed", output_text=spec().model_dump_json())

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
    assert requests[0]["text"] == {"format": {"type": "json_object"}}
    assert requests[0]["store"] is False
    assert json.loads(requests[0]["instructions"].splitlines()[-1]) == DemoSpec.model_json_schema(
        mode="validation"
    )


def test_deepseek_compacts_large_observation_but_keeps_relevant_tail_control(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[dict[str, Any]] = []

    class FakeResponses:
        def create(self, **kwargs: Any) -> SimpleNamespace:
            requests.append(kwargs)
            return SimpleNamespace(status="completed", output_text=spec().model_dump_json())

    controls = tuple(
        ObservedControl(
            id=f"page-1-control-{index + 1}",
            kind="link",
            name="Target Game" if index == 119 else f"Game {index}",
            target=RoleTarget(
                strategy="role",
                role="link",
                name="Target Game" if index == 119 else f"Game {index}",
            ),
            href=f"{SOURCE}games/{index}",
        )
        for index in range(120)
    )
    report = ExplorationReport(
        source_url=SOURCE,
        status=ExplorationStatus.PARTIAL,
        pages=(
            PageObservation(
                url=SOURCE,
                title="Games",
                headings=("Choose a game",),
                controls=controls,
                screenshot_path="exploration/page-1.png",
                screenshot_sha256="a" * 64,
            ),
        ),
        warnings=("many links remain",),
        unvisited_link_count=50,
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only-deepseek-key")
    monkeypatch.setattr(
        deepseek, "OpenAI", lambda **kwargs: SimpleNamespace(responses=FakeResponses())
    )

    result = DeepSeekPlanner("deepseek-flash").plan_grounded(
        DemoIntent(source_url=SOURCE, goal="Open Target Game"), report
    )

    evidence = json.loads(requests[0]["input"])["exploration"]
    shown = evidence["pages"][0]["controls"]
    assert result.spec == spec()
    assert len(shown) == deepseek.MAX_PLANNING_CONTROLS_PER_PAGE
    assert any(control["name"] == "Target Game" for control in shown)
    assert evidence["pages"][0]["omitted_actionable_control_count"] == 96
    assert evidence["unvisited_link_count"] == 50
    assert "screenshot_sha256" not in requests[0]["input"]
    assert "many links remain" not in requests[0]["input"]
    assert len(report.pages[0].controls) == 120
    assert len(requests[0]["input"]) < len(report.model_dump_json())


def test_deepseek_repairs_invalid_candidate_once_without_echoing_model_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[dict[str, Any]] = []
    invalid = spec().model_dump(mode="json")
    invalid["sk-sensitive-model-field"] = "secret-value"

    class FakeResponses:
        def create(self, **kwargs: Any) -> SimpleNamespace:
            requests.append(kwargs)
            output = json.dumps(invalid) if len(requests) == 1 else spec().model_dump_json()
            return SimpleNamespace(status="completed", output_text=output)

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only-deepseek-key")
    monkeypatch.setattr(
        deepseek, "OpenAI", lambda **kwargs: SimpleNamespace(responses=FakeResponses())
    )

    candidate = DeepSeekPlanner("deepseek-flash").plan(
        DemoIntent(source_url=SOURCE, goal="Create one task")
    )

    assert candidate.spec == spec()
    assert len(requests) == 2
    assert requests[0]["input"] == requests[1]["input"]
    assert "field:extra_forbidden" in requests[1]["instructions"]
    assert "sk-sensitive-model-field" not in requests[1]["instructions"]
    assert "secret-value" not in requests[1]["instructions"]
    assert all(request["store"] is False and "tools" not in request for request in requests)


def test_deepseek_normalizes_only_malformed_ids_without_another_provider_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[dict[str, Any]] = []
    candidate = spec().model_dump(mode="json")
    candidate["id"] = "中文网站演示"
    scene = candidate["scenes"][0]
    scene["id"] = "首页场景"
    scene["actions"] = [
        {"id": "action-1", "type": "goto", "url": SOURCE},
        {"id": "点击按钮", "type": "screenshot", "name": "home"},
    ]
    scene["assertions"] = [
        scene["assertions"][0] | {"id": "assertion-1"},
        scene["assertions"][0] | {"id": "页面可见"},
    ]

    class FakeResponses:
        def create(self, **kwargs: Any) -> SimpleNamespace:
            requests.append(kwargs)
            return SimpleNamespace(status="completed", output_text=json.dumps(candidate))

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only-deepseek-key")
    monkeypatch.setattr(
        deepseek, "OpenAI", lambda **kwargs: SimpleNamespace(responses=FakeResponses())
    )

    result = DeepSeekPlanner("deepseek-flash").plan(
        DemoIntent(source_url=SOURCE, goal="Show the site")
    )

    assert len(requests) == 1
    assert result.spec.id == "demo-1"
    assert result.spec.scenes[0].id == "scene-1"
    assert [action.id for action in result.spec.scenes[0].actions] == ["action-1", "action-2"]
    assert [assertion.id for assertion in result.spec.scenes[0].assertions] == [
        "assertion-1",
        "assertion-2",
    ]
    assert str(result.spec.scenes[0].actions[0].url) == SOURCE
    assert result.spec.scenes[0].assertions[1].target == spec().scenes[0].assertions[0].target


def test_deepseek_id_normalization_does_not_accept_other_contract_violations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[dict[str, Any]] = []
    candidate = spec().model_dump(mode="json")
    candidate["id"] = "无效 ID"
    candidate["scenes"][0]["actions"][0]["url"] = "https://other.example.test/"

    class FakeResponses:
        def create(self, **kwargs: Any) -> SimpleNamespace:
            requests.append(kwargs)
            return SimpleNamespace(status="completed", output_text=json.dumps(candidate))

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only-deepseek-key")
    monkeypatch.setattr(
        deepseek, "OpenAI", lambda **kwargs: SimpleNamespace(responses=FakeResponses())
    )

    with pytest.raises(DeepSeekInvalidCandidateError):
        DeepSeekPlanner("deepseek-flash").plan(DemoIntent(source_url=SOURCE, goal="Show the site"))

    assert len(requests) == 2


def test_deepseek_stops_after_two_invalid_candidates_with_safe_diagnostic(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    requests: list[dict[str, Any]] = []
    invalid = spec().model_dump(mode="json")
    invalid["sk-sensitive-model-field"] = "secret-value"

    class FakeResponses:
        def create(self, **kwargs: Any) -> SimpleNamespace:
            requests.append(kwargs)
            return SimpleNamespace(status="completed", output_text=json.dumps(invalid))

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only-deepseek-key")
    monkeypatch.setattr(
        deepseek, "OpenAI", lambda **kwargs: SimpleNamespace(responses=FakeResponses())
    )

    with pytest.raises(DeepSeekInvalidCandidateError) as caught:
        DeepSeekPlanner("deepseek-flash").plan(DemoIntent(source_url=SOURCE, goal="Create task"))

    assert len(requests) == 2
    assert caught.value.diagnostics == ("field:extra_forbidden",)
    jobs = JobManager.from_settings(
        Settings(
            environment="test",
            job_root=tmp_path,
            planner_provider="deepseek",
            deepseek_model="deepseek-flash",
        )
    )
    message = jobs._safe_error("Planning blocked", caught.value)
    assert "field:extra_forbidden" in message
    assert "sk-sensitive-model-field" not in message
    assert "secret-value" not in message


def test_deepseek_sdk_sends_json_mode_without_strict_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[dict[str, Any]] = []

    def capture(request: Request) -> Response:
        requests.append(json.loads(request.content))
        return Response(400, json={"error": {"message": "offline stop"}})

    client = OpenAI(
        api_key="test-only-deepseek-key",
        base_url="https://api.deepseek.com",
        max_retries=0,
        http_client=Client(transport=MockTransport(capture)),
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only-deepseek-key")
    monkeypatch.setattr(deepseek, "OpenAI", lambda **kwargs: client)

    with pytest.raises(PlannerUnavailableError):
        DeepSeekPlanner("deepseek-flash").plan(DemoIntent(source_url=SOURCE, goal="Create task"))

    assert len(requests) == 1
    assert requests[0]["text"] == {"format": {"type": "json_object"}}
    assert "schema" not in json.dumps(requests[0]["text"])
    assert "DemoSpec JSON Schema" in requests[0]["instructions"]
    assert requests[0]["reasoning"] == {"effort": "none"}
    assert requests[0]["store"] is False


def test_deepseek_sdk_parses_completed_json_response(monkeypatch: pytest.MonkeyPatch) -> None:
    def completed(request: Request) -> Response:
        return Response(
            200,
            json={
                "id": "resp_offline",
                "object": "response",
                "created_at": 0,
                "status": "completed",
                "model": "deepseek-flash",
                "output": [
                    {
                        "id": "msg_offline",
                        "type": "message",
                        "status": "completed",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": spec().model_dump_json(),
                                "annotations": [],
                            }
                        ],
                    }
                ],
                "error": None,
                "incomplete_details": None,
                "store": False,
                "previous_response_id": None,
                "parallel_tool_calls": True,
            },
        )

    client = OpenAI(
        api_key="test-only-deepseek-key",
        base_url="https://api.deepseek.com",
        max_retries=0,
        http_client=Client(transport=MockTransport(completed)),
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only-deepseek-key")
    monkeypatch.setattr(deepseek, "OpenAI", lambda **kwargs: client)

    candidate = DeepSeekPlanner("deepseek-flash").plan(
        DemoIntent(source_url=SOURCE, goal="Create task")
    )

    assert candidate.spec == spec()
    assert candidate.provider == "deepseek"


def test_deepseek_rejects_invalid_or_incomplete_json_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResponses:
        def __init__(self, status: str, output_text: str) -> None:
            self.status = status
            self.output_text = output_text

        def create(self, **kwargs: Any) -> SimpleNamespace:
            return SimpleNamespace(status=self.status, output_text=self.output_text)

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only-deepseek-key")
    intent = DemoIntent(source_url=SOURCE, goal="Create one task")
    for status, output, expected_error in (
        ("completed", "{}", DeepSeekInvalidCandidateError),
        ("incomplete", spec().model_dump_json(), DeepSeekIncompleteCandidateError),
    ):
        monkeypatch.setattr(
            deepseek,
            "OpenAI",
            lambda status=status, output=output, **kwargs: SimpleNamespace(
                responses=FakeResponses(status, output)
            ),
        )
        with pytest.raises(expected_error):
            DeepSeekPlanner("deepseek-flash").plan(intent)


def test_deepseek_requires_new_local_key_and_explicit_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "not-a-deepseek-key")

    with pytest.raises(PlannerUnavailableError, match="DEEPSEEK_API_KEY"):
        DeepSeekPlanner("deepseek-flash")
    with pytest.raises(PlannerUnavailableError, match="PROOFDEMO_DEEPSEEK_MODEL"):
        DeepSeekPlanner(" ")


def test_deepseek_http_400_is_not_reported_as_missing_credentials(tmp_path: Path) -> None:
    jobs = JobManager.from_settings(
        Settings(
            environment="test",
            job_root=tmp_path,
            planner_provider="deepseek",
            deepseek_model="deepseek-flash",
        )
    )
    remote = BadRequestError(
        "remote-secret-detail",
        response=Response(400, request=Request("POST", "https://api.deepseek.com/responses")),
        body={"error": {"message": "remote-secret-detail"}},
    )
    local = PlannerUnavailableError("DeepSeek planner request failed")
    local.__cause__ = remote

    message = jobs._safe_error("Planning blocked", local)

    assert "HTTP 400" in message
    assert "DEEPSEEK_API_KEY" not in message
    assert "remote-secret-detail" not in message
    assert "valid DemoSpec" in jobs._safe_error(
        "Planning blocked", PlannerResponseError("remote-secret-detail")
    )
    assert "empty or incomplete" in jobs._safe_error(
        "Planning blocked", DeepSeekIncompleteCandidateError("internal-only")
    )
    assert "did not match" in jobs._safe_error(
        "Planning blocked", DeepSeekInvalidCandidateError(("scenes:missing",))
    )


def test_deepseek_provider_error_never_reveals_remote_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingResponses:
        def create(self, **kwargs: Any) -> None:
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
