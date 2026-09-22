"""Deterministic stable-ID comparison between baseline and replay evidence."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from proofdemo.application.artifacts import ArtifactDeclaration, ArtifactKind
from proofdemo.application.execution import (
    ActionResult,
    ExecutionReport,
)
from proofdemo.application.verification import AssertionResult, OutcomeStatus
from proofdemo.domain.demo_run import DemoRunStatus
from proofdemo.domain.recipe import DemoRecipe


class ChangeStatus(StrEnum):
    UNCHANGED = "UNCHANGED"
    CHANGED = "CHANGED"
    NOT_EVALUATED = "NOT_EVALUATED"


class ChangeCategory(StrEnum):
    SELECTOR_BROKEN = "SELECTOR_BROKEN"
    ACTION_BROKEN = "ACTION_BROKEN"
    ASSERTION_BROKEN = "ASSERTION_BROKEN"
    OBSERVATION_CHANGED = "OBSERVATION_CHANGED"
    SCENE_ASSUMPTION_BROKEN = "SCENE_ASSUMPTION_BROKEN"


class UIChangeFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    category: ChangeCategory
    scene_id: str
    action_id: str | None = None
    assertion_id: str | None = None
    baseline_status: str
    replay_status: str
    description: str = Field(min_length=1, max_length=2_000)
    baseline_observed: JsonValue | None = None
    replay_observed: JsonValue | None = None


class UIChangeSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scenes_compared: int = Field(ge=0)
    actions_compared: int = Field(ge=0)
    assertions_compared: int = Field(ge=0)
    finding_count: int = Field(ge=0)


class UIChangeReport(BaseModel):
    """Versioned diagnosis that never changes replay verification semantics."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    recipe_id: str
    spec_id: str
    baseline_run_id: str
    replay_run_id: str
    status: ChangeStatus
    summary: UIChangeSummary
    findings: tuple[UIChangeFinding, ...]
    unavailable_reason: str | None = Field(default=None, min_length=1, max_length=2_000)


@dataclass(frozen=True)
class ChangeDetectionContext:
    recipe_id: str
    spec_id: str
    source_run_id: str
    baseline: ExecutionReport | None
    unavailable_reason: str | None = None


class BaselineMissingError(FileNotFoundError):
    """The referenced baseline report is not locally available."""


class BaselineInvalidError(ValueError):
    """The local baseline conflicts with recipe provenance or schema."""


class ChangeDetectionError(RuntimeError):
    """A comparison report could not be created safely."""


class ChangeDetectionService:
    REPORT_PATH = "ui_change_report.json"

    @staticmethod
    def load_baseline(recipe: DemoRecipe, artifact_dir: Path) -> ExecutionReport:
        root = artifact_dir.resolve()
        path = (root / recipe.provenance.execution_report.path).resolve()
        if not path.is_relative_to(root):
            raise BaselineInvalidError("baseline report path escaped artifact directory")
        if not path.is_file():
            raise BaselineMissingError(f"baseline report is missing: {path}")
        if _sha256(path) != recipe.provenance.execution_report.sha256:
            raise BaselineInvalidError("baseline report does not match recipe provenance hash")
        try:
            report = ExecutionReport.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise BaselineInvalidError("baseline report is not a valid ExecutionReport") from error
        if (
            str(report.run.id) != str(recipe.provenance.source_run_id)
            or report.run.spec_id != recipe.spec.id
            or report.run.status is not DemoRunStatus.PASSED
            or report.verification_status.value != DemoRunStatus.PASSED.value
        ):
            raise BaselineInvalidError("baseline report identity or status is inconsistent")
        return report

    @staticmethod
    def context(
        recipe: DemoRecipe,
        baseline: ExecutionReport | None,
        *,
        unavailable_reason: str | None = None,
    ) -> ChangeDetectionContext:
        return ChangeDetectionContext(
            recipe_id=str(recipe.id),
            spec_id=recipe.spec.id,
            source_run_id=str(recipe.provenance.source_run_id),
            baseline=baseline,
            unavailable_reason=unavailable_reason,
        )

    @staticmethod
    def compare(
        context: ChangeDetectionContext,
        replay: ExecutionReport,
    ) -> UIChangeReport:
        if replay.run.spec_id != context.spec_id:
            raise ChangeDetectionError("replay spec does not match change-detection context")
        if context.baseline is None:
            return UIChangeReport(
                recipe_id=context.recipe_id,
                spec_id=context.spec_id,
                baseline_run_id=context.source_run_id,
                replay_run_id=str(replay.run.id),
                status=ChangeStatus.NOT_EVALUATED,
                summary=UIChangeSummary(
                    scenes_compared=0,
                    actions_compared=0,
                    assertions_compared=0,
                    finding_count=0,
                ),
                findings=(),
                unavailable_reason=context.unavailable_reason
                or "baseline report was not available locally",
            )

        baseline = context.baseline
        findings: list[UIChangeFinding] = []
        replay_actions = {
            (action.scene_id, action.action_id): action for action in replay.action_results
        }
        for action in baseline.action_results:
            current_action = replay_actions.get((action.scene_id, action.action_id))
            finding = _compare_action(action, current_action)
            if finding is not None:
                findings.append(finding)

        replay_assertions = {
            (assertion.scene_id, assertion.assertion_id): assertion
            for scene in replay.scene_results
            for assertion in scene.assertion_results
        }
        baseline_assertions = [
            assertion for scene in baseline.scene_results for assertion in scene.assertion_results
        ]
        for assertion in baseline_assertions:
            current_assertion = replay_assertions.get((assertion.scene_id, assertion.assertion_id))
            finding = _compare_assertion(assertion, current_assertion)
            if finding is not None:
                findings.append(finding)

        replay_scenes = {scene.scene_id: scene for scene in replay.scene_results}
        scenes_with_findings = {finding.scene_id for finding in findings}
        for scene in baseline.scene_results:
            current_scene = replay_scenes.get(scene.scene_id)
            if scene.scene_id not in scenes_with_findings and (
                current_scene is None or current_scene.status is not scene.status
            ):
                findings.append(
                    UIChangeFinding(
                        category=ChangeCategory.SCENE_ASSUMPTION_BROKEN,
                        scene_id=scene.scene_id,
                        baseline_status=scene.status.value,
                        replay_status=current_scene.status.value if current_scene else "MISSING",
                        description="Scene outcome no longer matches the successful baseline.",
                    )
                )

        return UIChangeReport(
            recipe_id=context.recipe_id,
            spec_id=context.spec_id,
            baseline_run_id=str(baseline.run.id),
            replay_run_id=str(replay.run.id),
            status=ChangeStatus.CHANGED if findings else ChangeStatus.UNCHANGED,
            summary=UIChangeSummary(
                scenes_compared=len(baseline.scene_results),
                actions_compared=len(baseline.action_results),
                assertions_compared=len(baseline_assertions),
                finding_count=len(findings),
            ),
            findings=tuple(findings),
        )

    @staticmethod
    def write(report: UIChangeReport, artifact_dir: Path) -> ArtifactDeclaration:
        path = (artifact_dir.resolve() / ChangeDetectionService.REPORT_PATH).resolve()
        if not path.is_relative_to(artifact_dir.resolve()):
            raise ChangeDetectionError("change report path escaped artifact directory")
        path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as temporary:
            temporary.write(report.model_dump_json(indent=2) + "\n")
            temporary.flush()
            temporary_path = Path(temporary.name)
        temporary_path.replace(path)
        return ArtifactDeclaration(
            path=ChangeDetectionService.REPORT_PATH, kind=ArtifactKind.UI_CHANGE_REPORT
        )


def _compare_action(
    baseline: ActionResult,
    replay: ActionResult | None,
) -> UIChangeFinding | None:
    if replay is not None and replay.status is baseline.status:
        return None
    replay_status = replay.status.value if replay else "MISSING"
    error = replay.error if replay else None
    category = (
        ChangeCategory.SELECTOR_BROKEN
        if replay is not None
        and baseline.action_type in {"click", "fill"}
        and _looks_like_selector_problem(error)
        else ChangeCategory.ACTION_BROKEN
    )
    return UIChangeFinding(
        category=category,
        scene_id=baseline.scene_id,
        action_id=baseline.action_id,
        baseline_status=baseline.status.value,
        replay_status=replay_status,
        description=error or "Expected action result is missing from replay.",
    )


def _compare_assertion(
    baseline: AssertionResult,
    replay: AssertionResult | None,
) -> UIChangeFinding | None:
    if replay is None:
        return UIChangeFinding(
            category=ChangeCategory.ASSERTION_BROKEN,
            scene_id=baseline.scene_id,
            assertion_id=baseline.assertion_id,
            baseline_status=baseline.status.value,
            replay_status="MISSING",
            description="Expected assertion result is missing from replay.",
            baseline_observed=_observed(baseline),
        )
    if replay.status is not OutcomeStatus.PASSED:
        category = (
            ChangeCategory.SELECTOR_BROKEN
            if baseline.assertion_type in {"element_visible", "text_contains"}
            and _looks_like_selector_problem(replay.reason)
            else ChangeCategory.ASSERTION_BROKEN
        )
        return UIChangeFinding(
            category=category,
            scene_id=baseline.scene_id,
            assertion_id=baseline.assertion_id,
            baseline_status=baseline.status.value,
            replay_status=replay.status.value,
            description=replay.reason or "Assertion no longer passes.",
            baseline_observed=_observed(baseline),
            replay_observed=_observed(replay),
        )
    if baseline.evidence is None or replay.evidence is None:
        return UIChangeFinding(
            category=ChangeCategory.ASSERTION_BROKEN,
            scene_id=baseline.scene_id,
            assertion_id=baseline.assertion_id,
            baseline_status=baseline.status.value,
            replay_status=replay.status.value,
            description="Passed assertion evidence is missing.",
            baseline_observed=_observed(baseline),
            replay_observed=_observed(replay),
        )
    if baseline.evidence.expected != replay.evidence.expected:
        return UIChangeFinding(
            category=ChangeCategory.SCENE_ASSUMPTION_BROKEN,
            scene_id=baseline.scene_id,
            assertion_id=baseline.assertion_id,
            baseline_status=baseline.status.value,
            replay_status=replay.status.value,
            description="Assertion expectation changed from the successful baseline.",
            baseline_observed=baseline.evidence.observed,
            replay_observed=replay.evidence.observed,
        )
    if baseline.evidence.observed != replay.evidence.observed:
        return UIChangeFinding(
            category=ChangeCategory.OBSERVATION_CHANGED,
            scene_id=baseline.scene_id,
            assertion_id=baseline.assertion_id,
            baseline_status=baseline.status.value,
            replay_status=replay.status.value,
            description="Observed evidence changed while the assertion still passes.",
            baseline_observed=baseline.evidence.observed,
            replay_observed=replay.evidence.observed,
        )
    return None


def _observed(assertion: AssertionResult) -> JsonValue | None:
    return assertion.evidence.observed if assertion.evidence is not None else None


def _looks_like_selector_problem(reason: str | None) -> bool:
    if reason is None:
        return False
    lowered = reason.lower()
    return any(
        marker in lowered
        for marker in ("target", "locator", "selector", "not actionable", "element")
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
