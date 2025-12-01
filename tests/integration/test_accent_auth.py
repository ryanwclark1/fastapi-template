"""Integration tests for Accent-Auth integration.

Tests cover:
- Token validation via Accent-Auth API
- ACL permission checking
- Multi-tenant context
- Header-based authentication
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from example_service.infra.auth.accent_auth import (
    AccentAuthACL,
    AccentAuthClient,
    AccentAuthToken,
)


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
            }
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
            ]
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
            ]
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
            ]
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

        async with AsyncClient(app=app, base_url="http://test") as ac:
            yield ac

    @pytest.mark.asyncio
    async def test_protected_endpoint_without_token(self, client: AsyncClient):
        """Test accessing protected endpoint without X-Auth-Token."""
        response = await client.get("/api/v1/reminders")

        assert response.status_code == 401
        assert "X-Auth-Token" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_protected_endpoint_with_invalid_token(self, client: AsyncClient):
        """Test accessing protected endpoint with invalid token."""
        response = await client.get(
            "/api/v1/reminders",
            headers={"X-Auth-Token": "invalid-token"},
        )

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_tenant_header_propagation(self, client: AsyncClient):
        """Test that Accent-Tenant header is used for tenant context."""
        # This would require mocking the auth service
        # Placeholder for actual implementation
        pass

    @pytest.mark.asyncio
    async def test_acl_permission_check(self, client: AsyncClient):
        """Test ACL-based permission checking on endpoints."""
        # This would require mocking the auth service and testing
        # endpoints decorated with require_acl()
        pass


class TestAccentAuthDependencies:
    """Test FastAPI dependencies for Accent-Auth."""

    @pytest.mark.asyncio
    async def test_get_current_user_caching(self):
        """Test that token validation results are cached."""
        # Mock Redis cache and verify caching behavior
        pass

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
