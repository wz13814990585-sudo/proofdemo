"""Acceptance tests for the Stage 0.1 HTTP surface."""

import asyncio

from httpx import ASGITransport, AsyncClient, Response

from proofdemo.api import create_app
from proofdemo.config import Settings


async def request(app, method: str, path: str, **kwargs) -> Response:  # type: ignore[no-untyped-def]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.request(method, path, **kwargs)


def test_health_endpoint_returns_service_metadata() -> None:
    app = create_app(Settings(environment="test"))

    response = asyncio.run(request(app, "GET", "/health"))

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "proofdemo-api",
        "version": "0.1.0",
        "environment": "test",
    }


def test_documented_frontend_origin_passes_cors_preflight() -> None:
    settings = Settings(environment="test")
    app = create_app(settings)

    response = asyncio.run(
        request(
            app,
            "OPTIONS",
            "/health",
            headers={
                "Origin": settings.frontend_origin,
                "Access-Control-Request-Method": "GET",
            },
        )
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
