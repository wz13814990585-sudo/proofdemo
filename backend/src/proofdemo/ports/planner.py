"""Application-owned boundary for bounded DemoSpec planning."""

from dataclasses import dataclass
from typing import Protocol

from proofdemo.domain.demo_spec import DemoSpec
from proofdemo.domain.planning import DemoIntent


class PlannerUnavailableError(RuntimeError):
    """Planner configuration or provider infrastructure is unavailable."""


class PlannerResponseError(RuntimeError):
    """The provider refused or returned no usable structured candidate."""


@dataclass(frozen=True)
class PlannerCandidate:
    spec: DemoSpec
    provider: str
    model: str


class PlannerPort(Protocol):
    def plan(self, intent: DemoIntent) -> PlannerCandidate:
        """Make one bounded structured-output call for a candidate DemoSpec."""
