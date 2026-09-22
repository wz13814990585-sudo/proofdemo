"""Strict review-required contracts for one-scene target repair."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from proofdemo.domain.demo_spec import ElementTarget, Scene


class RepairModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TargetReplacement(RepairModel):
    entity: Literal["action", "assertion"]
    entity_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    target: ElementTarget


class SceneRepairProposal(RepairModel):
    schema_version: Literal["1.0"] = "1.0"
    source_recipe_id: UUID
    source_spec_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    scene_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    diagnostic_categories: tuple[str, ...] = Field(min_length=1, max_length=10)
    replacements: tuple[TargetReplacement, ...] = Field(min_length=1, max_length=5)
    rationale: str = Field(min_length=1, max_length=1_000)
    requires_review: Literal[True] = True


class RepairFindingContext(RepairModel):
    category: str
    action_id: str | None = None
    assertion_id: str | None = None
    description: str = Field(min_length=1, max_length=2_000)


class RepairRequest(RepairModel):
    recipe_id: UUID
    spec_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    scene: Scene
    findings: tuple[RepairFindingContext, ...] = Field(min_length=1)
    user_hint: str | None = Field(default=None, min_length=1, max_length=1_000)
