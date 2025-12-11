"""Accent-Auth integration for authentication and authorization.

This module provides integration with the Accent-Auth service via the
official accent-auth-client library. It supports:
- Token validation and retrieval
- ACL-based authorization with dot-notation
- Multi-tenant support via Accent-Tenant header
- Session management

═══════════════════════════════════════════════════════════════════════════════
DUAL-MODE ARCHITECTURE: AUTOMATIC INTERNAL/EXTERNAL ROUTING
═══════════════════════════════════════════════════════════════════════════════

This module implements an adaptive client pattern that automatically chooses
between two execution modes based on the SERVICE_NAME environment variable:

┌────────────────────────────────────────────────────────────────────────────┐
│ MODE DETECTION LOGIC                                                       │
│                                                                            │
│   if SERVICE_NAME == "accent-auth":                                        │
│       → INTERNAL MODE (Database Access)                                    │
│   else:                                                                    │
│       → EXTERNAL MODE (HTTP Client)                                        │
└────────────────────────────────────────────────────────────────────────────┘

INTERNAL MODE (accent-auth service calling itself):
───────────────────────────────────────────────────
Configuration:
    SERVICE_NAME=accent-auth  # ← Triggers internal mode

Flow:
    AccentAuthClient.validate_token()
      └─> _InternalTokenAdapter.validate_token()
          └─> TokenService.get_token(session, token_uuid)
              └─> TokenRepository.get(session, token_uuid)
                  └─> SELECT * FROM tokens WHERE uuid = ?

Benefits:
    ✅ 10-100x faster (direct database access)
    ✅ No network overhead or HTTP serialization
    ✅ Prevents circular HTTP dependencies
    ✅ Simpler error handling (database exceptions)
    ✅ Better debugging (full stack traces)

Dependencies:
    - AsyncSession (database connection)
    - TokenService (business logic layer)

EXTERNAL MODE (other services calling accent-auth):
────────────────────────────────────────────────────
Configuration:
    SERVICE_NAME=voicemail-service  # ← Triggers external mode
    AUTH_SERVICE_URL=https://accent-auth:443
    AUTH_SERVICE_TOKEN=secret-token

Flow:
    AccentAuthClient.validate_token()
      └─> accent_auth_client.token.get_token()
          └─> GET https://accent-auth:443/api/tokens/{token}
              └─> (network call to accent-auth service)

Benefits:
    ✅ Proper service boundaries
    ✅ Works across network/containers
    ✅ Standard HTTP-based microservice pattern
    ✅ No database coupling

Dependencies:
    - accent-auth-client library (pip install accent-auth-client)
    - AUTH_SERVICE_URL configuration

WHY THIS PATTERN?
─────────────────
Problem: When accent-auth needs to validate a token for internal operations
(e.g., validating admin access for a management API), making an HTTP call to
itself creates:
    ❌ Circular dependency (Service → HTTP → Same Service)
    ❌ Performance overhead (network, serialization, deserialization)
    ❌ Resource waste (HTTP connections, thread context switching)
    ❌ Complexity (HTTP retries, timeouts, error handling)

Solution: Auto-detect "we're calling ourselves" and use direct database access.
The same AccentAuthClient code works in both modes - consumers don't need to
know or care which mode is active.

FOR FASTAPI TEMPLATE USERS
───────────────────────────
If you're using this file from the fastapi-template, your service will
AUTOMATICALLY use EXTERNAL MODE (HTTP client) because your SERVICE_NAME
will not be "accent-auth".

You don't need to do anything special - just use AccentAuthClient normally:
    async with AccentAuthClient() as client:
        token_info = await client.validate_token(token)

The internal mode path (database) is only activated when SERVICE_NAME equals
"accent-auth", which only happens in the accent-auth service itself. This
dual-mode implementation is included in the template for completeness and
future extensibility, but template-based services will always use HTTP mode.

USAGE EXAMPLES
──────────────
Same code works in both modes:

    from accent_auth.infra.auth import AccentAuthClient

    async with AccentAuthClient() as client:
        # Automatically uses internal or external mode
        token_info = await client.validate_token(token)
        has_access = await client.check_token(token, "confd.users.read")

See AccentAuthClient class docstring for detailed examples and API reference.

Requirements:
    pip install accent-auth-client

    Or add to pyproject.toml:
    [project.dependencies]
    accent-auth-client = "..."
"""

from __future__ import annotations

from datetime import UTC, datetime
from functools import lru_cache
import logging
from typing import TYPE_CHECKING, Any, Self

from pydantic import BaseModel, Field, model_validator

from example_service.core.acl import AccessCheck, get_cached_access_check
from example_service.core.schemas.auth import AuthUser
from example_service.core.settings import get_app_settings, get_auth_settings

if TYPE_CHECKING:
    from types import TracebackType

    from sqlalchemy.ext.asyncio import AsyncSession

    # Note: TokenServiceDep and Token are only needed for internal mode
    # which requires the accent-auth service. Template users will use
    # external mode (HTTP) which doesn't need these.
    try:
        from accent_auth.core.dependencies.services import (
            TokenServiceDep,
        )
        from accent_auth.features.tokens.models import (
            Token,
        )
    except ImportError:
        # Template services won't have these - only needed for internal mode
        TokenServiceDep = None
        Token = None

logger = logging.getLogger(__name__)

# Import the accent-auth-client library (required)
try:
    from accent_auth_client import (
        Client as AccentAuthClientLib,
    )
    from accent_auth_client.exceptions import (
        InvalidTokenException,
        MissingPermissionsTokenException,
    )
    from accent_auth_client.types import TokenDict

    ACCENT_AUTH_CLIENT_AVAILABLE = True
    logger.debug("accent-auth-client library loaded")
except ImportError:
    ACCENT_AUTH_CLIENT_AVAILABLE = False
    AccentAuthClientLib = None  # type: ignore[misc,assignment]
    InvalidTokenException = Exception  # type: ignore[misc,assignment]
    MissingPermissionsTokenException = Exception  # type: ignore[misc,assignment]
    TokenDict = dict  # type: ignore[misc,assignment]
    logger.warning(
        "accent-auth-client library not installed. "
        "Install with: pip install accent-auth-client",
    )


class AccentAuthMetadata(BaseModel):
    """Accent-Auth token metadata."""

    uuid: str = Field(description="User UUID")
    tenant_uuid: str = Field(description="Tenant UUID")
    auth_id: str | None = Field(default=None, description="Auth backend ID")
    pbx_user_uuid: str | None = Field(default=None, description="PBX user UUID")
    accent_uuid: str | None = Field(default=None, description="Accent UUID")


class AccentAuthToken(BaseModel):
    """Accent-Auth token response model."""

    token: str = Field(description="Token value")
    auth_id: str = Field(description="Authentication ID")
    session_uuid: str | None = Field(default=None, description="Session UUID")
    accent_uuid: str | None = Field(default=None, description="Accent UUID")
    issued_at: str = Field(description="Token issue timestamp")
    expires_at: str = Field(description="Token expiration timestamp")
    utc_issued_at: str = Field(description="UTC issue timestamp")
    utc_expires_at: str = Field(description="UTC expiration timestamp")
    metadata: AccentAuthMetadata = Field(description="Token metadata")
    acl: list[str] = Field(default_factory=list, description="Access Control List")
    user_agent: str | None = Field(default=None, description="User agent")
    remote_addr: str | None = Field(default=None, description="Remote address")

    @model_validator(mode="before")
    @classmethod
    def _coerce_acl_field(cls, data: Any) -> Any:
        """Support legacy 'acls' field name returned by Accent-Auth API."""
        if isinstance(data, dict) and "acl" not in data and "acls" in data:
            # Copy to avoid mutating caller-provided dict
            coerced = dict(data)
            coerced["acl"] = coerced.get("acls")
            return coerced
        return data

    @property
    def acls(self) -> list[str]:
        """Backward-compatible alias for ACL list."""
        return self.acl

    @classmethod
    def from_token_dict(cls, data: dict[str, Any]) -> AccentAuthToken:
        """Create from accent-auth-client TokenDict.

        Args:
            data: Token dictionary from accent-auth-client API

        Returns:
            AccentAuthToken instance

        Raises:
            ValueError: If required fields are missing from token dict
        """
        # Validate required fields
        required_fields = ["token", "auth_id"]
        missing = [f for f in required_fields if not data.get(f)]
        if missing:
            msg = f"Token dict missing required fields: {missing}"
            raise ValueError(msg)

        metadata = AccentAuthMetadata(
            uuid=data.get("metadata", {}).get("uuid", ""),
            tenant_uuid=data.get("metadata", {}).get("tenant_uuid", ""),
            auth_id=data.get("metadata", {}).get("auth_id"),
            pbx_user_uuid=data.get("metadata", {}).get("pbx_user_uuid"),
            accent_uuid=data.get("metadata", {}).get("accent_uuid"),
        )
        return cls(
            token=data.get("token", ""),
            auth_id=data.get("auth_id", ""),
            session_uuid=data.get("session_uuid"),
            accent_uuid=data.get("accent_uuid"),
            issued_at=data.get("issued_at", ""),
            expires_at=data.get("expires_at", ""),
            utc_issued_at=data.get("utc_issued_at", ""),
            utc_expires_at=data.get("utc_expires_at", ""),
            metadata=metadata,
            acl=data.get("acl") or data.get("acls", []),
            user_agent=data.get("user_agent"),
            remote_addr=data.get("remote_addr"),
        )

    @classmethod
    def from_token_model(cls, token: Token) -> AccentAuthToken:
        """Create from internal Token model (for internal usage).

        Args:
            token: Internal Token database model

        Returns:
            AccentAuthToken with data from Token model
        """
        metadata = AccentAuthMetadata(
            uuid=token.metadata_.get("uuid", token.auth_id)
            if token.metadata_
            else token.auth_id,
            tenant_uuid=token.metadata_.get("tenant_uuid", "")
            if token.metadata_
            else "",
            auth_id=token.auth_id,
            pbx_user_uuid=token.pbx_user_uuid,
            accent_uuid=token.metadata_.get("accent_uuid") if token.metadata_ else None,
        )

        # Convert timestamps to ISO format
        issued_at_str = (
            token.utc_issued_at.isoformat()
            if token.utc_issued_at
            else datetime.fromtimestamp(token.issued_t, tz=UTC).isoformat()
            if token.issued_t
            else ""
        )
        expires_at_str = (
            token.utc_expires_at.isoformat()
            if token.utc_expires_at
            else datetime.fromtimestamp(token.expire_t, tz=UTC).isoformat()
            if token.expire_t
            else ""
        )

        return cls(
            token=token.uuid,
            auth_id=token.auth_id,
            session_uuid=token.session_uuid,
            accent_uuid=token.metadata_.get("accent_uuid") if token.metadata_ else None,
            issued_at=issued_at_str,
            expires_at=expires_at_str,
            utc_issued_at=issued_at_str,
            utc_expires_at=expires_at_str,
            metadata=metadata,
            acl=token.acl or [],
            user_agent=token.metadata_.get("user_agent") if token.metadata_ else None,
            remote_addr=token.metadata_.get("remote_addr") if token.metadata_ else None,
        )


def _is_running_internally() -> bool:
    """Detect if code is running within the accent-auth service itself.

    This function enables automatic routing between internal (database) and
    external (HTTP) modes. It checks the SERVICE_NAME environment variable
    or configuration to determine the execution context.

    How It Works:
        1. Loads application settings (which reads SERVICE_NAME from env)
        2. Checks if service_name == "accent-auth"
        3. Returns True if running in accent-auth, False otherwise

    Configuration Examples:
        # In accent-auth service (.env):
        SERVICE_NAME=accent-auth  # ← Triggers internal mode (database)

        # In other services (.env):
        SERVICE_NAME=voicemail-service  # ← Triggers external mode (HTTP)
        AUTH_SERVICE_URL=https://accent-auth:443

    Why This Matters:
        - Internal mode: Direct database access (10-100x faster, no HTTP overhead)
        - External mode: HTTP client (works across network, proper service boundaries)
        - Prevents circular dependencies (accent-auth calling itself via HTTP)

    Returns:
        True if running in accent-auth service (use database),
        False if external service (use HTTP)

    Note:
        If detection fails (exception), defaults to False (external mode) as
        this is the safer assumption - better to make an HTTP call than to
        attempt database access without proper setup.
    """
    try:
        app_settings = get_app_settings()
        return app_settings.service_name == "accent-auth"
    except Exception:
        # If we can't determine, assume external (safer default)
        # External mode will fail gracefully if misconfigured
        return False


class _InternalTokenAdapter:
    """Internal adapter for token validation using direct database access.

    ROLE IN DUAL-MODE ARCHITECTURE
    ===============================
    This adapter implements the "internal mode" path of AccentAuthClient.
    It's automatically used when SERVICE_NAME == "accent-auth" to route
    token operations directly to the database instead of making HTTP calls.

    Architecture Position:
        AccentAuthClient (public API)
          └─> _InternalTokenAdapter (internal mode handler)
              └─> TokenService (business logic)
                  └─> TokenRepository (data access)
                      └─> Database (PostgreSQL)

    Why This Exists:
        When accent-auth needs to validate tokens for its own operations
        (e.g., admin endpoints, internal workflows), we can't make HTTP
        calls to ourselves. This adapter provides the database-backed
        implementation that mirrors the HTTP client's interface.

    Design Pattern:
        This is an Adapter pattern implementation that adapts the database
        layer (TokenService) to match the interface expected by consumers
        of AccentAuthClient, but optimized for internal use.

    Usage:
        This class is NOT meant to be used directly. It's automatically
        instantiated and used by AccentAuthClient when internal mode is
        detected. Consumers interact with AccentAuthClient, which delegates
        to this adapter transparently.

    Attributes:
        _session: Optional cached database session
        _token_service: Optional cached token service instance

    Note:
        Methods accept session/token_service as parameters to support both:
        - FastAPI dependency injection (passed on each call)
        - Standalone usage (cached in __init__)
    """

    def __init__(self) -> None:
        """Initialize internal adapter."""
        self._session: AsyncSession | None = None
        self._token_service: TokenServiceDep | None = None

    async def _ensure_dependencies(
        self,
        session: AsyncSession | None = None,
        token_service: TokenServiceDep | None = None,
    ) -> tuple[AsyncSession, TokenServiceDep]:
        """Ensure database session and token service are available.

        Args:
            session: Optional database session
            token_service: Optional token service

        Returns:
            Tuple of (session, token_service)

        Raises:
            RuntimeError: If dependencies cannot be resolved
        """
        # If provided, use them
        if session and token_service:
            return session, token_service

        # Try to use cached instances if available
        if self._session and self._token_service:
            return self._session, self._token_service

        # Cannot resolve dependencies - must be provided
        msg = (
            "Internal adapter requires database session and token service. "
            "Pass them as arguments or use AccentAuthClient in FastAPI dependency context."
        )
        raise RuntimeError(msg)

    async def validate_token(
        self,
        token: str,
        tenant_uuid: str | None = None,
        required_acl: str | None = None,
        session: AsyncSession | None = None,
        token_service: TokenServiceDep | None = None,
    ) -> AccentAuthToken:
        """Validate token using direct database access.

        Args:
            token: Token string to validate
            tenant_uuid: Optional tenant UUID for validation
            required_acl: Optional ACL to check during validation
            session: Database session (required for standalone usage)
            token_service: Token service (required for standalone usage)

        Returns:
            Token information with ACLs and metadata

        Raises:
            InvalidTokenException: If token is invalid
            MissingPermissionsTokenException: If token lacks required ACL
        """
        # Ensure dependencies are available
        session, token_service = await self._ensure_dependencies(session, token_service)

        # Direct database lookup
        db_token = await token_service.get_token(session, token)

        if not db_token:
            msg = "Invalid token"
            if ACCENT_AUTH_CLIENT_AVAILABLE:
                raise InvalidTokenException(msg)
            raise ValueError(msg)

        # Check expiration
        if db_token.is_expired:
            msg = "Token expired"
            if ACCENT_AUTH_CLIENT_AVAILABLE:
                raise InvalidTokenException(msg)
            raise ValueError(msg)

        # Check tenant if specified
        if tenant_uuid:
            token_tenant = (
                db_token.metadata_.get("tenant_uuid") if db_token.metadata_ else None
            )
            if token_tenant != tenant_uuid:
                msg = "Token tenant mismatch"
                if ACCENT_AUTH_CLIENT_AVAILABLE:
                    raise InvalidTokenException(msg)
                raise ValueError(msg)

        # Check ACL if specified
        if required_acl:
            checker = AccessCheck(
                auth_id=db_token.auth_id,
                session_id=db_token.session_uuid or "",
                acl=db_token.acl or [],
            )
            if not checker.matches_required_access(required_acl):
                message = f"Token lacks required ACL: {required_acl}"
                if ACCENT_AUTH_CLIENT_AVAILABLE:
                    raise MissingPermissionsTokenException(message)
                raise ValueError(message)

        # Convert to AccentAuthToken
        token_info = AccentAuthToken.from_token_model(db_token)

        logger.debug(
            "Token validated internally (database)",
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
        session: AsyncSession | None = None,
        token_service: TokenServiceDep | None = None,
    ) -> bool:
        """Check if token is valid using direct database access.

        Args:
            token: Token string to check
            required_acl: Optional ACL to check
            tenant_uuid: Optional tenant UUID
            session: Database session (required for standalone usage)
            token_service: Token service (required for standalone usage)

        Returns:
            True if token is valid (and has required ACL if specified)
        """
        try:
            await self.validate_token(
                token,
                tenant_uuid,
                required_acl,
                session,
                token_service,
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
        session: AsyncSession | None = None,
        token_service: TokenServiceDep | None = None,
    ) -> bool:
        """Check if token is valid without raising exceptions.

        Args:
            token: Token string to check
            required_acl: Optional ACL to check
            tenant_uuid: Optional tenant UUID
            session: Database session (required for standalone usage)
            token_service: Token service (required for standalone usage)

        Returns:
            True if token is valid, False otherwise
        """
        return await self.check_token(
            token,
            required_acl,
            tenant_uuid,
            session,
            token_service,
        )


class AccentAuthClient:
    """Async wrapper for Accent-Auth client with automatic internal/external routing.

    ARCHITECTURE: DUAL-MODE CLIENT
    ===============================
    This client implements an adaptive pattern that automatically chooses between
    two execution modes based on the SERVICE_NAME environment variable:

    MODE 1: INTERNAL (Database Access)
    -----------------------------------
    When: SERVICE_NAME == "accent-auth" (i.e., code running in accent-auth service)
    Uses: _InternalTokenAdapter → TokenService → Database
    Performance: Very fast (direct database queries, ~1-10ms)
    Dependencies: Requires AsyncSession and TokenService

    Flow:
        AccentAuthClient.validate_token()
          └─> _InternalTokenAdapter.validate_token()
              └─> TokenService.get_token(session, token_uuid)
                  └─> SELECT * FROM tokens WHERE uuid = ?

    MODE 2: EXTERNAL (HTTP Client)
    -------------------------------
    When: SERVICE_NAME != "accent-auth" (i.e., code running in other services)
    Uses: accent-auth-client library → HTTP client
    Performance: Network latency (~10-100ms)
    Dependencies: Requires AUTH_SERVICE_URL configuration

    Flow:
        AccentAuthClient.validate_token()
          └─> accent_auth_client.token.get_token()
              └─> GET https://accent-auth:443/api/tokens/{token_uuid}

    CONFIGURATION
    =============
    External Services (e.g., voicemail-service):
        # .env file
        SERVICE_NAME=voicemail-service  # Triggers external mode
        AUTH_SERVICE_URL=https://accent-auth:443
        AUTH_SERVICE_TOKEN=secret-token-for-service-auth

    Accent-Auth Service:
        # .env file
        SERVICE_NAME=accent-auth  # Triggers internal mode
        # No AUTH_SERVICE_URL needed - uses database directly

    USAGE EXAMPLES
    ==============
    Basic usage (works in both modes):
        async with AccentAuthClient() as client:
            # Validate token and get full info
            token_info = await client.validate_token(token)
            print(f"User: {token_info.metadata.uuid}")

            # Check token with ACL requirement
            has_access = await client.check_token(token, "confd.users.read")

            # Check if valid (boolean, no exceptions)
            is_valid = await client.is_token_valid(token)

    Internal mode with explicit dependencies (FastAPI):
        @router.get("/internal-example")
        async def example(
            session: AsyncSession = Depends(get_db_session),
            token_service: TokenServiceDep = Depends(get_token_service),
        ):
            async with AccentAuthClient() as client:
                # Internal mode auto-detected, uses provided dependencies
                token_info = await client.validate_token(
                    token="some-token",
                    session=session,
                    token_service=token_service,
                )

    WHY THIS PATTERN?
    =================
    Problem: When accent-auth needs to validate a token (e.g., for an internal
    operation), making an HTTP call to itself creates:
        - Circular dependency (Service → HTTP → Same Service)
        - Performance overhead (network stack, serialization)
        - Resource waste (HTTP connections, context switching)
        - Complexity (retries, timeouts, error handling)

    Solution: Detect "we're calling ourselves" and use direct database access:
        ✅ 10-100x faster (nanoseconds vs milliseconds)
        ✅ Simpler error handling (database exceptions vs HTTP errors)
        ✅ Better debugging (stack traces vs network logs)
        ✅ Lower resource usage (no HTTP overhead)

    Attributes:
        _is_internal: Boolean flag set at initialization, determines routing
        _client: HTTP client instance (external mode only)
        _internal_adapter: Database adapter (internal mode only)
        _session: Database session (internal mode only)
        _token_service: Token service (internal mode only)
    """

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        https: bool = True,
        verify_certificate: bool = True,
        timeout: float = 5.0,
        token: str | None = None,
        *,
        base_url: str | None = None,
        max_retries: int | None = None,
        session: AsyncSession | None = None,
        token_service: TokenServiceDep | None = None,
    ) -> None:
        """Initialize Accent-Auth client with automatic mode detection.

        INITIALIZATION FLOW:
        ===================
        1. Check SERVICE_NAME environment variable via _is_running_internally()
        2. If SERVICE_NAME == "accent-auth": Set up internal mode (database)
        3. If SERVICE_NAME != "accent-auth": Set up external mode (HTTP)

        Args:
            host: Accent-Auth service hostname (external mode only)
                  Default: from AUTH_SERVICE_URL or "localhost"
            port: Accent-Auth service port (external mode only)
                  Default: 443 for HTTPS, 80 for HTTP
            https: Use HTTPS for connections (external mode only)
                   Default: True
            verify_certificate: Verify SSL certificate (external mode only)
                                Default: True
            timeout: Request timeout in seconds (external mode only)
                     Default: 5.0
            token: Service token for authentication (external mode only)
                   Default: from AUTH_SERVICE_TOKEN
            base_url: Explicit base URL for the Accent-Auth service (external mode only).
            max_retries: Maximum HTTP retries when contacting Accent-Auth.
            session: Database session (internal mode only)
                     Optional: for standalone usage outside FastAPI DI
            token_service: Token service (internal mode only)
                           Optional: for standalone usage outside FastAPI DI

        Raises:
            RuntimeError: If accent-auth-client library not installed (external mode)

        Note:
            The session and token_service parameters are only used in internal mode
            when using the client outside FastAPI's dependency injection system.
            When used in FastAPI route handlers, these are typically injected
            automatically via Depends().
        """
        # ═══════════════════════════════════════════════════════════════
        # STEP 1: DETECT EXECUTION MODE
        # ═══════════════════════════════════════════════════════════════
        # This is the critical decision point that determines all routing.
        # Checks: SERVICE_NAME environment variable == "accent-auth"
        self._is_internal = _is_running_internally()

        self.max_retries = max_retries

        if self._is_internal:
            # ═══════════════════════════════════════════════════════════════
            # INTERNAL MODE SETUP (Database Access)
            # ═══════════════════════════════════════════════════════════════
            # We detected SERVICE_NAME == "accent-auth", so we're running
            # inside the accent-auth service itself. Use direct database
            # access to avoid HTTP overhead and circular dependencies.

            # Create adapter for database operations
            self._internal_adapter = _InternalTokenAdapter()

            # Store optional database dependencies (for standalone usage)
            # These will be used if provided, otherwise _InternalTokenAdapter
            # will expect them to be passed to each method call
            self._session = session
            self._token_service = token_service

            # No HTTP client needed in internal mode
            self._client = None

            logger.info(
                "Accent-Auth client initialized (internal mode - using database)",
            )
        else:
            # ═══════════════════════════════════════════════════════════════
            # EXTERNAL MODE SETUP (HTTP Client)
            # ═══════════════════════════════════════════════════════════════
            # We detected SERVICE_NAME != "accent-auth", so we're running
            # in a different service. Use HTTP client to call accent-auth.

            # Verify accent-auth-client library is installed
            if not ACCENT_AUTH_CLIENT_AVAILABLE:
                msg = (
                    "accent-auth-client library is required but not installed. "
                    "Install with: pip install accent-auth-client"
                )
                raise RuntimeError(msg)

            # Load auth service configuration
            settings = get_auth_settings()

            # Parse host/port from provided base_url or AUTH_SERVICE_URL
            service_url = base_url or (
                str(settings.service_url) if settings.service_url else None
            )

            if host is None and service_url:
                from urllib.parse import urlparse

                parsed = urlparse(service_url)
                host = parsed.hostname or "localhost"
                port = parsed.port or (443 if parsed.scheme == "https" else 80)
                https = parsed.scheme == "https"

            # Store HTTP client configuration
            self.host = host or "localhost"
            self.port = port or (443 if https else 80)
            self.https = https
            self.verify_certificate = verify_certificate
            self.timeout = timeout
            self.token = token or (
                settings.service_token.get_secret_value()
                if settings.service_token
                else None
            )

            # HTTP client will be initialized in __aenter__
            self._client: Any = None

            # No database adapter needed in external mode
            self._internal_adapter = None  # type: ignore[assignment]
            self._session = None
            self._token_service = None

            logger.info(
                "Accent-Auth client initialized (external mode - using HTTP)",
                extra={
                    "host": self.host,
                    "port": self.port,
                    "https": self.https,
                },
            )

    async def __aenter__(self) -> Self:
        """Async context manager entry."""
        if not self._is_internal:
            self._client = self._client or self._build_http_client()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Async context manager exit."""
        # No cleanup needed for internal mode
        # accent-auth-client doesn't require explicit cleanup for external mode

    def _get_client(self) -> Any:
        """Return the underlying HTTP client (external mode only)."""
        if self._is_internal:
            msg = "HTTP client not available in internal mode"
            raise RuntimeError(msg)
        if self._client is None:
            self._client = self._build_http_client()
        return self._client

    def _build_http_client(self) -> Any:
        """Create the accent-auth HTTP client."""
        return AccentAuthClientLib(
            host=self.host,
            port=self.port,
            https=self.https,
            verify_certificate=self.verify_certificate,
            timeout=self.timeout,
            token=self.token,
        )

    def _client_supports_sdk(self, client: Any) -> bool:
        """Check if the underlying client is the official Accent-Auth SDK."""
        if AccentAuthClientLib is None:
            return False
        return isinstance(client, AccentAuthClientLib)

    def _build_request_headers(self, tenant_uuid: str | None) -> dict[str, str]:
        """Create standard headers for Accent-Auth HTTP requests."""
        headers: dict[str, str] = {}
        if tenant_uuid:
            headers["Accent-Tenant"] = tenant_uuid
        return headers

    async def _fetch_external_token_data(
        self,
        client: Any,
        token: str,
        *,
        tenant_uuid: str | None,
        required_acl: str | None,
    ) -> dict[str, Any]:
        """Fetch token information using either SDK or raw HTTP client."""
        if self._client_supports_sdk(client):
            return await client.token.get_token(
                token,
                required_acl=required_acl,
                tenant=tenant_uuid,
            )

        headers = self._build_request_headers(tenant_uuid)
        params: dict[str, str] = {}
        if required_acl:
            params["required_acl"] = required_acl

        response = await client.get(
            f"{self.base_url}/api/auth/0.1/token/{token}",
            headers=headers or None,
            params=params or None,
            timeout=self.timeout,
        )
        if response.status_code == 200:
            payload = (
                response.json() if callable(getattr(response, "json", None)) else {}
            )
            return payload.get("data", payload)

        if response.status_code == 403:
            msg = (
                f"Token missing required ACL: {required_acl}"
                if required_acl
                else "Token missing required ACL"
            )
            raise MissingPermissionsTokenException(msg)

        if response.status_code in {401, 404}:
            msg = "Invalid or expired token"
            raise InvalidTokenException(msg)

        msg = f"Unexpected Accent-Auth response (status={response.status_code})"
        raise InvalidTokenException(msg)

    @property
    def base_url(self) -> str:
        """Get the base URL for the Accent-Auth service."""
        protocol = "https" if self.https else "http"
        return f"{protocol}://{self.host}:{self.port}"

    async def validate_token(
        self,
        token: str,
        tenant_uuid: str | None = None,
        required_acl: str | None = None,
        *,
        session: AsyncSession | None = None,
        token_service: TokenServiceDep | None = None,
    ) -> AccentAuthToken:
        """Validate token and retrieve full token information.

        ROUTING LOGIC:
        ==============
        This method demonstrates the core routing pattern used throughout this client.
        Based on self._is_internal (set during __init__), it chooses between:

        Path A (Internal): Direct database access
            validate_token()
              └─> _InternalTokenAdapter.validate_token()
                  └─> TokenService.get_token()
                      └─> SELECT * FROM tokens WHERE uuid = ?

        Path B (External): HTTP API call
            validate_token()
              └─> accent_auth_client.token.get_token()
                  └─> GET https://accent-auth/api/tokens/{token}

        Args:
            token: Bearer token to validate (UUID string)
            tenant_uuid: Optional tenant UUID for multi-tenant validation
            required_acl: Optional ACL to check (e.g., "confd.users.read")
            session: Database session (internal mode only, for standalone usage)
            token_service: Token service (internal mode only, for standalone usage)

        Returns:
            AccentAuthToken with full token information including:
                - Token UUID
                - User authentication ID
                - ACL list (permissions)
                - Metadata (user info, tenant info, etc.)
                - Expiration timestamps

        Raises:
            InvalidTokenException: Token doesn't exist, expired, or tenant mismatch
            MissingPermissionsTokenException: Token lacks required_acl permission
            RuntimeError: Client not initialized with context manager (external mode)

        Example:
            async with AccentAuthClient() as client:
                # Works in both internal and external modes
                token_info = await client.validate_token(
                    token="550e8400-e29b-41d4-a716-446655440000",
                    required_acl="confd.users.read",
                )
                print(f"User: {token_info.metadata.uuid}")
        """
        # ═══════════════════════════════════════════════════════════════
        # ROUTING DECISION POINT
        # ═══════════════════════════════════════════════════════════════
        # Check the flag set during __init__ to determine which path to take

        if self._is_internal:
            # ──────────────────────────────────────────────────────────────
            # PATH A: INTERNAL MODE (Database Access)
            # ──────────────────────────────────────────────────────────────
            # We're running inside accent-auth service. Use direct database
            # access via _InternalTokenAdapter for optimal performance.
            return await self._internal_adapter.validate_token(
                token,
                tenant_uuid,
                required_acl,
                session,
                token_service,
            )

        # ──────────────────────────────────────────────────────────────
        # PATH B: EXTERNAL MODE (HTTP Client)
        # ──────────────────────────────────────────────────────────────
        # We're running in a different service. Make HTTP call to
        # accent-auth API using the official client library.

        # Call accent-auth API via HTTP
        # Note: The client library is fully async, no thread pool needed
        client = self._get_client()
        token_dict = await self._fetch_external_token_data(
            client,
            token,
            tenant_uuid=tenant_uuid,
            required_acl=required_acl,
        )

        # Convert HTTP response to our internal model
        token_info = AccentAuthToken.from_token_dict(token_dict)

        logger.info(
            "Token validated successfully (HTTP)",
            extra={
                "user_uuid": token_info.metadata.uuid,
                "tenant_uuid": token_info.metadata.tenant_uuid,
                "acl_count": len(token_info.acl),
            },
        )

        return token_info

    async def validate_token_simple(
        self,
        token: str,
        tenant_uuid: str | None = None,
    ) -> bool:
        """Perform a lightweight token validation using HTTP HEAD.

        This helper is useful for integration tests or health checks where
        only existence/validity of the token matters without fetching the
        full token payload.
        """
        if self._is_internal:
            try:
                await self.validate_token(token, tenant_uuid=tenant_uuid)
                return True
            except (InvalidTokenException, MissingPermissionsTokenException):
                return False

        client = self._get_client()
        headers = {}
        if tenant_uuid:
            headers["Accent-Tenant"] = tenant_uuid

        response = await client.head(
            f"{self.base_url}/api/auth/0.1/token/{token}",
            headers=headers,
            timeout=self.timeout,
        )
        return response.status_code == 204

    async def check_token(
        self,
        token: str,
        required_acl: str | None = None,
        tenant_uuid: str | None = None,
        *,
        session: AsyncSession | None = None,
        token_service: TokenServiceDep | None = None,
    ) -> bool:
        """Check if token is valid.

        Automatically routes to internal database access when running within
        accent-auth service, or HTTP client when running externally.

        Args:
            token: Bearer token to check
            required_acl: Optional ACL to check
            tenant_uuid: Optional tenant UUID
            session: Database session (internal mode only, for standalone usage)
            token_service: Token service (internal mode only, for standalone usage)

        Returns:
            True if token is valid (and has required ACL if specified)

        Raises:
            InvalidTokenException: If token is invalid (external mode only)
            MissingPermissionsTokenException: If token lacks required ACL (external mode only)
            RuntimeError: If client not initialized (external mode)
        """
        if self._is_internal:
            # Internal mode: use database adapter
            return await self._internal_adapter.check_token(
                token,
                required_acl,
                tenant_uuid,
                session,
                token_service,
            )

        # External mode: use HTTP client
        client = self._get_client()
        if self._client_supports_sdk(client):
            return await client.token.check(
                token,
                required_acl=required_acl,
                tenant=tenant_uuid,
            )

        try:
            await self._fetch_external_token_data(
                client,
                token,
                tenant_uuid=tenant_uuid,
                required_acl=required_acl,
            )
            return True
        except (InvalidTokenException, MissingPermissionsTokenException):
            return False

    async def check_acl(
        self,
        token: str,
        required_acl: str,
        tenant_uuid: str | None = None,
        *,
        session: AsyncSession | None = None,
        token_service: TokenServiceDep | None = None,
    ) -> bool:
        """Alias that emphasizes ACL-specific checks."""
        return await self.check_token(
            token,
            required_acl=required_acl,
            tenant_uuid=tenant_uuid,
            session=session,
            token_service=token_service,
        )

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

        Automatically routes to internal database access when running within
        accent-auth service, or HTTP client when running externally.

        Args:
            token: Bearer token to check
            required_acl: Optional ACL to check
            tenant_uuid: Optional tenant UUID
            session: Database session (internal mode only, for standalone usage)
            token_service: Token service (internal mode only, for standalone usage)

        Returns:
            True if token is valid, False otherwise
        """
        if self._is_internal:
            # Internal mode: use database adapter
            return await self._internal_adapter.is_token_valid(
                token,
                required_acl,
                tenant_uuid,
                session,
                token_service,
            )

        # External mode: use HTTP client
        client = self._get_client()
        # Use official client (it's async, no thread pool needed)
        return await client.token.is_valid(
            token,
            required_acl=required_acl,
            tenant=tenant_uuid,
        )

    async def revoke_token(self, token: str) -> None:
        """Revoke a token.

        Args:
            token: Token to revoke

        Raises:
            NotImplementedError: If running in internal mode
            RuntimeError: If client not initialized (external mode)
        """
        if self._is_internal:
            msg = (
                "Token revocation not supported in internal mode. "
                "Use TokenService.delete_token() or TokenRepository directly."
            )
            raise NotImplementedError(msg)

        client = self._get_client()
        # Use official client (it's async, no thread pool needed)
        await client.token.revoke(token)

    def to_auth_user(self, token_info: AccentAuthToken) -> AuthUser:
        """Convert Accent-Auth token to AuthUser model.

        Args:
            token_info: Accent-Auth token information

        Returns:
            AuthUser model for use in FastAPI dependencies
        """
        acl_dict: dict[str, set[str]] = {}
        for permission in token_info.acl:
            if "." in permission:
                resource, action = permission.rsplit(".", 1)
            else:
                resource, action = permission, "*"
            acl_dict.setdefault(resource, set()).add(action)

        normalized_acl = {
            resource: sorted(actions) for resource, actions in acl_dict.items()
        }

        return AuthUser(
            user_id=token_info.metadata.uuid,
            service_id=None,
            email=None,
            roles=[],
            permissions=token_info.acl,
            acl=normalized_acl,
            metadata={
                "tenant_uuid": token_info.metadata.tenant_uuid,
                "auth_id": token_info.metadata.auth_id or token_info.auth_id,
                "session_uuid": token_info.session_uuid,
                "token": token_info.token,
                "expires_at": token_info.expires_at,
                "accent_uuid": token_info.accent_uuid,
            },
        )


@lru_cache(maxsize=1)
def get_accent_auth_client() -> AccentAuthClient:
    """Get configured Accent-Auth client instance.

    Automatically detects if running within accent-auth service and routes
    to internal database operations. For external services, requires
    AUTH_SERVICE_URL configuration.

    Returns:
        Configured AccentAuthClient (internal or external mode)

    Raises:
        ValueError: If AUTH_SERVICE_URL is not configured (external mode only)
        RuntimeError: If accent-auth-client is not installed (external mode only)

    Note:
        When running within accent-auth service, this returns a client that
        uses direct database access. No HTTP calls are made to itself.
    """
    # Check if running internally
    if _is_running_internally():
        # Internal mode: return client that uses database
        logger.debug("Creating AccentAuthClient in internal mode (database)")
        return AccentAuthClient()

    # External mode: require HTTP client library and service URL
    if not ACCENT_AUTH_CLIENT_AVAILABLE:
        msg = (
            "accent-auth-client library is required but not installed. "
            "Install with: pip install accent-auth-client"
        )
        raise RuntimeError(msg)

    settings = get_auth_settings()

    if not settings.service_url:
        msg = (
            "AUTH_SERVICE_URL must be configured for Accent-Auth. "
            "Set AUTH_SERVICE_URL environment variable or configure in settings."
        )
        raise ValueError(msg)

    logger.debug("Creating AccentAuthClient in external mode (HTTP)")
    return AccentAuthClient(
        timeout=float(settings.request_timeout),
        verify_certificate=settings.verify_ssl,
        max_retries=settings.retry_count,
    )


class AccentAuthACL:
    """Helper class for working with Accent-Auth ACL patterns.

    Accent-Auth uses dot-notation ACLs with wildcard support:
    - service.resource.action (e.g., "confd.users.read")
    - Wildcards: * (single level), # (multi-level)
    - Negation: ! prefix (e.g., "!confd.users.delete")
    - Reserved: me, my_session, my_tenant (dynamic substitution)

    This class delegates to the core ACL module which provides:
    - Full regex-based pattern matching
    - LRU caching at multiple levels for performance
    - Proper reserved word substitution

    Example:
        acl = AccentAuthACL(["confd.users.*", "webhookd.#"])
        acl.has_permission("confd.users.read")  # True
        acl.has_permission("confd.users.delete")  # True
        acl.has_permission("webhookd.subscriptions.read")  # True

        # With user context (enables 'me' and 'my_session' substitution)
        acl = AccentAuthACL(
            ["users.me.read", "sessions.my_session.delete"],
            auth_id="user-123",
            session_id="sess-456",
        )
        acl.has_permission("users.user-123.read")  # True

        # With tenant context (enables 'my_tenant' substitution)
        acl = AccentAuthACL(
            ["storage.my_tenant.#", "confd.my_tenant.users.read"],
            auth_id="user-123",
            session_id="sess-456",
            tenant_id="tenant-789",
        )
        acl.has_permission("storage.tenant-789.buckets.list")  # True
        acl.has_permission("confd.tenant-789.users.read")  # True
    """

    def __init__(
        self,
        acls: list[str],
        auth_id: str | None = None,
        session_id: str | None = None,
        tenant_id: str | None = None,
    ) -> None:
        """Initialize with list of ACL patterns.

        Args:
            acls: List of ACL patterns
            auth_id: User auth ID for 'me' reserved word substitution
            session_id: Session ID for 'my_session' reserved word substitution
            tenant_id: Tenant ID for 'my_tenant' reserved word substitution
        """
        self.acls = acls
        self.auth_id = auth_id
        self.session_id = session_id
        self.tenant_id = tenant_id

        # Use the full ACL implementation with caching
        self._checker = get_cached_access_check(
            auth_id=auth_id,
            session_id=session_id,
            acl=acls,
            tenant_id=tenant_id,
        )

    def has_permission(self, required: str) -> bool:
        """Check if ACL grants permission.

        Args:
            required: Required permission (e.g., "confd.users.read")

        Returns:
            True if permission is granted
        """
        return self._checker.matches_required_access(required)

    def has_any_permission(self, *required: str) -> bool:
        """Check if ACL grants any of the specified permissions.

        Args:
            *required: Required permissions to check

        Returns:
            True if any permission is granted
        """
        return any(self.has_permission(r) for r in required)

    def has_all_permissions(self, *required: str) -> bool:
        """Check if ACL grants all of the specified permissions.

        Args:
            *required: Required permissions to check

        Returns:
            True if all permissions are granted
        """
        return all(self.has_permission(r) for r in required)

    def is_superuser(self) -> bool:
        """Check if ACL grants superuser access (# wildcard).

        Returns:
            True if user has # ACL
        """
        return self.has_permission("#")
