"""Offline representative benchmark over execution and verification services."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from proofdemo import __version__
from proofdemo.application.execution import ExecutionBundle, ExecutionService
from proofdemo.application.trace import TraceEventKind
from proofdemo.domain.demo_spec import DemoSpec, ElementTarget
from proofdemo.ports.browser import (
    AppStateObservation,
    BrowserActionError,
    BrowserSessionArtifacts,
    BrowserUnavailableError,
    DownloadObservation,
)


class BenchmarkStatus(StrEnum):
    PASSED = "PASSED"
    FAILED = "FAILED"


class BenchmarkCaseResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    expected_status: str
    observed_status: str
    outcome_correct: bool
    expected_evidence_count: int = Field(ge=0)
    observed_evidence_count: int = Field(ge=0)
    evidence_complete: bool
    trace_sequence_valid: bool
    trace_correlation_valid: bool
    passed: bool


class BenchmarkMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    terminal_outcome_accuracy: float = Field(ge=0, le=1)
    expected_evidence_coverage: float = Field(ge=0, le=1)
    trace_integrity: float = Field(ge=0, le=1)


class BenchmarkThresholds(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    terminal_outcome_accuracy: float = 1.0
    expected_evidence_coverage: float = 1.0
    trace_integrity: float = 1.0


class BenchmarkReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    proofdemo_version: str
    status: BenchmarkStatus
    case_count: int = Field(gt=0)
    passed_case_count: int = Field(ge=0)
    thresholds: BenchmarkThresholds
    metrics: BenchmarkMetrics
    cases: tuple[BenchmarkCaseResult, ...]


@dataclass(frozen=True)
class _Case:
    case_id: str
    expected_status: str
    expected_evidence_count: int
    startup_blocked: bool = False
    action_failed: bool = False
    text: str = "Expected result"


CASES = (
    _Case("verified_success", "PASSED", 2),
    _Case("assertion_mismatch", "FAILED", 2, text="Different result"),
    _Case("action_failure", "FAILED", 0, action_failed=True),
    _Case("browser_blocked", "BLOCKED", 0, startup_blocked=True),
)


class BenchmarkService:
    """Run fixed cases without network, provider, browser, or media dependencies."""

    def run(self, thresholds: BenchmarkThresholds | None = None) -> BenchmarkReport:
        required = thresholds or BenchmarkThresholds()
        results: list[BenchmarkCaseResult] = []
        with TemporaryDirectory(prefix="proofdemo-benchmark-") as temporary:
            root = Path(temporary)
            for case in CASES:
                bundle = ExecutionService(_BenchmarkBrowser(case)).execute_bundle(
                    _benchmark_spec(),
                    root / case.case_id,
                )
                results.append(_evaluate_case(case, bundle))
        count = len(results)
        evidence_expected = sum(item.expected_evidence_count for item in results)
        evidence_observed = sum(
            min(item.observed_evidence_count, item.expected_evidence_count) for item in results
        )
        metrics = BenchmarkMetrics(
            terminal_outcome_accuracy=sum(item.outcome_correct for item in results) / count,
            expected_evidence_coverage=(
                evidence_observed / evidence_expected if evidence_expected else 1.0
            ),
            trace_integrity=sum(
                item.trace_sequence_valid and item.trace_correlation_valid for item in results
            )
            / count,
        )
        passed = (
            metrics.terminal_outcome_accuracy >= required.terminal_outcome_accuracy
            and metrics.expected_evidence_coverage >= required.expected_evidence_coverage
            and metrics.trace_integrity >= required.trace_integrity
        )
        return BenchmarkReport(
            proofdemo_version=__version__,
            status=BenchmarkStatus.PASSED if passed else BenchmarkStatus.FAILED,
            case_count=count,
            passed_case_count=sum(item.passed for item in results),
            thresholds=required,
            metrics=metrics,
            cases=tuple(results),
        )


class _BenchmarkBrowser:
    def __init__(self, case: _Case) -> None:
        self._case = case

    def open(self, source_url: str, *, recording_dir: Path | None = None) -> None:
        if self._case.startup_blocked:
            raise BrowserUnavailableError("benchmark browser unavailable")

    def goto(self, url: str, *, timeout_ms: int) -> None:
        return None

    def click(self, target: ElementTarget, *, timeout_ms: int) -> None:
        if self._case.action_failed:
            raise BrowserActionError("benchmark target not actionable")

    def fill(self, target: ElementTarget, value: str, *, timeout_ms: int) -> None:
        return None

    def pause(self, duration_ms: int) -> None:
        return None

    def screenshot(self, path: Path, *, full_page: bool) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"benchmark screenshot")

    def is_visible(self, target: ElementTarget, *, timeout_ms: int) -> bool:
        return True

    def text_content(self, target: ElementTarget, *, timeout_ms: int) -> str | None:
        return self._case.text

    def current_url(self) -> str:
        return "https://benchmark.invalid/"

    def completed_download(self, filename: str, *, timeout_ms: int) -> DownloadObservation:
        return DownloadObservation(filename=filename, completed=True, byte_count=1)

    def application_state(self, key: str) -> AppStateObservation:
        return AppStateObservation(found=True, value=True)

    def close(self) -> BrowserSessionArtifacts:
        return BrowserSessionArtifacts()


def _benchmark_spec() -> DemoSpec:
    return DemoSpec.model_validate(
        {
            "schema_version": "1.2",
            "id": "benchmark_demo",
            "title": "Benchmark demo",
            "goal": "Exercise deterministic execution and verification.",
            "source_url": "https://benchmark.invalid/",
            "scenes": [
                {
                    "id": "benchmark_scene",
                    "title": "Exercise the pipeline",
                    "goal": "Click and verify the expected result.",
                    "actions": [
                        {
                            "id": "open",
                            "type": "goto",
                            "url": "https://benchmark.invalid/",
                        },
                        {
                            "id": "act",
                            "type": "click",
                            "target": {
                                "strategy": "role",
                                "role": "button",
                                "name": "Run benchmark",
                            },
                        },
                    ],
                    "assertions": [
                        {
                            "id": "text",
                            "type": "text_contains",
                            "target": {"strategy": "test_id", "test_id": "result"},
                            "expected_text": "Expected result",
                        },
                        {
                            "id": "visible",
                            "type": "element_visible",
                            "target": {"strategy": "test_id", "test_id": "result"},
                        },
                    ],
                }
            ],
        }
    )


def _evaluate_case(case: _Case, bundle: ExecutionBundle) -> BenchmarkCaseResult:
    observed_status = bundle.report.run.status.value
    evidence_count = sum(
        assertion.evidence is not None
        for scene in bundle.report.scene_results
        for assertion in scene.assertion_results
    )
    sequence_valid = [event.sequence for event in bundle.trace_events] == list(
        range(1, len(bundle.trace_events) + 1)
    )
    action_keys = {
        (event.scene_id, event.action_id)
        for event in bundle.trace_events
        if event.kind is TraceEventKind.ACTION_FINISHED
    }
    assertion_keys = {
        (event.scene_id, event.assertion_id)
        for event in bundle.trace_events
        if event.kind is TraceEventKind.ASSERTION_EVALUATED
    }
    correlation_valid = all(
        (action.scene_id, action.action_id) in action_keys
        for action in bundle.report.action_results
    ) and all(
        (assertion.scene_id, assertion.assertion_id) in assertion_keys
        for scene in bundle.report.scene_results
        for assertion in scene.assertion_results
    )
    outcome_correct = observed_status == case.expected_status
    evidence_complete = evidence_count == case.expected_evidence_count
    return BenchmarkCaseResult(
        case_id=case.case_id,
        expected_status=case.expected_status,
        observed_status=observed_status,
        outcome_correct=outcome_correct,
        expected_evidence_count=case.expected_evidence_count,
        observed_evidence_count=evidence_count,
        evidence_complete=evidence_complete,
        trace_sequence_valid=sequence_valid,
        trace_correlation_valid=correlation_valid,
        passed=outcome_correct and evidence_complete and sequence_valid and correlation_valid,
    )
