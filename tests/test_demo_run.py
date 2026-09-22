"""Tests for hardened DemoRun state and timestamp invariants."""

from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

import pytest

from proofdemo.domain.demo_run import (
    DemoRun,
    DemoRunStatus,
    InvalidRunTimestamp,
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


def test_run_reaches_executed_without_claiming_verification() -> None:
    running = advance_to_running()

    executed = transition_demo_run(
        running,
        DemoRunStatus.EXECUTED,
        now=START + timedelta(seconds=3),
    )

    assert executed.status is DemoRunStatus.EXECUTED
    assert len(executed.transitions) == 3
    assert running.status is DemoRunStatus.RUNNING


@pytest.mark.parametrize(
    ("terminal_status", "reason"),
    [
        (DemoRunStatus.FAILED, "Action could not be completed"),
        (DemoRunStatus.BLOCKED, "Authentication required"),
    ],
)
def test_run_reaches_unsuccessful_terminal_outcome(
    terminal_status: DemoRunStatus, reason: str
) -> None:
    terminal = transition_demo_run(
        advance_to_running(),
        terminal_status,
        reason=reason,
        now=START + timedelta(seconds=3),
    )

    assert terminal.status is terminal_status
    assert terminal.transitions[-1].reason == reason


@pytest.mark.parametrize("start_status", [DemoRunStatus.RUNNING, DemoRunStatus.EXECUTED])
def test_passed_is_reserved_for_future_verification(start_status: DemoRunStatus) -> None:
    run = advance_to_running()
    if start_status is DemoRunStatus.EXECUTED:
        run = transition_demo_run(
            run,
            DemoRunStatus.EXECUTED,
            now=START + timedelta(seconds=3),
        )

    with pytest.raises(InvalidRunTransition, match="PASSED"):
        transition_demo_run(run, DemoRunStatus.PASSED)


def test_run_rejects_skipping_validation() -> None:
    run = create_demo_run("todo_demo", now=START)

    with pytest.raises(InvalidRunTransition, match="CREATED -> RUNNING"):
        transition_demo_run(run, DemoRunStatus.RUNNING)


def test_terminal_run_rejects_further_transitions() -> None:
    failed = transition_demo_run(
        advance_to_running(),
        DemoRunStatus.FAILED,
        reason="Action failed",
        now=START + timedelta(seconds=3),
    )

    with pytest.raises(InvalidRunTransition, match="FAILED -> BLOCKED"):
        transition_demo_run(failed, DemoRunStatus.BLOCKED, reason="too late")


@pytest.mark.parametrize("status", [DemoRunStatus.FAILED, DemoRunStatus.BLOCKED])
def test_unsuccessful_terminal_outcome_requires_reason(status: DemoRunStatus) -> None:
    with pytest.raises(InvalidRunTransition, match="require a reason"):
        transition_demo_run(advance_to_running(), status)


def test_run_rejects_naive_creation_timestamp() -> None:
    with pytest.raises(InvalidRunTimestamp, match="timezone-aware"):
        create_demo_run("todo_demo", now=datetime(2026, 1, 1))


def test_run_rejects_naive_transition_timestamp() -> None:
    with pytest.raises(InvalidRunTimestamp, match="timezone-aware"):
        transition_demo_run(
            create_demo_run("todo_demo", now=START),
            DemoRunStatus.VALIDATED,
            now=datetime(2026, 1, 1, 0, 0, 1),
        )


def test_run_normalizes_aware_timestamps_to_utc() -> None:
    sydney_offset = timezone(timedelta(hours=10))

    run = create_demo_run(
        "todo_demo",
        now=datetime(2026, 1, 1, 10, 0, tzinfo=sydney_offset),
    )

    assert run.created_at == START
    assert run.created_at.tzinfo is UTC


def test_deserialized_run_normalizes_aware_timestamps_to_utc() -> None:
    sydney_offset = timezone(timedelta(hours=10))
    local_time = datetime(2026, 1, 1, 10, 0, tzinfo=sydney_offset)

    run = DemoRun(
        id=uuid4(),
        spec_id="todo_demo",
        created_at=local_time,
        updated_at=local_time,
    )

    assert run.created_at == START
    assert run.created_at.tzinfo is UTC
    assert run.updated_at.tzinfo is UTC
