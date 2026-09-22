"""Bounded local product jobs over the existing verified execution services."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock, Thread
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from proofdemo.adapters.ffmpeg_render import FFmpegRenderAdapter
from proofdemo.adapters.openai_planner import OpenAIPlanner
from proofdemo.adapters.playwright_browser import PlaywrightBrowser
from proofdemo.application.artifacts import ArtifactKind, ArtifactManifest, ArtifactWriter
from proofdemo.application.execution import ExecutionReport, ExecutionService
from proofdemo.application.planning import InvalidPlannerCandidate, PlanningService
from proofdemo.application.recipes import RecipeService
from proofdemo.application.rendering import CompositionService
from proofdemo.application.safety import SafetyDecision, SafetyFinding, SafetyService
from proofdemo.application.trace import TraceEvent
from proofdemo.config import Settings
from proofdemo.domain.demo_run import DemoRunStatus
from proofdemo.domain.demo_spec import DemoSpec
from proofdemo.domain.planning import DemoIntent
from proofdemo.domain.recipe import demo_spec_sha256
from proofdemo.ports.browser import BrowserPort
from proofdemo.ports.planner import PlannerPort, PlannerUnavailableError
from proofdemo.ports.render import RenderPort, RenderUnavailableError


class JobStatus(StrEnum):
    QUEUED = "QUEUED"
    PLANNING = "PLANNING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    EXECUTING = "EXECUTING"
    RENDERING = "RENDERING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


TERMINAL = {JobStatus.PASSED, JobStatus.FAILED, JobStatus.BLOCKED}


class JobRecord(BaseModel):
    """Small durable state snapshot; user intent is not copied into status files."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    status: JobStatus
    created_at: datetime
    updated_at: datetime
    message: str = Field(max_length=2_000)
    spec_id: str | None = None
    spec_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    run_status: DemoRunStatus | None = None
    safety_decision: SafetyDecision | None = None
    safety_findings: tuple[SafetyFinding, ...] = ()
    preview_revision: int = 0


class JobEvent(BaseModel):
    """Live event without fill payloads or assertion observations."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sequence: int
    occurred_at: datetime
    kind: str
    status: str | None = None
    scene_id: str | None = None
    action_id: str | None = None
    assertion_id: str | None = None
    message: str | None = None


class JobBusyError(RuntimeError):
    """The local single-job execution slot is occupied."""


class JobStateError(RuntimeError):
    """A transition is invalid for this job."""


class JobIntegrityError(RuntimeError):
    """A requested artifact is absent or fails integrity checks."""


class JobManager:
    """One-process local orchestrator with durable snapshots and explicit recovery."""

    def __init__(
        self,
        root: Path,
        *,
        planner_factory: Callable[[], PlannerPort],
        browser_factory: Callable[[], BrowserPort] = PlaywrightBrowser,
        renderer_factory: Callable[[], RenderPort] = FFmpegRenderAdapter,
    ) -> None:
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        self._planner_factory = planner_factory
        self._browser_factory = browser_factory
        self._renderer_factory = renderer_factory
        self._lock = Lock()
        self._jobs: dict[UUID, JobRecord] = {}
        self._events: dict[UUID, list[JobEvent]] = {}
        self._recover()

    @classmethod
    def from_settings(cls, settings: Settings) -> JobManager:
        return cls(
            settings.job_root,
            planner_factory=lambda: OpenAIPlanner(settings.openai_model or ""),
        )

    def create(self, intent: DemoIntent) -> JobRecord:
        with self._lock:
            if any(job.status not in TERMINAL for job in self._jobs.values()):
                raise JobBusyError("one local demo is already active")
            now = datetime.now(UTC)
            job = JobRecord(
                id=uuid4(),
                status=JobStatus.QUEUED,
                created_at=now,
                updated_at=now,
                message="Waiting to plan the demo",
            )
            self._job_dir(job.id).mkdir(parents=True, exist_ok=False)
            self._jobs[job.id] = job
            self._events[job.id] = []
            self._save(job)
            self._append_event(job.id, "JOB_STATUS", status=job.status, message=job.message)
        Thread(target=self._plan, args=(job.id, intent), daemon=True).start()
        return job

    def get(self, job_id: UUID) -> JobRecord | None:
        with self._lock:
            return self._jobs.get(job_id)

    def events_since(self, job_id: UUID, sequence: int) -> tuple[JobEvent, ...]:
        with self._lock:
            if job_id not in self._jobs:
                raise KeyError(job_id)
            return tuple(event for event in self._events[job_id] if event.sequence > sequence)

    def approve(self, job_id: UUID) -> JobRecord:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise KeyError(job_id)
            if job.status is not JobStatus.AWAITING_APPROVAL:
                raise JobStateError("job is not waiting for approval")
            job = self._set_locked(job_id, JobStatus.QUEUED, "Risky actions approved for this run")
        Thread(target=self._execute, args=(job_id, True), daemon=True).start()
        return job

    def spec(self, job_id: UUID) -> DemoSpec:
        job = self._require(job_id)
        try:
            spec = DemoSpec.model_validate_json(
                self._job_path(job_id, "demo_spec.json").read_text(encoding="utf-8")
            )
        except ValidationError as error:
            raise JobIntegrityError("DemoSpec is invalid") from error
        if job.spec_sha256 is not None and demo_spec_sha256(spec) != job.spec_sha256:
            raise JobIntegrityError("DemoSpec changed after safety review")
        return spec

    def report(self, job_id: UUID) -> ExecutionReport:
        self._require(job_id)
        self.manifest(job_id)
        try:
            return ExecutionReport.model_validate_json(
                self._job_path(job_id, "run/execution_report.json").read_text(encoding="utf-8")
            )
        except ValidationError as error:
            raise JobIntegrityError("Execution report is invalid") from error

    def manifest(self, job_id: UUID) -> ArtifactManifest:
        self._require(job_id)
        try:
            manifest = ArtifactManifest.model_validate_json(
                self._job_path(job_id, "run/artifact_manifest.json").read_text(encoding="utf-8")
            )
        except ValidationError as error:
            raise JobIntegrityError("Artifact manifest is invalid") from error
        problems = ArtifactWriter.verify(self._job_path(job_id, "run"), manifest)
        if problems:
            raise JobIntegrityError(problems[0])
        return manifest

    def preview_path(self, job_id: UUID) -> Path:
        self._require(job_id)
        path = self._job_path(job_id, "run/preview/latest.png")
        if not path.is_file():
            raise FileNotFoundError(path)
        return path

    def video_path(self, job_id: UUID) -> Path:
        job = self._require(job_id)
        if job.status is not JobStatus.PASSED:
            raise JobIntegrityError("job has no verified final video")
        manifest = self.manifest(job_id)
        if manifest.run_status != DemoRunStatus.PASSED:
            raise JobIntegrityError("artifact manifest is not from a passed run")
        record = next(
            (item for item in manifest.artifacts if item.kind is ArtifactKind.FINAL_VIDEO),
            None,
        )
        if record is None:
            raise JobIntegrityError("manifest has no final video")
        return self._job_path(job_id, f"run/{record.path}")

    def _plan(self, job_id: UUID, intent: DemoIntent) -> None:
        self._set(job_id, JobStatus.PLANNING, "Creating a reviewable DemoSpec")
        try:
            result = PlanningService(self._planner_factory()).plan(intent)
            self._atomic_text(
                self._job_path(job_id, "demo_spec.json"),
                result.spec.model_dump_json(indent=2) + "\n",
            )
            assessment = SafetyService.assess(result.spec, approval_acknowledged=False)
            SafetyService.write(assessment, self._job_path(job_id, "run"))
            self._set(
                job_id,
                JobStatus.PLANNING,
                "DemoSpec created and safety checked",
                spec_id=result.spec.id,
                spec_sha256=demo_spec_sha256(result.spec),
                safety_decision=assessment.decision,
                safety_findings=assessment.findings,
            )
            if assessment.decision is SafetyDecision.BLOCKED:
                self._set(job_id, JobStatus.BLOCKED, "Credential-like fill is blocked")
            elif assessment.decision is SafetyDecision.REQUIRES_APPROVAL:
                self._set(
                    job_id,
                    JobStatus.AWAITING_APPROVAL,
                    "Review the plan and approve the listed risky actions",
                )
            else:
                self._execute(job_id, False)
        except Exception as error:
            self._set(job_id, JobStatus.BLOCKED, self._safe_error("Planning blocked", error))

    def _execute(self, job_id: UUID, approved: bool) -> None:
        try:
            spec = self.spec(job_id)
            expected_hash = self._require(job_id).spec_sha256
            if expected_hash is None or demo_spec_sha256(spec) != expected_hash:
                raise JobIntegrityError("DemoSpec changed after safety review")
            run_dir = self._job_path(job_id, "run")
            assessment = SafetyService.assess(spec, approval_acknowledged=approved)
            safety_declaration = SafetyService.write(assessment, run_dir)
            if assessment.decision is not SafetyDecision.ALLOWED:
                self._set(job_id, JobStatus.BLOCKED, "Safety policy did not allow execution")
                return
            self._set(
                job_id,
                JobStatus.EXECUTING,
                "Browser is executing and verifying the plan",
                safety_decision=assessment.decision,
                safety_findings=assessment.findings,
            )
            bundle = ExecutionService(
                self._browser_factory(),
                trace_observer=lambda event: self._record_trace(job_id, event),
                capture_live_preview=True,
            ).execute_bundle(spec, run_dir)
            writer = ArtifactWriter()
            declarations = [safety_declaration]
            manifest = writer.persist(bundle, run_dir, extra_artifacts=declarations)
            status = bundle.report.run.status
            if status is not DemoRunStatus.PASSED:
                terminal = JobStatus.FAILED if status is DemoRunStatus.FAILED else JobStatus.BLOCKED
                self._set(job_id, terminal, f"Verification ended {status}", run_status=status)
                return
            self._set(
                job_id,
                JobStatus.RENDERING,
                "Verified; rendering the final video",
                run_status=status,
            )
            composition = CompositionService(self._renderer_factory()).compose(
                bundle, manifest, run_dir
            )
            declarations.extend(composition.declarations)
            manifest = writer.persist(bundle, run_dir, extra_artifacts=declarations)
            recipe = RecipeService().create(spec, bundle, manifest, run_dir)
            declarations.append(recipe.declaration)
            manifest = writer.persist(bundle, run_dir, extra_artifacts=declarations)
            problems = ArtifactWriter.verify(run_dir, manifest)
            if problems:
                raise JobIntegrityError(problems[0])
            self._set(job_id, JobStatus.PASSED, "Verified demo video is ready")
        except Exception as error:
            self._set(job_id, JobStatus.BLOCKED, self._safe_error("Demo blocked", error))

    def _record_trace(self, job_id: UUID, event: TraceEvent) -> None:
        with self._lock:
            item = self._append_event(
                job_id,
                event.kind.value,
                status=event.status,
                scene_id=event.scene_id,
                action_id=event.action_id,
                assertion_id=event.assertion_id,
            )
            if event.kind.value == "PREVIEW_UPDATED":
                job = self._jobs[job_id]
                self._save_and_replace(job.model_copy(update={"preview_revision": item.sequence}))

    def _set(self, job_id: UUID, status: JobStatus, message: str, **changes: object) -> JobRecord:
        with self._lock:
            return self._set_locked(job_id, status, message, **changes)

    def _set_locked(
        self, job_id: UUID, status: JobStatus, message: str, **changes: object
    ) -> JobRecord:
        previous = self._jobs[job_id]
        if previous.status in TERMINAL:
            raise JobStateError("terminal job cannot be revived")
        job = previous.model_copy(
            update={
                "status": status,
                "message": message,
                "updated_at": datetime.now(UTC),
                **changes,
            }
        )
        self._save_and_replace(job)
        self._append_event(job_id, "JOB_STATUS", status=status, message=message)
        return job

    def _append_event(self, job_id: UUID, kind: str, **fields: object) -> JobEvent:
        items = self._events[job_id]
        event = JobEvent(
            sequence=len(items) + 1,
            occurred_at=datetime.now(UTC),
            kind=kind,
            **fields,
        )
        path = self._job_path(job_id, "events.jsonl")
        with path.open("a", encoding="utf-8") as stream:
            stream.write(event.model_dump_json() + "\n")
        items.append(event)
        return event

    def _save_and_replace(self, job: JobRecord) -> None:
        self._save(job)
        self._jobs[job.id] = job

    def _save(self, job: JobRecord) -> None:
        self._atomic_text(self._job_path(job.id, "job.json"), job.model_dump_json(indent=2) + "\n")

    def _recover(self) -> None:
        for directory in self._root.iterdir():
            if not directory.is_dir() or directory.is_symlink():
                continue
            try:
                job = JobRecord.model_validate_json((directory / "job.json").read_text())
                if directory.name != str(job.id):
                    continue
                events_path = directory / "events.jsonl"
                events: list[JobEvent] = []
                if events_path.exists():
                    for line in events_path.read_text(encoding="utf-8").splitlines():
                        try:
                            candidate = JobEvent.model_validate_json(line)
                        except ValueError:
                            break
                        if candidate.sequence != len(events) + 1:
                            break
                        events.append(candidate)
            except (OSError, ValueError):
                continue
            self._jobs[job.id] = job
            self._events[job.id] = events
            self._atomic_text(
                self._job_path(job.id, "events.jsonl"),
                "".join(event.model_dump_json() + "\n" for event in events),
            )
            if job.status not in TERMINAL:
                self._set_locked(job.id, JobStatus.BLOCKED, "Interrupted by server restart")

    def _require(self, job_id: UUID) -> JobRecord:
        job = self.get(job_id)
        if job is None:
            raise KeyError(job_id)
        return job

    def _job_dir(self, job_id: UUID) -> Path:
        return self._root / str(job_id)

    def _job_path(self, job_id: UUID, relative_path: str) -> Path:
        path = (self._job_dir(job_id) / relative_path).resolve()
        if not path.is_relative_to(self._root):
            raise JobIntegrityError("job artifact path escaped local root")
        return path

    @staticmethod
    def _atomic_text(path: Path, contents: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as temporary:
            temporary.write(contents)
            temporary.flush()
            temporary_path = Path(temporary.name)
        temporary_path.replace(path)

    @staticmethod
    def _safe_error(prefix: str, error: Exception) -> str:
        if isinstance(error, PlannerUnavailableError):
            return (
                "Planning blocked: configure PROOFDEMO_OPENAI_MODEL and OPENAI_API_KEY, "
                "then check provider connectivity"
            )
        if isinstance(error, InvalidPlannerCandidate):
            return "Planning blocked: candidate DemoSpec violated the requested source origin"
        if isinstance(error, RenderUnavailableError):
            return "Rendering blocked: install FFmpeg and FFprobe"
        if isinstance(error, JobIntegrityError):
            return f"{prefix}: job artifact integrity check failed"
        return f"{prefix}: {type(error).__name__}; inspect the local execution report"
