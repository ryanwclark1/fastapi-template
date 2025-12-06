"""FastAPI dependencies for route handlers.

This module re-exports commonly used dependencies for cleaner imports.
It acts as the central Dependency Injection (DI) registry for the application.

Architecture Note:
    This module intentionally imports from `infra/` (e.g., get_cache) despite
    the typical layering where core should not depend on infra. This is a
    pragmatic design choice for DI:

    - `core/dependencies/` serves as the DI registry, the composition root
    - Features import dependencies from here, not directly from infra
    - This provides a stable API for features while allowing infra changes
    - The tradeoff: core has awareness of infra, but only for DI wiring

    Alternative patterns considered but rejected:
    - Protocols in core with infra implementations: More complex, less ergonomic
    - Direct infra imports in features: Tighter coupling, harder to mock

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
        CurrentActiveUser,
        CurrentUser,
        OptionalUser,
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

from example_service.core.dependencies.availability import (
    RequireAuth,
    RequireBroker,
    RequireCache,
    RequireConsul,
    RequireDatabase,
    RequireDatabaseAndBroker,
    RequireDatabaseAndCache,
    RequireStorage,
    require_services,
)
from example_service.core.dependencies.database import get_db_session
from example_service.core.dependencies.events import (
    EventPublisherDep,
    get_event_publisher,
)

# Re-export pagination dependencies
from example_service.core.dependencies.pagination import (
    ExtendedPagination,
    ExtendedPaginationParams,
    PaginationParams,
    SearchPagination,
    SearchPaginationParams,
    StandardPagination,
    get_extended_pagination,
    get_search_pagination,
    get_standard_pagination,
)

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
    # Service availability
    "RequireAuth",
    "RequireBroker",
    "RequireCache",
    "RequireConsul",
    "RequireDatabase",
    "RequireDatabaseAndBroker",
    "RequireDatabaseAndCache",
    "RequireStorage",
    "require_services",
    "EventPublisherDep",
    "ExtendedPagination",
    "ExtendedPaginationParams",
    "HealthService",
    "HealthServiceDep",
    "PaginationParams",
    "RateLimited",
    "SearchPagination",
    "SearchPaginationParams",
    "StandardPagination",
    "StrictRateLimit",
    "UserRateLimit",
    # Cache (infrastructure)
    "get_cache",
    # Database
    "get_db_session",
    # Events
    "get_event_publisher",
    "get_extended_pagination",
    # Services
    "get_health_service",
    # Rate limiting
    "get_rate_limiter",
    "get_search_pagination",
    # Pagination
    "get_standard_pagination",
    "per_api_key_rate_limit",
    "per_user_rate_limit",
    "rate_limit",
]
