"""Multi-tenancy middleware for tenant context management.

This middleware provides:
- Tenant identification from various sources (header, subdomain, JWT claim)
- Tenant context propagation throughout the request lifecycle
- Tenant validation and authorization
- Support for both single-tenant and multi-tenant deployments
"""

from __future__ import annotations

import logging
import re
from contextvars import ContextVar
from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware

from example_service.core.schemas.tenant import TenantContext

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from fastapi import Request, Response
    from starlette.types import ASGIApp

logger = logging.getLogger(__name__)

# Context variable for storing tenant information
_tenant_context: ContextVar[TenantContext | None] = ContextVar("tenant_context", default=None)


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
        raise RuntimeError("No tenant context available")
    return context


class TenantIdentificationStrategy:
    """Base class for tenant identification strategies."""

    async def identify(self, request: Request) -> str | None:
        """Identify tenant from request.

        Args:
            request: FastAPI request

        Returns:
            Tenant identifier or None if not found
        """
        raise NotImplementedError


class HeaderTenantStrategy(TenantIdentificationStrategy):
    """Identify tenant from HTTP header.

    For Accent-Auth, use header_name="Accent-Tenant" to match the standard.

    Example:
        Accent-Tenant: <tenant-uuid>
        X-Tenant-ID: acme-corp
    """

    def __init__(self, header_name: str = "Accent-Tenant"):
        """Initialize strategy.

        Args:
            header_name: HTTP header name (default: Accent-Tenant for accent-auth)
        """
        self.header_name = header_name.lower()

    async def identify(self, request: Request) -> str | None:
        """Identify tenant from header.

        Args:
            request: FastAPI request

        Returns:
            Tenant ID/UUID from header or None
        """
        tenant_id = request.headers.get(self.header_name)
        if tenant_id:
            logger.debug(f"Identified tenant from header: {tenant_id}")
        return tenant_id


class SubdomainTenantStrategy(TenantIdentificationStrategy):
    """Identify tenant from subdomain.

    Example:
        acme-corp.example.com -> tenant_id: acme-corp
    """

    def __init__(self, base_domain: str, subdomain_pattern: str = r"^([a-z0-9-]+)"):
        """Initialize strategy.

        Args:
            base_domain: Base domain (e.g., example.com)
            subdomain_pattern: Regex pattern for extracting subdomain
        """
        self.base_domain = base_domain.lower()
        self.pattern = re.compile(subdomain_pattern)

    async def identify(self, request: Request) -> str | None:
        """Identify tenant from subdomain.

        Args:
            request: FastAPI request

        Returns:
            Tenant ID from subdomain or None
        """
        # Get host from request
        host = request.headers.get("host", "").lower()

        # Remove port if present
        host = host.split(":")[0]

        # Check if host matches pattern
        if not host.endswith(f".{self.base_domain}"):
            return None

        # Extract subdomain
        subdomain = host[: -(len(self.base_domain) + 1)]
        match = self.pattern.match(subdomain)

        if match:
            tenant_id = match.group(1)
            logger.debug(f"Identified tenant from subdomain: {tenant_id}")
            return tenant_id

        return None


class JWTClaimTenantStrategy(TenantIdentificationStrategy):
    """Identify tenant from JWT token claim.

    This strategy requires the request to already have authentication
    processed (e.g., via AuthenticationMiddleware).

    Example JWT claim:
        {
            "sub": "user123",
            "tenant_id": "acme-corp"
        }
    """

    def __init__(self, claim_name: str = "tenant_id"):
        """Initialize strategy.

        Args:
            claim_name: JWT claim name containing tenant ID
        """
        self.claim_name = claim_name

    async def identify(self, request: Request) -> str | None:
        """Identify tenant from JWT claim.

        Args:
            request: FastAPI request

        Returns:
            Tenant ID from JWT or None
        """
        # Get user from request state (set by auth middleware)
        user = getattr(request.state, "user", None)

        if not user:
            return None

        # Check for tenant_id in user metadata or direct attribute
        tenant_id = None

        if hasattr(user, "tenant_id"):
            tenant_id = user.tenant_id
        elif hasattr(user, "metadata") and isinstance(user.metadata, dict):
            tenant_id = user.metadata.get(self.claim_name)

        if tenant_id:
            logger.debug(f"Identified tenant from JWT: {tenant_id}")

        return tenant_id


class PathPrefixTenantStrategy(TenantIdentificationStrategy):
    """Identify tenant from URL path prefix.

    Example:
        /t/acme-corp/api/users -> tenant_id: acme-corp
    """

    def __init__(self, prefix: str = "/t"):
        """Initialize strategy.

        Args:
            prefix: URL path prefix
        """
        self.prefix = prefix.rstrip("/")
        self.pattern = re.compile(rf"^{re.escape(self.prefix)}/([a-z0-9-]+)")

    async def identify(self, request: Request) -> str | None:
        """Identify tenant from path.

        Args:
            request: FastAPI request

        Returns:
            Tenant ID from path or None
        """
        path = request.url.path
        match = self.pattern.match(path)

        if match:
            tenant_id = match.group(1)
            logger.debug(f"Identified tenant from path: {tenant_id}")
            return tenant_id

        return None


class TenantMiddleware(BaseHTTPMiddleware):
    """Middleware for multi-tenant support.

    This middleware:
    1. Identifies tenant using configured strategies
    2. Validates tenant (optional)
    3. Sets tenant context for the request
    4. Adds tenant ID to response headers
    5. Logs tenant information

    Example:
        app.add_middleware(
            TenantMiddleware,
            strategies=[
                HeaderTenantStrategy(),
                SubdomainTenantStrategy("example.com"),
            ],
            required=True,
        )
    """

    def __init__(
        self,
        app: ASGIApp,
        strategies: list[TenantIdentificationStrategy] | None = None,
        required: bool = False,
        default_tenant: str | None = None,
        tenant_validator: Callable[[str], Awaitable[bool]] | None = None,
    ):
        """Initialize tenant middleware.

        Args:
            app: ASGI application
            strategies: List of tenant identification strategies (tried in order)
            required: Whether tenant is required for all requests
            default_tenant: Default tenant ID if none identified
            tenant_validator: Async function to validate tenant exists/is active
        """
        super().__init__(app)
        self.strategies = strategies or [HeaderTenantStrategy()]
        self.required = required
        self.default_tenant = default_tenant
        self.tenant_validator = tenant_validator

        logger.info(
            "Tenant middleware initialized",
            extra={
                "strategies": [s.__class__.__name__ for s in self.strategies],
                "required": required,
                "default_tenant": default_tenant,
            },
        )

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Process request with tenant context.

        Args:
            request: FastAPI request
            call_next: Next middleware/handler

        Returns:
            HTTP response
        """
        # Clear any previous tenant context
        clear_tenant_context()

        # Try each strategy to identify tenant
        tenant_id = None
        identified_by = None

        for strategy in self.strategies:
            try:
                tenant_id = await strategy.identify(request)
                if tenant_id:
                    identified_by = strategy.__class__.__name__
                    break
            except Exception as e:
                logger.warning(
                    f"Tenant identification failed for {strategy.__class__.__name__}",
                    extra={"error": str(e)},
                )

        # Use default tenant if none identified
        if not tenant_id and self.default_tenant:
            tenant_id = self.default_tenant
            identified_by = "default"

        # Check if tenant is required
        if self.required and not tenant_id:
            from fastapi import HTTPException, status

            logger.warning("Tenant required but not identified")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Tenant identifier required",
            )

        # Validate tenant if validator provided
        if tenant_id and self.tenant_validator:
            try:
                is_valid = await self.tenant_validator(tenant_id)
                if not is_valid:
                    from fastapi import HTTPException, status

                    logger.warning(f"Invalid tenant: {tenant_id}")
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Tenant not found or inactive",
                    )
            except Exception as e:
                logger.error(
                    "Tenant validation failed",
                    extra={"tenant_id": tenant_id, "error": str(e)},
                )
                from fastapi import HTTPException, status

                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Tenant validation error",
                ) from e

        # Create and set tenant context
        if tenant_id:
            context = TenantContext(
                tenant_id=tenant_id,
                identified_by=identified_by,
            )
            set_tenant_context(context)

            # Store in request state for easy access
            request.state.tenant_id = tenant_id
            request.state.tenant_context = context

            logger.debug(
                f"Tenant context set: {tenant_id}",
                extra={"tenant_id": tenant_id, "identified_by": identified_by},
            )

        # Process request
        response = await call_next(request)

        # Add tenant header to response (using Accent-Tenant for accent-auth compatibility)
        if tenant_id:
            response.headers["Accent-Tenant"] = tenant_id

        # Clear context after request
        clear_tenant_context()

        return response
