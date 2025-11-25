"""Pytest configuration and fixtures."""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def app():
    """Create FastAPI application for testing.

    Returns:
        FastAPI application instance.
    """
    from example_service.app.main import create_app

    return create_app()


@pytest.fixture
async def client(app) -> AsyncGenerator[AsyncClient]:
    """Create async HTTP client for testing.

    Args:
        app: FastAPI application fixture.

    Yields:
        Async HTTP client for making test requests.

    Example:
            async def test_health_check(client):
            response = await client.get("/api/v1/health/")
            assert response.status_code == 200
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.fixture
def anyio_backend():
    """Configure anyio backend for async tests.

    Returns:
        Backend name for anyio.
    """
    return "asyncio"
