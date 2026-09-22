"""Release-gate tests for the deterministic Stage 10 benchmark."""

from __future__ import annotations

from pathlib import Path

from proofdemo.cli import EXIT_EXECUTED, run
from proofdemo.evaluation.benchmark import (
    BenchmarkService,
    BenchmarkStatus,
    BenchmarkThresholds,
)


def test_release_benchmark_meets_all_v1_thresholds() -> None:
    report = BenchmarkService().run()

    assert report.status is BenchmarkStatus.PASSED
    assert report.case_count == 4
    assert report.passed_case_count == 4
    assert report.metrics.terminal_outcome_accuracy == 1.0
    assert report.metrics.expected_evidence_coverage == 1.0
    assert report.metrics.trace_integrity == 1.0
    assert {case.observed_status for case in report.cases} == {
        "PASSED",
        "FAILED",
        "BLOCKED",
    }


def test_benchmark_fails_when_threshold_is_unreachable() -> None:
    report = BenchmarkService().run(
        BenchmarkThresholds(
            terminal_outcome_accuracy=1.1,
            expected_evidence_coverage=1.0,
            trace_integrity=1.0,
        ).model_copy()
    )

    assert report.status is BenchmarkStatus.FAILED


def test_benchmark_cli_writes_repeatable_offline_report(tmp_path: Path) -> None:
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"

    assert run(["benchmark", "--output", str(first)]) == EXIT_EXECUTED
    assert run(["benchmark", "--output", str(second)]) == EXIT_EXECUTED

    assert first.read_bytes() == second.read_bytes()
    assert not list(tmp_path.glob(".*.json.*"))
