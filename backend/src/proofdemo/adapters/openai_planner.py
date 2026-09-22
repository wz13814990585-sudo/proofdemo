"""Bounded OpenAI Responses API adapter for DemoSpec structured output."""

from __future__ import annotations

from typing import Any

from openai import OpenAI, OpenAIError

from proofdemo.domain.demo_spec import DemoSpec
from proofdemo.domain.planning import DemoIntent
from proofdemo.ports.planner import (
    PlannerCandidate,
    PlannerResponseError,
    PlannerUnavailableError,
)

PLANNER_INSTRUCTIONS = """\
Produce one reviewable ProofDemo DemoSpec 1.2 candidate from the supplied intent.
Use only the declared source origin. The first action must be goto. Every scene
must contain at least one deterministic assertion. Prefer role, label, text, or
test-id targets over CSS. Literal fill values must be non-sensitive demo data.
Do not include credentials, secrets, cross-origin navigation, JavaScript,
autonomous exploration, or claims that execution has already succeeded.
"""


class OpenAIPlanner:
    """One tool-free, non-persisted structured-output model call."""

    def __init__(self, model: str, *, client: Any | None = None) -> None:
        if not model.strip():
            raise PlannerUnavailableError("an explicit OpenAI planner model is required")
        self._model = model
        try:
            self._client = client or OpenAI()
        except OpenAIError as error:
            raise PlannerUnavailableError("OpenAI client configuration is unavailable") from error

    def plan(self, intent: DemoIntent) -> PlannerCandidate:
        try:
            response = self._client.responses.parse(
                model=self._model,
                instructions=PLANNER_INSTRUCTIONS,
                input=intent.model_dump_json(),
                text_format=DemoSpec,
                max_output_tokens=4_000,
                store=False,
            )
        except OpenAIError as error:
            raise PlannerUnavailableError("OpenAI planner request failed") from error
        parsed = response.output_parsed
        if not isinstance(parsed, DemoSpec):
            raise PlannerResponseError("planner returned no structured DemoSpec candidate")
        return PlannerCandidate(spec=parsed, provider="openai", model=self._model)
