"""Authentication client protocol definitions.

This module defines the AuthClient protocol that all authentication
implementations must satisfy. It enables:
- Protocol-based test doubles (no mocking library needed)
- Multiple authentication backends (HTTP, database, custom)
- Clear separation between interface and implementation
- Type-safe dependency injection

Pattern: Protocol-based abstraction (PEP 544)
Similar to: BusPublisher (messaging), StorageBackend (storage), HealthProvider (health)

The protocol uses structural subtyping (@runtime_checkable), so any class
implementing these methods will satisfy the protocol without explicit inheritance.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from example_service.infra.auth.models import AccentAuthToken


@runtime_checkable
class AuthClient(Protocol):
    """Protocol for authentication client operations.

    This protocol defines the contract for token validation and authorization.
    Implementations can use HTTP, database, or any other mechanism.

    The protocol specifies the minimum interface required for authentication:
    - Token validation with optional tenant and ACL checking
    - Boolean checks for token validity
    - Configuration status
    - Operational mode identification

    Implementations:
        - HttpAuthClient: External HTTP-based auth via accent-auth-client library
        - DatabaseAuthClient: Internal database access for accent-auth service
        - MockAuthClient: Test double for testing (no mocking library needed)

    Example:
        # Using in a route handler
        @router.get("/protected")
        async def protected_endpoint(
            token: str,
            auth_client: AuthClientDep,
        ):
            token_info = await auth_client.validate_token(token)
            return {"user_id": token_info.metadata.uuid}

        # Testing with Protocol-based test double
        mock_client = MockAuthClient.admin()
        app.dependency_overrides[get_auth_client] = lambda: mock_client
        response = await client.get("/protected", headers={"X-Auth-Token": "test"})
    """

    # ========================================================================
    # Properties
    # ========================================================================

    @property
    def is_configured(self) -> bool:
        """Check if the client is properly configured and ready for operations.

        Returns True if the client has all required configuration (connection
        details, credentials, etc.) and is ready to validate tokens.

        For HttpAuthClient: Returns True if accent-auth-client library is
        available and AUTH_SERVICE_URL is configured.

        For DatabaseAuthClient: Always returns True (dependencies injected
        at runtime via FastAPI DI).

        For MockAuthClient: Always returns True (test double).

        Returns:
            True if client is ready for operations, False otherwise

        Example:
            if auth_client.is_configured:
                await auth_client.validate_token(token)
            else:
                logger.warning("Auth client not configured")
        """
        ...

    @property
    def mode(self) -> str:
        """Get the operational mode of this client.

        Returns:
            "internal" for DatabaseAuthClient (direct DB access)
            "external" for HttpAuthClient (HTTP client)
            "mock" for MockAuthClient (test double)

        Example:
            logger.info(f"Auth client running in {auth_client.mode} mode")
        """
        ...

    # ========================================================================
    # Core Token Operations
    # ========================================================================

    async def validate_token(
        self,
        token: str,
        tenant_uuid: str | None = None,
        required_acl: str | None = None,
    ) -> AccentAuthToken:
        """Validate token and retrieve full token information.

        Validates the token against the authentication backend and returns
        complete token information including user details, ACL permissions,
        and metadata.

        The token must:
        1. Exist in the authentication system
        2. Not be expired
        3. Match the specified tenant (if tenant_uuid provided)
        4. Have the required ACL permission (if required_acl provided)

        Args:
            token: Bearer token to validate (UUID string format)
            tenant_uuid: Optional tenant UUID for multi-tenant validation.
                If specified, token's tenant must match.
            required_acl: Optional ACL pattern to check during validation
                (e.g., "confd.users.read", "admin.#").
                If specified, token must have this permission.

        Returns:
            AccentAuthToken with complete token information:
                - token: Token UUID
                - auth_id: Authentication backend ID
                - session_uuid: Session identifier
                - metadata: User UUID, tenant UUID, additional context
                - acl: List of ACL permission patterns
                - issued_at, expires_at: Timestamps

        Raises:
            InvalidTokenException: Token doesn't exist, expired, or tenant mismatch
            MissingPermissionsTokenException: Token lacks required_acl permission

        Example:
            # Basic validation
            token_info = await auth_client.validate_token("token-uuid")

            # With tenant validation
            token_info = await auth_client.validate_token(
                "token-uuid",
                tenant_uuid="tenant-123"
            )

            # With ACL requirement
            token_info = await auth_client.validate_token(
                "token-uuid",
                required_acl="confd.users.delete"
            )

            # Full validation
            token_info = await auth_client.validate_token(
                "token-uuid",
                tenant_uuid="tenant-123",
                required_acl="confd.users.delete"
            )
        """
        ...

    async def check_token(
        self,
        token: str,
        required_acl: str | None = None,
        tenant_uuid: str | None = None,
    ) -> bool:
        """Check if token is valid (returns boolean, raises on error).

        This is similar to validate_token() but returns a boolean instead of
        the full token information. It still raises exceptions for invalid
        tokens or missing permissions.

        Use this when you only need to know if a token is valid, not the
        full token details.

        Args:
            token: Bearer token to check
            required_acl: Optional ACL pattern to check
            tenant_uuid: Optional tenant UUID to validate against

        Returns:
            True if token is valid (and has required ACL if specified)

        Raises:
            InvalidTokenException: If token is invalid (external mode)
            MissingPermissionsTokenException: If lacks ACL (external mode)

        Note:
            In external mode (HttpAuthClient), this method raises exceptions
            like validate_token(). In internal mode (DatabaseAuthClient),
            behavior may vary by implementation.

        Example:
            # Check basic validity
            if await auth_client.check_token("token-uuid"):
                print("Token is valid")

            # Check with ACL
            if await auth_client.check_token("token-uuid", required_acl="admin.#"):
                print("Token has admin access")
        """
        ...

    async def is_token_valid(
        self,
        token: str,
        required_acl: str | None = None,
        tenant_uuid: str | None = None,
    ) -> bool:
        """Check if token is valid without raising exceptions.

        This is a safe version of check_token() that never raises exceptions.
        It returns False for any validation failure (invalid token, missing
        ACL, tenant mismatch, etc.).

        Use this for non-critical checks where you want to handle invalid
        tokens gracefully.

        Args:
            token: Bearer token to check
            required_acl: Optional ACL pattern to check
            tenant_uuid: Optional tenant UUID to validate against

        Returns:
            True if token is valid and meets all criteria, False otherwise
            (never raises exceptions)

        Example:
            # Safe check with fallback
            if await auth_client.is_token_valid("token-uuid"):
                user = await get_user_from_token(token)
            else:
                user = get_anonymous_user()

            # Conditional feature access
            has_admin = await auth_client.is_token_valid(
                "token-uuid",
                required_acl="admin.#"
            )
            if has_admin:
                show_admin_panel()
        """
        ...


__all__ = [
    "AuthClient",
]
