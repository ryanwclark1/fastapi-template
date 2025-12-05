"""Unit tests for tenant context utility functions.

These functions provide context variable management for tenant propagation
throughout the request lifecycle, used by the database tenancy layer.
"""

from __future__ import annotations

import pytest

from example_service.app.middleware.tenant import (
    clear_tenant_context,
    get_tenant_context,
    require_tenant,
    set_tenant_context,
)
from example_service.core.schemas.tenant import TenantContext


class TestTenantContextFunctions:
    """Test tenant context utility functions."""

    def test_get_tenant_context_returns_none_when_not_set(self) -> None:
        """Test that get_tenant_context returns None when not set."""
        clear_tenant_context()
        assert get_tenant_context() is None

    def test_set_and_get_tenant_context(self) -> None:
        """Test setting and getting tenant context."""
        clear_tenant_context()
        context = TenantContext(tenant_id="test-tenant", identified_by="test")
        set_tenant_context(context)

        retrieved = get_tenant_context()
        assert retrieved is not None
        assert retrieved.tenant_id == "test-tenant"
        assert retrieved.identified_by == "test"

    def test_clear_tenant_context(self) -> None:
        """Test clearing tenant context."""
        context = TenantContext(tenant_id="test-tenant")
        set_tenant_context(context)
        assert get_tenant_context() is not None

        clear_tenant_context()
        assert get_tenant_context() is None

    def test_require_tenant_raises_when_not_set(self) -> None:
        """Test that require_tenant raises RuntimeError when context not set."""
        clear_tenant_context()
        with pytest.raises(RuntimeError, match="No tenant context available"):
            require_tenant()

    def test_require_tenant_returns_context_when_set(self) -> None:
        """Test that require_tenant returns context when set."""
        clear_tenant_context()
        context = TenantContext(tenant_id="test-tenant")
        set_tenant_context(context)

        retrieved = require_tenant()
        assert retrieved.tenant_id == "test-tenant"

    def test_tenant_context_is_frozen(self) -> None:
        """Test that TenantContext is immutable."""
        context = TenantContext(tenant_id="test-tenant", identified_by="test")
        with pytest.raises(Exception):  # Pydantic raises ValidationError for frozen models
            context.tenant_id = "new-tenant"  # type: ignore[misc]

    def test_context_isolation_between_calls(self) -> None:
        """Test that context changes don't affect previously retrieved contexts."""
        clear_tenant_context()

        context1 = TenantContext(tenant_id="tenant-1", identified_by="test")
        set_tenant_context(context1)
        retrieved1 = get_tenant_context()

        context2 = TenantContext(tenant_id="tenant-2", identified_by="test")
        set_tenant_context(context2)
        retrieved2 = get_tenant_context()

        # Previous retrieval should still have original values (immutable)
        assert retrieved1 is not None
        assert retrieved1.tenant_id == "tenant-1"

        # Current context should have new values
        assert retrieved2 is not None
        assert retrieved2.tenant_id == "tenant-2"
