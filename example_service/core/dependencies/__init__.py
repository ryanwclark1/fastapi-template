"""FastAPI dependencies for route handlers.

This module re-exports commonly used dependencies for cleaner imports.

Usage:
    from example_service.core.dependencies import (
        get_db_session,
        get_event_publisher,
        EventPublisherDep,
        get_cache,
    )

    @router.post("/items")
    async def create_item(
        session: AsyncSession = Depends(get_db_session),
        publisher: EventPublisher = Depends(get_event_publisher),
        cache: RedisCache = Depends(get_cache),
    ):
        ...

Authentication Dependencies:
    For authentication, import from the specific submodule you need:

    # External auth service (Bearer token)
    from example_service.core.dependencies.auth import (
        get_current_user,
        get_current_user_optional,
        require_permission,
        require_role,
        require_resource_access,
    )

    # Accent-Auth service (X-Auth-Token header)
    from example_service.core.dependencies.accent_auth import (
        get_current_user,
        get_current_user_optional,
        require_acl,
        require_any_acl,
        require_all_acls,
        get_tenant_uuid,
    )
"""

from example_service.core.dependencies.database import get_db_session
from example_service.core.dependencies.events import EventPublisherDep, get_event_publisher

# Re-export rate limit dependencies
from example_service.core.dependencies.ratelimit import (
    RateLimited,
    StrictRateLimit,
    UserRateLimit,
    get_rate_limiter,
    per_api_key_rate_limit,
    per_user_rate_limit,
    rate_limit,
)

# Re-export service dependencies
from example_service.core.dependencies.services import (
    HealthService,
    HealthServiceDep,
    get_health_service,
)
from example_service.infra.cache import get_cache

__all__ = [
    # Database
    "get_db_session",
    # Events
    "get_event_publisher",
    "EventPublisherDep",
    # Cache (infrastructure)
    "get_cache",
    # Rate limiting
    "get_rate_limiter",
    "rate_limit",
    "per_user_rate_limit",
    "per_api_key_rate_limit",
    "RateLimited",
    "StrictRateLimit",
    "UserRateLimit",
    # Services
    "get_health_service",
    "HealthService",
    "HealthServiceDep",
]
