"""Accent-Auth dependencies for FastAPI endpoints.

This module provides FastAPI dependencies for:
- Extracting X-Auth-Token from requests
- Validating tokens with Accent-Auth service
- Caching validated tokens to reduce external calls
- Checking ACL permissions
- Managing tenant context
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, Header, HTTPException, Request, status

from example_service.core.schemas.auth import AuthUser
from example_service.core.settings import get_auth_settings
from example_service.infra.auth.accent_auth import (
    AccentAuthACL,
    get_accent_auth_client,
)
from example_service.infra.cache.redis import get_cache
from example_service.infra.logging.context import set_log_context

if TYPE_CHECKING:
    from example_service.infra.cache.redis import RedisCache

logger = logging.getLogger(__name__)

auth_settings = get_auth_settings()


async def get_current_user(
    request: Request,
    x_auth_token: Annotated[str | None, Header(alias="X-Auth-Token")] = None,
    accent_tenant: Annotated[str | None, Header(alias="Accent-Tenant")] = None,
    cache: Annotated[RedisCache, Depends(get_cache)] = None,
) -> AuthUser:
    """Get currently authenticated user from Accent-Auth.

    This dependency:
    1. Extracts X-Auth-Token from request headers
    2. Extracts Accent-Tenant header (optional)
    3. Validates token with Accent-Auth service
    4. Caches validation results in Redis
    5. Returns AuthUser with ACL permissions

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
    cache: Annotated[RedisCache, Depends(get_cache)] = None,
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


def require_acl(required_acl: str):
    """Dependency factory to require specific ACL permission.

    Uses Accent-Auth ACL format with dot-notation:
    - service.resource.action (e.g., "confd.users.read")
    - Wildcards supported: * (single level), # (multi-level)

    Args:
        required_acl: Required ACL permission

    Returns:
        Dependency function that checks for the ACL

    Example:
        @router.delete("/users/{user_id}")
        async def delete_user(
            user: Annotated[AuthUser, Depends(require_acl("confd.users.delete"))]
        ):
            # Only users with confd.users.delete ACL can access
            pass
    """

    async def acl_checker(user: Annotated[AuthUser, Depends(get_current_user)]) -> AuthUser:
        # Create ACL checker
        acl = AccentAuthACL(user.permissions)

        if not acl.has_permission(required_acl):
            logger.warning(
                "User lacks required ACL",
                extra={
                    "user_uuid": user.user_id,
                    "required_acl": required_acl,
                    "user_acls": user.permissions,
                },
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required ACL: {required_acl}",
            )

        return user

    return acl_checker


def require_any_acl(*required_acls: str):
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

    async def acl_checker(user: Annotated[AuthUser, Depends(get_current_user)]) -> AuthUser:
        acl = AccentAuthACL(user.permissions)

        has_any = any(acl.has_permission(required) for required in required_acls)

        if not has_any:
            logger.warning(
                "User lacks required ACLs",
                extra={
                    "user_uuid": user.user_id,
                    "required_acls": list(required_acls),
                    "user_acls": user.permissions,
                },
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required ACLs: {', '.join(required_acls)}",
            )

        return user

    return acl_checker


def require_all_acls(*required_acls: str):
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

    async def acl_checker(user: Annotated[AuthUser, Depends(get_current_user)]) -> AuthUser:
        acl = AccentAuthACL(user.permissions)

        missing_acls = [required for required in required_acls if not acl.has_permission(required)]

        if missing_acls:
            logger.warning(
                "User missing required ACLs",
                extra={
                    "user_uuid": user.user_id,
                    "missing_acls": missing_acls,
                    "required_acls": list(required_acls),
                },
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required ACLs: {', '.join(missing_acls)}",
            )

        return user

    return acl_checker


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
    from fastapi import Request

    # Try to get from request state (set by get_current_user)
    try:
        request = Request(scope={"type": "http"}, receive=None)
        return getattr(request.state, "tenant_uuid", None)
    except Exception:
        return None
