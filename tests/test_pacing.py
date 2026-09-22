"""Bounded studio viewing pauses over an otherwise unchanged DemoSpec."""

from __future__ import annotations

from proofdemo.application.grounding import GroundingService
from proofdemo.application.pacing import pace_studio_spec
from proofdemo.domain.demo_spec import DemoSpec, PauseAction
from proofdemo.domain.exploration import (
    ExplorationReport,
    ExplorationStatus,
    ObservedControl,
    PageObservation,
)


def spec() -> DemoSpec:
    return DemoSpec.model_validate(
        {
            "schema_version": "1.2",
            "id": "watchable_todo",
            "title": "Create task",
            "goal": "Create and verify one task",
            "source_url": "https://product.example.test/",
            "scenes": [
                {
                    "id": "main",
                    "title": "Create task",
                    "goal": "Add a task",
                    "actions": [
                        {
                            "id": "open",
                            "type": "goto",
                            "url": "https://product.example.test/",
                        },
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
                            "id": "listed",
                            "type": "text_contains",
                            "target": {"strategy": "test_id", "test_id": "task-list"},
                            "expected_text": "Launch update",
                        }
                    ],
                }
            ],
        }
    )


def test_three_step_studio_flow_gets_readable_pauses() -> None:
    original = spec()

    paced = pace_studio_spec(original, 30)

    assert [action.type for action in paced.scenes[0].actions] == [
        "goto",
        "pause",
        "fill",
        "pause",
        "click",
        "pause",
    ]
    assert [
        action.duration_ms for action in paced.scenes[0].actions if isinstance(action, PauseAction)
    ] == [3_000, 3_000, 3_000]
    assert paced.scenes[0].assertions == original.scenes[0].assertions
    assert original.scenes[0].actions[1].type == "fill"


def test_viewing_pauses_need_no_invented_page_control() -> None:
    report = ExplorationReport(
        source_url="https://product.example.test/",
        status=ExplorationStatus.COMPLETE,
        pages=(
            PageObservation(
                url="https://product.example.test/",
                title="Tasks",
                headings=(),
                controls=(
                    ObservedControl(
                        id="page-1-control-1",
                        kind="input",
                        name="Task title",
                        target={"strategy": "label", "label": "Task title"},
                    ),
                    ObservedControl(
                        id="page-1-control-2",
                        kind="button",
                        name="Add task",
                        target={"strategy": "role", "role": "button", "name": "Add task"},
                    ),
                ),
            ),
        ),
        warnings=(),
        unvisited_link_count=0,
    )

    grounding = GroundingService.assess(pace_studio_spec(spec(), 30), report)

    assert grounding.status == "GROUNDED"
    assert all(check.status == "GROUNDED" for check in grounding.checks)


def test_short_or_unspecified_intent_does_not_change_spec() -> None:
    original = spec()

    assert pace_studio_spec(original, None) == original
    assert pace_studio_spec(original, 10) == original


def test_existing_pauses_are_not_doubled_and_ids_remain_unique() -> None:
    original = spec().model_dump(mode="json")
    original["scenes"][0]["actions"].insert(
        2, {"id": "watch-01", "type": "pause", "duration_ms": 3_000}
    )
    paced = pace_studio_spec(DemoSpec.model_validate(original), 30)

    actions = paced.scenes[0].actions
    assert len({action.id for action in actions}) == len(actions)
    assert sum(action.duration_ms for action in actions if isinstance(action, PauseAction)) == 9_000
    ids = [action.id for action in actions]
    assert ids.index("watch-01") == ids.index("title") + 1


def test_sufficient_existing_pauses_are_preserved() -> None:
    original = spec().model_dump(mode="json")
    original["scenes"][0]["actions"].insert(
        1, {"id": "already-paced", "type": "pause", "duration_ms": 10_000}
    )
    existing = DemoSpec.model_validate(original)

    assert pace_studio_spec(existing, 30) == existing
