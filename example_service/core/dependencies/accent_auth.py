"""Accent-Auth dependencies for FastAPI endpoints.

This module provides FastAPI dependencies for:
- Extracting X-Auth-Token from requests
- Validating tokens with Accent-Auth service
- Caching validated tokens to reduce external calls
- Checking ACL permissions
- Managing tenant context
- Mock mode with multiple personas for development/testing

Type Alias Pattern (recommended for cleaner code):
    ```python
    from typing import Annotated
    from fastapi import Depends
    from example_service.core.dependencies.accent_auth import (
        get_current_user,
        require_acl,
    )
    from example_service.core.schemas.auth import AuthUser

    # Common patterns
    CurrentUser = Annotated[AuthUser, Depends(get_current_user)]
    AdminUser = Annotated[AuthUser, Depends(require_acl("#"))]

    # Usage in routes
    @router.get("/me")
    async def get_profile(user: CurrentUser):
        return {"email": user.email}

    @router.get("/admin/settings")
    async def admin_settings(user: AdminUser):
        return {"settings": "..."}
    ```

Mock Mode:
    Enable mock mode for local testing without Accent-Auth service:

    ```bash
    # In .env or environment
    MOCK_MODE=true
    MOCK_PERSONA=admin  # admin, user, readonly, service, multitenant_admin, limited_user

    # Quick persona switching
    export MOCK_MODE=true
    export MOCK_PERSONA=readonly
    ```

    WARNING: Mock mode is automatically blocked in production environments!
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import Depends, Header, HTTPException, Request, status

from example_service.core.schemas.auth import AuthUser
from example_service.core.settings import get_auth_settings, get_mock_settings
from example_service.infra.auth.accent_auth import (
    AccentAuthACL,
    get_accent_auth_client,
)
from example_service.infra.cache.redis import RedisCache, get_cache
from example_service.infra.logging.context import set_log_context

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

logger = logging.getLogger(__name__)

auth_settings = get_auth_settings()
mock_settings = get_mock_settings()


def _get_mock_user() -> AuthUser | None:
    """Get mock user for mock mode based on active persona.

    Returns None if mock mode disabled, otherwise returns configured mock user.
    Uses MOCK_PERSONA environment variable for quick persona switching.

    Returns:
        Mock AuthUser if mock mode enabled, None otherwise.

    """
    if not mock_settings.enabled:
        return None

    persona_name = mock_settings.persona

    try:
        # Get the active persona's user configuration
        mock_user_settings = mock_settings.get_active_user()

        # Convert to AuthUser schema
        mock_user = AuthUser(
            user_id=mock_user_settings.user_id,
            email=mock_user_settings.email or "",
            roles=mock_user_settings.roles,
            permissions=mock_user_settings.permissions,
            metadata={
                "tenant_uuid": mock_user_settings.tenant_id,
                "tenant_slug": mock_user_settings.tenant_slug,
                "session_uuid": mock_user_settings.session_id,
                **mock_user_settings.metadata,
            },
        )

        logger.warning(
            "MOCK MODE: Using mock authentication with persona '%s'",
            persona_name,
            extra={
                "persona": persona_name,
                "user_id": mock_user.user_id,
                "tenant_uuid": mock_user_settings.tenant_id,
                "acl_count": len(mock_user_settings.permissions),
            },
        )

        # Add user context to logs
        set_log_context(
            user_id=mock_user.user_id,
            tenant_id=mock_user_settings.tenant_id,
            mock_mode=True,
        )

        return mock_user

    except ValueError as e:
        logger.error("Mock mode configuration error: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Mock mode misconfigured: {e}",
        ) from e


async def get_current_user(
    request: Request,
    x_auth_token: Annotated[str | None, Header(alias="X-Auth-Token")] = None,
    accent_tenant: Annotated[str | None, Header(alias="Accent-Tenant")] = None,
    cache: Annotated[RedisCache | None, Depends(get_cache)] = None,
) -> AuthUser:
    """Get currently authenticated user from Accent-Auth.

    In mock mode (MOCK_MODE=true), this returns a mock user based on the
    active persona without validating the X-Auth-Token header. Mock users
    include realistic ACL patterns for testing different permission levels.

    WARNING: Mock mode bypasses all authentication. It is automatically
    blocked in production environments via settings validation.

    This dependency:
    1. Checks for mock mode (returns mock user if enabled)
    2. Extracts X-Auth-Token from request headers
    3. Extracts Accent-Tenant header (optional)
    4. Validates token with Accent-Auth service
    5. Caches validation results in Redis
    6. Returns AuthUser with ACL permissions

    Args:
        request: FastAPI request
        x_auth_token: Token from X-Auth-Token header
        accent_tenant: Optional tenant UUID from Accent-Tenant header
        cache: Redis cache instance

    Returns:
        Authenticated user with ACL permissions

    Raises:
        HTTPException: If authentication fails

    Example:
        @router.get("/protected")
        async def protected_endpoint(
            user: Annotated[AuthUser, Depends(get_current_user)]
        ):
            return {"user_id": user.user_id}
    """
    # Mock mode: Return mock user immediately (production safety in settings validator)
    mock_user = _get_mock_user()
    if mock_user is not None:
        # Store in request state for consistency
        request.state.user = mock_user
        request.state.tenant_uuid = mock_user.tenant_id
        return mock_user

    # Normal authentication flow
    if not x_auth_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-Auth-Token header",
            headers={"WWW-Authenticate": "X-Auth-Token"},
        )

    # Build cache key
    cache_key_parts = [f"accent_auth:token:{x_auth_token[:16]}"]
    if accent_tenant:
        cache_key_parts.append(f"tenant:{accent_tenant}")
    cache_key = ":".join(cache_key_parts)

    # Check cache first
    if cache is not None:
        try:
            cached = await cache.get(cache_key)
            if cached:
                logger.debug("Token validation cache hit")
                auth_user = AuthUser(**cached)

                # Add user context to logs
                set_log_context(
                    user_id=auth_user.user_id,
                    tenant_id=auth_user.metadata.get("tenant_uuid"),
                )

                # Store in request state
                request.state.user = auth_user
                request.state.tenant_uuid = auth_user.metadata.get("tenant_uuid")

                return auth_user
        except Exception as e:
            logger.warning("Cache lookup failed, proceeding to validation", extra={"error": str(e)})

    # Validate with Accent-Auth
    try:
        client = get_accent_auth_client()
        token_info = await client.validate_token(x_auth_token, accent_tenant)

        # Convert to AuthUser
        auth_user = client.to_auth_user(token_info)

        # Cache the result
        if cache is not None:
            try:
                await cache.set(
                    cache_key,
                    auth_user.model_dump(),
                    ttl=auth_settings.token_cache_ttl,
                )
            except Exception as e:
                logger.warning("Failed to cache token validation", extra={"error": str(e)})

        # Add user context to logs
        set_log_context(
            user_id=auth_user.user_id,
            tenant_id=auth_user.metadata.get("tenant_uuid"),
        )

        # Store in request state
        request.state.user = auth_user
        request.state.tenant_uuid = auth_user.metadata.get("tenant_uuid")

        logger.info(
            "User authenticated via Accent-Auth",
            extra={
                "user_uuid": auth_user.user_id,
                "tenant_uuid": auth_user.metadata.get("tenant_uuid"),
                "acl_count": len(auth_user.permissions),
            },
        )

        return auth_user

    except Exception as e:
        logger.error("Authentication failed", extra={"error": str(e)}, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "X-Auth-Token"},
        ) from e


async def get_current_user_optional(
    request: Request,
    x_auth_token: Annotated[str | None, Header(alias="X-Auth-Token")] = None,
    accent_tenant: Annotated[str | None, Header(alias="Accent-Tenant")] = None,
    cache: Annotated[RedisCache | None, Depends(get_cache)] = None,
) -> AuthUser | None:
    """Get currently authenticated user (optional).

    Similar to get_current_user but returns None instead of raising
    an exception if no token is provided. Useful for endpoints
    that have optional authentication.

    Args:
        request: FastAPI request
        x_auth_token: Token from X-Auth-Token header
        accent_tenant: Optional tenant UUID
        cache: Redis cache instance

    Returns:
        Authenticated user or None if not authenticated

    Example:
        @router.get("/optional-auth")
        async def optional_auth_endpoint(
            user: Annotated[AuthUser | None, Depends(get_current_user_optional)]
        ):
            if user:
                return {"message": f"Hello, {user.user_id}"}
            return {"message": "Hello, anonymous"}
    """
    if not x_auth_token:
        return None

    try:
        return await get_current_user(request, x_auth_token, accent_tenant, cache)
    except HTTPException:
        return None


def require_acl(required_acl: str) -> Callable[[Request, AuthUser], Coroutine[Any, Any, AuthUser]]:
    """Dependency factory to require specific ACL permission.

    Uses Accent-Auth ACL format with dot-notation:
    - service.resource.action (e.g., "confd.users.read")
    - Wildcards supported: * (single level), # (multi-level)
    - Negation: ! prefix for explicit deny
    - Reserved words: me (current user), my_session (current session)

    The pattern can include path parameter placeholders like {user_id}
    that will be formatted with actual request values.

    Args:
        required_acl: Required ACL permission (may include placeholders)

    Returns:
        Dependency function that checks for the ACL

    Example:
        @router.delete("/users/{user_id}")
        async def delete_user(
            user: Annotated[AuthUser, Depends(require_acl("confd.users.delete"))]
        ):
            # Only users with confd.users.delete ACL can access
            pass

        # With path parameter substitution:
        @router.get("/users/{user_id}/profile")
        async def get_profile(
            user: Annotated[AuthUser, Depends(require_acl("users.{user_id}.read"))]
        ):
            # Checks against actual user_id from path
            pass
    """

    async def acl_checker(
        request: Request,
        user: Annotated[AuthUser, Depends(get_current_user)],
    ) -> AuthUser:
        # Format ACL pattern with path parameters if any
        formatted_acl = required_acl.format(**request.path_params)

        # Get session ID from metadata if available
        session_id = user.metadata.get("session_uuid") or user.metadata.get("token")

        # Create ACL checker with user context for reserved word substitution
        acl = AccentAuthACL(
            user.permissions,
            auth_id=user.user_id,
            session_id=session_id,
        )

        if not acl.has_permission(formatted_acl):
            logger.warning(
                "User lacks required ACL",
                extra={
                    "user_uuid": user.user_id,
                    "required_acl": formatted_acl,
                    "original_pattern": required_acl,
                    "user_acls": user.permissions,
                },
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "insufficient_permissions",
                    "message": f"Missing required ACL: {formatted_acl}",
                    "required_acl": formatted_acl,
                },
            )

        return user

    return acl_checker


def require_any_acl(*required_acls: str) -> Callable[[Request, AuthUser], Coroutine[Any, Any, AuthUser]]:
    """Dependency factory to require any of the specified ACLs.

    Args:
        *required_acls: One or more required ACL permissions

    Returns:
        Dependency function that checks for any of the ACLs

    Example:
        @router.get("/users")
        async def list_users(
            user: Annotated[
                AuthUser,
                Depends(require_any_acl("confd.users.read", "confd.users.*"))
            ]
        ):
            # Users with either confd.users.read or confd.users.* can access
            pass
    """

    async def acl_checker(
        request: Request,
        user: Annotated[AuthUser, Depends(get_current_user)],
    ) -> AuthUser:
        # Format ACL patterns with path parameters
        formatted_acls = [acl.format(**request.path_params) for acl in required_acls]

        # Get session ID from metadata if available
        session_id = user.metadata.get("session_uuid") or user.metadata.get("token")

        # Create ACL checker with user context
        acl = AccentAuthACL(
            user.permissions,
            auth_id=user.user_id,
            session_id=session_id,
        )

        if not acl.has_any_permission(*formatted_acls):
            logger.warning(
                "User lacks required ACLs",
                extra={
                    "user_uuid": user.user_id,
                    "required_acls": formatted_acls,
                    "user_acls": user.permissions,
                },
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "insufficient_permissions",
                    "message": f"Missing required ACLs (need any): {', '.join(formatted_acls)}",
                    "required_acls": formatted_acls,
                },
            )

        return user

    return acl_checker


def require_all_acls(*required_acls: str) -> Callable[[Request, AuthUser], Coroutine[Any, Any, AuthUser]]:
    """Dependency factory to require all of the specified ACLs.

    Args:
        *required_acls: All required ACL permissions

    Returns:
        Dependency function that checks for all ACLs

    Example:
        @router.post("/admin/users")
        async def create_admin_user(
            user: Annotated[
                AuthUser,
                Depends(require_all_acls("confd.users.create", "confd.users.admin"))
            ]
        ):
            # Users must have both ACLs to access
            pass
    """

    async def acl_checker(
        request: Request,
        user: Annotated[AuthUser, Depends(get_current_user)],
    ) -> AuthUser:
        # Format ACL patterns with path parameters
        formatted_acls = [acl.format(**request.path_params) for acl in required_acls]

        # Get session ID from metadata if available
        session_id = user.metadata.get("session_uuid") or user.metadata.get("token")

        # Create ACL checker with user context
        acl = AccentAuthACL(
            user.permissions,
            auth_id=user.user_id,
            session_id=session_id,
        )

        missing_acls = [required for required in formatted_acls if not acl.has_permission(required)]

        if missing_acls:
            logger.warning(
                "User missing required ACLs",
                extra={
                    "user_uuid": user.user_id,
                    "missing_acls": missing_acls,
                    "required_acls": formatted_acls,
                },
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "insufficient_permissions",
                    "message": f"Missing required ACLs: {', '.join(missing_acls)}",
                    "required_acls": formatted_acls,
                    "missing_acls": missing_acls,
                },
            )

        return user

    return acl_checker


def require_superuser() -> Callable[[Request, AuthUser], Coroutine[Any, Any, AuthUser]]:
    """Dependency factory to require superuser access (# wildcard ACL).

    This is a convenience dependency for operations requiring full system access.

    Returns:
        Dependency function that checks for # ACL

    Example:
        @router.post("/system/reset")
        async def reset_system(
            user: Annotated[AuthUser, Depends(require_superuser())]
        ):
            # Only users with # ACL can access
            pass
    """
    return require_acl("#")


def get_tenant_uuid() -> str | None:
    """Get tenant UUID from current request context.

    Returns:
        Tenant UUID if available, None otherwise

    Example:
        @router.get("/tenant-data")
        async def get_data(tenant_uuid: Annotated[str | None, Depends(get_tenant_uuid)]):
            if not tenant_uuid:
                raise HTTPException(400, "Tenant context required")
            return {"tenant_uuid": tenant_uuid}
    """
    # Try to get from request state (set by get_current_user)
    try:
        from starlette.requests import Request as StarletteRequest

        async def dummy_receive() -> dict[str, Any]:
            return {"type": "http.request", "body": b""}

        request = StarletteRequest(
            scope={"type": "http", "method": "GET", "path": "/"},
            receive=dummy_receive,
        )
        return getattr(request.state, "tenant_uuid", None)
    except Exception:
        return None
