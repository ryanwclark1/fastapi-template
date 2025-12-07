"""Tenant context management utilities.

This module provides context variable helpers for tenant context propagation
throughout the request lifecycle. These utilities are used by:
- Database tenancy layer (TenantAwareSession) for automatic filtering
- Background tasks that need tenant context outside of request handlers

For tenant resolution in endpoints, use the dependency approach:
    from example_service.core.dependencies.tenant import TenantContextDep

The context variables here serve as a bridge for non-dependency contexts
(database sessions, background workers, etc.).
"""

from __future__ import annotations

from contextvars import ContextVar
import logging

from example_service.core.schemas.tenant import TenantContext

logger = logging.getLogger(__name__)

# Context variable for storing tenant information
_tenant_context: ContextVar[TenantContext | None] = ContextVar(
    "tenant_context", default=None
)


def get_tenant_context() -> TenantContext | None:
    """Get current tenant context from request.

    Returns:
        Current tenant context or None if not in request context
    """
    return _tenant_context.get()


def set_tenant_context(context: TenantContext) -> None:
    """Set tenant context for current request.

    Args:
        context: Tenant context to set
    """
    _tenant_context.set(context)
    logger.debug(
        "Tenant context set",
        extra={"tenant_id": context.tenant_id, "identified_by": context.identified_by},
    )


def clear_tenant_context() -> None:
    """Clear tenant context."""
    _tenant_context.set(None)


def require_tenant() -> TenantContext:
    """Get current tenant context, raising if not available.

    Returns:
        Current tenant context

    Raises:
        RuntimeError: If no tenant context is available
    """
    context = get_tenant_context()
    if not context:
        msg = "No tenant context available"
        raise RuntimeError(msg)
    return context
