"""Stage 10 pre-execution safety policy tests."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from proofdemo.application.safety import SafetyDecision, SafetyService
from proofdemo.domain.demo_spec import DemoSpec

ROOT = Path(__file__).resolve().parents[1]


def _raw_spec() -> dict[str, object]:
    return json.loads((ROOT / "examples" / "demo_spec.json").read_text(encoding="utf-8"))


def test_safe_demo_is_allowed_without_approval() -> None:
    assessment = SafetyService.assess(
        DemoSpec.model_validate(_raw_spec()),
        approval_acknowledged=False,
    )

    assert assessment.decision is SafetyDecision.ALLOWED
    assert assessment.findings == ()


def test_credential_like_fill_is_always_blocked() -> None:
    raw = deepcopy(_raw_spec())
    raw["scenes"][0]["actions"][1]["target"] = {  # type: ignore[index]
        "strategy": "label",
        "label": "Password",
    }
    spec = DemoSpec.model_validate(raw)

    without_approval = SafetyService.assess(spec, approval_acknowledged=False)
    with_approval = SafetyService.assess(spec, approval_acknowledged=True)

    assert without_approval.decision is SafetyDecision.BLOCKED
    assert with_approval.decision is SafetyDecision.BLOCKED
    assert with_approval.findings[0].code == "CREDENTIAL_FILL_BLOCKED"


def test_named_risky_action_requires_fresh_approval() -> None:
    raw = deepcopy(_raw_spec())
    raw["scenes"][0]["actions"][2]["target"] = {  # type: ignore[index]
        "strategy": "role",
        "role": "button",
        "name": "Delete account",
    }
    spec = DemoSpec.model_validate(raw)

    pending = SafetyService.assess(spec, approval_acknowledged=False)
    approved = SafetyService.assess(spec, approval_acknowledged=True)

    assert pending.decision is SafetyDecision.REQUIRES_APPROVAL
    assert approved.decision is SafetyDecision.ALLOWED
    assert approved.approval_acknowledged is True
    assert approved.findings[0].code == "RISKY_ACTION_REQUIRES_APPROVAL"
