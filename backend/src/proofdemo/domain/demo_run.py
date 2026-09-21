"""Deterministic DemoRun lifecycle and transition invariants."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DemoRunStatus(StrEnum):
    CREATED = "CREATED"
    VALIDATED = "VALIDATED"
    RUNNING = "RUNNING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


TERMINAL_STATUSES = frozenset({DemoRunStatus.PASSED, DemoRunStatus.FAILED, DemoRunStatus.BLOCKED})

ALLOWED_TRANSITIONS = MappingProxyType(
    {
        DemoRunStatus.CREATED: frozenset(
            {DemoRunStatus.VALIDATED, DemoRunStatus.FAILED, DemoRunStatus.BLOCKED}
        ),
        DemoRunStatus.VALIDATED: frozenset(
            {DemoRunStatus.RUNNING, DemoRunStatus.FAILED, DemoRunStatus.BLOCKED}
        ),
        DemoRunStatus.RUNNING: TERMINAL_STATUSES,
        DemoRunStatus.PASSED: frozenset(),
        DemoRunStatus.FAILED: frozenset(),
        DemoRunStatus.BLOCKED: frozenset(),
    }
)


class InvalidRunTransition(ValueError):
    """Raised when a DemoRun state transition violates domain rules."""


class RunTransition(BaseModel):
    """Immutable audit entry for a single accepted state transition."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    from_status: DemoRunStatus
    to_status: DemoRunStatus
    occurred_at: datetime
    reason: str | None = Field(default=None, min_length=1, max_length=2_000)

    @model_validator(mode="after")
    def validate_transition(self) -> RunTransition:
        if self.to_status not in ALLOWED_TRANSITIONS[self.from_status]:
            raise ValueError(f"illegal DemoRun transition: {self.from_status} -> {self.to_status}")
        if self.to_status in {DemoRunStatus.FAILED, DemoRunStatus.BLOCKED} and not self.reason:
            raise ValueError(f"{self.to_status} transitions require a reason")
        return self


class DemoRun(BaseModel):
    """Immutable state of one DemoSpec execution attempt."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    spec_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    status: DemoRunStatus = DemoRunStatus.CREATED
    created_at: datetime
    updated_at: datetime
    transitions: tuple[RunTransition, ...] = ()

    @model_validator(mode="after")
    def validate_history(self) -> DemoRun:
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot be earlier than created_at")
        if not self.transitions:
            if self.status is not DemoRunStatus.CREATED:
                raise ValueError("a DemoRun without transition history must be CREATED")
            return self

        expected_from = DemoRunStatus.CREATED
        previous_time = self.created_at
        for transition in self.transitions:
            if transition.from_status is not expected_from:
                raise ValueError("DemoRun transition history is not contiguous")
            if transition.occurred_at < previous_time:
                raise ValueError("DemoRun transition timestamps are not monotonic")
            expected_from = transition.to_status
            previous_time = transition.occurred_at

        if self.status is not self.transitions[-1].to_status:
            raise ValueError("DemoRun status does not match transition history")
        if self.updated_at != self.transitions[-1].occurred_at:
            raise ValueError("updated_at must match the latest transition")
        return self


def create_demo_run(spec_id: str, *, now: datetime | None = None) -> DemoRun:
    """Create a new run without relying on mutable global state."""
    timestamp = now or datetime.now(UTC)
    return DemoRun(
        id=uuid4(),
        spec_id=spec_id,
        created_at=timestamp,
        updated_at=timestamp,
    )


def transition_demo_run(
    run: DemoRun,
    to_status: DemoRunStatus,
    *,
    reason: str | None = None,
    now: datetime | None = None,
) -> DemoRun:
    """Return a new run after applying one legal, auditable transition."""
    if to_status not in ALLOWED_TRANSITIONS[run.status]:
        raise InvalidRunTransition(f"illegal DemoRun transition: {run.status} -> {to_status}")

    timestamp = now or datetime.now(UTC)
    if timestamp < run.updated_at:
        raise InvalidRunTransition("transition timestamp cannot move backwards")

    try:
        transition = RunTransition(
            from_status=run.status,
            to_status=to_status,
            occurred_at=timestamp,
            reason=reason,
        )
    except ValueError as error:
        raise InvalidRunTransition(str(error)) from error

    return run.model_copy(
        update={
            "status": to_status,
            "updated_at": timestamp,
            "transitions": (*run.transitions, transition),
        }
    )
