"""Integration tests for Accent-Auth integration.

Tests cover:
- Token validation via Accent-Auth API
- ACL permission checking
- Multi-tenant context
- Header-based authentication
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from httpx import ASGITransport, AsyncClient
import pytest

from example_service.infra.auth import AuthClient
from example_service.infra.auth.accent_auth import (
    AccentAuthACL,
    AccentAuthClient,
    AccentAuthToken,
)
from example_service.infra.auth.testing import MockAuthClient


class TestAccentAuthClient:
    """Test Accent-Auth client functionality."""

    @pytest.fixture
    def accent_auth_client(self) -> AccentAuthClient:
        """Create Accent-Auth client for testing."""
        return AccentAuthClient(
            base_url="http://accent-auth:9497",
            timeout=5.0,
            max_retries=3,
        )

    @pytest.fixture
    def mock_token_response(self) -> dict:
        """Create mock token validation response."""
        return {
            "data": {
                "token": "test-token-123",
                "auth_id": "test-auth",
                "issued_at": "2025-12-01T10:00:00",
                "expires_at": "2025-12-01T18:00:00",
                "utc_issued_at": "2025-12-01T10:00:00Z",
                "utc_expires_at": "2025-12-01T18:00:00Z",
                "metadata": {
                    "uuid": "user-uuid-123",
                    "tenant_uuid": "tenant-uuid-456",
                    "auth_id": "test-auth",
                },
                "acls": [
                    "confd.users.read",
                    "confd.users.create",
                    "webhookd.subscriptions.*",
                    "calld.#",
                ],
            },
        }

    @pytest.mark.asyncio
    async def test_validate_token_simple_valid(self, accent_auth_client: AccentAuthClient):
        """Test simple token validation (HEAD request)."""
        mock_response = MagicMock()
        mock_response.status_code = 204

        with patch.object(accent_auth_client, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.head = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            is_valid = await accent_auth_client.validate_token_simple("test-token")

            assert is_valid is True
            mock_client.head.assert_called_once()

    @pytest.mark.asyncio
    async def test_validate_token_simple_invalid(self, accent_auth_client: AccentAuthClient):
        """Test simple validation with invalid token."""
        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch.object(accent_auth_client, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.head = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            is_valid = await accent_auth_client.validate_token_simple("invalid-token")

            assert is_valid is False

    @pytest.mark.asyncio
    async def test_validate_token_full(
        self,
        accent_auth_client: AccentAuthClient,
        mock_token_response: dict,
    ):
        """Test full token validation (GET request)."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_token_response

        with patch.object(accent_auth_client, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            token_info = await accent_auth_client.validate_token("test-token")

            assert isinstance(token_info, AccentAuthToken)
            assert token_info.token == "test-token-123"
            assert token_info.metadata.uuid == "user-uuid-123"
            assert token_info.metadata.tenant_uuid == "tenant-uuid-456"
            assert "confd.users.read" in token_info.acls
            assert len(token_info.acls) == 4

    @pytest.mark.asyncio
    async def test_validate_token_with_tenant(
        self,
        accent_auth_client: AccentAuthClient,
        mock_token_response: dict,
    ):
        """Test token validation with tenant context."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_token_response

        with patch.object(accent_auth_client, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            await accent_auth_client.validate_token(
                "test-token",
                tenant_uuid="tenant-uuid-456",
            )

            # Verify Accent-Tenant header was sent
            call_args = mock_client.get.call_args
            assert call_args.kwargs["headers"]["Accent-Tenant"] == "tenant-uuid-456"

    @pytest.mark.asyncio
    async def test_check_acl_success(
        self,
        accent_auth_client: AccentAuthClient,
        mock_token_response: dict,
    ):
        """Test ACL checking with valid permission."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_token_response

        with patch.object(accent_auth_client, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            has_access = await accent_auth_client.check_acl(
                "test-token",
                "confd.users.read",
            )

            assert has_access is True

    @pytest.mark.asyncio
    async def test_check_acl_forbidden(self, accent_auth_client: AccentAuthClient):
        """Test ACL checking without required permission."""
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.request = MagicMock()

        with patch.object(accent_auth_client, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            has_access = await accent_auth_client.check_acl(
                "test-token",
                "admin.all",
            )

            assert has_access is False

    def test_to_auth_user(
        self,
        accent_auth_client: AccentAuthClient,
        mock_token_response: dict,
    ):
        """Test conversion from AccentAuthToken to AuthUser."""
        token_info = AccentAuthToken(**mock_token_response["data"])
        auth_user = accent_auth_client.to_auth_user(token_info)

        assert auth_user.user_id == "user-uuid-123"
        assert auth_user.service_id is None
        assert len(auth_user.permissions) == 4
        assert "confd.users.read" in auth_user.permissions
        assert auth_user.metadata["tenant_uuid"] == "tenant-uuid-456"

        # Check ACL dict structure
        assert "confd.users" in auth_user.acl
        assert "read" in auth_user.acl["confd.users"]
        assert "create" in auth_user.acl["confd.users"]


class TestAccentAuthACL:
    """Test ACL permission checking with wildcards."""

    def test_exact_match(self):
        """Test exact ACL match."""
        acl = AccentAuthACL(["confd.users.read", "confd.users.create"])

        assert acl.has_permission("confd.users.read") is True
        assert acl.has_permission("confd.users.create") is True
        assert acl.has_permission("confd.users.delete") is False

    def test_single_level_wildcard(self):
        """Test single-level wildcard (*)."""
        acl = AccentAuthACL(["confd.users.*", "webhookd.subscriptions.*"])

        # Single-level wildcard matches any action
        assert acl.has_permission("confd.users.read") is True
        assert acl.has_permission("confd.users.create") is True
        assert acl.has_permission("confd.users.delete") is True

        # But not nested resources
        assert acl.has_permission("confd.users.groups.read") is False

        # Works for other services too
        assert acl.has_permission("webhookd.subscriptions.read") is True

    def test_multi_level_wildcard(self):
        """Test multi-level wildcard (#)."""
        acl = AccentAuthACL(["calld.#", "confd.users.#"])

        # Multi-level matches everything under the prefix
        assert acl.has_permission("calld.calls.read") is True
        assert acl.has_permission("calld.calls.hangup") is True
        assert acl.has_permission("calld.applications.create") is True
        assert acl.has_permission("calld.anything.deeply.nested") is True

        # Scoped to prefix
        assert acl.has_permission("confd.users.read") is True
        assert acl.has_permission("confd.users.groups.read") is True
        assert acl.has_permission("confd.tenants.read") is False

    def test_negation_acl(self):
        """Test negation ACLs (!)."""
        acl = AccentAuthACL(
            [
                "confd.users.*",
                "!confd.users.delete",
            ],
        )

        # Positive ACLs grant access
        assert acl.has_permission("confd.users.read") is True
        assert acl.has_permission("confd.users.create") is True

        # Negative ACL explicitly denies
        assert acl.has_permission("confd.users.delete") is False

    def test_negation_with_wildcard(self):
        """Test negation with wildcards."""
        acl = AccentAuthACL(
            [
                "confd.#",
                "!confd.users.delete",
                "!confd.tenants.*",
            ],
        )

        # Broad access
        assert acl.has_permission("confd.users.read") is True
        assert acl.has_permission("confd.extensions.read") is True

        # Specific denial
        assert acl.has_permission("confd.users.delete") is False

        # Wildcard denial
        assert acl.has_permission("confd.tenants.read") is False
        assert acl.has_permission("confd.tenants.create") is False

    def test_complex_acl_patterns(self):
        """Test complex ACL patterns."""
        acl = AccentAuthACL(
            [
                "confd.users.read",
                "confd.users.me.#",  # Full access to own user
                "webhookd.subscriptions.*",
                "calld.calls.my_session.*",  # Access to own session calls
                "!admin.*",  # No admin access
            ],
        )

        assert acl.has_permission("confd.users.read") is True
        assert acl.has_permission("confd.users.me.update") is True
        assert acl.has_permission("confd.users.me.password.update") is True
        assert acl.has_permission("webhookd.subscriptions.create") is True
        assert acl.has_permission("calld.calls.my_session.hangup") is True

        # Admin explicitly denied
        assert acl.has_permission("admin.anything") is False


@pytest.mark.integration
class TestAccentAuthIntegration:
    """Integration tests with FastAPI endpoints."""

    @pytest.fixture
    async def client(self) -> AsyncClient:
        """Create test client."""
        from example_service.app.main import app

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            yield ac

    @pytest.mark.asyncio
    async def test_protected_endpoint_without_token(self, client: AsyncClient):
        """Test accessing protected endpoint without X-Auth-Token."""
        response = await client.get("/api/v1/reminders", follow_redirects=True)

        assert response.status_code == 401
        assert "X-Auth-Token" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_protected_endpoint_with_invalid_token(self, client: AsyncClient):
        """Test accessing protected endpoint with invalid token."""
        response = await client.get(
            "/api/v1/reminders",
            headers={"X-Auth-Token": "invalid-token"},
            follow_redirects=True,
        )

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_tenant_header_propagation(self, client: AsyncClient):
        """Test that Accent-Tenant header is used for tenant context."""
        # This would require mocking the auth service
        # Placeholder for actual implementation

    @pytest.mark.asyncio
    async def test_acl_permission_check(self, client: AsyncClient):
        """Test ACL-based permission checking on endpoints."""
        # This would require mocking the auth service and testing
        # endpoints decorated with require_acl()


class TestAccentAuthDependencies:
    """Test FastAPI dependencies for Accent-Auth."""

    @pytest.mark.asyncio
    async def test_get_current_user_caching(self):
        """Test that token validation results are cached."""
        # Mock Redis cache and verify caching behavior

    @pytest.mark.asyncio
    async def test_require_acl_dependency(self):
        """Test require_acl dependency factory."""
        from example_service.core.dependencies.accent_auth import require_acl
        from example_service.core.schemas.auth import AuthUser

        # Create mock user with ACLs
        user = AuthUser(
            user_id="test-user",
            permissions=["confd.users.read", "webhookd.subscriptions.*"],
            roles=[],
            acl={},
        )

        # Create ACL checker
        checker = require_acl("confd.users.read")

        # Should pass with correct ACL
        result = await checker(user)
        assert result.user_id == "test-user"

    @pytest.mark.asyncio
    async def test_require_acl_forbidden(self):
        """Test require_acl raises 403 for missing ACL."""
        from fastapi import HTTPException

        from example_service.core.dependencies.accent_auth import require_acl
        from example_service.core.schemas.auth import AuthUser

        user = AuthUser(
            user_id="test-user",
            permissions=["confd.users.read"],
            roles=[],
            acl={},
        )

        checker = require_acl("admin.all")

        with pytest.raises(HTTPException) as exc_info:
            await checker(user)

        assert exc_info.value.status_code == 403


class TestProtocolBasedAuth:
    """Test Protocol-based authentication using MockAuthClient.

    These tests demonstrate the advantage of the Protocol pattern:
    - No unittest.mock required
    - Clear, readable test code
    - Protocol compliance verified
    - Easy to test different scenarios
    """

    def test_protocol_compliance(self):
        """Test that MockAuthClient implements AuthClient protocol."""
        mock_client = MockAuthClient.admin()

        # Protocol check via isinstance
        assert isinstance(mock_client, AuthClient)

        # Verify protocol methods exist
        assert hasattr(mock_client, "is_configured")
        assert hasattr(mock_client, "mode")
        assert hasattr(mock_client, "validate_token")
        assert hasattr(mock_client, "check_token")
        assert hasattr(mock_client, "is_token_valid")

    def test_mock_client_properties(self):
        """Test MockAuthClient properties."""
        mock_client = MockAuthClient()

        assert mock_client.is_configured is True
        assert mock_client.mode == "mock"

    @pytest.mark.asyncio
    async def test_admin_persona(self, mock_auth_admin):
        """Test admin persona has full access."""
        token_info = await mock_auth_admin.validate_token("test-token")

        assert token_info.metadata.uuid == "admin-user-id"
        assert token_info.metadata.tenant_uuid == "admin-tenant-id"
        assert "#" in token_info.acl

        # Verify ACL helper works
        acl = AccentAuthACL(token_info.acl)
        assert acl.is_superuser()
        assert acl.has_permission("anything.at.all")

    @pytest.mark.asyncio
    async def test_readonly_persona(self, mock_auth_readonly):
        """Test readonly persona has limited access."""
        token_info = await mock_auth_readonly.validate_token("test-token")

        assert token_info.metadata.uuid == "readonly-user-id"
        assert "*.*.read" in token_info.acl

        # Can read
        acl = AccentAuthACL(token_info.acl)
        assert acl.has_permission("confd.users.read")
        assert acl.has_permission("webhookd.subscriptions.read")

        # Cannot write
        assert not acl.has_permission("confd.users.delete")
        assert not acl.has_permission("webhookd.subscriptions.create")

    @pytest.mark.asyncio
    async def test_user_persona(self, mock_auth_standard_user):
        """Test user persona with standard permissions."""
        token_info = await mock_auth_standard_user.validate_token("test-token")

        assert token_info.metadata.uuid == "user-user-id"
        assert "users.me.read" in token_info.acl
        assert "sessions.my_session.delete" in token_info.acl

        # Reserved word substitution
        acl = AccentAuthACL(
            token_info.acl,
            auth_id=token_info.metadata.uuid,
            session_id=token_info.session_uuid,
        )

        # Can access own user (me substitution)
        assert acl.has_permission("users.user-user-id.read")

        # Can manage own session
        assert acl.has_permission("sessions.mock-session-id.delete")

    @pytest.mark.asyncio
    async def test_unauthorized_persona(self, mock_auth_unauthorized):
        """Test unauthorized persona raises permission errors."""
        from example_service.infra.auth.testing import MissingPermissionsTokenException

        # Basic validation works (no ACL required)
        token_info = await mock_auth_unauthorized.validate_token("test-token")
        assert token_info.metadata.uuid == "unauthorized-user-id"
        assert len(token_info.acl) == 0

        # ACL check fails
        with pytest.raises(MissingPermissionsTokenException):
            await mock_auth_unauthorized.validate_token(
                "test-token",
                required_acl="users.read",
            )

    @pytest.mark.asyncio
    async def test_expired_persona(self, mock_auth_expired):
        """Test expired persona raises invalid token error."""
        from example_service.infra.auth.testing import InvalidTokenException

        with pytest.raises(InvalidTokenException, match="expired"):
            await mock_auth_expired.validate_token("test-token")

        # is_token_valid doesn't raise
        is_valid = await mock_auth_expired.is_token_valid("test-token")
        assert is_valid is False

    @pytest.mark.asyncio
    async def test_custom_permissions(self, mock_auth_custom):
        """Test custom permissions via factory."""
        client = mock_auth_custom(
            user_id="custom-user",
            permissions=["confd.users.read", "webhookd.#"],
            tenant_id="custom-tenant",
        )

        token_info = await client.validate_token("test-token")

        assert token_info.metadata.uuid == "custom-user"
        assert token_info.metadata.tenant_uuid == "custom-tenant"
        assert "confd.users.read" in token_info.acl
        assert "webhookd.#" in token_info.acl

        acl = AccentAuthACL(token_info.acl)
        assert acl.has_permission("confd.users.read")
        assert acl.has_permission("webhookd.subscriptions.create")
        assert not acl.has_permission("confd.users.delete")

    @pytest.mark.asyncio
    async def test_multitenant_scenario(self, mock_auth_multitenant):
        """Test multi-tenant isolation with token registry."""
        # Tenant A - admin
        token_a = await mock_auth_multitenant.validate_token("tenant-a-token")
        assert token_a.metadata.tenant_uuid == "tenant-a"
        assert token_a.metadata.uuid == "admin-user-a"
        assert "#" in token_a.acl

        # Tenant B - user
        token_b = await mock_auth_multitenant.validate_token("tenant-b-token")
        assert token_b.metadata.tenant_uuid == "tenant-b"
        assert token_b.metadata.uuid == "user-b"
        assert "#" not in token_b.acl

        # Tenant C - readonly
        token_c = await mock_auth_multitenant.validate_token("tenant-c-token")
        assert token_c.metadata.tenant_uuid == "tenant-c"
        assert token_c.metadata.uuid == "readonly-user-c"

        # Verify tenant isolation
        from example_service.infra.auth.testing import InvalidTokenException

        with pytest.raises(InvalidTokenException, match="mismatch"):
            await mock_auth_multitenant.validate_token(
                "tenant-a-token",
                tenant_uuid="tenant-b",  # Wrong tenant
            )

    @pytest.mark.asyncio
    async def test_acl_validation(self):
        """Test ACL validation in validate_token."""
        from example_service.infra.auth.testing import MissingPermissionsTokenException

        client = MockAuthClient(
            permissions=["users.read", "posts.write"],
        )

        # Valid ACL
        token_info = await client.validate_token(
            "test-token",
            required_acl="users.read",
        )
        assert token_info is not None

        # Invalid ACL
        with pytest.raises(
            MissingPermissionsTokenException,
            match=r"admin\.delete",
        ):
            await client.validate_token(
                "test-token",
                required_acl="admin.delete",
            )

    @pytest.mark.asyncio
    async def test_check_token_vs_is_token_valid(self):
        """Test difference between check_token and is_token_valid."""
        from example_service.infra.auth.testing import InvalidTokenException

        expired_client = MockAuthClient.expired()

        # check_token raises exception
        with pytest.raises(InvalidTokenException):
            await expired_client.check_token("test-token")

        # is_token_valid returns False (no exception)
        result = await expired_client.is_token_valid("test-token")
        assert result is False

    @pytest.mark.asyncio
    async def test_tenant_validation(self):
        """Test tenant UUID validation."""
        from example_service.infra.auth.testing import InvalidTokenException

        client = MockAuthClient(tenant_id="tenant-123")

        # Matching tenant
        token_info = await client.validate_token(
            "test-token",
            tenant_uuid="tenant-123",
        )
        assert token_info.metadata.tenant_uuid == "tenant-123"

        # Mismatched tenant
        with pytest.raises(InvalidTokenException, match="mismatch"):
            await client.validate_token(
                "test-token",
                tenant_uuid="different-tenant",
            )

    @pytest.mark.asyncio
    async def test_token_registry(self):
        """Test token registry for multi-user scenarios."""
        client = MockAuthClient()

        # Register multiple tokens
        client.register_token(
            "admin-token",
            "admin-id",
            ["#"],
            tenant_id="tenant-1",
        )
        client.register_token(
            "user-token",
            "user-id",
            ["users.read"],
            tenant_id="tenant-2",
        )

        # Validate different tokens
        admin_info = await client.validate_token("admin-token")
        assert admin_info.metadata.uuid == "admin-id"
        assert admin_info.metadata.tenant_uuid == "tenant-1"
        assert "#" in admin_info.acl

        user_info = await client.validate_token("user-token")
        assert user_info.metadata.uuid == "user-id"
        assert user_info.metadata.tenant_uuid == "tenant-2"
        assert "users.read" in user_info.acl

    @pytest.mark.asyncio
    async def test_fastapi_dependency_override(self, mock_auth_admin):
        """Test using MockAuthClient with FastAPI dependency overrides."""
        from example_service.core.dependencies.auth_client import get_auth_client

        # In real tests, override get_auth_client to return mock_auth_admin.

        # Verify the mock client works
        token_info = await mock_auth_admin.validate_token("test-token")
        assert isinstance(mock_auth_admin, AuthClient)
        assert token_info.metadata.uuid == "admin-user-id"

    def test_no_mocking_library_needed(self):
        """Demonstrate that no mocking library is needed.

        This test verifies that MockAuthClient provides everything needed
        for testing without unittest.mock, pytest-mock, or similar libraries.
        """
        # Create mock without any mocking libraries
        client = MockAuthClient.admin()

        # All assertions work on real methods and properties
        assert client.is_configured
        assert client.mode == "mock"

        # No patch(), MagicMock(), or AsyncMock() needed!
        # This is the power of Protocol-based design.
