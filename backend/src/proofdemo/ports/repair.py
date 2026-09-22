"""Application-owned boundary for bounded repair proposals."""

from dataclasses import dataclass
from typing import Protocol

from proofdemo.domain.repair import RepairRequest, SceneRepairProposal


class RepairUnavailableError(RuntimeError):
    """Repair provider configuration or infrastructure is unavailable."""


class RepairResponseError(RuntimeError):
    """The provider refused or returned no structured repair candidate."""


@dataclass(frozen=True)
class RepairCandidate:
    proposal: SceneRepairProposal
    provider: str
    model: str


class RepairPort(Protocol):
    def propose(self, request: RepairRequest) -> RepairCandidate:
        """Make one tool-free structured call for a review-required proposal."""
