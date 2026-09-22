"""Bounded OpenAI structured-output adapter for scene target repair."""

from __future__ import annotations

from typing import Any

from openai import OpenAI, OpenAIError

from proofdemo.domain.repair import RepairRequest, SceneRepairProposal
from proofdemo.ports.repair import (
    RepairCandidate,
    RepairResponseError,
    RepairUnavailableError,
)

REPAIR_INSTRUCTIONS = """\
Propose the smallest target-only repair for exactly the supplied scene.
Return replacements only for diagnosed click/fill actions or element-visible/
text-contains assertions. Preserve every ID and all behavior. Do not add steps,
change URLs, values, expected results, timeouts, goals, or claim success. Use the
user hint only as locator guidance. The proposal requires human review.
"""


class OpenAIRepairAdapter:
    """One tool-free, non-persisted repair proposal call."""

    def __init__(self, model: str, *, client: Any | None = None) -> None:
        if not model.strip():
            raise RepairUnavailableError("an explicit OpenAI repair model is required")
        self._model = model
        try:
            self._client = client or OpenAI()
        except OpenAIError as error:
            raise RepairUnavailableError(
                "OpenAI repair client configuration is unavailable"
            ) from error

    def propose(self, request: RepairRequest) -> RepairCandidate:
        try:
            response = self._client.responses.parse(
                model=self._model,
                instructions=REPAIR_INSTRUCTIONS,
                input=request.model_dump_json(),
                text_format=SceneRepairProposal,
                max_output_tokens=2_000,
                store=False,
            )
        except OpenAIError as error:
            raise RepairUnavailableError("OpenAI repair request failed") from error
        parsed = response.output_parsed
        if not isinstance(parsed, SceneRepairProposal):
            raise RepairResponseError("repair provider returned no structured proposal")
        return RepairCandidate(proposal=parsed, provider="openai", model=self._model)
