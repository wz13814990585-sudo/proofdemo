"""Explicit DeepSeek routing over its documented Responses-compatible endpoint."""

from __future__ import annotations

from os import getenv

from openai import OpenAI, OpenAIError

from proofdemo.adapters.openai_exploration import OpenAILinkAdvisor
from proofdemo.adapters.openai_planner import OpenAIPlanner
from proofdemo.ports.explorer import ExplorationUnavailableError
from proofdemo.ports.planner import PlannerUnavailableError

DEEPSEEK_BASE_URL = "https://api.deepseek.com"


class _DeepSeekConfigurationError(RuntimeError):
    """A local provider prerequisite is missing; never includes secret values."""


def _client() -> OpenAI:
    key = getenv("DEEPSEEK_API_KEY")
    if key is None or not key.strip():
        raise _DeepSeekConfigurationError("DEEPSEEK_API_KEY is not configured")
    try:
        return OpenAI(api_key=key, base_url=DEEPSEEK_BASE_URL, timeout=60.0, max_retries=0)
    except OpenAIError as error:
        raise _DeepSeekConfigurationError("DeepSeek client configuration is unavailable") from error


class DeepSeekPlanner(OpenAIPlanner):
    """Reuse the typed Responses parser, but keep key and endpoint provider-scoped."""

    def __init__(self, model: str) -> None:
        if not model.strip():
            raise PlannerUnavailableError("PROOFDEMO_DEEPSEEK_MODEL is not configured")
        try:
            client = _client()
        except _DeepSeekConfigurationError as error:
            raise PlannerUnavailableError(str(error)) from error
        super().__init__(model, client=client, provider="deepseek")


class DeepSeekLinkAdvisor(OpenAILinkAdvisor):
    """Rank observed links only; application grounding retains final authority."""

    def __init__(self, model: str) -> None:
        if not model.strip():
            raise ExplorationUnavailableError("PROOFDEMO_DEEPSEEK_MODEL is not configured")
        try:
            client = _client()
        except _DeepSeekConfigurationError as error:
            raise ExplorationUnavailableError(str(error)) from error
        super().__init__(model, client=client)
