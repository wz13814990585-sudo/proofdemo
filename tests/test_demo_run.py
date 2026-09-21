"""Tests for legal, illegal, and terminal DemoRun state transitions."""

from datetime import UTC, datetime, timedelta

import pytest

from proofdemo.domain.demo_run import (
    DemoRun,
    DemoRunStatus,
    InvalidRunTransition,
    create_demo_run,
    transition_demo_run,
)

START = datetime(2026, 1, 1, tzinfo=UTC)


def advance_to_running() -> DemoRun:
    created = create_demo_run("todo_demo", now=START)
    validated = transition_demo_run(
        created, DemoRunStatus.VALIDATED, now=START + timedelta(seconds=1)
    )
    return transition_demo_run(validated, DemoRunStatus.RUNNING, now=START + timedelta(seconds=2))


@pytest.mark.parametrize(
    ("terminal_status", "reason"),
    [
        (DemoRunStatus.PASSED, None),
        (DemoRunStatus.FAILED, "Assertion did not match"),
        (DemoRunStatus.BLOCKED, "Authentication required"),
    ],
)
def test_run_reaches_each_terminal_outcome(
    terminal_status: DemoRunStatus, reason: str | None
) -> None:
    running = advance_to_running()

    terminal = transition_demo_run(
        running,
        terminal_status,
        reason=reason,
        now=START + timedelta(seconds=3),
    )

    assert terminal.status is terminal_status
    assert terminal.transitions[-1].reason == reason
    assert len(terminal.transitions) == 3
    assert running.status is DemoRunStatus.RUNNING


def test_run_rejects_skipping_validation() -> None:
    run = create_demo_run("todo_demo", now=START)

    with pytest.raises(InvalidRunTransition, match="CREATED -> RUNNING"):
        transition_demo_run(run, DemoRunStatus.RUNNING)


def test_terminal_run_rejects_further_transitions() -> None:
    passed = transition_demo_run(
        advance_to_running(),
        DemoRunStatus.PASSED,
        now=START + timedelta(seconds=3),
    )

    with pytest.raises(InvalidRunTransition, match="PASSED -> FAILED"):
        transition_demo_run(passed, DemoRunStatus.FAILED, reason="too late")


@pytest.mark.parametrize("status", [DemoRunStatus.FAILED, DemoRunStatus.BLOCKED])
def test_unsuccessful_terminal_outcome_requires_reason(status: DemoRunStatus) -> None:
    with pytest.raises(InvalidRunTransition, match="require a reason"):
        transition_demo_run(advance_to_running(), status)
