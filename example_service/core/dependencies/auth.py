"""Authentication dependencies for validating external auth tokens.

This module provides FastAPI dependencies for:
- Extracting auth tokens from requests
- Validating tokens with external auth service
- Caching validated tokens to reduce external calls
- Checking permissions and ACLs
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Annotated

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from example_service.core.schemas.auth import AuthUser, TokenPayload
from example_service.core.settings import get_auth_settings
from example_service.infra.cache.redis import get_cache
from example_service.infra.logging.context import set_log_context
from example_service.utils.retry import retry

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from example_service.infra.cache.redis import RedisCache

logger = logging.getLogger(__name__)

# Security scheme for extracting Bearer tokens
security = HTTPBearer(auto_error=False)
auth_settings = get_auth_settings()


def _is_retryable_auth_error(exc: Exception) -> bool:
    """Check if an auth service error should trigger a retry."""
    if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError)):
        return True
    # Retry on gateway errors (auth service behind load balancer)
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in {502, 503, 504}
    return False


@retry(
    max_attempts=auth_settings.max_retries,
    initial_delay=0.5,
    max_delay=auth_settings.request_timeout,
    retry_if=_is_retryable_auth_error,
    stop_after_delay=auth_settings.request_timeout * 2,  # 2x single request timeout
)
async def validate_token_with_auth_service(token: str) -> TokenPayload:
    """Validate token with external auth service.

    This function calls the external authentication service to validate
    the provided token and retrieve user/service information and permissions.

    Args:
        token: Bearer token to validate.

    Returns:
        Token payload with user/service info and permissions.

    Raises:
        HTTPException: If token is invalid or auth service is unavailable.
    """
    if not auth_settings.is_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service not configured",
        )

    try:
        validation_url = auth_settings.get_validation_url()
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                validation_url,
                headers={"Authorization": f"Bearer {token}"},
            )

            if response.status_code == 401:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid or expired token",
                    headers={"WWW-Authenticate": "Bearer"},
                )

            if response.status_code != 200:
                logger.error(
                    "Auth service returned unexpected status",
                    extra={"status_code": response.status_code},
                )
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Authentication service unavailable",
                )

            data = response.json()
            return TokenPayload(**data)

    except httpx.TimeoutException as err:
        logger.error("Timeout calling auth service")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service timeout",
        ) from err
    except httpx.NetworkError as e:
        logger.error("Network error calling auth service", extra={"error": str(e)})
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service unavailable",
        ) from e
    except Exception as e:
        logger.exception("Unexpected error validating token", extra={"error": str(e)})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authentication error",
        ) from e


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
    cache: Annotated[RedisCache, Depends(get_cache)],
) -> AuthUser:
    """Get currently authenticated user or service.

    This dependency extracts the Bearer token from the request,
    validates it with the external auth service, and returns the
    authenticated user/service with their permissions.

    Token validation results are cached in Redis to reduce load
    on the external auth service.

    Args:
        credentials: HTTP Bearer credentials from request.
        cache: Redis cache instance.

    Returns:
        Authenticated user or service with permissions.

    Raises:
        HTTPException: If authentication fails.

    Example:
            @router.get("/protected")
        async def protected_endpoint(
            user: Annotated[AuthUser, Depends(get_current_user)]
        ):
            return {"user_id": user.identifier}
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials

    # Check cache first
    cache_key = f"auth:token:{token[:16]}"  # Use token prefix as key
    try:
        cached = await cache.get(cache_key)
        if cached:
            logger.debug("Token validation cache hit")
            auth_user = AuthUser(**cached)
            # Add user context to logs even for cached results
            set_log_context(
                user_id=auth_user.user_id or auth_user.service_id,
                email=auth_user.email,
                user_type="service" if auth_user.service_id else "user",
            )
            return auth_user
    except Exception as e:
        logger.warning("Cache lookup failed, proceeding to validation", extra={"error": str(e)})

    # Validate with auth service
    try:
        payload = await validate_token_with_auth_service(token)

        # Convert to AuthUser
        auth_user = AuthUser(
            user_id=payload.user_id,
            service_id=payload.service_id,
            email=payload.email,
            roles=payload.roles,
            permissions=payload.permissions,
            acl=payload.acl,
            metadata=payload.metadata,
        )

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
        # All subsequent logs will automatically include user information
        set_log_context(
            user_id=auth_user.user_id or auth_user.service_id,
            email=auth_user.email,
            user_type="service" if auth_user.service_id else "user",
        )

        return auth_user

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error getting current user", extra={"error": str(e)})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authentication error",
        ) from e


async def get_current_user_optional(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
    cache: Annotated[RedisCache, Depends(get_cache)],
) -> AuthUser | None:
    """Get currently authenticated user or service (optional).

    Similar to get_current_user but returns None instead of raising
    an exception if no credentials are provided. Useful for endpoints
    that have optional authentication.

    Args:
        credentials: HTTP Bearer credentials from request.
        cache: Redis cache instance.

    Returns:
        Authenticated user/service or None if not authenticated.

    Example:
            @router.get("/optional-auth")
        async def optional_auth_endpoint(
            user: Annotated[AuthUser | None, Depends(get_current_user_optional)]
        ):
            if user:
                return {"message": f"Hello, {user.identifier}"}
            return {"message": "Hello, anonymous"}
    """
    if not credentials:
        return None

    try:
        return await get_current_user(credentials, cache)
    except HTTPException:
        return None


def require_permission(permission: str) -> Callable[[AuthUser], Awaitable[AuthUser]]:
    """Dependency factory to require specific permission.

    Args:
        permission: Required permission.

    Returns:
        Dependency function that checks for the permission.

    Example:
            @router.delete("/users/{user_id}")
        async def delete_user(
            user: Annotated[AuthUser, Depends(require_permission("users:delete"))]
        ):
            # Only users with "users:delete" permission can access
            pass
    """

    async def permission_checker(user: Annotated[AuthUser, Depends(get_current_user)]) -> AuthUser:
        if not user.has_permission(permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required permission: {permission}",
            )
        return user

    return permission_checker


def require_role(role: str) -> Callable[[AuthUser], Awaitable[AuthUser]]:
    """Dependency factory to require specific role.

    Args:
        role: Required role.

    Returns:
        Dependency function that checks for the role.

    Example:
            @router.get("/admin")
        async def admin_endpoint(
            user: Annotated[AuthUser, Depends(require_role("admin"))]
        ):
            # Only users with "admin" role can access
            pass
    """

    async def role_checker(user: Annotated[AuthUser, Depends(get_current_user)]) -> AuthUser:
        if not user.has_role(role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required role: {role}",
            )
        return user

    return role_checker


def require_resource_access(
    resource: str, action: str
) -> Callable[[AuthUser], Awaitable[AuthUser]]:
    """Dependency factory to require resource access.

    Args:
        resource: Resource identifier.
        action: Required action.

    Returns:
        Dependency function that checks ACL for resource access.

    Example:
            @router.delete("/posts/{post_id}")
        async def delete_post(
            user: Annotated[AuthUser, Depends(require_resource_access("posts", "delete"))]
        ):
            # Only users with ACL permission to delete posts can access
            pass
    """

    async def acl_checker(user: Annotated[AuthUser, Depends(get_current_user)]) -> AuthUser:
        if not user.can_access_resource(resource, action):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied to {action} on {resource}",
            )
        return user

    return acl_checker
