"""Tenant context dependencies for multi-tenant storage operations.

This module provides FastAPI dependencies for extracting tenant context
from authenticated requests. Tenant context is used for:
- Tenant-aware bucket resolution
- Multi-tenant storage isolation
- Audit logging and tracking
- Database tenant filtering (via context var bridge)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, Header
from frozendict import frozendict
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: TC002

from example_service.app.middleware.tenant import (
    set_tenant_context as set_middleware_tenant_context,
)
from example_service.core.schemas.tenant import TenantContext as SchemaTenantContext
from example_service.infra.storage.backends import TenantContext

from .auth import get_current_user
from .database import get_db_session

if TYPE_CHECKING:
    from example_service.core.schemas.auth import AuthUser

logger = logging.getLogger(__name__)

# In-memory cache for tenant lookups (simple TTL-based)
# Key: tenant_id (UUID or slug), Value: (tenant_uuid, tenant_slug, expiry_time)
_tenant_cache: dict[str, tuple[str, str, float]] = {}
_CACHE_TTL_SECONDS = 300  # 5 minutes


def get_tenant_context_from_user(
    user: Annotated[AuthUser, Depends(get_current_user)],
) -> TenantContext | None:
    """Extract tenant context from authenticated user's JWT metadata.

    This is the primary method for getting tenant context. The JWT token
    payload includes tenant information in the metadata field.

    Args:
        user: Authenticated user from JWT token

    Returns:
        TenantContext if tenant info found in metadata, None otherwise

    Example:
        @router.post("/upload")
        async def upload_file(
            tenant: Annotated[TenantContext | None, Depends(get_tenant_context_from_user)],
        ):
            if tenant:
                print(f"Tenant: {tenant.tenant_slug}")
    """
    # Extract tenant info from user metadata
    tenant_uuid = user.metadata.get("tenant_uuid")
    tenant_slug = user.metadata.get("tenant_slug")

    if not tenant_uuid or not tenant_slug:
        logger.debug(
            "No tenant context found in user metadata",
            extra={
                "user_id": user.user_id,
                "service_id": user.service_id,
            },
        )
        return None

    logger.debug(
        "Extracted tenant context from JWT",
        extra={
            "tenant_uuid": tenant_uuid,
            "tenant_slug": tenant_slug,
            "user_id": user.user_id,
        },
    )

    return TenantContext(
        tenant_uuid=tenant_uuid,
        tenant_slug=tenant_slug,
        metadata=frozendict(user.metadata),
    )


async def _lookup_tenant(
    session: AsyncSession,
    tenant_id: str,
) -> tuple[str, str] | None:
    """Look up tenant UUID and slug from database with caching.

    Uses a simple TTL cache to avoid repeated database queries for
    the same tenant during a request burst.

    Args:
        session: Database session
        tenant_id: Tenant ID (can be UUID or slug)

    Returns:
        Tuple of (tenant_uuid, tenant_slug) if found, None otherwise
    """
    import time

    from sqlalchemy import select

    from example_service.core.models.tenant import Tenant

    # Check cache first
    now = time.time()
    if tenant_id in _tenant_cache:
        uuid, slug, expiry = _tenant_cache[tenant_id]
        if now < expiry:
            logger.debug(
                "Tenant cache hit",
                extra={"tenant_id": tenant_id, "uuid": uuid, "slug": slug},
            )
            return (uuid, slug)
        else:
            # Expired entry
            del _tenant_cache[tenant_id]

    # Query database - try by ID first (most common case)
    stmt = select(Tenant).where(
        (Tenant.id == tenant_id) & (Tenant.is_active == True)  # noqa: E712
    )
    result = await session.execute(stmt)
    tenant = result.scalar_one_or_none()

    if tenant is None:
        logger.debug(
            "Tenant not found by ID, skipping lookup",
            extra={"tenant_id": tenant_id},
        )
        return None

    # Extract slug from tenant name (create URL-friendly version)
    # In a real system, you might have a dedicated slug column
    tenant_slug = tenant.name.lower().replace(" ", "-")[:20] if tenant.name else tenant.id[:20]

    # Cache the result
    _tenant_cache[tenant_id] = (tenant.id, tenant_slug, now + _CACHE_TTL_SECONDS)

    logger.debug(
        "Tenant looked up from database",
        extra={"tenant_id": tenant_id, "uuid": tenant.id, "slug": tenant_slug},
    )

    return (tenant.id, tenant_slug)


def invalidate_tenant_cache(tenant_id: str | None = None) -> None:
    """Invalidate tenant cache entries.

    Call this after tenant updates to ensure fresh data.

    Args:
        tenant_id: Specific tenant to invalidate, or None for all
    """
    if tenant_id is None:
        _tenant_cache.clear()
        logger.debug("Tenant cache cleared")
    elif tenant_id in _tenant_cache:
        del _tenant_cache[tenant_id]
        logger.debug("Tenant cache invalidated", extra={"tenant_id": tenant_id})


async def get_tenant_context_from_header(
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-ID")] = None,
    session: Annotated[AsyncSession, Depends(get_db_session)] = ...,  # type: ignore[assignment]
) -> TenantContext | None:
    """Extract tenant context from custom header (fallback for service-to-service calls).

    This fallback method is used when:
    - Service-to-service calls with explicit tenant
    - CLI operations with explicit tenant flag
    - Admin operations

    The tenant is looked up in the database to validate it exists and
    is active, and to retrieve the proper UUID and slug.

    Args:
        x_tenant_id: Tenant UUID or slug from X-Tenant-ID header
        session: Database session for tenant lookup

    Returns:
        TenantContext if tenant found and active, None otherwise

    Example:
        # HTTP request with header
        curl -H "X-Tenant-ID: acme-123" https://api.example.com/upload
    """
    if not x_tenant_id:
        return None

    logger.debug(
        "Looking up tenant from X-Tenant-ID header",
        extra={"tenant_id": x_tenant_id},
    )

    # Look up tenant in database to get proper UUID and slug
    lookup_result = await _lookup_tenant(session, x_tenant_id)

    if lookup_result is None:
        logger.warning(
            "Tenant not found or inactive",
            extra={"tenant_id": x_tenant_id},
        )
        return None

    tenant_uuid, tenant_slug = lookup_result

    logger.debug(
        "Extracted tenant context from X-Tenant-ID header",
        extra={"tenant_uuid": tenant_uuid, "tenant_slug": tenant_slug},
    )

    return TenantContext(
        tenant_uuid=tenant_uuid,
        tenant_slug=tenant_slug,
        metadata=frozendict({"source": "header"}),
    )


def get_tenant_context(
    user_context: Annotated[TenantContext | None, Depends(get_tenant_context_from_user)] = None,
    header_context: Annotated[TenantContext | None, Depends(get_tenant_context_from_header)] = None,
) -> TenantContext | None:
    """Get tenant context with priority: JWT > Header.

    This is the main dependency to use in endpoints that support multi-tenant
    operations. It tries JWT metadata first, then falls back to the X-Tenant-ID
    header.

    This function also bridges to the middleware context var, enabling:
    - TenantAwareSession for automatic database filtering
    - Background tasks that need tenant context

    Args:
        user_context: Tenant context from JWT token
        header_context: Tenant context from X-Tenant-ID header

    Returns:
        TenantContext from the first available source, or None

    Example:
        @router.post("/files/upload")
        async def upload_file(
            file: UploadFile,
            tenant: TenantContextDep,  # Uses type alias
            storage: Annotated[StorageService, Depends(get_storage_service)],
        ):
            result = await storage.upload_file(
                file_obj=file.file,
                key=file.filename,
                tenant_context=tenant,
            )
            return result
    """
    # JWT takes priority over header
    context = user_context or header_context
    source = "jwt" if user_context else "header"

    if context:
        logger.debug(
            "Using tenant context",
            extra={
                "tenant_uuid": context.tenant_uuid,
                "tenant_slug": context.tenant_slug,
                "source": source,
            },
        )

        # Bridge to middleware context var for database tenancy layer
        # Maps storage TenantContext to schema TenantContext
        schema_context = SchemaTenantContext(
            tenant_id=context.tenant_uuid,
            identified_by=source,
        )
        set_middleware_tenant_context(schema_context)
    else:
        logger.debug("No tenant context available")

    return context


# ============================================================================
# Type Aliases for Convenience
# ============================================================================

# Use this type alias in endpoint signatures for cleaner code:
# tenant: TenantContextDep instead of tenant: Annotated[TenantContext | None, Depends(get_tenant_context)]
TenantContextDep = Annotated[TenantContext | None, Depends(get_tenant_context)]
