"""HTTP boundary for the ProofDemo application."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict

from proofdemo import __version__
from proofdemo.config import Settings


class HealthResponse(BaseModel):
    """Non-sensitive service readiness metadata."""

    model_config = ConfigDict(extra="forbid")

    status: str
    service: str
    version: str
    environment: str


def create_app(settings: Settings | None = None) -> FastAPI:
    """Construct an API instance with explicit, testable configuration."""
    current_settings = settings or Settings.from_env()
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
        allow_methods=["GET"],
        allow_headers=["Content-Type"],
    )

    @application.get("/health", response_model=HealthResponse, tags=["system"])
    def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            service=current_settings.app_name,
            version=__version__,
            environment=current_settings.environment,
        )

    return application


app = create_app()
