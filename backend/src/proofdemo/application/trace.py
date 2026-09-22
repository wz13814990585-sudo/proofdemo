"""Versioned immutable trace events for execution and verification facts."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue, field_validator


class TraceEventKind(StrEnum):
    RUN_TRANSITION = "RUN_TRANSITION"
    ACTION_STARTED = "ACTION_STARTED"
    ACTION_FINISHED = "ACTION_FINISHED"
    ASSERTION_EVALUATED = "ASSERTION_EVALUATED"
    SCENE_EVALUATED = "SCENE_EVALUATED"
    ARTIFACT_CAPTURED = "ARTIFACT_CAPTURED"
    ARTIFACT_CAPTURE_FAILED = "ARTIFACT_CAPTURE_FAILED"
    BROWSER_SESSION_CLOSED = "BROWSER_SESSION_CLOSED"
    PREVIEW_UPDATED = "PREVIEW_UPDATED"


class TraceEvent(BaseModel):
    """One ordered fact; payloads must stay JSON-compatible and non-sensitive."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    sequence: int = Field(ge=1)
    occurred_at: AwareDatetime
    kind: TraceEventKind
    run_id: UUID
    spec_id: str
    scene_id: str | None = None
    action_id: str | None = None
    assertion_id: str | None = None
    status: str | None = None
    data: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("occurred_at")
    @classmethod
    def normalize_timestamp(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)


class TraceRecorder:
    """Append-only in-memory recorder with injectable UTC clock."""

    def __init__(
        self,
        run_id: UUID,
        spec_id: str,
        *,
        clock: Callable[[], datetime] | None = None,
        observer: Callable[[TraceEvent], None] | None = None,
    ) -> None:
        self._run_id = run_id
        self._spec_id = spec_id
        self._clock = clock or (lambda: datetime.now(UTC))
        self._events: list[TraceEvent] = []
        self._observer = observer

    @property
    def events(self) -> tuple[TraceEvent, ...]:
        return tuple(self._events)

    def record(
        self,
        kind: TraceEventKind,
        *,
        scene_id: str | None = None,
        action_id: str | None = None,
        assertion_id: str | None = None,
        status: str | None = None,
        data: dict[str, JsonValue] | None = None,
    ) -> TraceEvent:
        event = TraceEvent(
            sequence=len(self._events) + 1,
            occurred_at=self._clock(),
            kind=kind,
            run_id=self._run_id,
            spec_id=self._spec_id,
            scene_id=scene_id,
            action_id=action_id,
            assertion_id=assertion_id,
            status=status,
            data=data or {},
        )
        self._events.append(event)
        if self._observer is not None:
            # A live UI subscriber is never execution or verification truth.
            with suppress(Exception):
                self._observer(event)
        return event
