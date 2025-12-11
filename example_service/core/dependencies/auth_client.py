"""Authentication client dependency factory.

This module provides the factory function and type alias for injecting
AuthClient instances into FastAPI route handlers. The factory automatically
detects whether to use HttpAuthClient (external mode) or DatabaseAuthClient
(internal mode) based on SERVICE_NAME configuration.

Key Features:
    - Automatic mode detection (internal vs external)
    - Singleton pattern via @lru_cache
    - Protocol-based (works with any AuthClient implementation)
    - Type-safe dependency injection

Usage:
    from example_service.core.dependencies.auth_client import AuthClientDep

    @router.get("/validate")
    async def validate_endpoint(
        client: AuthClientDep,
        token: str,
    ):
        token_info = await client.validate_token(token)
        return {"user_id": token_info.metadata.uuid}

Pattern: Factory with @lru_cache singleton (like get_bus_publisher, get_storage_service)
"""

from __future__ import annotations

from functools import lru_cache
import logging
from typing import Annotated

from fastapi import Depends

from example_service.core.settings import get_app_settings, get_auth_settings
from example_service.infra.auth.protocols import AuthClient

logger = logging.getLogger(__name__)


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


@lru_cache(maxsize=1)
def get_auth_client() -> AuthClient:
    """Get authentication client with automatic mode detection.

    Factory function that creates the appropriate AuthClient implementation
    based on SERVICE_NAME configuration. This function uses @lru_cache to
    ensure a single instance is created and reused across the application.

    Routing Logic:
        if SERVICE_NAME == "accent-auth":
            return DatabaseAuthClient()  # Internal mode
        else:
            return HttpAuthClient()      # External mode

    Internal Mode (accent-auth service):
        - Uses DatabaseAuthClient
        - Direct database access via TokenService
        - 10-100x faster than HTTP
        - Prevents circular HTTP calls
        - Requires database session injection per-request

    External Mode (other services):
        - Uses HttpAuthClient
        - HTTP communication via accent-auth-client library
        - Requires AUTH_SERVICE_URL configuration
        - Works across service boundaries

    Returns:
        AuthClient instance (DatabaseAuthClient or HttpAuthClient)

    Raises:
        RuntimeError: If accent-auth-client not installed (external mode)
        ValueError: If AUTH_SERVICE_URL not configured (external mode)

    Example:
        # Via dependency injection (recommended)
        from example_service.core.dependencies.auth_client import AuthClientDep

        @router.get("/protected")
        async def protected_endpoint(client: AuthClientDep):
            token_info = await client.validate_token(request.headers["X-Auth-Token"])
            return {"user_id": token_info.metadata.uuid}

        # Direct usage (testing)
        client = get_auth_client()
        assert isinstance(client, AuthClient)  # Protocol check
        if client.mode == "internal":
            # DatabaseAuthClient
            pass
        elif client.mode == "external":
            # HttpAuthClient
            pass
    """
    is_internal = _is_running_internally()

    if is_internal:
        # ═══════════════════════════════════════════════════════════════
        # INTERNAL MODE: DatabaseAuthClient (accent-auth service)
        # ═══════════════════════════════════════════════════════════════
        logger.debug("Creating DatabaseAuthClient for internal mode")

        from example_service.infra.auth.db_client import DatabaseAuthClient

        # DatabaseAuthClient doesn't need upfront configuration
        # Dependencies (session, token_service) injected per-request
        return DatabaseAuthClient()

    # ═══════════════════════════════════════════════════════════════
    # EXTERNAL MODE: HttpAuthClient (other services)
    # ═══════════════════════════════════════════════════════════════
    logger.debug("Creating HttpAuthClient for external mode")

    from example_service.infra.auth.http_client import (
        ACCENT_AUTH_CLIENT_AVAILABLE,
        HttpAuthClient,
    )

    # Verify accent-auth-client library is installed
    if not ACCENT_AUTH_CLIENT_AVAILABLE:
        msg = (
            "accent-auth-client library is required but not installed. "
            "Install with: pip install accent-auth-client"
        )
        raise RuntimeError(msg)

    # Verify AUTH_SERVICE_URL is configured
    settings = get_auth_settings()
    if not settings.service_url:
        msg = (
            "AUTH_SERVICE_URL must be configured for Accent-Auth. "
            "Set AUTH_SERVICE_URL environment variable or configure in settings. "
            "Example: AUTH_SERVICE_URL=https://accent-auth:443"
        )
        raise ValueError(msg)

    # HttpAuthClient automatically parses AUTH_SERVICE_URL
    # Pass settings for timeout and SSL verification
    return HttpAuthClient(
        timeout=float(settings.request_timeout),
        verify_certificate=settings.verify_ssl,
    )


# ============================================================================
# Type Alias for Dependency Injection
# ============================================================================

AuthClientDep = Annotated[AuthClient, Depends(get_auth_client)]
"""Type alias for AuthClient dependency injection.

Use this in route handlers to automatically inject the appropriate
AuthClient implementation (DatabaseAuthClient or HttpAuthClient) based
on SERVICE_NAME configuration.

Example:
    from example_service.core.dependencies.auth_client import AuthClientDep

    @router.get("/validate")
    async def validate_endpoint(
        client: AuthClientDep,
        token: str,
    ):
        token_info = await client.validate_token(token)
        return {"user_id": token_info.metadata.uuid}

Pattern: Dependency type alias (like BusPublisherDep, StorageServiceDep)
"""


__all__ = [
    "AuthClientDep",
    "get_auth_client",
]
