"""Integration tests for tenant dependency and context var bridge.

These tests verify that the tenant dependency correctly bridges to the
middleware context var, enabling TenantAwareSession to access tenant context.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from frozendict import frozendict
import pytest

from example_service.app.middleware.tenant import (
    clear_tenant_context,
)
from example_service.app.middleware.tenant import (
    get_tenant_context as get_middleware_tenant_context,
)
from example_service.core.dependencies.tenant import (
    get_tenant_context,
    get_tenant_context_from_user,
)
from example_service.core.schemas.auth import AuthUser
from example_service.infra.storage.backends import TenantContext


class TestTenantDependencyBridge:
    """Test that tenant dependency bridges to middleware context var."""

    @pytest.fixture(autouse=True)
    def clear_context(self) -> None:
        """Clear tenant context before and after each test."""
        clear_tenant_context()
        yield
        clear_tenant_context()

    def test_get_tenant_context_from_user_extracts_tenant(self) -> None:
        """Test that tenant context is extracted from user metadata."""
        # Arrange: Create a mock user with tenant metadata
        user = AuthUser(
            user_id="user-123",
            service_id="service-456",
            metadata={
                "tenant_uuid": "tenant-uuid-789",
                "tenant_slug": "acme-corp",
            },
        )

        # Act
        result = get_tenant_context_from_user(user)

        # Assert
        assert result is not None
        assert result.tenant_uuid == "tenant-uuid-789"
        assert result.tenant_slug == "acme-corp"

    def test_get_tenant_context_from_user_returns_none_without_tenant_info(self) -> None:
        """Test that None is returned when user has no tenant metadata."""
        # Arrange: User without tenant info
        user = AuthUser(
            user_id="user-123",
            service_id="service-456",
            metadata={},
        )

        # Act
        result = get_tenant_context_from_user(user)

        # Assert
        assert result is None

    def test_get_tenant_context_sets_middleware_context_var(self) -> None:
        """Test that get_tenant_context bridges to middleware context var.

        This is the critical test - it verifies that when get_tenant_context
        resolves a tenant, it also sets the middleware context var so that
        TenantAwareSession can access it.
        """
        # Arrange: Create storage TenantContext (what the dependency returns)
        storage_context = TenantContext(
            tenant_uuid="tenant-uuid-789",
            tenant_slug="acme-corp",
            metadata=frozendict({"source": "test"}),
        )

        # Act: Call get_tenant_context with the storage context
        result = get_tenant_context(user_context=storage_context, header_context=None)

        # Assert: Dependency returns the storage context
        assert result is not None
        assert result.tenant_uuid == "tenant-uuid-789"
        assert result.tenant_slug == "acme-corp"

        # Assert: Middleware context var is also set (THE BRIDGE)
        middleware_context = get_middleware_tenant_context()
        assert middleware_context is not None
        assert middleware_context.tenant_id == "tenant-uuid-789"  # Mapped from tenant_uuid
        assert middleware_context.identified_by == "jwt"  # Source tracking

    def test_get_tenant_context_header_fallback_sets_middleware_context(self) -> None:
        """Test that header fallback also bridges to middleware context var."""
        # Arrange: Create storage TenantContext from header
        header_context = TenantContext(
            tenant_uuid="header-tenant-uuid",
            tenant_slug="header-tenant",
            metadata=frozendict({"source": "header"}),
        )

        # Act: Call get_tenant_context with header context (no user context)
        result = get_tenant_context(user_context=None, header_context=header_context)

        # Assert: Dependency returns the header context
        assert result is not None
        assert result.tenant_uuid == "header-tenant-uuid"

        # Assert: Middleware context var is set with header source
        middleware_context = get_middleware_tenant_context()
        assert middleware_context is not None
        assert middleware_context.tenant_id == "header-tenant-uuid"
        assert middleware_context.identified_by == "header"

    def test_get_tenant_context_jwt_takes_priority_over_header(self) -> None:
        """Test that JWT context takes priority over header context."""
        # Arrange: Both JWT and header contexts
        jwt_context = TenantContext(
            tenant_uuid="jwt-tenant-uuid",
            tenant_slug="jwt-tenant",
            metadata=frozendict({}),
        )
        header_context = TenantContext(
            tenant_uuid="header-tenant-uuid",
            tenant_slug="header-tenant",
            metadata=frozendict({}),
        )

        # Act
        result = get_tenant_context(user_context=jwt_context, header_context=header_context)

        # Assert: JWT context wins
        assert result is not None
        assert result.tenant_uuid == "jwt-tenant-uuid"

        # Assert: Middleware context reflects JWT source
        middleware_context = get_middleware_tenant_context()
        assert middleware_context is not None
        assert middleware_context.tenant_id == "jwt-tenant-uuid"
        assert middleware_context.identified_by == "jwt"

    def test_get_tenant_context_no_context_does_not_set_middleware_var(self) -> None:
        """Test that no middleware context is set when no tenant is available."""
        # Act: Call with no contexts
        result = get_tenant_context(user_context=None, header_context=None)

        # Assert
        assert result is None
        assert get_middleware_tenant_context() is None


class TestTenantAwareSessionIntegration:
    """Test that TenantAwareSession can read the bridged context.

    These tests verify the end-to-end flow from dependency to database layer.
    """

    @pytest.fixture(autouse=True)
    def clear_context(self) -> None:
        """Clear tenant context before and after each test."""
        clear_tenant_context()
        yield
        clear_tenant_context()

    def test_tenant_aware_session_reads_bridged_context(self) -> None:
        """Test that database tenancy layer can read the bridged context.

        This simulates what happens when:
        1. Endpoint uses TenantContextDep (calls get_tenant_context)
        2. TenantAwareSession reads from middleware context var
        """
        from example_service.core.database.tenancy import (
            get_tenant_context as db_get_tenant_context,
        )

        # Arrange: Set up tenant via dependency (simulating endpoint call)
        storage_context = TenantContext(
            tenant_uuid="db-tenant-uuid",
            tenant_slug="db-tenant",
            metadata=frozendict({}),
        )
        get_tenant_context(user_context=storage_context, header_context=None)

        # Act: Database layer reads context (what TenantAwareSession does)
        db_context = db_get_tenant_context()

        # Assert: Database layer sees the tenant
        assert db_context is not None
        assert db_context.tenant_id == "db-tenant-uuid"
