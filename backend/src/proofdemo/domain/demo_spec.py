"""Versioned, declarative ProofDemo specification models."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class DomainModel(BaseModel):
    """Strict, immutable base for persisted domain values."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ElementTarget(DomainModel):
    """A stable description of a browser element to resolve later."""

    strategy: Literal["role", "label", "text", "test_id", "css"]
    value: str = Field(min_length=1, max_length=500)
    name: str | None = Field(default=None, min_length=1, max_length=200)


class GotoAction(DomainModel):
    type: Literal["goto"]
    url: HttpUrl
    timeout_ms: int = Field(default=30_000, ge=1, le=120_000)


class ClickAction(DomainModel):
    type: Literal["click"]
    target: ElementTarget
    timeout_ms: int = Field(default=10_000, ge=1, le=120_000)


class FillAction(DomainModel):
    type: Literal["fill"]
    target: ElementTarget
    value: str = Field(max_length=10_000)
    timeout_ms: int = Field(default=10_000, ge=1, le=120_000)


class WaitAction(DomainModel):
    type: Literal["wait"]
    duration_ms: int = Field(ge=1, le=30_000)


class ScreenshotAction(DomainModel):
    type: Literal["screenshot"]
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,99}$")
    full_page: bool = False


Action = Annotated[
    GotoAction | ClickAction | FillAction | WaitAction | ScreenshotAction,
    Field(discriminator="type"),
]


class ElementVisibleAssertion(DomainModel):
    type: Literal["element_visible"]
    target: ElementTarget
    timeout_ms: int = Field(default=10_000, ge=1, le=120_000)


class UrlEqualsAssertion(DomainModel):
    type: Literal["url_equals"]
    expected_url: HttpUrl


class TextContainsAssertion(DomainModel):
    type: Literal["text_contains"]
    target: ElementTarget
    expected_text: str = Field(min_length=1, max_length=2_000)
    timeout_ms: int = Field(default=10_000, ge=1, le=120_000)


Assertion = Annotated[
    ElementVisibleAssertion | UrlEqualsAssertion | TextContainsAssertion,
    Field(discriminator="type"),
]


class Scene(DomainModel):
    """An ordered story beat. Assertion execution starts in Stage 2."""

    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    title: str = Field(min_length=1, max_length=200)
    goal: str = Field(min_length=1, max_length=1_000)
    actions: tuple[Action, ...] = Field(min_length=1)
    assertions: tuple[Assertion, ...] = ()


class DemoSpec(DomainModel):
    """The authoritative, versioned contract for a requested demo."""

    schema_version: Literal["1.0"]
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    title: str = Field(min_length=1, max_length=200)
    goal: str = Field(min_length=1, max_length=2_000)
    source_url: HttpUrl
    audience: str | None = Field(default=None, min_length=1, max_length=200)
    language: str = Field(default="en", pattern=r"^[a-z]{2,3}(?:-[A-Z]{2})?$")
    approximate_duration_seconds: int | None = Field(default=None, ge=1, le=3_600)
    scenes: tuple[Scene, ...] = Field(min_length=1)
