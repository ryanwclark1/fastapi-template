"""HTTP-based Accent-Auth client implementation (external mode).

This module provides the HttpAuthClient class, which implements the AuthClient
protocol using HTTP communication with the Accent-Auth service via the official
accent-auth-client library.

Use this client when:
- Running in any service OTHER than accent-auth (external mode)
- Need to validate tokens across service boundaries
- Want network-isolated authentication

Key Features:
    - Protocol-compliant (implements AuthClient)
    - Wraps accent-auth-client library for HTTP communication
    - Automatic URL parsing from AUTH_SERVICE_URL configuration
    - Full async support (no thread pools needed)
    - Exception-safe token validation

Lifecycle:
    The HTTP client library is initialized when needed. Unlike the legacy
    AccentAuthClient, this class doesn't require async context manager usage.
    The accent-auth-client library handles connection pooling internally.

Example:
    # Via dependency injection (recommended)
    from example_service.core.dependencies.auth_client import AuthClientDep

    @router.get("/protected")
    async def protected_endpoint(client: AuthClientDep):
        token_info = await client.validate_token(request.headers["X-Auth-Token"])
        return {"user_id": token_info.metadata.uuid}

    # Direct usage (testing)
    client = HttpAuthClient(host="auth.example.com", port=443, https=True)
    token_info = await client.validate_token("token-uuid")

Pattern: Adapter wrapping external library (like RabbitBusPublisher wraps RabbitBroker)
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

from example_service.core.settings import get_auth_settings
from example_service.infra.auth.models import AccentAuthToken

logger = logging.getLogger(__name__)

# Import the accent-auth-client library (required for external mode)
try:
    from accent_auth_client import Client as AccentAuthClientLib
    from accent_auth_client.exceptions import (
        InvalidTokenException,
        MissingPermissionsTokenException,
    )

    ACCENT_AUTH_CLIENT_AVAILABLE = True
    logger.debug("accent-auth-client library loaded for HttpAuthClient")
except ImportError:
    ACCENT_AUTH_CLIENT_AVAILABLE = False
    AccentAuthClientLib = None  # type: ignore[misc,assignment]
    InvalidTokenException = Exception  # type: ignore[misc,assignment]
    MissingPermissionsTokenException = Exception  # type: ignore[misc,assignment]
    logger.warning(
        "accent-auth-client library not installed. "
        "HttpAuthClient will not be available. "
        "Install with: pip install accent-auth-client",
    )


class HttpAuthClient:
    """HTTP-based authentication client (external mode).

    Implements the AuthClient protocol using HTTP communication with the
    Accent-Auth service. This client wraps the official accent-auth-client
    library and provides a consistent interface for token validation.

    The client automatically parses configuration from AUTH_SERVICE_URL or
    accepts explicit host/port parameters for testing.

    Attributes:
        host: Accent-Auth service hostname
        port: Accent-Auth service port
        https: Whether to use HTTPS (True) or HTTP (False)
        verify_certificate: Whether to verify SSL certificates
        timeout: Request timeout in seconds
        token: Service token for authenticated requests (optional)

    Lifecycle Management:
        This client wraps accent-auth-client which uses async context managers
        for connection pooling. We initialize the client lazily on first use
        to avoid blocking __init__, and keep the connection pool open for the
        application lifecycle (singleton pattern via @lru_cache).

    Implementation Notes:
        - Lazy initialization of accent-auth-client on first method call
        - Connection pool stays open for application lifetime
        - Proper cleanup via aclose() if needed (not typically called in production)
        - Raises exceptions on invalid tokens (as per protocol)
    """

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        https: bool = True,
        verify_certificate: bool = True,
        timeout: float = 5.0,
        token: str | None = None,
    ) -> None:
        """Initialize HTTP authentication client.

        Args:
            host: Accent-Auth hostname (auto-detected from AUTH_SERVICE_URL if None)
            port: Accent-Auth port (auto-detected from AUTH_SERVICE_URL if None)
            https: Use HTTPS (default: True)
            verify_certificate: Verify SSL certificates (default: True)
            timeout: Request timeout in seconds (default: 5.0)
            token: Service token for authenticated requests (optional)

        Raises:
            RuntimeError: If accent-auth-client library is not installed

        Example:
            # Auto-detect from settings (recommended for production)
            client = HttpAuthClient()

            # Explicit configuration (testing)
            client = HttpAuthClient(
                host="auth.example.com",
                port=443,
                https=True,
            )
        """
        # Verify library availability
        if not ACCENT_AUTH_CLIENT_AVAILABLE:
            msg = (
                "accent-auth-client library is required but not installed. "
                "Install with: pip install accent-auth-client"
            )
            raise RuntimeError(msg)

        # Load configuration from settings if not explicitly provided
        settings = get_auth_settings()

        # Parse host/port from AUTH_SERVICE_URL if not explicitly provided
        if host is None and settings.service_url:
            parsed = urlparse(str(settings.service_url))
            host = parsed.hostname or "localhost"
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            https = parsed.scheme == "https"

        # Store configuration
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

        # Initialize HTTP client library (but don't enter context yet)
        # We'll call __aenter__() lazily on first use to avoid blocking __init__
        self._client: Any = AccentAuthClientLib(
            host=self.host,
            port=self.port,
            https=self.https,
            verify_certificate=self.verify_certificate,
            timeout=self.timeout,
            prefix="/api/auth",
            version="0.1",
        )

        # Set token if provided (for service-to-service auth)
        if self.token:
            self._client.set_token(self.token)

        # Track initialization state
        self._initialized = False

        logger.info(
            "HttpAuthClient initialized (external mode)",
            extra={
                "host": self.host,
                "port": self.port,
                "https": self.https,
                "timeout": self.timeout,
            },
        )

    # ========================================================================
    # Lifecycle Management
    # ========================================================================

    async def _ensure_initialized(self) -> None:
        """Ensure the accent-auth-client is properly initialized.

        This method lazily initializes the HTTP client by calling __aenter__()
        on the accent-auth-client. This is done once on first use rather than
        in __init__ to avoid blocking operations during dependency injection.

        The client lifecycle is managed as follows:
        1. __init__: Create client object (sync, fast)
        2. First async method call: Call __aenter__() to init HTTPX pool
        3. Application lifetime: Keep connection pool open
        4. (Optional) Shutdown: Call aclose() to cleanup

        Thread-safety: Not thread-safe, but FastAPI typically uses async
        single-threaded model per request.
        """
        if not self._initialized:
            await self._client.__aenter__()
            self._initialized = True
            logger.debug(
                "HttpAuthClient HTTP connection pool initialized",
                extra={"host": self.host, "port": self.port},
            )

    async def aclose(self) -> None:
        """Close the HTTP client and clean up resources.

        This method is provided for explicit cleanup (e.g., in testing or
        graceful shutdown scenarios). In production with @lru_cache singleton,
        this is typically not called as the client lives for the application
        lifetime.

        Example:
            client = HttpAuthClient(...)
            try:
                token_info = await client.validate_token("token")
            finally:
                await client.aclose()  # Cleanup
        """
        if self._initialized:
            await self._client.__aexit__(None, None, None)
            self._initialized = False
            logger.debug("HttpAuthClient HTTP connection pool closed")

    # ========================================================================
    # AuthClient Protocol Implementation
    # ========================================================================

    @property
    def is_configured(self) -> bool:
        """Check if client is properly configured and ready for operations.

        For HttpAuthClient, this checks if:
        - accent-auth-client library is available
        - Host is configured (not None)

        Returns:
            True if client is ready for operations, False otherwise
        """
        return ACCENT_AUTH_CLIENT_AVAILABLE and self.host is not None

    @property
    def mode(self) -> str:
        """Get the operational mode of this client.

        Returns:
            "external" (HTTP-based communication)
        """
        return "external"

    @property
    def base_url(self) -> str:
        """Get the base URL for the Accent-Auth service.

        Returns:
            Full base URL (e.g., "https://auth.example.com:443")
        """
        protocol = "https" if self.https else "http"
        return f"{protocol}://{self.host}:{self.port}"

    async def validate_token(
        self,
        token: str,
        tenant_uuid: str | None = None,
        required_acl: str | None = None,
    ) -> AccentAuthToken:
        """Validate token and retrieve full token information.

        Makes HTTP call to Accent-Auth API to validate the token and retrieve
        complete token information including user details, ACL permissions,
        and metadata.

        Args:
            token: Bearer token to validate (UUID string format)
            tenant_uuid: Optional tenant UUID for multi-tenant validation.
                If specified, token's tenant must match.
            required_acl: Optional ACL pattern to check during validation
                (e.g., "confd.users.read", "admin.#").
                If specified, token must have this permission.

        Returns:
            AccentAuthToken with complete token information

        Raises:
            InvalidTokenException: Token doesn't exist, expired, or tenant mismatch
            MissingPermissionsTokenException: Token lacks required_acl permission

        Example:
            # Basic validation
            token_info = await client.validate_token("token-uuid")

            # With tenant validation
            token_info = await client.validate_token(
                "token-uuid",
                tenant_uuid="tenant-123"
            )

            # With ACL requirement
            token_info = await client.validate_token(
                "token-uuid",
                required_acl="confd.users.delete"
            )
        """
        # Ensure HTTP client is initialized
        await self._ensure_initialized()

        # Call accent-auth API via HTTP
        # Note: The client library is fully async, no thread pool needed
        token_dict = await self._client.token.get_token(
            token,
            required_acl=required_acl,
            tenant=tenant_uuid,
        )

        # Convert HTTP response to our internal model
        # The get_token() method returns a TokenDict with all token information
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

    async def check_token(
        self,
        token: str,
        required_acl: str | None = None,
        tenant_uuid: str | None = None,
    ) -> bool:
        """Check if token is valid (returns boolean, raises on error).

        Similar to validate_token() but returns a boolean instead of the
        full token information. Still raises exceptions for invalid tokens
        or missing permissions.

        Args:
            token: Bearer token to check
            required_acl: Optional ACL pattern to check
            tenant_uuid: Optional tenant UUID to validate against

        Returns:
            True if token is valid (and has required ACL if specified)

        Raises:
            InvalidTokenException: If token is invalid
            MissingPermissionsTokenException: If token lacks ACL

        Example:
            # Check basic validity
            if await client.check_token("token-uuid"):
                print("Token is valid")

            # Check with ACL
            if await client.check_token("token-uuid", required_acl="admin.#"):
                print("Token has admin access")
        """
        # Ensure HTTP client is initialized
        await self._ensure_initialized()

        # Use official client library (it's async, no thread pool needed)
        return await self._client.token.check(
            token,
            required_acl=required_acl,
            tenant=tenant_uuid,
        )

    async def is_token_valid(
        self,
        token: str,
        required_acl: str | None = None,
        tenant_uuid: str | None = None,
    ) -> bool:
        """Check if token is valid without raising exceptions.

        This is a safe version of check_token() that never raises exceptions.
        It returns False for any validation failure (invalid token, missing
        ACL, tenant mismatch, network errors, etc.).

        Args:
            token: Bearer token to check
            required_acl: Optional ACL pattern to check
            tenant_uuid: Optional tenant UUID to validate against

        Returns:
            True if token is valid and meets all criteria, False otherwise
            (never raises exceptions)

        Example:
            # Safe check with fallback
            if await client.is_token_valid("token-uuid"):
                user = await get_user_from_token(token)
            else:
                user = get_anonymous_user()

            # Conditional feature access
            has_admin = await client.is_token_valid(
                "token-uuid",
                required_acl="admin.#"
            )
            if has_admin:
                show_admin_panel()
        """
        try:
            # Ensure HTTP client is initialized
            await self._ensure_initialized()

            # Use official client library (it's async, no thread pool needed)
            return await self._client.token.is_valid(
                token,
                required_acl=required_acl,
                tenant=tenant_uuid,
            )
        except Exception as e:
            logger.debug(
                "Token validation failed (exception caught)",
                extra={"error": str(e)},
            )
            return False


__all__ = [
    "HttpAuthClient",
    "InvalidTokenException",
    "MissingPermissionsTokenException",
]
