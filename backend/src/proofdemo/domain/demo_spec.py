"""Versioned, declarative ProofDemo specification models."""

from __future__ import annotations

from collections import Counter
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

Identifier = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")]


def _duplicates(values: list[str]) -> list[str]:
    """Return repeated identifiers in stable lexical order."""
    return sorted(value for value, count in Counter(values).items() if count > 1)


def _url_origin(url: HttpUrl) -> tuple[str, str, int]:
    """Return a normalized HTTP origin suitable for deterministic comparison."""
    if url.host is None:
        raise ValueError("HTTP URLs must include a host")
    default_port = 443 if url.scheme == "https" else 80
    return (url.scheme, url.host.lower(), url.port or default_port)


class DomainModel(BaseModel):
    """Strict, immutable base for persisted domain values."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class RoleTarget(DomainModel):
    strategy: Literal["role"]
    role: str = Field(min_length=1, max_length=100)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    exact: bool = True


class LabelTarget(DomainModel):
    strategy: Literal["label"]
    label: str = Field(min_length=1, max_length=500)
    exact: bool = True


class TextTarget(DomainModel):
    strategy: Literal["text"]
    text: str = Field(min_length=1, max_length=500)
    exact: bool = True


class TestIdTarget(DomainModel):
    strategy: Literal["test_id"]
    test_id: str = Field(min_length=1, max_length=200)


class CssTarget(DomainModel):
    strategy: Literal["css"]
    selector: str = Field(min_length=1, max_length=1_000)


ElementTarget = Annotated[
    RoleTarget | LabelTarget | TextTarget | TestIdTarget | CssTarget,
    Field(discriminator="strategy"),
]


class ActionModel(DomainModel):
    """Shared identity for one deterministic action."""

    id: Identifier


class GotoAction(ActionModel):
    type: Literal["goto"]
    url: HttpUrl
    timeout_ms: int = Field(default=30_000, ge=1, le=120_000)


class ClickAction(ActionModel):
    type: Literal["click"]
    target: ElementTarget
    timeout_ms: int = Field(default=10_000, ge=1, le=120_000)


class FillAction(ActionModel):
    type: Literal["fill"]
    target: ElementTarget
    value: str = Field(
        max_length=10_000,
        description="Non-sensitive demonstration data; never a credential or secret.",
    )
    timeout_ms: int = Field(default=10_000, ge=1, le=120_000)


class PauseAction(ActionModel):
    """A presentation delay, not a page-readiness primitive."""

    type: Literal["pause"]
    duration_ms: int = Field(ge=1, le=30_000)


class ScreenshotAction(ActionModel):
    type: Literal["screenshot"]
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,99}$")
    full_page: bool = False


Action = Annotated[
    GotoAction | ClickAction | FillAction | PauseAction | ScreenshotAction,
    Field(discriminator="type"),
]


class AssertionModel(DomainModel):
    """Shared identity for one expected outcome."""

    id: Identifier


class ElementVisibleAssertion(AssertionModel):
    type: Literal["element_visible"]
    target: ElementTarget
    timeout_ms: int = Field(default=10_000, ge=1, le=120_000)


class UrlEqualsAssertion(AssertionModel):
    type: Literal["url_equals"]
    expected_url: HttpUrl


class TextContainsAssertion(AssertionModel):
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

    id: Identifier
    title: str = Field(min_length=1, max_length=200)
    goal: str = Field(min_length=1, max_length=1_000)
    actions: tuple[Action, ...] = Field(min_length=1)
    assertions: tuple[Assertion, ...] = ()

    @model_validator(mode="after")
    def validate_child_identifiers(self) -> Scene:
        duplicate_actions = _duplicates([action.id for action in self.actions])
        if duplicate_actions:
            raise ValueError(f"duplicate Action IDs in Scene {self.id}: {duplicate_actions}")

        duplicate_assertions = _duplicates([assertion.id for assertion in self.assertions])
        if duplicate_assertions:
            raise ValueError(f"duplicate Assertion IDs in Scene {self.id}: {duplicate_assertions}")
        return self


class DemoSpec(DomainModel):
    """The authoritative, versioned contract for a requested demo."""

    schema_version: Literal["1.1"]
    id: Identifier
    title: str = Field(min_length=1, max_length=200)
    goal: str = Field(min_length=1, max_length=2_000)
    source_url: HttpUrl
    audience: str | None = Field(default=None, min_length=1, max_length=200)
    language: str = Field(default="en", pattern=r"^[a-z]{2,3}(?:-[A-Z]{2})?$")
    approximate_duration_seconds: int | None = Field(default=None, ge=1, le=3_600)
    scenes: tuple[Scene, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_execution_contract(self) -> DemoSpec:
        duplicate_scenes = _duplicates([scene.id for scene in self.scenes])
        if duplicate_scenes:
            raise ValueError(f"duplicate Scene IDs: {duplicate_scenes}")

        if self.source_url.username is not None or self.source_url.password is not None:
            raise ValueError("source_url must not contain embedded credentials")

        first_action = self.scenes[0].actions[0]
        if not isinstance(first_action, GotoAction):
            raise ValueError("the first DemoSpec action must be goto")

        allowed_origin = _url_origin(self.source_url)
        for scene in self.scenes:
            for action in scene.actions:
                if isinstance(action, GotoAction):
                    if action.url.username is not None or action.url.password is not None:
                        raise ValueError(
                            f"goto Action {scene.id}/{action.id} must not contain credentials"
                        )
                    if _url_origin(action.url) != allowed_origin:
                        raise ValueError(
                            f"goto Action {scene.id}/{action.id} must remain on source_url origin"
                        )
        return self
