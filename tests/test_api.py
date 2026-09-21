"""Acceptance tests for the Stage 0 HTTP surface."""

import asyncio

from httpx import ASGITransport, AsyncClient, Response

from proofdemo.api import create_app
from proofdemo.config import Settings


def test_health_endpoint_returns_service_metadata() -> None:
    app = create_app(Settings(environment="test"))

    async def get_health() -> Response:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.get("/health")

    response = asyncio.run(get_health())

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "proofdemo-api",
        "version": "0.1.0",
        "environment": "test",
    }
