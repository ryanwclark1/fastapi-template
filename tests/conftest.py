"""Pytest configuration and shared fixtures.

This module provides reusable fixtures for testing across the entire test suite.
Fixtures are organized by category to make them easy to discover and extend.

Organization:
    - Application Fixtures: FastAPI app and HTTP client
    - Database Fixtures: SQLAlchemy engine, session, and test data factories
    - Cache Fixtures: Redis mocks and cache utilities
    - Authentication Fixtures: User models and auth tokens
    - Utility Fixtures: Helper functions and common test data

When adding new features:
    1. Add fixtures to the appropriate section below
    2. Use @pytest.fixture with clear docstrings
    3. Use scopes appropriately (function, class, module, session)
    4. Make fixtures composable (fixtures can depend on other fixtures)
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

    from example_service.core.database.base import Base

# Ensure tests run without external infrastructure
os.environ.setdefault("APP_ROOT_PATH", "")
os.environ.setdefault("DB_ENABLED", "false")
os.environ.setdefault("DB_DATABASE_URL", "")
os.environ.setdefault("REDIS_REDIS_URL", "")
os.environ.setdefault("RABBIT_ENABLED", "false")
os.environ.setdefault("AUTH_SERVICE_URL", "")
os.environ.setdefault("OTEL_ENABLED", "false")
os.environ.setdefault("GRAPHQL_ENABLED", "false")


# ============================================================================
# Application Fixtures
# ============================================================================


@pytest.fixture
async def app():
    """Create FastAPI application for testing.

    This fixture creates a fresh FastAPI application instance for each test.
    The app is configured to run without external dependencies (database, cache, etc.)
    via environment variables set above.

    Returns:
        FastAPI application instance.

    Example:
        async def test_endpoint(app):
            # Access routes, dependencies, etc.
            assert app.title == "Example Service"
    """
    from example_service.app.main import create_app

    return create_app()


@pytest.fixture
async def client(app) -> AsyncGenerator[AsyncClient]:
    """Create async HTTP client for testing.

    This fixture provides an HTTPX AsyncClient for making requests to the FastAPI app.
    The client is automatically closed after the test completes.

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


# ============================================================================
# Database Fixtures
# ============================================================================


@pytest.fixture
async def db_engine() -> AsyncGenerator[AsyncEngine]:
    """Create async SQLAlchemy engine with in-memory SQLite.

    This fixture creates a fresh in-memory database for each test that needs it.
    The database is automatically cleaned up after the test completes.

    Yields:
        Async SQLAlchemy engine connected to in-memory SQLite.

    Example:
        async def test_with_db(db_engine):
            async with db_engine.begin() as conn:
                await conn.execute(text("SELECT 1"))
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        future=True,
    )

    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
async def db_session(db_engine: AsyncEngine) -> AsyncGenerator[AsyncSession]:
    """Create async database session with automatic table creation and cleanup.

    This fixture:
    1. Creates all tables defined in Base.metadata
    2. Provides a session for database operations
    3. Automatically rolls back transactions after each test
    4. Cleans up tables after the test

    Args:
        db_engine: Async SQLAlchemy engine fixture.

    Yields:
        Async database session for testing.

    Example:
        async def test_create_user(db_session):
            user = User(email="test@example.com")
            db_session.add(user)
            await db_session.commit()
            assert user.id is not None
    """
    from example_service.core.database.base import Base

    # Create all tables
    async with db_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Create session factory
    async_session_maker = sessionmaker(
        db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    # Provide session
    async with async_session_maker() as session:
        try:
            yield session
        finally:
            await session.rollback()

    # Clean up tables
    async with db_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
def current_user() -> dict[str, str]:
    """Provide simulated current user for audit tracking.

    Returns:
        Dictionary with user information (user_id, email).

    Example:
        def test_audit_trail(current_user):
            document = Document(title="Test")
            document.created_by = current_user["email"]
            assert document.created_by == "user@example.com"
    """
    return {
        "user_id": "user-123",
        "email": "user@example.com",
        "name": "Test User",
    }


@pytest.fixture
def admin_user() -> dict[str, str]:
    """Provide simulated admin user for audit tracking.

    Returns:
        Dictionary with admin user information.

    Example:
        def test_admin_action(admin_user):
            user.updated_by = admin_user["email"]
            assert user.updated_by == "admin@example.com"
    """
    return {
        "user_id": "admin-456",
        "email": "admin@example.com",
        "name": "Admin User",
    }


# ============================================================================
# Cache Fixtures
# ============================================================================


@pytest.fixture
def mock_redis_client():
    """Create mock Redis client for cache testing.

    This fixture provides a comprehensive mock of Redis operations including:
    - get/set/delete for basic key-value operations
    - sadd/smembers for set operations (used in tag-based caching)
    - expire for TTL management
    - scan_iter for pattern-based operations

    Returns:
        AsyncMock Redis client with common operations.

    Example:
        async def test_cache(mock_redis_client):
            await mock_redis_client.set("key", "value")
            value = await mock_redis_client.get("key")
            assert value == "value"
    """
    mock_client = AsyncMock()

    # Storage for mock Redis operations
    mock_storage: dict = {}
    mock_sets: dict = {}

    async def mock_get(key: str):
        return mock_storage.get(key)

    async def mock_set(key: str, value, ex=None):
        mock_storage[key] = value
        return True

    async def mock_delete(*keys: str):
        deleted = 0
        for key in keys:
            if key in mock_storage:
                del mock_storage[key]
                deleted += 1
            if key in mock_sets:
                del mock_sets[key]
                deleted += 1
        return deleted

    async def mock_sadd(key: str, *values):
        if key not in mock_sets:
            mock_sets[key] = set()
        mock_sets[key].update(values)
        return len(values)

    async def mock_smembers(key: str):
        return mock_sets.get(key, set())

    async def mock_expire(key: str, seconds: int):
        return True

    async def mock_scan_iter(match: str, count: int = 100):
        """Mock scan_iter for pattern matching."""
        import fnmatch

        for key in list(mock_storage.keys()):
            if fnmatch.fnmatch(key, match):
                yield key.encode()

    # Configure mock
    mock_client.get = mock_get
    mock_client.set = mock_set
    mock_client.delete = mock_delete
    mock_client.sadd = mock_sadd
    mock_client.smembers = mock_smembers
    mock_client.expire = mock_expire
    mock_client.scan_iter = mock_scan_iter

    return mock_client


@pytest.fixture
def mock_cache(mock_redis_client):
    """Create mock cache with Redis client for testing cache decorators.

    This fixture provides a mock cache instance that works with the cache
    decorators and invalidation utilities.

    Args:
        mock_redis_client: Mock Redis client fixture.

    Returns:
        AsyncMock cache with context manager support.

    Example:
        async def test_cached_function(mock_cache):
            @cached(key_prefix="test", ttl=300)
            async def get_data():
                return {"data": "value"}

            result = await get_data()
            assert result["data"] == "value"
    """
    mock = AsyncMock()
    mock._client = mock_redis_client

    # Storage for the cache
    cache_storage: dict = {}

    async def mock_get(key: str):
        return cache_storage.get(key)

    async def mock_set(key: str, value, ttl=None):
        cache_storage[key] = value

    async def mock_delete(key: str):
        if key in cache_storage:
            del cache_storage[key]
            return True
        return False

    mock.get = mock_get
    mock.set = mock_set
    mock.delete = mock_delete

    return mock


# ============================================================================
# Authentication Fixtures
# ============================================================================


@pytest.fixture
def mock_auth_token() -> str:
    """Provide mock authentication token for testing protected endpoints.

    Returns:
        JWT-like token string.

    Example:
        async def test_protected_endpoint(client, mock_auth_token):
            headers = {"Authorization": f"Bearer {mock_auth_token}"}
            response = await client.get("/api/v1/protected", headers=headers)
            assert response.status_code == 200
    """
    return "mock.jwt.token"


@pytest.fixture
def mock_auth_user():
    """Provide mock authenticated user data.

    Returns:
        Dictionary with authenticated user information.

    Example:
        def test_user_action(mock_auth_user):
            assert mock_auth_user["permissions"] == ["read", "write"]
    """
    return {
        "user_id": "auth-user-789",
        "email": "auth@example.com",
        "name": "Authenticated User",
        "permissions": ["read", "write"],
        "roles": ["user"],
    }


# ============================================================================
# Utility Fixtures
# ============================================================================


@pytest.fixture
def anyio_backend():
    """Configure anyio backend for async tests.

    Returns:
        Backend name for anyio.
    """
    return "asyncio"


@pytest.fixture
def utc_now() -> datetime:
    """Provide current UTC datetime for consistent testing.

    Returns:
        Current UTC datetime.

    Example:
        def test_timestamp(utc_now):
            user.created_at = utc_now
            assert user.created_at.tzinfo is not None
    """
    return datetime.now(UTC)


@pytest.fixture
def sample_ids() -> dict[str, int | str]:
    """Provide sample IDs for testing.

    Returns:
        Dictionary with various ID formats.

    Example:
        def test_with_ids(sample_ids):
            user_id = sample_ids["user_id"]
            assert isinstance(user_id, int)
    """
    return {
        "user_id": 1,
        "document_id": 100,
        "post_id": 42,
        "uuid": "123e4567-e89b-12d3-a456-426614174000",
    }


# ============================================================================
# Factory Fixtures - Use these to create test data easily
# ============================================================================


@pytest.fixture
def make_test_model():
    """Factory fixture for creating test models with default values.

    This fixture returns a factory function that can create instances of
    any model class with sensible defaults and optional overrides.

    Returns:
        Factory function for creating test models.

    Example:
        def test_create_users(make_test_model):
            # Create user with defaults
            user1 = make_test_model(User, email="user1@example.com")

            # Create user with overrides
            user2 = make_test_model(
                User,
                email="user2@example.com",
                name="Custom Name"
            )
    """

    def factory(model_class: type[Base], **kwargs) -> Base:
        """Create instance of model with provided kwargs.

        Args:
            model_class: The model class to instantiate.
            **kwargs: Field values for the model.

        Returns:
            Instance of the model class.
        """
        return model_class(**kwargs)

    return factory


@pytest.fixture
def make_test_users(current_user, admin_user):
    """Factory fixture for creating multiple test users with audit tracking.

    Returns:
        Factory function for creating user lists.

    Example:
        def test_with_users(make_test_users):
            users = make_test_users(count=3)
            assert len(users) == 3
            assert all(u.created_by == "user@example.com" for u in users)
    """

    def factory(count: int = 1, created_by: str | None = None) -> list[dict]:
        """Create list of user dictionaries.

        Args:
            count: Number of users to create.
            created_by: Email of the creator (defaults to current_user).

        Returns:
            List of user dictionaries.
        """
        creator = created_by or current_user["email"]
        return [
            {
                "email": f"user{i}@example.com",
                "name": f"Test User {i}",
                "created_by": creator,
            }
            for i in range(count)
        ]

    return factory


# ============================================================================
# Parametrize Helpers - Common test data sets
# ============================================================================


@pytest.fixture(params=["integer", "uuid_v4", "uuid_v7"])
def primary_key_strategy(request):
    """Parametrize fixture for testing all primary key strategies.

    This fixture will run tests with each primary key strategy.

    Yields:
        String identifier for the primary key strategy.

    Example:
        def test_all_pk_strategies(primary_key_strategy):
            # This test runs 3 times, once for each PK strategy
            assert primary_key_strategy in ["integer", "uuid_v4", "uuid_v7"]
    """
    return request.param


@pytest.fixture(params=[True, False])
def with_soft_delete(request):
    """Parametrize fixture for testing with/without soft delete.

    This fixture will run tests both with and without soft delete enabled.

    Yields:
        Boolean indicating if soft delete should be used.

    Example:
        def test_deletion(with_soft_delete):
            # This test runs twice: once with soft delete, once without
            if with_soft_delete:
                # Test soft delete behavior
                pass
            else:
                # Test hard delete behavior
                pass
    """
    return request.param
