"""HTTP boundary for local ProofDemo product jobs."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict

from proofdemo import __version__
from proofdemo.application.artifacts import ArtifactManifest
from proofdemo.application.execution import ExecutionReport
from proofdemo.application.jobs import (
    TERMINAL,
    JobBusyError,
    JobEvent,
    JobIntegrityError,
    JobManager,
    JobRecord,
    JobStateError,
)
from proofdemo.config import Settings
from proofdemo.domain.demo_spec import DemoSpec
from proofdemo.domain.planning import DemoIntent


class HealthResponse(BaseModel):
    """Non-sensitive service readiness metadata."""

    model_config = ConfigDict(extra="forbid")

    status: str
    service: str
    version: str
    environment: str


def create_app(settings: Settings | None = None, jobs: JobManager | None = None) -> FastAPI:
    """Construct an API instance with explicit, testable configuration."""
    current_settings = settings or Settings.from_env()
    job_manager = jobs or JobManager.from_settings(current_settings)
    application = FastAPI(
        title="ProofDemo API",
        version=__version__,
        docs_url="/docs" if current_settings.environment != "production" else None,
        redoc_url=None,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[current_settings.frontend_origin],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-ProofDemo-Client"],
    )

    @application.middleware("http")
    async def security_headers(request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
        blocked = False
        if request.method == "POST" and request.url.path.startswith("/jobs"):
            origin = request.headers.get("Origin")
            blocked = request.headers.get("X-ProofDemo-Client") != "studio" or (
                origin is not None and origin != current_settings.frontend_origin
            )
        response: Response = (
            JSONResponse(status_code=403, content={"detail": "Local studio request required"})
            if blocked
            else await call_next(request)
        )
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        if current_settings.environment == "production":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
            response.headers["Content-Security-Policy"] = (
                "default-src 'none'; frame-ancestors 'none'"
            )
        return response

    @application.get("/health", response_model=HealthResponse, tags=["system"])
    def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            service=current_settings.app_name,
            version=__version__,
            environment=current_settings.environment,
        )

    def require_job(job_id: UUID) -> JobRecord:
        job = job_manager.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return job

    @application.post("/jobs", response_model=JobRecord, status_code=status.HTTP_202_ACCEPTED)
    def create_job(intent: DemoIntent) -> JobRecord:
        try:
            return job_manager.create(intent)
        except JobBusyError as error:
            raise HTTPException(status_code=429, detail=str(error)) from error

    @application.get("/jobs/{job_id}", response_model=JobRecord)
    def get_job(job_id: UUID) -> JobRecord:
        return require_job(job_id)

    @application.post("/jobs/{job_id}/approve", response_model=JobRecord)
    def approve_job(job_id: UUID) -> JobRecord:
        require_job(job_id)
        try:
            return job_manager.approve(job_id)
        except JobStateError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @application.get("/jobs/{job_id}/spec", response_model=DemoSpec)
    def get_spec(job_id: UUID) -> DemoSpec:
        require_job(job_id)
        try:
            return job_manager.spec(job_id)
        except FileNotFoundError as error:
            raise HTTPException(status_code=404, detail="DemoSpec not available") from error
        except JobIntegrityError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @application.get("/jobs/{job_id}/report", response_model=ExecutionReport)
    def get_report(job_id: UUID) -> ExecutionReport:
        require_job(job_id)
        try:
            return job_manager.report(job_id)
        except FileNotFoundError as error:
            raise HTTPException(status_code=404, detail="Execution report not available") from error
        except JobIntegrityError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @application.get("/jobs/{job_id}/manifest", response_model=ArtifactManifest)
    def get_manifest(job_id: UUID) -> ArtifactManifest:
        require_job(job_id)
        try:
            return job_manager.manifest(job_id)
        except FileNotFoundError as error:
            raise HTTPException(
                status_code=404, detail="Artifact manifest not available"
            ) from error
        except JobIntegrityError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @application.get("/jobs/{job_id}/preview")
    def get_preview(job_id: UUID) -> FileResponse:
        require_job(job_id)
        try:
            return FileResponse(job_manager.preview_path(job_id), media_type="image/png")
        except FileNotFoundError as error:
            raise HTTPException(status_code=404, detail="Live preview not available") from error
        except JobIntegrityError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @application.get("/jobs/{job_id}/video")
    def get_video(job_id: UUID) -> FileResponse:
        require_job(job_id)
        try:
            return FileResponse(
                job_manager.video_path(job_id),
                media_type="video/mp4",
                filename=f"proofdemo-{job_id}.mp4",
                content_disposition_type="inline",
            )
        except JobIntegrityError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except FileNotFoundError as error:
            raise HTTPException(status_code=404, detail="Video not available") from error

    @application.get("/jobs/{job_id}/events")
    async def stream_events(job_id: UUID, request: Request, since: int = 0) -> StreamingResponse:
        require_job(job_id)
        last_id = request.headers.get("Last-Event-ID")
        if last_id is not None and last_id.isdecimal():
            since = max(since, int(last_id))
        if since < 0:
            raise HTTPException(status_code=422, detail="since must be non-negative")

        async def event_stream() -> AsyncIterator[str]:
            cursor = since
            while not await request.is_disconnected():
                for event in job_manager.events_since(job_id, cursor):
                    cursor = event.sequence
                    yield f"id: {cursor}\ndata: {event.model_dump_json()}\n\n"
                if require_job(job_id).status in TERMINAL:
                    return
                await asyncio.sleep(0.35)

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @application.get("/jobs/{job_id}/event-log", response_model=list[JobEvent])
    def get_event_log(job_id: UUID) -> tuple[JobEvent, ...]:
        require_job(job_id)
        return job_manager.events_since(job_id, 0)

    return application


app = create_app()
