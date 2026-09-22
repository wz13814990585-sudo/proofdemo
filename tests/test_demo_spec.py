"""Contract tests for DemoSpec 1.2 and its generated schema."""

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from proofdemo.domain.demo_spec import DemoSpec

ROOT = Path(__file__).resolve().parents[1]


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def example_spec() -> Any:
    return load_json(ROOT / "examples" / "demo_spec.json")


def test_example_demo_spec_is_valid() -> None:
    spec = DemoSpec.model_validate(example_spec())

    assert spec.schema_version == "1.2"
    assert spec.id == "todo_demo"
    assert spec.scenes[0].actions[0].id == "open-todo-app"
    assert spec.scenes[0].assertions[0].id == "task-is-listed"


def test_notes_example_demo_spec_is_valid() -> None:
    spec = DemoSpec.model_validate(load_json(ROOT / "examples" / "notes_demo_spec.json"))

    assert spec.id == "notes_demo"
    assert str(spec.source_url) == "http://127.0.0.1:4174/"
    assert spec.scenes[0].actions[1].id == "open-composer"
    assert spec.scenes[0].assertions[0].id == "note-is-published"


def test_demo_spec_accepts_explicit_pause_action() -> None:
    raw_spec = example_spec()
    raw_spec["scenes"][0]["actions"].insert(
        1,
        {"id": "presentation-beat", "type": "pause", "duration_ms": 250},
    )

    spec = DemoSpec.model_validate(raw_spec)

    assert spec.scenes[0].actions[1].type == "pause"


def test_demo_spec_rejects_unknown_action() -> None:
    raw_spec = example_spec()
    raw_spec["scenes"][0]["actions"][0]["type"] = "invent_success"

    with pytest.raises(ValidationError):
        DemoSpec.model_validate(raw_spec)


def test_demo_spec_rejects_duplicate_scene_ids() -> None:
    raw_spec = example_spec()
    raw_spec["scenes"].append(deepcopy(raw_spec["scenes"][0]))

    with pytest.raises(ValidationError, match="duplicate Scene IDs"):
        DemoSpec.model_validate(raw_spec)


def test_scene_rejects_duplicate_action_ids() -> None:
    raw_spec = example_spec()
    raw_spec["scenes"][0]["actions"].append(deepcopy(raw_spec["scenes"][0]["actions"][0]))

    with pytest.raises(ValidationError, match="duplicate Action IDs"):
        DemoSpec.model_validate(raw_spec)


def test_scene_rejects_duplicate_assertion_ids() -> None:
    raw_spec = example_spec()
    raw_spec["scenes"][0]["assertions"].append(deepcopy(raw_spec["scenes"][0]["assertions"][0]))

    with pytest.raises(ValidationError, match="duplicate Assertion IDs"):
        DemoSpec.model_validate(raw_spec)


def test_scene_requires_at_least_one_assertion() -> None:
    raw_spec = example_spec()
    raw_spec["scenes"][0]["assertions"] = []

    with pytest.raises(ValidationError, match="at least 1 item"):
        DemoSpec.model_validate(raw_spec)


def test_demo_spec_requires_initial_navigation() -> None:
    raw_spec = example_spec()
    raw_spec["scenes"][0]["actions"].pop(0)

    with pytest.raises(ValidationError, match="first DemoSpec action must be goto"):
        DemoSpec.model_validate(raw_spec)


def test_demo_spec_rejects_cross_origin_navigation() -> None:
    raw_spec = example_spec()
    raw_spec["scenes"][0]["actions"][0]["url"] = "https://other.example.test/todos"

    with pytest.raises(ValidationError, match="must remain on source_url origin"):
        DemoSpec.model_validate(raw_spec)


def test_demo_spec_rejects_cross_origin_url_assertion() -> None:
    raw_spec = example_spec()
    url_assertion = next(
        item for item in raw_spec["scenes"][0]["assertions"] if item["type"] == "url_equals"
    )
    url_assertion["expected_url"] = "https://other.example.test/"

    with pytest.raises(ValidationError, match="url_equals Assertion"):
        DemoSpec.model_validate(raw_spec)


def test_app_state_key_cannot_contain_javascript() -> None:
    raw_spec = example_spec()
    state_assertion = next(
        item for item in raw_spec["scenes"][0]["assertions"] if item["type"] == "app_state_equals"
    )
    state_assertion["key"] = "constructor.constructor('return window')()"

    with pytest.raises(ValidationError, match="string_pattern_mismatch"):
        DemoSpec.model_validate(raw_spec)


def test_download_assertion_requires_plain_filename() -> None:
    raw_spec = example_spec()
    download_assertion = next(
        item for item in raw_spec["scenes"][0]["assertions"] if item["type"] == "download_completed"
    )
    download_assertion["filename"] = "../secret.txt"

    with pytest.raises(ValidationError, match="plain filename"):
        DemoSpec.model_validate(raw_spec)


def test_demo_spec_rejects_credentials_embedded_in_urls() -> None:
    raw_spec = example_spec()
    raw_spec["source_url"] = "https://demo:secret@example.test/todos"

    with pytest.raises(ValidationError, match="must not contain embedded credentials"):
        DemoSpec.model_validate(raw_spec)


def test_target_rejects_fields_from_another_strategy() -> None:
    raw_spec = example_spec()
    raw_spec["scenes"][0]["actions"][1]["target"]["name"] = "not valid for label"

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        DemoSpec.model_validate(raw_spec)


def test_scene_rejects_unbounded_action_collection() -> None:
    raw_spec = example_spec()
    raw_spec["scenes"][0]["actions"] = [
        raw_spec["scenes"][0]["actions"][0],
        *({"id": f"pause-{index}", "type": "pause", "duration_ms": 1} for index in range(100)),
    ]

    with pytest.raises(ValidationError, match="at most 100 items"):
        DemoSpec.model_validate(raw_spec)


def test_demo_spec_rejects_excessive_total_pause_budget() -> None:
    raw_spec = example_spec()
    raw_spec["scenes"][0]["actions"] = [
        raw_spec["scenes"][0]["actions"][0],
        *({"id": f"pause-{index}", "type": "pause", "duration_ms": 30_000} for index in range(11)),
    ]

    with pytest.raises(ValidationError, match="pause budget"):
        DemoSpec.model_validate(raw_spec)


def test_committed_json_schema_matches_model() -> None:
    committed_schema = load_json(ROOT / "shared" / "schemas" / "demo_spec.schema.json")

    assert committed_schema == DemoSpec.model_json_schema(mode="validation")
