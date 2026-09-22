"""Portable non-sensitive recipe contracts for deterministic replay."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from proofdemo.domain.demo_spec import DemoSpec


class RecipeModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RecipeRequirements(RecipeModel):
    minimum_proofdemo_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    demo_spec_schema: str = Field(pattern=r"^\d+\.\d+$")
    execution_report_schema: str = Field(pattern=r"^\d+\.\d+$")
    artifact_manifest_schema: str = Field(pattern=r"^\d+\.\d+$")


class RecipeExecutionProfile(RecipeModel):
    browser_engine: str
    headless: bool
    viewport_width: int = Field(gt=0)
    viewport_height: int = Field(gt=0)
    locale: str
    output_width: int = Field(gt=0)
    output_height: int = Field(gt=0)
    output_fps: int = Field(gt=0)


class RecipeArtifactProvenance(RecipeModel):
    path: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class RecipeProvenance(RecipeModel):
    source_run_id: UUID
    source_run_status: Literal["PASSED"] = "PASSED"
    execution_report: RecipeArtifactProvenance
    final_video: RecipeArtifactProvenance


class DemoRecipe(RecipeModel):
    """Canonical input plus compatibility and verified-source provenance."""

    schema_version: str = Field(pattern=r"^\d+\.\d+$")
    id: UUID
    created_at: AwareDatetime
    created_by_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    spec_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    spec: DemoSpec
    requirements: RecipeRequirements
    execution_profile: RecipeExecutionProfile
    provenance: RecipeProvenance

    @field_validator("created_at")
    @classmethod
    def normalize_timestamp(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)


def demo_spec_sha256(spec: DemoSpec) -> str:
    """Fingerprint canonical semantic JSON, independent of file formatting."""
    payload = spec.model_dump_json(exclude_none=False, by_alias=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
