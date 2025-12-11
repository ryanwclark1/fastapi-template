"""Database-based Accent-Auth client implementation (internal mode).

This module provides the DatabaseAuthClient class, which implements the AuthClient
protocol using direct database access. This client is automatically used when
SERVICE_NAME == "accent-auth" to prevent circular HTTP dependencies.

Why This Exists:
    When the accent-auth service needs to validate tokens (e.g., for its own
    admin endpoints), it cannot make HTTP calls to itself. This would create
    circular dependencies and unnecessary network overhead. Instead, we bypass
    the HTTP layer and access the token data directly from the database.

Performance Benefits:
    - 10-100x faster than HTTP (no network serialization, no HTTP overhead)
    - Direct database access with single query
    - No external service dependencies
    - Simpler error handling (database exceptions only)
    - Full stack traces for debugging

Key Features:
    - Protocol-compliant (implements AuthClient)
    - FastAPI dependency injection support
    - ACL validation using core ACL module
    - Token expiration checking
    - Multi-tenant support

Dependency Injection:
    This client is designed to work with FastAPI's dependency injection system.
    The database session and TokenService are injected at runtime rather than
    during initialization, allowing proper request-scoped lifecycle management.

Example:
    # Via dependency injection (recommended)
    from example_service.core.dependencies.auth_client import AuthClientDep

    @router.get("/internal-endpoint")
    async def internal_endpoint(
        client: AuthClientDep,
        session: AsyncSession = Depends(get_db_session),
        token_service: TokenServiceDep = Depends(get_token_service),
    ):
        # DatabaseAuthClient automatically receives session and token_service
        token_info = await client.validate_token(
            request.headers["X-Auth-Token"],
            session=session,
            token_service=token_service,
        )
        return {"user_id": token_info.metadata.uuid}

Pattern: Database adapter with FastAPI dependency injection
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from example_service.core.acl import AccessCheck
from example_service.infra.auth.models import AccentAuthToken

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    # TokenServiceDep and Token are only needed for internal mode
    # which requires the accent-auth service. Template users will use
    # external mode (HTTP) which doesn't need these.
    try:
        from accent_auth.core.dependencies.services import (
            TokenServiceDep,  # type: ignore[import-not-found]
        )
    except ImportError:
        TokenServiceDep = None

logger = logging.getLogger(__name__)

# Import exceptions if accent-auth-client is available
try:
    from accent_auth_client.exceptions import (
        InvalidTokenException,
        MissingPermissionsTokenException,
    )

    ACCENT_AUTH_CLIENT_AVAILABLE = True
except ImportError:
    # Define fallback exceptions if library not available
    ACCENT_AUTH_CLIENT_AVAILABLE = False

    class InvalidTokenException(ValueError):  # type: ignore[no-redef]
        """Fallback exception for invalid tokens."""

    class MissingPermissionsTokenException(ValueError):  # type: ignore[no-redef]
        """Fallback exception for missing permissions."""


class DatabaseAuthClient:
    """Database-based authentication client (internal mode).

    Implements the AuthClient protocol using direct database access to the
    accent-auth token storage. This client is automatically used when running
    within the accent-auth service itself (SERVICE_NAME == "accent-auth").

    The client prevents circular HTTP dependencies by accessing tokens directly
    from the database instead of making HTTP calls to the same service.

    Architecture:
        DatabaseAuthClient (AuthClient protocol)
          └─> TokenService (business logic)
              └─> TokenRepository (data access)
                  └─> Database (PostgreSQL)

    Attributes:
        _session: Cached database session (optional, usually injected per-request)
        _token_service: Cached token service (optional, usually injected per-request)

    Design Notes:
        - Database session and TokenService are injected via method parameters
        - Supports FastAPI dependency injection pattern
        - Falls back to cached instances if no parameters provided
        - Raises exceptions matching accent-auth-client library interface
    """

    def __init__(
        self,
        session: AsyncSession | None = None,
        token_service: TokenServiceDep | None = None,
    ) -> None:
        """Initialize database authentication client.

        Args:
            session: Optional database session (usually injected per-request)
            token_service: Optional token service (usually injected per-request)

        Note:
            In most cases, you should pass None for both parameters and instead
            provide them in the method calls. This allows FastAPI's dependency
            injection to manage the request-scoped lifecycle properly.

        Example:
            # Recommended (DI-managed lifecycle)
            client = DatabaseAuthClient()
            token_info = await client.validate_token(
                token,
                session=session,  # Injected per-request
                token_service=token_service,  # Injected per-request
            )

            # Direct usage (testing)
            client = DatabaseAuthClient(session=session, token_service=token_service)
            token_info = await client.validate_token(token)
        """
        self._session = session
        self._token_service = token_service

        logger.info("DatabaseAuthClient initialized (internal mode)")

    # ========================================================================
    # AuthClient Protocol Implementation
    # ========================================================================

    @property
    def is_configured(self) -> bool:
        """Check if client is properly configured and ready for operations.

        For DatabaseAuthClient, configuration is always True because dependencies
        are injected at runtime via FastAPI dependency injection. The client
        doesn't require upfront configuration.

        Returns:
            True (always ready - dependencies injected at call time)
        """
        return True

    @property
    def mode(self) -> str:
        """Get the operational mode of this client.

        Returns:
            "internal" (direct database access)
        """
        return "internal"

    async def _ensure_dependencies(
        self,
        session: AsyncSession | None = None,
        token_service: TokenServiceDep | None = None,
    ) -> tuple[AsyncSession, TokenServiceDep]:
        """Ensure database session and token service are available.

        Tries to resolve dependencies in this order:
        1. Use parameters if provided (per-request injection)
        2. Use cached instances if available (initialization)
        3. Raise error if neither available

        Args:
            session: Optional database session
            token_service: Optional token service

        Returns:
            Tuple of (session, token_service)

        Raises:
            RuntimeError: If dependencies cannot be resolved
        """
        # If provided as parameters, use them (preferred - request-scoped)
        if session and token_service:
            return session, token_service

        # Try to use cached instances if available (initialization)
        if self._session and self._token_service:
            return self._session, self._token_service

        # Cannot resolve dependencies - must be provided
        msg = (
            "DatabaseAuthClient requires database session and token service. "
            "Pass them as arguments or use within FastAPI dependency context. "
            "Example: client.validate_token(token, session=session, token_service=token_service)"
        )
        raise RuntimeError(msg)

    async def validate_token(
        self,
        token: str,
        tenant_uuid: str | None = None,
        required_acl: str | None = None,
        *,
        session: AsyncSession | None = None,
        token_service: TokenServiceDep | None = None,
    ) -> AccentAuthToken:
        """Validate token using direct database access.

        Validates the token against the database and returns complete token
        information. This method bypasses HTTP and queries the token table
        directly for optimal performance.

        Validation includes:
        1. Token exists in database
        2. Token is not expired
        3. Token tenant matches (if tenant_uuid specified)
        4. Token has required ACL (if required_acl specified)

        Args:
            token: Bearer token to validate (UUID string format)
            tenant_uuid: Optional tenant UUID for multi-tenant validation.
                If specified, token's tenant must match.
            required_acl: Optional ACL pattern to check during validation
                (e.g., "confd.users.read", "admin.#").
                If specified, token must have this permission.
            session: Database session (required if not provided in __init__)
            token_service: Token service (required if not provided in __init__)

        Returns:
            AccentAuthToken with complete token information

        Raises:
            InvalidTokenException: Token doesn't exist, expired, or tenant mismatch
            MissingPermissionsTokenException: Token lacks required_acl permission
            RuntimeError: If session or token_service not available

        Example:
            # With FastAPI dependency injection
            token_info = await client.validate_token(
                "token-uuid",
                session=session,
                token_service=token_service,
            )

            # With ACL requirement
            token_info = await client.validate_token(
                "token-uuid",
                required_acl="confd.users.delete",
                session=session,
                token_service=token_service,
            )
        """
        # Ensure dependencies are available
        session, token_service = await self._ensure_dependencies(session, token_service)

        # Direct database lookup
        db_token = await token_service.get_token(session, token)

        if not db_token:
            msg = "Invalid token"
            raise InvalidTokenException(msg)

        # Check expiration
        if db_token.is_expired:
            msg = "Token expired"
            raise InvalidTokenException(msg)

        # Check tenant if specified
        if tenant_uuid:
            token_tenant = (
                db_token.metadata_.get("tenant_uuid") if db_token.metadata_ else None
            )
            if token_tenant != tenant_uuid:
                msg = "Token tenant mismatch"
                raise InvalidTokenException(msg)

        # Check ACL if specified
        if required_acl:
            checker = AccessCheck(
                auth_id=db_token.auth_id,
                session_id=db_token.session_uuid or "",
                acl=db_token.acl or [],
            )
            if not checker.matches_required_access(required_acl):
                message = f"Token lacks required ACL: {required_acl}"
                raise MissingPermissionsTokenException(message)

        # Convert to AccentAuthToken
        token_info = AccentAuthToken.from_token_model(db_token)

        logger.debug(
            "Token validated successfully (database)",
            extra={
                "user_uuid": token_info.metadata.uuid,
                "tenant_uuid": token_info.metadata.tenant_uuid,
                "acl_count": len(token_info.acl),
            },
        )

        return token_info

    async def check_token(
        self,
        token: str,
        required_acl: str | None = None,
        tenant_uuid: str | None = None,
        *,
        session: AsyncSession | None = None,
        token_service: TokenServiceDep | None = None,
    ) -> bool:
        """Check if token is valid (returns boolean, raises on error).

        Similar to validate_token() but returns a boolean instead of the
        full token information. Still raises exceptions for invalid tokens
        or missing permissions.

        Args:
            token: Bearer token to check
            required_acl: Optional ACL pattern to check
            tenant_uuid: Optional tenant UUID to validate against
            session: Database session (required if not provided in __init__)
            token_service: Token service (required if not provided in __init__)

        Returns:
            True if token is valid (and has required ACL if specified)

        Raises:
            InvalidTokenException: If token is invalid
            MissingPermissionsTokenException: If token lacks ACL
            RuntimeError: If session or token_service not available

        Example:
            # Check basic validity
            is_valid = await client.check_token(
                "token-uuid",
                session=session,
                token_service=token_service,
            )
        """
        try:
            await self.validate_token(
                token,
                tenant_uuid,
                required_acl,
                session=session,
                token_service=token_service,
            )
            return True
        except (
            InvalidTokenException,
            MissingPermissionsTokenException,
            ValueError,
            RuntimeError,
        ):
            return False

    async def is_token_valid(
        self,
        token: str,
        required_acl: str | None = None,
        tenant_uuid: str | None = None,
        *,
        session: AsyncSession | None = None,
        token_service: TokenServiceDep | None = None,
    ) -> bool:
        """Check if token is valid without raising exceptions.

        This is a safe version of check_token() that never raises exceptions.
        It returns False for any validation failure (invalid token, missing
        ACL, tenant mismatch, database errors, etc.).

        Args:
            token: Bearer token to check
            required_acl: Optional ACL pattern to check
            tenant_uuid: Optional tenant UUID to validate against
            session: Database session (required if not provided in __init__)
            token_service: Token service (required if not provided in __init__)

        Returns:
            True if token is valid and meets all criteria, False otherwise
            (never raises exceptions)

        Example:
            # Safe check with fallback
            is_valid = await client.is_token_valid(
                "token-uuid",
                session=session,
                token_service=token_service,
            )
            if is_valid:
                process_request()
            else:
                return_unauthorized()
        """
        return await self.check_token(
            token,
            required_acl,
            tenant_uuid,
            session=session,
            token_service=token_service,
        )


__all__ = [
    "DatabaseAuthClient",
    "InvalidTokenException",
    "MissingPermissionsTokenException",
]
