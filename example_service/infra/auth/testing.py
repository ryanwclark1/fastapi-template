"""Mock authentication client for testing.

This module provides MockAuthClient, a Protocol-based test double that implements
the AuthClient protocol without requiring mocking libraries or external services.

Key Features:
    - Protocol-compliant (implements AuthClient via structural subtyping)
    - No mocking library needed (unittest.mock not required)
    - Pre-built factory methods for common scenarios
    - Token registry for multi-user testing
    - Configurable ACL patterns and permissions
    - Deterministic test behavior

Pre-Built Personas:
    - admin(): Full system access (# wildcard)
    - readonly(): Read-only permissions (*.*.read)
    - user(): Standard user permissions
    - unauthorized(): No permissions (empty ACL)
    - expired(): Simulates expired token

Usage:
    # Basic usage with pre-built persona
    from example_service.infra.auth.testing import MockAuthClient

    mock_client = MockAuthClient.admin()
    token_info = await mock_client.validate_token("test-token")
    assert token_info.metadata.uuid == "admin-user-id"

    # Custom permissions
    mock_client = MockAuthClient(
        user_id="user-123",
        permissions=["confd.users.read", "webhookd.#"],
        tenant_id="tenant-456",
    )

    # FastAPI dependency override
    from example_service.core.dependencies.auth_client import get_auth_client

    app.dependency_overrides[get_auth_client] = lambda: MockAuthClient.admin()

    # Multi-user scenario
    client = MockAuthClient()
    client.register_token("admin-token", "admin-id", ["#"])
    client.register_token("user-token", "user-id", ["users.read"])

    admin_info = await client.validate_token("admin-token")
    user_info = await client.validate_token("user-token")

Pattern: Protocol-based test double (no mocking library needed)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import logging
from typing import TYPE_CHECKING

from example_service.infra.auth.models import (
    AccentAuthACL,
    AccentAuthMetadata,
    AccentAuthToken,
)

if TYPE_CHECKING:
    from typing import Self

logger = logging.getLogger(__name__)

# Import exceptions if accent-auth-client is available, otherwise use fallbacks
try:
    from accent_auth_client.exceptions import (
        InvalidTokenException,
        MissingPermissionsTokenException,
    )
except ImportError:
    # Define fallback exceptions
    class InvalidTokenException(ValueError):  # type: ignore[no-redef]
        """Fallback exception for invalid tokens."""

    class MissingPermissionsTokenException(ValueError):  # type: ignore[no-redef]
        """Fallback exception for missing permissions."""


class MockAuthClient:
    """Mock authentication client for testing (Protocol-based test double).

    Implements the AuthClient protocol via structural subtyping, providing
    deterministic test behavior without external service dependencies or
    mocking libraries.

    This mock supports:
    - Pre-built personas for common scenarios (admin, readonly, user, etc.)
    - Custom user configurations
    - Token registry for multi-user scenarios
    - ACL pattern validation
    - Tenant isolation testing
    - Token expiration simulation

    Attributes:
        user_id: User identifier
        tenant_id: Tenant identifier
        permissions: List of ACL permission patterns
        expired: Whether token is expired
        _token_registry: Registry for multi-user scenarios

    Example:
        # Simple admin mock
        mock = MockAuthClient.admin()
        token_info = await mock.validate_token("any-token")
        assert token_info.metadata.uuid == "admin-user-id"

        # Custom mock
        mock = MockAuthClient(
            user_id="custom-user",
            permissions=["users.{user_id}.read"],
            tenant_id="tenant-123",
        )
        token_info = await mock.validate_token("token", tenant_uuid="tenant-123")
        assert token_info.acl == ["users.{user_id}.read"]

        # Multi-user mock
        mock = MockAuthClient()
        mock.register_token("admin-token", "admin", ["#"])
        mock.register_token("user-token", "user", ["users.read"])

        admin = await mock.validate_token("admin-token")
        user = await mock.validate_token("user-token")
    """

    def __init__(
        self,
        user_id: str = "mock-user-id",
        tenant_id: str = "mock-tenant-id",
        permissions: list[str] | None = None,
        expired: bool = False,
        session_id: str = "mock-session-id",
    ) -> None:
        """Initialize mock authentication client.

        Args:
            user_id: User identifier (default: "mock-user-id")
            tenant_id: Tenant identifier (default: "mock-tenant-id")
            permissions: List of ACL patterns (default: ["#"] - full access)
            expired: Whether token should be expired (default: False)
            session_id: Session identifier (default: "mock-session-id")
        """
        self.user_id = user_id
        self.tenant_id = tenant_id
        self.permissions = permissions if permissions is not None else ["#"]
        self.expired = expired  # type: ignore[assignment,method-assign]
        self.session_id = session_id

        # Token registry for multi-user scenarios
        self._token_registry: dict[str, dict[str, str | list[str] | bool]] = {}

        logger.debug(
            "MockAuthClient initialized",
            extra={
                "user_id": user_id,
                "tenant_id": tenant_id,
                "permissions": self.permissions,
                "expired": expired,
            },
        )

    # ========================================================================
    # Factory Methods (Pre-Built Personas)
    # ========================================================================

    @classmethod
    def admin(cls) -> Self:
        """Create mock client with admin permissions (# wildcard).

        Returns:
            MockAuthClient with full system access

        Example:
            mock = MockAuthClient.admin()
            token_info = await mock.validate_token("test-token")
            assert "#" in token_info.acl
        """
        return cls(
            user_id="admin-user-id",
            tenant_id="admin-tenant-id",
            permissions=["#"],
        )

    @classmethod
    def readonly(cls) -> Self:
        """Create mock client with read-only permissions.

        Returns:
            MockAuthClient with *.*.read permissions

        Example:
            mock = MockAuthClient.readonly()
            token_info = await mock.validate_token("test-token")
            acl = AccentAuthACL(token_info.acl)
            assert acl.has_permission("confd.users.read")
            assert not acl.has_permission("confd.users.delete")
        """
        return cls(
            user_id="readonly-user-id",
            tenant_id="readonly-tenant-id",
            permissions=["*.*.read"],
        )

    @classmethod
    def user(cls) -> Self:
        """Create mock client with standard user permissions.

        Returns:
            MockAuthClient with typical user-level access

        Example:
            mock = MockAuthClient.user()
            token_info = await mock.validate_token("test-token")
            acl = AccentAuthACL(token_info.acl)
            assert acl.has_permission("users.me.read")
        """
        return cls(
            user_id="user-user-id",
            tenant_id="user-tenant-id",
            permissions=[
                "users.me.read",
                "users.me.write",
                "sessions.my_session.read",
                "sessions.my_session.delete",
            ],
        )

    @classmethod
    def unauthorized(cls) -> Self:
        """Create mock client with no permissions (empty ACL).

        Returns:
            MockAuthClient with no permissions

        Example:
            mock = MockAuthClient.unauthorized()
            with pytest.raises(MissingPermissionsTokenException):
                await mock.validate_token("test-token", required_acl="users.read")
        """
        return cls(
            user_id="unauthorized-user-id",
            tenant_id="unauthorized-tenant-id",
            permissions=[],
        )

    @classmethod
    def expired(cls) -> Self:
        """Create mock client with expired token.

        Returns:
            MockAuthClient that simulates expired token

        Example:
            mock = MockAuthClient.expired()
            with pytest.raises(InvalidTokenException):
                await mock.validate_token("test-token")
        """
        return cls(
            user_id="expired-user-id",
            tenant_id="expired-tenant-id",
            permissions=["#"],
            expired=True,
        )

    # ========================================================================
    # Token Registry (Multi-User Scenarios)
    # ========================================================================

    def register_token(
        self,
        token: str,
        user_id: str,
        permissions: list[str],
        tenant_id: str | None = None,
        expired: bool = False,
    ) -> None:
        """Register token for multi-user testing scenarios.

        Allows simulating multiple users with different permissions
        by registering distinct tokens.

        Args:
            token: Token value to register
            user_id: User identifier for this token
            permissions: ACL permissions for this token
            tenant_id: Optional tenant identifier (defaults to "mock-tenant-id")
            expired: Whether this token is expired

        Example:
            mock = MockAuthClient()
            mock.register_token("admin-token", "admin", ["#"])
            mock.register_token("user-token", "user", ["users.read"])

            admin = await mock.validate_token("admin-token")
            user = await mock.validate_token("user-token")

            assert admin.metadata.uuid == "admin"
            assert user.metadata.uuid == "user"
        """
        self._token_registry[token] = {
            "user_id": user_id,
            "permissions": permissions,
            "tenant_id": tenant_id or "mock-tenant-id",
            "expired": expired,
        }

        logger.debug(
            "Token registered in MockAuthClient",
            extra={
                "token": token[:8] + "...",
                "user_id": user_id,
                "tenant_id": tenant_id,
                "permissions": permissions,
            },
        )

    # ========================================================================
    # AuthClient Protocol Implementation
    # ========================================================================

    @property
    def is_configured(self) -> bool:
        """Check if client is ready for operations.

        Returns:
            True (always ready for testing)
        """
        return True

    @property
    def mode(self) -> str:
        """Get operational mode.

        Returns:
            "mock" (test double)
        """
        return "mock"

    async def validate_token(
        self,
        token: str,
        tenant_uuid: str | None = None,
        required_acl: str | None = None,
    ) -> AccentAuthToken:
        """Validate token and return full token information (mock implementation).

        Checks token against registry (if multi-user) or default configuration.
        Validates expiration, tenant matching, and ACL requirements.

        Args:
            token: Token to validate (any string accepted)
            tenant_uuid: Optional tenant UUID for validation
            required_acl: Optional ACL pattern to check

        Returns:
            AccentAuthToken with mock data

        Raises:
            InvalidTokenException: If token is expired or tenant mismatch
            MissingPermissionsTokenException: If lacks required_acl

        Example:
            mock = MockAuthClient.admin()
            token_info = await mock.validate_token("test-token")
            assert token_info.metadata.uuid == "admin-user-id"

            # With ACL requirement
            token_info = await mock.validate_token(
                "test-token",
                required_acl="users.delete"
            )
        """
        # Check token registry for multi-user scenarios
        if token in self._token_registry:
            token_data = self._token_registry[token]
            user_id = str(token_data["user_id"])
            tenant_id = str(token_data["tenant_id"])
            permissions = list(token_data["permissions"])  # type: ignore[arg-type]
            is_expired = bool(token_data.get("expired", False))
        else:
            # Use default configuration
            user_id = self.user_id
            tenant_id = self.tenant_id
            permissions = self.permissions
            is_expired = self.expired  # type: ignore[assignment]

        # Check expiration
        if is_expired:
            msg = "Token expired (mock)"
            raise InvalidTokenException(msg)

        # Check tenant if specified
        if tenant_uuid and tenant_id != tenant_uuid:
            msg = f"Token tenant mismatch: expected {tenant_uuid}, got {tenant_id}"
            raise InvalidTokenException(msg)

        # Check ACL if specified
        if required_acl:
            acl_checker = AccentAuthACL(
                permissions,
                auth_id=user_id,
                session_id=self.session_id,
            )
            if not acl_checker.has_permission(required_acl):
                msg = f"Token lacks required ACL: {required_acl}"
                raise MissingPermissionsTokenException(msg)

        # Create mock token info
        now = datetime.now(tz=UTC)
        expires_at = now + timedelta(hours=24)

        metadata = AccentAuthMetadata(
            uuid=user_id,
            tenant_uuid=tenant_id,
            auth_id=user_id,
            pbx_user_uuid=None,
            accent_uuid=None,
        )

        return AccentAuthToken(
            token=token,
            auth_id=user_id,
            session_uuid=self.session_id,
            accent_uuid=None,
            issued_at=now.isoformat(),
            expires_at=expires_at.isoformat(),
            utc_issued_at=now.isoformat(),
            utc_expires_at=expires_at.isoformat(),
            metadata=metadata,
            acl=permissions,
            user_agent="MockAuthClient/1.0",
            remote_addr="127.0.0.1",
        )

    async def check_token(
        self,
        token: str,
        required_acl: str | None = None,
        tenant_uuid: str | None = None,
    ) -> bool:
        """Check if token is valid (raises on error).

        Args:
            token: Token to check
            required_acl: Optional ACL to check
            tenant_uuid: Optional tenant UUID

        Returns:
            True if token is valid

        Raises:
            InvalidTokenException: If token invalid
            MissingPermissionsTokenException: If lacks ACL

        Example:
            mock = MockAuthClient.admin()
            assert await mock.check_token("test-token")

            with pytest.raises(MissingPermissionsTokenException):
                await mock.check_token("test-token", required_acl="admin.delete")
        """
        await self.validate_token(token, tenant_uuid, required_acl)
        return True

    async def is_token_valid(
        self,
        token: str,
        required_acl: str | None = None,
        tenant_uuid: str | None = None,
    ) -> bool:
        """Check if token is valid without raising exceptions.

        Args:
            token: Token to check
            required_acl: Optional ACL to check
            tenant_uuid: Optional tenant UUID

        Returns:
            True if valid, False otherwise (never raises)

        Example:
            mock = MockAuthClient.expired()
            assert not await mock.is_token_valid("test-token")

            mock = MockAuthClient.admin()
            assert await mock.is_token_valid("test-token")
        """
        try:
            await self.validate_token(token, tenant_uuid, required_acl)
            return True
        except (InvalidTokenException, MissingPermissionsTokenException):
            return False


__all__ = [
    "InvalidTokenException",
    "MissingPermissionsTokenException",
    "MockAuthClient",
]
