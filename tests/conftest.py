"""Pytest configuration and fixtures."""
from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

# Set test environment variables before any imports
os.environ["APP_SERVICE_NAME"] = "test-service"
os.environ["APP_DEBUG"] = "true"
os.environ["APP_ENVIRONMENT"] = "test"
os.environ["LOG_LEVEL"] = "DEBUG"

from example_service.app.main import create_app
from example_service.core.settings.loader import clear_all_caches


@pytest.fixture(autouse=True)
def reset_settings():
    """Clear settings cache before each test."""
    clear_all_caches()
    yield
    clear_all_caches()


@pytest.fixture
async def app():
    """Create FastAPI application for testing."""
    return create_app()


@pytest.fixture
async def client(app) -> AsyncGenerator[AsyncClient, None]:
    """Create async HTTP client for testing."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


@pytest.fixture
def anyio_backend():
    """Configure anyio backend for async tests."""
    return "asyncio"


@pytest.fixture
def mock_redis():
    """Mock Redis client for testing."""
    mock = AsyncMock()
    mock.get = AsyncMock(return_value=None)
    mock.set = AsyncMock(return_value=True)
    mock.delete = AsyncMock(return_value=1)
    mock.exists = AsyncMock(return_value=False)
    mock.ping = AsyncMock(return_value=True)
    mock.close = AsyncMock()
    return mock


@pytest.fixture
def mock_db_session():
    """Mock database session for testing."""
    mock = AsyncMock()
    mock.execute = AsyncMock()
    mock.commit = AsyncMock()
    mock.rollback = AsyncMock()
    mock.close = AsyncMock()
    return mock


@pytest.fixture
def sample_user_data() -> dict[str, Any]:
    """Sample user data for testing."""
    return {
        "user_id": "test-user-123",
        "email": "test@example.com",
        "service_id": None,
        "roles": ["user"],
        "permissions": ["read", "write"],
        "acl": {"documents": ["read", "write"]},
        "metadata": {"team": "engineering"},
    }


def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line("markers", "unit: mark test as a unit test")
    config.addinivalue_line("markers", "integration: mark test as an integration test")
    config.addinivalue_line("markers", "slow: mark test as slow running")
