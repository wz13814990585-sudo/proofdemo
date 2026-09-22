"""Atomic Stage 3 artifact persistence and manifest integrity checks."""

from __future__ import annotations

import hashlib
import json
import mimetypes
from collections.abc import Sequence
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from proofdemo.application.execution import ExecutionBundle


class ArtifactKind(StrEnum):
    EXECUTION_REPORT = "EXECUTION_REPORT"
    TRACE = "TRACE"
    BROWSER_LOG = "BROWSER_LOG"
    REQUESTED_SCREENSHOT = "REQUESTED_SCREENSHOT"
    EVIDENCE_SCREENSHOT = "EVIDENCE_SCREENSHOT"
    BROWSER_VIDEO = "BROWSER_VIDEO"
    TIMELINE = "TIMELINE"
    FINAL_VIDEO = "FINAL_VIDEO"


class ArtifactDeclaration(BaseModel):
    """A post-execution artifact to include in the final manifest."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str
    kind: ArtifactKind
    scene_id: str | None = None
    action_id: str | None = None
    assertion_id: str | None = None


class ArtifactRecord(BaseModel):
    """Integrity and correlation metadata for one persisted artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str
    kind: ArtifactKind
    media_type: str
    byte_count: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    scene_id: str | None = None
    action_id: str | None = None
    assertion_id: str | None = None


class ArtifactManifest(BaseModel):
    """Versioned manifest. It intentionally does not hash itself."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    run_id: str
    spec_id: str
    run_status: str
    created_at: AwareDatetime
    artifacts: tuple[ArtifactRecord, ...]

    @field_validator("created_at")
    @classmethod
    def normalize_timestamp(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)


class ArtifactWriteError(RuntimeError):
    """A declared artifact could not be safely persisted or indexed."""


class ArtifactWriter:
    """Persist one completed execution bundle and build its integrity manifest."""

    def persist(
        self,
        bundle: ExecutionBundle,
        artifact_dir: Path,
        *,
        extra_artifacts: Sequence[ArtifactDeclaration] = (),
    ) -> ArtifactManifest:
        artifact_dir.mkdir(parents=True, exist_ok=True)
        report = bundle.report

        self._atomic_text(
            self._contained(artifact_dir, report.trace_path),
            "".join(event.model_dump_json() + "\n" for event in bundle.trace_events),
        )
        self._atomic_text(
            self._contained(artifact_dir, report.browser_log_path),
            "".join(
                json.dumps(
                    {"level": entry.level, "message": entry.message},
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                + "\n"
                for entry in bundle.browser_logs
            ),
        )
        self._atomic_text(
            self._contained(artifact_dir, "execution_report.json"),
            report.model_dump_json(indent=2) + "\n",
        )

        records = self._artifact_records(bundle, artifact_dir, extra_artifacts)
        manifest = ArtifactManifest(
            run_id=str(report.run.id),
            spec_id=report.run.spec_id,
            run_status=report.run.status.value,
            created_at=datetime.now(UTC),
            artifacts=tuple(records),
        )
        self._atomic_text(
            self._contained(artifact_dir, report.artifact_manifest_path),
            manifest.model_dump_json(indent=2) + "\n",
        )
        return manifest

    def _artifact_records(
        self,
        bundle: ExecutionBundle,
        artifact_dir: Path,
        extra_artifacts: Sequence[ArtifactDeclaration],
    ) -> list[ArtifactRecord]:
        report = bundle.report
        declarations: list[tuple[str, ArtifactKind, str | None, str | None, str | None]] = [
            ("execution_report.json", ArtifactKind.EXECUTION_REPORT, None, None, None),
            (report.trace_path, ArtifactKind.TRACE, None, None, None),
            (report.browser_log_path, ArtifactKind.BROWSER_LOG, None, None, None),
        ]
        declarations.extend(
            (
                result.screenshot_path,
                ArtifactKind.REQUESTED_SCREENSHOT,
                result.scene_id,
                result.action_id,
                None,
            )
            for result in report.action_results
            if result.screenshot_path is not None
        )
        declarations.extend(
            (
                capture.path,
                ArtifactKind.EVIDENCE_SCREENSHOT,
                capture.scene_id,
                None,
                capture.assertion_id,
            )
            for capture in bundle.evidence_captures
        )
        if report.browser_video_path is not None:
            declarations.append(
                (
                    report.browser_video_path,
                    ArtifactKind.BROWSER_VIDEO,
                    None,
                    None,
                    None,
                )
            )
        declarations.extend(
            (
                declaration.path,
                declaration.kind,
                declaration.scene_id,
                declaration.action_id,
                declaration.assertion_id,
            )
            for declaration in extra_artifacts
        )

        records: list[ArtifactRecord] = []
        seen: set[str] = set()
        for relative_path, kind, scene_id, action_id, assertion_id in declarations:
            if relative_path in seen:
                continue
            seen.add(relative_path)
            path = self._contained(artifact_dir, relative_path)
            if not path.is_file():
                raise ArtifactWriteError(f"declared artifact does not exist: {relative_path}")
            media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            records.append(
                ArtifactRecord(
                    path=relative_path,
                    kind=kind,
                    media_type=media_type,
                    byte_count=path.stat().st_size,
                    sha256=self._sha256(path),
                    scene_id=scene_id,
                    action_id=action_id,
                    assertion_id=assertion_id,
                )
            )
        return records

    @staticmethod
    def verify(artifact_dir: Path, manifest: ArtifactManifest) -> tuple[str, ...]:
        """Return integrity errors without mutating any artifact."""
        errors: list[str] = []
        root = artifact_dir.resolve()
        for record in manifest.artifacts:
            path = (root / record.path).resolve()
            if not path.is_relative_to(root):
                errors.append(f"path escaped artifact directory: {record.path}")
                continue
            if not path.is_file():
                errors.append(f"artifact is missing: {record.path}")
                continue
            if path.stat().st_size != record.byte_count:
                errors.append(f"byte count changed: {record.path}")
            if ArtifactWriter._sha256(path) != record.sha256:
                errors.append(f"sha256 changed: {record.path}")
        return tuple(errors)

    @staticmethod
    def _contained(artifact_dir: Path, relative_path: str) -> Path:
        root = artifact_dir.resolve()
        path = (root / relative_path).resolve()
        if not path.is_relative_to(root):
            raise ArtifactWriteError(f"artifact path escaped requested directory: {relative_path}")
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

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()
