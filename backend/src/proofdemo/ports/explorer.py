"""Narrow browser and advisor ports for read-only exploration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from proofdemo.domain.demo_spec import ElementTarget
from proofdemo.domain.exploration import PageObservation
from proofdemo.domain.planning import DemoIntent


class ExplorationUnavailableError(RuntimeError):
    """The isolated browser could not inspect the requested page."""


class InvalidLinkChoice(ValueError):
    """An advisor selected a URL absent from the safe observed frontier."""


@dataclass(frozen=True)
class ControlSnapshot:
    kind: str
    name: str
    target: ElementTarget | None = None
    href: str | None = None


@dataclass(frozen=True)
class PageSnapshot:
    url: str
    title: str
    headings: tuple[str, ...]
    controls: tuple[ControlSnapshot, ...]


class ExplorerPort(Protocol):
    def open(self, source_url: str) -> None:
        """Start an isolated, no-credentials browser session."""

    def visit(self, url: str, *, screenshot_path: Path, timeout_ms: int) -> PageSnapshot:
        """Navigate and return visible metadata; never submit or click."""

    def close(self) -> None:
        """Release the isolated browser session."""


class LinkAdvisorPort(Protocol):
    def choose(
        self,
        intent: DemoIntent,
        pages: tuple[PageObservation, ...],
        candidates: tuple[str, ...],
    ) -> str | None:
        """Suggest one exact observed safe URL, or stop; no browser authority."""
