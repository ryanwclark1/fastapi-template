"""Shared fixtures for integration tests.

This module provides reusable fixtures for integration testing including:
- Test FastAPI applications with various middleware configurations
- Database session management with transaction rollback
- Mock external services (Accent-Auth, storage, etc.)
- HTTP clients with proper configuration
- Test data factories
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from example_service.core.dependencies.accent_auth import (
    get_auth_user,
    get_current_user,
)
from example_service.core.dependencies.auth_client import get_auth_client
from example_service.core.dependencies.database import get_db_session
from example_service.core.models.tenant import Tenant
from example_service.core.schemas.auth import AuthUser
from example_service.features.ai.models import Agent
from example_service.infra.cache.redis import get_cache

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Generator
else:  # pragma: no cover - runtime placeholders for typing-only imports
    AsyncGenerator = Generator = Any


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop]:
    """Create event loop for async tests.

    Uses session scope to avoid creating new loops for each test.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    loop.close()


@pytest.fixture
def mock_accent_auth_client() -> MagicMock:
    """Mock Accent-Auth client for testing.

    Returns:
        Mock client with standard validation methods.
    """
    mock = MagicMock()
    mock.validate_token_simple = AsyncMock(return_value=True)
    mock.validate_token = AsyncMock(
        return_value=MagicMock(
            token="test-token",
            metadata=MagicMock(
                uuid="user-uuid-123",
                tenant_uuid="tenant-uuid-456",
                auth_id="test-auth",
            ),
            acls=["read", "write"],
        ),
    )
    mock.check_acl = AsyncMock(return_value=True)
    return mock


@pytest.fixture
def test_app_minimal() -> FastAPI:
    """Create minimal FastAPI app for testing.

    Returns:
        Bare FastAPI application without middleware.
    """
    app = FastAPI(title="Test App")

    @app.get("/test")
    async def test_endpoint():
        return {"message": "ok"}

    @app.get("/error")
    async def error_endpoint():
        msg = "Test error"
        raise ValueError(msg)

    @app.post("/echo")
    async def echo_endpoint(request: Request):
        return await request.json()

    return app


@pytest.fixture
def test_app_with_state() -> FastAPI:
    """Create FastAPI app with request state access.

    Returns:
        FastAPI app that exposes request state in responses.
    """
    app = FastAPI(title="Test App With State")

    @app.get("/state")
    async def state_endpoint(request: Request):
        return {
            "request_id": getattr(request.state, "request_id", None),
            "trace_id": getattr(request.state, "trace_id", None),
            "span_id": getattr(request.state, "span_id", None),
            "locale": getattr(request.state, "locale", None),
            "user_id": getattr(request.state, "user_id", None),
            "tenant_id": getattr(request.state, "tenant_id", None),
        }

    @app.get("/query-test")
    async def query_endpoint():
        """Endpoint for testing query detection."""
        return {"message": "ok"}

    return app


@pytest_asyncio.fixture
async def async_client(
    app: FastAPI,
    db_session: AsyncSession,
    mock_auth_admin,
    mock_cache,
    test_tenant_id: str,
) -> AsyncGenerator[AsyncClient]:
    """Create async HTTP client bound to the real application."""

    async def _override_db_session():
        yield db_session

    auth_user = AuthUser(
        user_id="admin-user-id",
        permissions=["#"],
        metadata={
            "tenant_uuid": test_tenant_id,
            "tenant_slug": f"{test_tenant_id}-slug",
        },
    )

    async def _override_auth_user() -> AuthUser:
        return auth_user

    app.dependency_overrides[get_auth_client] = lambda: mock_auth_admin
    app.dependency_overrides[get_db_session] = _override_db_session
    app.dependency_overrides[get_cache] = lambda: mock_cache
    app.dependency_overrides[get_auth_user] = _override_auth_user
    app.dependency_overrides[get_current_user] = _override_auth_user

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
    ) as client:
        yield client

    app.dependency_overrides.clear()


@pytest.fixture
def mock_db_session() -> AsyncMock:
    """Mock database session for testing.

    Returns:
        Mock async session with standard methods.
    """
    session = AsyncMock(spec=AsyncSession)
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.close = AsyncMock()
    return session


@pytest.fixture
def mock_sqlalchemy_engine() -> MagicMock:
    """Mock SQLAlchemy engine for testing.

    Returns:
        Mock engine with sync_engine attribute for event listeners.
    """
    from unittest.mock import Mock

    engine = MagicMock()
    sync_engine = Mock(spec=["dispatch", "_has_events"])
    # Make sync_engine support SQLAlchemy events
    sync_engine.dispatch = Mock()
    sync_engine._has_events = True
    # Add event listener support
    sync_engine._event_registry = {}
    engine.sync_engine = sync_engine
    return engine


@pytest.fixture
def sample_user_data() -> dict[str, Any]:
    """Sample user data for testing.

    Returns:
        Dictionary with user information.
    """
    return {
        "user_id": "user-uuid-123",
        "username": "testuser",
        "email": "test@example.com",
        "preferred_language": "en",
        "tenant_id": "tenant-uuid-456",
    }


@pytest.fixture
def sample_auth_token() -> str:
    """Sample authentication token for testing.

    Returns:
        Mock JWT token string.
    """
    return "test-token-abc123"


@pytest.fixture
def mock_redis_client() -> MagicMock:
    """Mock Redis client for testing.

    Returns:
        Mock Redis client with async methods.
    """
    redis = MagicMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock(return_value=True)
    redis.delete = AsyncMock(return_value=1)
    redis.exists = AsyncMock(return_value=False)
    return redis


@pytest.fixture
def mock_storage_client() -> MagicMock:
    """Mock storage client for testing.

    Returns:
        Mock storage client with upload/download methods.
    """
    client = MagicMock()
    client.upload = AsyncMock(return_value="file-uuid-123")
    client.download = AsyncMock(return_value=b"file content")
    client.delete = AsyncMock(return_value=True)
    return client


@pytest_asyncio.fixture
async def test_tenant_id(db_session: AsyncSession) -> str:
    """Ensure a tenant exists for integration tests."""
    tenant_id = "tenant-integration"
    tenant = await db_session.get(Tenant, tenant_id)
    if tenant is None:
        tenant = Tenant(id=tenant_id, name="Integration Tenant")
        db_session.add(tenant)
        await db_session.commit()
    return tenant_id


@pytest_asyncio.fixture
async def prebuilt_agent(db_session: AsyncSession) -> Agent:
    """Ensure a system prebuilt agent exists for template-related tests."""
    result = await db_session.execute(
        select(Agent).where(Agent.agent_key == "system:rag_agent"),
    )
    agent = result.scalar_one_or_none()
    if agent is not None:
        return agent

    agent = Agent(
        agent_key="system:rag_agent",
        name="RAG Agent Template",
        description="Prebuilt retrieval-augmented generation agent for tests",
        tenant_id=None,
        agent_type="rag",
        model="gpt-4o-mini",
        provider="openai",
        system_prompt="You are a helpful retrieval-augmented assistant.",
        temperature=0.2,
        max_tokens=4096,
        tools={
            "search_knowledge_base": {
                "enabled": True,
                "config": {"index": "main"},
            },
        },
        is_prebuilt=True,
        is_active=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)
    return agent


@pytest.fixture
def auth_headers(test_tenant_id: str) -> dict[str, str]:
    """Standard auth headers for hitting protected endpoints."""
    return {
        "X-Auth-Token": "integration-test-token",
        "Accent-Tenant": test_tenant_id,
        "X-Tenant-ID": test_tenant_id,
        "Content-Type": "application/json",
    }


@pytest.fixture
def translation_provider() -> dict[str, dict[str, str]]:
    """Translation provider for I18n testing.

    Returns:
        Dictionary mapping locales to translation dictionaries.
    """
    return {
        "en": {
            "hello": "Hello",
            "welcome": "Welcome",
            "goodbye": "Goodbye",
        },
        "es": {
            "hello": "Hola",
            "welcome": "Bienvenido",
            "goodbye": "Adiós",
        },
        "fr": {
            "hello": "Bonjour",
            "welcome": "Bienvenue",
            "goodbye": "Au revoir",
        },
    }


@pytest.fixture
def mock_external_api() -> AsyncMock:
    """Mock external API for circuit breaker testing.

    Returns:
        Mock async function that can be configured to succeed or fail.
    """
    return AsyncMock(return_value={"status": "success"})


@pytest.fixture
def performance_threshold() -> dict[str, float]:
    """Performance thresholds for integration tests.

    Returns:
        Dictionary with acceptable timing thresholds in seconds.
    """
    return {
        "single_request": 0.1,  # 100ms per request
        "batch_100": 3.0,  # 3 seconds for 100 requests
        "with_middleware": 0.2,  # 200ms with full middleware stack
    }


class IntegrationTestHelper:
    """Helper class for common integration test operations."""

    @staticmethod
    async def wait_for_condition(
        condition: callable, timeout: float = 5.0, interval: float = 0.1,
    ) -> bool:
        """Wait for a condition to become true.

        Args:
            condition: Callable that returns bool
            timeout: Maximum time to wait in seconds
            interval: Time between checks in seconds

        Returns:
            True if condition met, False if timeout
        """
        elapsed = 0.0
        while elapsed < timeout:
            if condition():
                return True
            await asyncio.sleep(interval)
            elapsed += interval
        return False

    @staticmethod
    def assert_headers_present(response: Any, expected_headers: list[str]) -> None:
        """Assert that expected headers are present in response.

        Args:
            response: HTTP response object
            expected_headers: List of header names to check

        Raises:
            AssertionError: If any expected header is missing
        """
        for header in expected_headers:
            assert header.lower() in response.headers, f"Missing expected header: {header}"

    @staticmethod
    def assert_security_headers(response: Any) -> None:
        """Assert that security headers are present.

        Args:
            response: HTTP response object

        Raises:
            AssertionError: If security headers are missing
        """
        security_headers = [
            "x-frame-options",
            "x-content-type-options",
            "referrer-policy",
        ]
        IntegrationTestHelper.assert_headers_present(response, security_headers)


@pytest.fixture
def test_helper() -> IntegrationTestHelper:
    """Provide integration test helper.

    Returns:
        Helper instance with utility methods.
    """
    return IntegrationTestHelper()


@pytest.fixture
def capture_logs():
    """Capture log output for assertions.

    Yields:
        List that will contain captured log records.
    """
    import logging

    captured_logs = []

    class ListHandler(logging.Handler):
        def emit(self, record):
            captured_logs.append(record)

    handler = ListHandler()
    logger = logging.getLogger()
    logger.addHandler(handler)
    original_level = logger.level
    logger.setLevel(logging.DEBUG)

    yield captured_logs

    logger.removeHandler(handler)
    logger.setLevel(original_level)


@pytest.fixture
def mock_query_result() -> list[dict[str, Any]]:
    """Mock database query results.

    Returns:
        List of mock database records.
    """
    return [
        {"id": 1, "name": "Item 1", "value": 100},
        {"id": 2, "name": "Item 2", "value": 200},
        {"id": 3, "name": "Item 3", "value": 300},
    ]


@pytest.fixture(autouse=True)
def reset_circuit_breakers():
    """Reset all circuit breakers between tests.

    This ensures circuit breaker state doesn't leak between tests.
    """
    # Import here to avoid circular dependencies
    try:
        from example_service.infra.resilience.circuit_breaker import CircuitBreaker

        # Reset all instances
        CircuitBreaker._instances.clear()
    except (ImportError, AttributeError):
        # Circuit breaker not available or doesn't have _instances
        pass

    yield

    # Cleanup after test
    try:
        from example_service.infra.resilience.circuit_breaker import CircuitBreaker

        CircuitBreaker._instances.clear()
    except (ImportError, AttributeError):
        pass
