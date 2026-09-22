"""Narrow browser contract for deterministic DemoSpec execution."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import JsonValue

from proofdemo.domain.demo_spec import ElementTarget


class BrowserActionError(RuntimeError):
    """A requested browser action could not be completed."""


class BrowserUnavailableError(RuntimeError):
    """The browser runtime could not be started or remained unavailable."""


@dataclass(frozen=True)
class DownloadObservation:
    """Completed-download metadata without leaking a Playwright type."""

    filename: str | None
    completed: bool
    byte_count: int | None = None
    failure: str | None = None


@dataclass(frozen=True)
class AppStateObservation:
    """One JSON-compatible value from the opt-in application-state hook."""

    found: bool
    value: JsonValue = None


@dataclass(frozen=True)
class BrowserLogEntry:
    """One bounded, sanitized browser diagnostic entry."""

    level: str
    message: str


@dataclass(frozen=True)
class BrowserSessionArtifacts:
    """Artifacts finalized only after the browser session closes."""

    video_path: Path | None = None
    logs: tuple[BrowserLogEntry, ...] = ()


@dataclass(frozen=True)
class VisualFocus:
    """A normalized viewport point; no DOM text or input value."""

    x: float
    y: float


@runtime_checkable
class VisualFocusPort(Protocol):
    def visual_focus(self, target: ElementTarget) -> VisualFocus | None:
        """Optionally locate a presentation focus without affecting execution."""


class BrowserPort(Protocol):
    """Operations the application service needs from a browser runtime."""

    def open(self, source_url: str, *, recording_dir: Path | None = None) -> None:
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

    def is_visible(self, target: ElementTarget, *, timeout_ms: int) -> bool:
        """Observe whether a typed target becomes visible."""

    def text_content(self, target: ElementTarget, *, timeout_ms: int) -> str | None:
        """Observe text content, or None when the target cannot be found."""

    def current_url(self) -> str:
        """Observe the current page URL."""

    def completed_download(self, filename: str, *, timeout_ms: int) -> DownloadObservation:
        """Observe completion metadata for a download with an exact filename."""

    def application_state(self, key: str) -> AppStateObservation:
        """Read one top-level key from the opt-in JSON application-state hook."""

    def close(self) -> BrowserSessionArtifacts:
        """Release resources and return finalized session artifacts."""
