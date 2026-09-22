"""Narrow browser contract for deterministic DemoSpec execution."""

from pathlib import Path
from typing import Protocol

from proofdemo.domain.demo_spec import ElementTarget


class BrowserActionError(RuntimeError):
    """A requested browser action could not be completed."""


class BrowserUnavailableError(RuntimeError):
    """The browser runtime could not be started or remained unavailable."""


class BrowserPort(Protocol):
    """Operations the application service needs from a browser runtime."""

    def open(self, source_url: str) -> None:
        """Start an isolated browser session constrained to the source origin."""

    def goto(self, url: str, *, timeout_ms: int) -> None:
        """Navigate within the source origin."""

    def click(self, target: ElementTarget, *, timeout_ms: int) -> None:
        """Click the element resolved by a typed target."""

    def fill(self, target: ElementTarget, value: str, *, timeout_ms: int) -> None:
        """Fill the element resolved by a typed target."""

    def pause(self, duration_ms: int) -> None:
        """Wait for a bounded presentation delay."""

    def screenshot(self, path: Path, *, full_page: bool) -> None:
        """Capture an explicitly requested screenshot."""

    def close(self) -> None:
        """Release all browser resources. Calling close repeatedly is safe."""
