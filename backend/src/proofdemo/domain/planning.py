"""Validated natural-language planning input."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class DemoIntent(BaseModel):
    """Non-sensitive user intent supplied to a bounded planner call."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_url: HttpUrl
    goal: str = Field(min_length=1, max_length=2_000)
    audience: str | None = Field(default=None, min_length=1, max_length=200)
    language: str = Field(default="en", pattern=r"^[a-z]{2,3}(?:-[A-Z]{2})?$")
    approximate_duration_seconds: int | None = Field(default=None, ge=1, le=3_600)

    @model_validator(mode="after")
    def reject_embedded_credentials(self) -> DemoIntent:
        if self.source_url.username is not None or self.source_url.password is not None:
            raise ValueError("planning source_url must not contain embedded credentials")
        return self
