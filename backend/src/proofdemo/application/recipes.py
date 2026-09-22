"""Verified recipe creation and deterministic replay compatibility checks."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from proofdemo import __version__
from proofdemo.application.artifacts import (
    ArtifactDeclaration,
    ArtifactKind,
    ArtifactManifest,
    ArtifactRecord,
    ArtifactWriter,
)
from proofdemo.application.execution import ExecutionBundle
from proofdemo.application.verification import VerificationStatus
from proofdemo.domain.demo_run import DemoRunStatus
from proofdemo.domain.demo_spec import DemoSpec
from proofdemo.domain.recipe import (
    DemoRecipe,
    RecipeArtifactProvenance,
    RecipeExecutionProfile,
    RecipeProvenance,
    RecipeRequirements,
    demo_spec_sha256,
)

RECIPE_SCHEMA = "1.0"
DEMO_SPEC_SCHEMA = "1.2"
EXECUTION_REPORT_SCHEMA = "3.0"
ARTIFACT_MANIFEST_SCHEMA = "1.0"
EXECUTION_PROFILE = RecipeExecutionProfile(
    browser_engine="chromium",
    headless=True,
    viewport_width=1280,
    viewport_height=720,
    locale="en-US",
    output_width=1920,
    output_height=1080,
    output_fps=30,
)


class CompatibilityStatus(StrEnum):
    COMPATIBLE = "COMPATIBLE"
    INCOMPATIBLE = "INCOMPATIBLE"


class CompatibilityIssue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    message: str


class ReplayPreflight(BaseModel):
    """Machine-readable compatibility and source provenance decision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    recipe_id: str
    source_run_id: str
    spec_id: str
    spec_sha256: str
    proofdemo_version: str
    status: CompatibilityStatus
    issues: tuple[CompatibilityIssue, ...]


@dataclass(frozen=True)
class RecipeCreationResult:
    recipe: DemoRecipe
    declaration: ArtifactDeclaration


class RecipeRefusedError(RuntimeError):
    """A recipe source is unverified, inconsistent, or fails integrity checks."""


class RecipeService:
    RECIPE_PATH = "demo_recipe.json"
    PREFLIGHT_PATH = "replay_preflight.json"

    def create(
        self,
        spec: DemoSpec,
        bundle: ExecutionBundle,
        manifest: ArtifactManifest,
        artifact_dir: Path,
    ) -> RecipeCreationResult:
        report = bundle.report
        if (
            report.run.status is not DemoRunStatus.PASSED
            or report.verification_status is not VerificationStatus.PASSED
        ):
            raise RecipeRefusedError("only a verified PASSED run can produce a recipe")
        if (
            spec.id != report.run.spec_id
            or manifest.run_id != str(report.run.id)
            or manifest.spec_id != spec.id
            or manifest.run_status != DemoRunStatus.PASSED.value
        ):
            raise RecipeRefusedError("recipe source identities do not agree")
        integrity_errors = ArtifactWriter.verify(artifact_dir, manifest)
        if integrity_errors:
            raise RecipeRefusedError(f"artifact integrity check failed: {integrity_errors[0]}")
        report_record = self._record(
            manifest,
            ArtifactKind.EXECUTION_REPORT,
            "execution_report.json",
        )
        video_record = self._final_video(manifest)
        recipe = DemoRecipe(
            schema_version=RECIPE_SCHEMA,
            id=uuid4(),
            created_at=report.run.transitions[-1].occurred_at,
            created_by_version=__version__,
            spec_sha256=demo_spec_sha256(spec),
            spec=spec,
            requirements=RecipeRequirements(
                minimum_proofdemo_version=__version__,
                demo_spec_schema=DEMO_SPEC_SCHEMA,
                execution_report_schema=EXECUTION_REPORT_SCHEMA,
                artifact_manifest_schema=ARTIFACT_MANIFEST_SCHEMA,
            ),
            execution_profile=EXECUTION_PROFILE,
            provenance=RecipeProvenance(
                source_run_id=report.run.id,
                execution_report=RecipeArtifactProvenance(
                    path=report_record.path,
                    sha256=report_record.sha256,
                ),
                final_video=RecipeArtifactProvenance(
                    path=video_record.path,
                    sha256=video_record.sha256,
                ),
            ),
        )
        self._atomic_text(
            self._contained(artifact_dir, self.RECIPE_PATH),
            recipe.model_dump_json(indent=2) + "\n",
        )
        return RecipeCreationResult(
            recipe=recipe,
            declaration=ArtifactDeclaration(
                path=self.RECIPE_PATH,
                kind=ArtifactKind.DEMO_RECIPE,
            ),
        )

    @staticmethod
    def compatibility(recipe: DemoRecipe) -> ReplayPreflight:
        issues: list[CompatibilityIssue] = []

        def require(condition: bool, code: str, message: str) -> None:
            if not condition:
                issues.append(CompatibilityIssue(code=code, message=message))

        require(
            recipe.schema_version == RECIPE_SCHEMA,
            "RECIPE_SCHEMA_UNSUPPORTED",
            f"recipe schema {recipe.schema_version} is not supported",
        )
        require(
            recipe.requirements.demo_spec_schema == DEMO_SPEC_SCHEMA,
            "DEMOSPEC_SCHEMA_UNSUPPORTED",
            "recipe requires an unsupported DemoSpec schema",
        )
        require(
            recipe.requirements.execution_report_schema == EXECUTION_REPORT_SCHEMA,
            "REPORT_SCHEMA_UNSUPPORTED",
            "recipe requires an unsupported execution report schema",
        )
        require(
            recipe.requirements.artifact_manifest_schema == ARTIFACT_MANIFEST_SCHEMA,
            "MANIFEST_SCHEMA_UNSUPPORTED",
            "recipe requires an unsupported artifact manifest schema",
        )
        require(
            _version_tuple(recipe.requirements.minimum_proofdemo_version)
            <= _version_tuple(__version__),
            "ENGINE_VERSION_UNSUPPORTED",
            "recipe requires a newer ProofDemo version",
        )
        require(
            recipe.execution_profile == EXECUTION_PROFILE,
            "EXECUTION_PROFILE_UNSUPPORTED",
            "recipe execution profile is not supported by this runtime",
        )
        require(
            recipe.spec.schema_version == DEMO_SPEC_SCHEMA,
            "EMBEDDED_SPEC_UNSUPPORTED",
            "embedded DemoSpec schema is not supported",
        )
        require(
            recipe.spec_sha256 == demo_spec_sha256(recipe.spec),
            "SPEC_FINGERPRINT_MISMATCH",
            "embedded DemoSpec does not match its fingerprint",
        )
        return ReplayPreflight(
            recipe_id=str(recipe.id),
            source_run_id=str(recipe.provenance.source_run_id),
            spec_id=recipe.spec.id,
            spec_sha256=recipe.spec_sha256,
            proofdemo_version=__version__,
            status=(
                CompatibilityStatus.COMPATIBLE if not issues else CompatibilityStatus.INCOMPATIBLE
            ),
            issues=tuple(issues),
        )

    def write_preflight(
        self, preflight: ReplayPreflight, artifact_dir: Path
    ) -> ArtifactDeclaration:
        self._atomic_text(
            self._contained(artifact_dir, self.PREFLIGHT_PATH),
            preflight.model_dump_json(indent=2) + "\n",
        )
        return ArtifactDeclaration(
            path=self.PREFLIGHT_PATH,
            kind=ArtifactKind.REPLAY_PREFLIGHT,
        )

    @staticmethod
    def _record(
        manifest: ArtifactManifest,
        kind: ArtifactKind,
        path: str,
    ) -> ArtifactRecord:
        record = next(
            (item for item in manifest.artifacts if item.kind is kind and item.path == path),
            None,
        )
        if record is None:
            raise RecipeRefusedError(f"recipe source artifact is missing: {path}")
        return record

    @staticmethod
    def _final_video(manifest: ArtifactManifest) -> ArtifactRecord:
        narrated = next(
            (item for item in manifest.artifacts if item.kind is ArtifactKind.NARRATED_VIDEO),
            None,
        )
        if narrated is not None:
            return narrated
        return RecipeService._record(manifest, ArtifactKind.FINAL_VIDEO, "demo.mp4")

    @staticmethod
    def _contained(artifact_dir: Path, relative_path: str) -> Path:
        root = artifact_dir.resolve()
        path = (root / relative_path).resolve()
        if not path.is_relative_to(root):
            raise RecipeRefusedError("recipe path escaped artifact directory")
        return path

    @staticmethod
    def _atomic_text(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as temporary:
            temporary.write(content)
            temporary.flush()
            temporary_path = Path(temporary.name)
        temporary_path.replace(path)


def _version_tuple(value: str) -> tuple[int, int, int]:
    major, minor, patch = value.split(".")
    return int(major), int(minor), int(patch)
