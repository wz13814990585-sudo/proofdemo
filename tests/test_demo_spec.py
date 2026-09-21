"""Contract tests for the authoritative DemoSpec model and schema."""

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from proofdemo.domain.demo_spec import DemoSpec

ROOT = Path(__file__).resolve().parents[1]


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def test_example_demo_spec_is_valid() -> None:
    raw_spec = load_json(ROOT / "examples" / "demo_spec.json")

    spec = DemoSpec.model_validate(raw_spec)

    assert spec.schema_version == "1.0"
    assert spec.id == "todo_demo"
    assert len(spec.scenes) == 1
    assert spec.scenes[0].actions[-1].type == "screenshot"


def test_demo_spec_rejects_unknown_action() -> None:
    raw_spec = load_json(ROOT / "examples" / "demo_spec.json")
    raw_spec["scenes"][0]["actions"][0]["type"] = "invent_success"

    with pytest.raises(ValidationError):
        DemoSpec.model_validate(raw_spec)


def test_committed_json_schema_matches_model() -> None:
    committed_schema = load_json(ROOT / "shared" / "schemas" / "demo_spec.schema.json")

    assert committed_schema == DemoSpec.model_json_schema(mode="validation")
