"""Deterministic pre-execution safety policy and approval record."""

from __future__ import annotations

import re
from enum import StrEnum
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from proofdemo.application.artifacts import ArtifactDeclaration, ArtifactKind
from proofdemo.domain.demo_spec import ClickAction, DemoSpec, FillAction

_CREDENTIAL_MARKERS = re.compile(
    r"(?i)(password|passcode|one.?time.?code|otp|api.?key|access.?token|secret|"
    r"private.?key|credit.?card|card.?number|cvv|social.?security|ssn)"
)
_RISKY_ACTION_MARKERS = re.compile(
    r"(?i)\b(delete|remove|purchase|buy|pay|transfer|send money|confirm order|"
    r"cancel account|close account|terminate account|publish|deploy production)\b"
)


class SafetyDecision(StrEnum):
    ALLOWED = "ALLOWED"
    REQUIRES_APPROVAL = "REQUIRES_APPROVAL"
    BLOCKED = "BLOCKED"


class SafetySeverity(StrEnum):
    APPROVAL = "APPROVAL"
    BLOCK = "BLOCK"


class SafetyFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    severity: SafetySeverity
    scene_id: str
    action_id: str
    code: str
    description: str = Field(min_length=1, max_length=500)


class SafetyAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    spec_id: str
    decision: SafetyDecision
    approval_acknowledged: bool
    findings: tuple[SafetyFinding, ...]


class SafetyService:
    REPORT_PATH = "safety_assessment.json"

    @staticmethod
    def assess(spec: DemoSpec, *, approval_acknowledged: bool) -> SafetyAssessment:
        findings: list[SafetyFinding] = []
        for scene in spec.scenes:
            for action in scene.actions:
                if isinstance(action, FillAction) and _CREDENTIAL_MARKERS.search(
                    _target_text(action.target)
                ):
                    findings.append(
                        SafetyFinding(
                            severity=SafetySeverity.BLOCK,
                            scene_id=scene.id,
                            action_id=action.id,
                            code="CREDENTIAL_FILL_BLOCKED",
                            description=(
                                "Credential-like fields are not permitted in DemoSpec execution."
                            ),
                        )
                    )
                if isinstance(action, ClickAction) and _RISKY_ACTION_MARKERS.search(
                    _target_text(action.target)
                ):
                    findings.append(
                        SafetyFinding(
                            severity=SafetySeverity.APPROVAL,
                            scene_id=scene.id,
                            action_id=action.id,
                            code="RISKY_ACTION_REQUIRES_APPROVAL",
                            description=(
                                "A destructive, financial, account, or production action requires "
                                "fresh explicit approval."
                            ),
                        )
                    )
        if any(item.severity is SafetySeverity.BLOCK for item in findings):
            decision = SafetyDecision.BLOCKED
        elif findings and not approval_acknowledged:
            decision = SafetyDecision.REQUIRES_APPROVAL
        else:
            decision = SafetyDecision.ALLOWED
        return SafetyAssessment(
            spec_id=spec.id,
            decision=decision,
            approval_acknowledged=approval_acknowledged,
            findings=tuple(findings),
        )

    @staticmethod
    def write(assessment: SafetyAssessment, artifact_dir: Path) -> ArtifactDeclaration:
        artifact_dir.mkdir(parents=True, exist_ok=True)
        path = (artifact_dir.resolve() / SafetyService.REPORT_PATH).resolve()
        if not path.is_relative_to(artifact_dir.resolve()):
            raise ValueError("safety assessment path escaped artifact directory")
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as temporary:
            temporary.write(assessment.model_dump_json(indent=2) + "\n")
            temporary.flush()
            temporary_path = Path(temporary.name)
        temporary_path.replace(path)
        return ArtifactDeclaration(
            path=SafetyService.REPORT_PATH,
            kind=ArtifactKind.SAFETY_ASSESSMENT,
        )


def _target_text(target: object) -> str:
    model_dump = getattr(target, "model_dump", None)
    if not callable(model_dump):
        return ""
    payload = model_dump(mode="json")
    return " ".join(str(value) for key, value in payload.items() if key != "strategy")
