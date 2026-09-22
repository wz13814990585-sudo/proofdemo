"""Bounded intent-to-DemoSpec planning orchestration."""

from __future__ import annotations

from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, HttpUrl

from proofdemo.domain.demo_spec import DemoSpec
from proofdemo.domain.planning import DemoIntent
from proofdemo.ports.planner import PlannerPort


class InvalidPlannerCandidate(ValueError):
    """A shaped candidate violates deterministic request boundaries."""


class PlanningResult(BaseModel):
    """Review-required candidate plus non-secret provider provenance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    spec: DemoSpec
    provider: str
    model: str
    requires_review: bool = True


def _origin(url: HttpUrl) -> tuple[str, str, int]:
    parsed = urlsplit(str(url))
    if parsed.hostname is None:
        raise InvalidPlannerCandidate("planned URL has no host")
    default_port = 443 if parsed.scheme == "https" else 80
    return parsed.scheme, parsed.hostname.lower(), parsed.port or default_port


class PlanningService:
    """Revalidate provider candidates against the original deterministic intent."""

    def __init__(self, planner: PlannerPort) -> None:
        self._planner = planner

    def plan(self, intent: DemoIntent) -> PlanningResult:
        candidate = self._planner.plan(intent)
        spec = DemoSpec.model_validate(candidate.spec.model_dump(mode="json"))
        if _origin(spec.source_url) != _origin(intent.source_url):
            raise InvalidPlannerCandidate("planned DemoSpec changed the requested source origin")
        return PlanningResult(
            spec=spec,
            provider=candidate.provider,
            model=candidate.model,
        )
