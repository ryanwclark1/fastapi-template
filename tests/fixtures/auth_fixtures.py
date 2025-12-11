"""Pytest fixtures for authentication testing.

This module provides pytest fixtures for testing authentication flows using
the Protocol-based MockAuthClient. These fixtures eliminate the need for
unittest.mock and provide consistent test behavior.

Fixtures:
    - mock_auth_admin: Admin user with full system access
    - mock_auth_readonly: Read-only user
    - mock_auth_user: Standard user with typical permissions
    - mock_auth_unauthorized: User with no permissions
    - mock_auth_expired: Expired token simulation
    - mock_auth_custom: Factory for custom auth configurations
    - mock_auth_multitenant: Multi-tenant testing scenario

Usage:
    def test_admin_access(mock_auth_admin):
        '''Test admin can access protected endpoints.'''
        token_info = await mock_auth_admin.validate_token("test-token")
        assert "#" in token_info.acl

    def test_custom_permissions(mock_auth_custom):
        '''Test with custom permissions.'''
        client = mock_auth_custom(
            user_id="custom-user",
            permissions=["users.read", "posts.write"],
        )
        token_info = await client.validate_token("test-token")
        assert "users.read" in token_info.acl

Pattern: pytest fixtures for Protocol-based test doubles
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from example_service.infra.auth.testing import MockAuthClient

if TYPE_CHECKING:
    from collections.abc import Callable


# =============================================================================
# Pre-Built Persona Fixtures
# =============================================================================


@pytest.fixture
def mock_auth_admin() -> MockAuthClient:
    """Mock auth client with admin permissions (# wildcard).

    Provides full system access for testing admin-only features.

    Returns:
        MockAuthClient with # ACL

    Example:
        def test_admin_endpoint(mock_auth_admin):
            token_info = await mock_auth_admin.validate_token("test-token")
            assert token_info.metadata.uuid == "admin-user-id"
            assert "#" in token_info.acl
    """
    return MockAuthClient.admin()


@pytest.fixture
def mock_auth_readonly() -> MockAuthClient:
    """Mock auth client with read-only permissions.

    Provides *.*.read permissions for testing read-only access patterns.

    Returns:
        MockAuthClient with *.*.read ACL

    Example:
        def test_readonly_access(mock_auth_readonly):
            token_info = await mock_auth_readonly.validate_token("test-token")

            # Can read
            from example_service.infra.auth.models import AccentAuthACL
            acl = AccentAuthACL(token_info.acl)
            assert acl.has_permission("confd.users.read")

            # Cannot write
            assert not acl.has_permission("confd.users.delete")
    """
    return MockAuthClient.readonly()


@pytest.fixture
def mock_auth_standard_user() -> MockAuthClient:
    """Mock auth client with standard user permissions.

    Provides typical user-level access (users.me.*, sessions.my_session.*).

    Returns:
        MockAuthClient with standard user ACLs

    Example:
        def test_user_access(mock_auth_standard_user):
            token_info = await mock_auth_standard_user.validate_token("test-token")

            from example_service.infra.auth.models import AccentAuthACL
            acl = AccentAuthACL(
                token_info.acl,
                auth_id=token_info.metadata.uuid,
                session_id=token_info.session_uuid,
            )

            # Can access own user
            assert acl.has_permission("users.user-user-id.read")

            # Cannot access other users
            assert not acl.has_permission("users.other-user.read")
    """
    return MockAuthClient.user()


@pytest.fixture
def mock_auth_unauthorized() -> MockAuthClient:
    """Mock auth client with no permissions (empty ACL).

    Useful for testing authorization failures and 403 responses.

    Returns:
        MockAuthClient with empty ACL

    Example:
        def test_unauthorized_access(mock_auth_unauthorized):
            from example_service.infra.auth.testing import (
                MissingPermissionsTokenException,
            )

            with pytest.raises(MissingPermissionsTokenException):
                await mock_auth_unauthorized.validate_token(
                    "test-token",
                    required_acl="users.read"
                )
    """
    return MockAuthClient.unauthorized()


@pytest.fixture
def mock_auth_expired() -> MockAuthClient:
    """Mock auth client with expired token.

    Simulates expired token for testing error handling.

    Returns:
        MockAuthClient that raises InvalidTokenException

    Example:
        def test_expired_token(mock_auth_expired):
            from example_service.infra.auth.testing import InvalidTokenException

            with pytest.raises(InvalidTokenException):
                await mock_auth_expired.validate_token("test-token")
    """
    return MockAuthClient.expired()


# =============================================================================
# Factory Fixtures
# =============================================================================


@pytest.fixture
def mock_auth_custom() -> Callable[..., MockAuthClient]:
    """Factory for creating custom mock auth clients.

    Provides a factory function for creating MockAuthClient instances
    with custom configurations. Useful for testing specific permission
    scenarios.

    Returns:
        Factory function that creates MockAuthClient instances

    Example:
        def test_custom_permissions(mock_auth_custom):
            # Create client with specific permissions
            client = mock_auth_custom(
                user_id="custom-user",
                permissions=["confd.users.read", "webhookd.#"],
                tenant_id="tenant-123",
            )

            token_info = await client.validate_token("test-token")
            assert token_info.metadata.uuid == "custom-user"
            assert token_info.metadata.tenant_uuid == "tenant-123"

            from example_service.infra.auth.models import AccentAuthACL
            acl = AccentAuthACL(token_info.acl)
            assert acl.has_permission("confd.users.read")
            assert acl.has_permission("webhookd.subscriptions.create")
    """

    def factory(
        user_id: str = "custom-user",
        tenant_id: str = "custom-tenant",
        permissions: list[str] | None = None,
        expired: bool = False,
        session_id: str = "custom-session",
    ) -> MockAuthClient:
        """Create custom MockAuthClient.

        Args:
            user_id: User identifier
            tenant_id: Tenant identifier
            permissions: ACL permissions (defaults to ["#"])
            expired: Whether token is expired
            session_id: Session identifier

        Returns:
            Configured MockAuthClient
        """
        return MockAuthClient(
            user_id=user_id,
            tenant_id=tenant_id,
            permissions=permissions,
            expired=expired,
            session_id=session_id,
        )

    return factory


@pytest.fixture
def mock_auth_multitenant() -> MockAuthClient:
    """Mock auth client configured for multi-tenant testing.

    Pre-registers three tokens for different tenants, enabling
    testing of tenant isolation.

    Returns:
        MockAuthClient with pre-registered tokens:
        - "tenant-a-token": Admin in tenant-a
        - "tenant-b-token": User in tenant-b
        - "tenant-c-token": Readonly in tenant-c

    Example:
        def test_tenant_isolation(mock_auth_multitenant):
            # Validate tenant A token
            token_a = await mock_auth_multitenant.validate_token("tenant-a-token")
            assert token_a.metadata.tenant_uuid == "tenant-a"

            # Validate tenant B token
            token_b = await mock_auth_multitenant.validate_token("tenant-b-token")
            assert token_b.metadata.tenant_uuid == "tenant-b"

            # Verify tenant isolation
            from example_service.infra.auth.testing import InvalidTokenException
            with pytest.raises(InvalidTokenException):
                await mock_auth_multitenant.validate_token(
                    "tenant-a-token",
                    tenant_uuid="tenant-b"  # Mismatch
                )
    """
    client = MockAuthClient()

    # Register tokens for different tenants
    client.register_token(
        token="tenant-a-token",
        user_id="admin-user-a",
        permissions=["#"],
        tenant_id="tenant-a",
    )

    client.register_token(
        token="tenant-b-token",
        user_id="user-b",
        permissions=["users.me.read", "users.me.write"],
        tenant_id="tenant-b",
    )

    client.register_token(
        token="tenant-c-token",
        user_id="readonly-user-c",
        permissions=["*.*.read"],
        tenant_id="tenant-c",
    )

    return client


# =============================================================================
# FastAPI Dependency Override Fixtures
# =============================================================================


@pytest.fixture
def override_auth_with_admin(mock_auth_admin) -> Callable[[], MockAuthClient]:
    """Get dependency override function for admin auth.

    Use with app.dependency_overrides to replace get_auth_client
    with MockAuthClient.admin().

    Returns:
        Function that returns mock_auth_admin

    Example:
        def test_admin_endpoint(client, override_auth_with_admin):
            from example_service.core.dependencies.auth_client import get_auth_client

            app.dependency_overrides[get_auth_client] = override_auth_with_admin

            response = client.get("/admin/users")
            assert response.status_code == 200

            # Cleanup
            app.dependency_overrides.clear()
    """

    def override() -> MockAuthClient:
        return mock_auth_admin

    return override


@pytest.fixture
def override_auth_with_readonly(mock_auth_readonly) -> Callable[[], MockAuthClient]:
    """Get dependency override function for readonly auth.

    Use with app.dependency_overrides to replace get_auth_client
    with MockAuthClient.readonly().

    Returns:
        Function that returns mock_auth_readonly

    Example:
        def test_readonly_access(client, override_auth_with_readonly):
            from example_service.core.dependencies.auth_client import get_auth_client

            app.dependency_overrides[get_auth_client] = override_auth_with_readonly

            # Can read
            response = client.get("/users")
            assert response.status_code == 200

            # Cannot delete
            response = client.delete("/users/123")
            assert response.status_code == 403

            app.dependency_overrides.clear()
    """

    def override() -> MockAuthClient:
        return mock_auth_readonly

    return override


@pytest.fixture
def override_auth_with_unauthorized(mock_auth_unauthorized) -> Callable[[], MockAuthClient]:
    """Get dependency override function for unauthorized auth.

    Use with app.dependency_overrides to test authorization failures.

    Returns:
        Function that returns mock_auth_unauthorized

    Example:
        def test_unauthorized_access(client, override_auth_with_unauthorized):
            from example_service.core.dependencies.auth_client import get_auth_client

            app.dependency_overrides[get_auth_client] = override_auth_with_unauthorized

            response = client.get("/users")
            assert response.status_code == 403

            app.dependency_overrides.clear()
    """

    def override() -> MockAuthClient:
        return mock_auth_unauthorized

    return override


__all__ = [
    "mock_auth_admin",
    "mock_auth_custom",
    "mock_auth_expired",
    "mock_auth_multitenant",
    "mock_auth_readonly",
    "mock_auth_standard_user",
    "mock_auth_unauthorized",
    "override_auth_with_admin",
    "override_auth_with_readonly",
    "override_auth_with_unauthorized",
]
