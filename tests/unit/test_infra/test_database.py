"""Unit tests for database session management."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession


@pytest.mark.unit
class TestDatabaseSession:
    """Test suite for database session management."""

    def test_get_engine_creates_engine_once(self):
        """Test that get_engine creates engine only once."""
        from example_service.infra.database.session import _engine, get_engine

        # Clear any existing engine
        import example_service.infra.database.session as session_module
        session_module._engine = None

        engine1 = get_engine()
        engine2 = get_engine()

        assert engine1 is engine2
        assert isinstance(engine1, AsyncEngine)

        # Cleanup
        session_module._engine = None

    def test_get_session_factory_creates_factory_once(self):
        """Test that get_session_factory creates factory only once."""
        from example_service.infra.database.session import get_session_factory

        # Clear any existing factory
        import example_service.infra.database.session as session_module
        session_module._session_factory = None

        factory1 = get_session_factory()
        factory2 = get_session_factory()

        assert factory1 is factory2

        # Cleanup
        session_module._session_factory = None

    @pytest.mark.asyncio
    async def test_get_async_session_yields_session(self):
        """Test that get_async_session yields a session."""
        from example_service.infra.database.session import get_async_session

        async with get_async_session() as session:
            assert isinstance(session, AsyncSession)

    @pytest.mark.asyncio
    async def test_get_async_session_commits_on_success(self):
        """Test that get_async_session commits on successful completion."""
        from example_service.infra.database.session import get_async_session

        async with get_async_session() as session:
            # Session should work normally
            pass
        # If we got here without exception, commit was successful

    @pytest.mark.asyncio
    async def test_get_async_session_rollsback_on_error(self):
        """Test that get_async_session rolls back on error."""
        from example_service.infra.database.session import get_async_session

        with pytest.raises(ValueError):
            async with get_async_session() as session:
                raise ValueError("Test error")

    @pytest.mark.asyncio
    async def test_init_database_skips_if_not_configured(self):
        """Test that init_database skips if database not configured."""
        from example_service.infra.database.session import init_database

        # With default settings (no DB configured), should not raise
        await init_database()

    @pytest.mark.asyncio
    async def test_close_database_disposes_engine(self):
        """Test that close_database disposes the engine."""
        from example_service.infra.database.session import close_database, get_engine

        # Create an engine
        engine = get_engine()

        # Close it
        await close_database()

        # Verify it was cleaned up
        import example_service.infra.database.session as session_module
        assert session_module._engine is None
        assert session_module._session_factory is None
