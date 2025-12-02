"""Tenant context dependencies for multi-tenant storage operations.

This module provides FastAPI dependencies for extracting tenant context
from authenticated requests. Tenant context is used for:
- Tenant-aware bucket resolution
- Multi-tenant storage isolation
- Audit logging and tracking
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, Header

from example_service.infra.storage.backends import TenantContext

from .auth import get_current_user

if TYPE_CHECKING:
    from example_service.core.schemas.auth import AuthUser

logger = logging.getLogger(__name__)


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
        metadata=user.metadata,
    )


def get_tenant_context_from_header(
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-ID")] = None,
) -> TenantContext | None:
    """Extract tenant context from custom header (fallback for service-to-service calls).

    This fallback method is used when:
    - Service-to-service calls with explicit tenant
    - CLI operations with explicit tenant flag
    - Admin operations

    Args:
        x_tenant_id: Tenant UUID or slug from X-Tenant-ID header

    Returns:
        TenantContext if header present, None otherwise

    Example:
        # HTTP request with header
        curl -H "X-Tenant-ID: acme-123" https://api.example.com/upload

    Note:
        In production, you should validate that the tenant exists and
        the caller has permission to act on behalf of that tenant.
        This validation is not implemented here for simplicity.
    """
    if not x_tenant_id:
        return None

    logger.debug(
        "Extracted tenant context from X-Tenant-ID header",
        extra={"tenant_id": x_tenant_id},
    )

    # For now, use the provided ID as both UUID and slug
    # In production, you would look up the tenant in the database
    # to get the proper UUID and slug
    return TenantContext(
        tenant_uuid=x_tenant_id,
        tenant_slug=x_tenant_id,  # TODO: Look up slug from database
        metadata={"source": "header"},
    )


def get_tenant_context(
    user_context: Annotated[
        TenantContext | None, Depends(get_tenant_context_from_user)
    ] = None,
    header_context: Annotated[
        TenantContext | None, Depends(get_tenant_context_from_header)
    ] = None,
) -> TenantContext | None:
    """Get tenant context with priority: JWT > Header.

    This is the main dependency to use in endpoints that support multi-tenant
    operations. It tries JWT metadata first, then falls back to the X-Tenant-ID
    header.

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

    if context:
        logger.debug(
            "Using tenant context",
            extra={
                "tenant_uuid": context.tenant_uuid,
                "tenant_slug": context.tenant_slug,
                "source": "jwt" if user_context else "header",
            },
        )
    else:
        logger.debug("No tenant context available")

    return context


# ============================================================================
# Type Aliases for Convenience
# ============================================================================

# Use this type alias in endpoint signatures for cleaner code:
# tenant: TenantContextDep instead of tenant: Annotated[TenantContext | None, Depends(get_tenant_context)]
TenantContextDep = Annotated[TenantContext | None, Depends(get_tenant_context)]
