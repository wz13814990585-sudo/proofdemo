"""Versioned, evidence-bearing observations from read-only product exploration."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

from proofdemo.domain.demo_spec import ElementTarget


class ExplorationStatus(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"


class ObservedControl(BaseModel):
    """One visible UI affordance; it never contains an input's current value."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^page-[0-9]+-control-[0-9]+$")
    kind: Literal["link", "button", "input", "element"]
    name: str = Field(min_length=1, max_length=200)
    target: ElementTarget | None = None
    href: HttpUrl | None = None

    @model_validator(mode="after")
    def validate_href(self) -> ObservedControl:
        if self.href is not None and self.kind != "link":
            raise ValueError("only observed links can include an href")
        return self


class PageObservation(BaseModel):
    """A bounded snapshot of one actually visited same-origin page."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    url: HttpUrl
    title: str = Field(max_length=200)
    headings: tuple[str, ...] = Field(max_length=30)
    controls: tuple[ObservedControl, ...] = Field(max_length=120)
    discovered_from: HttpUrl | None = None
    screenshot_path: str | None = None
    screenshot_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def validate_screenshot(self) -> PageObservation:
        if (self.screenshot_path is None) != (self.screenshot_sha256 is None):
            raise ValueError("screenshot path and hash must be present together")
        return self


class ExplorationReport(BaseModel):
    """Exploration evidence, not a declaration that the product is understood."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    source_url: HttpUrl
    status: ExplorationStatus
    pages: tuple[PageObservation, ...] = Field(max_length=5)
    warnings: tuple[str, ...] = Field(max_length=20)
    unvisited_link_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_status(self) -> ExplorationReport:
        if self.status is ExplorationStatus.COMPLETE and self.unvisited_link_count:
            raise ValueError("complete exploration cannot leave unvisited safe links")
        if self.status is ExplorationStatus.BLOCKED and not self.warnings:
            raise ValueError("blocked exploration requires a reason")
        return self
