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
        BusPublisherDep,  # New Protocol-based API (recommended)
        MessageBroker,     # Legacy API (still supported)
        Storage,
    )

    @router.post("/items")
    async def create_item(
        session: AsyncSession = Depends(get_db_session),
        publisher: EventPublisher = Depends(get_event_publisher),
        cache: RedisCache = Depends(get_cache),
        bus: BusPublisherDep,  # New Protocol-based messaging
        storage: Storage,
    ):
        ...

Authentication Dependencies (ACL-based using Accent-Auth):
    All authentication uses the Accent-Auth ACL system with X-Auth-Token header.

    from example_service.core.dependencies.auth import (
        # Type aliases
        AuthUserDep,          # Required authentication
        OptionalAuthUser,     # Optional authentication
        SuperuserDep,         # Superuser access only
        # Functions
        get_auth_user,
        get_auth_user_optional,
        require_acl,
        require_any_acl,
        require_all_acls,
        require_superuser,
        get_tenant_uuid,
    )

    # Or import directly from accent_auth:
    from example_service.core.dependencies.accent_auth import (
        get_auth_user,
        require_acl,
        require_any_acl,
        require_all_acls,
        require_superuser,
    )
"""

# AI dependencies
from example_service.core.dependencies.ai import (
    AILoggerDep,
    AIMetricsDep,
    AITracerDep,
    BudgetServiceDep,
    OptionalOrchestrator,
    OrchestratorDep,
    get_ai_budget_service,
    get_ai_logger_dep,
    get_ai_metrics_dep,
    get_ai_tracer_dep,
    get_orchestrator,
    get_pipeline_dep,
    optional_orchestrator,
    require_orchestrator,
)
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

# Discovery dependencies
from example_service.core.dependencies.discovery import (
    DiscoveryServiceDep,
    OptionalDiscoveryService,
    get_discovery_service_dep,
    optional_discovery_service,
    require_discovery_service,
)

# Email dependencies
from example_service.core.dependencies.email import (
    EmailServiceDep,
    EnhancedEmailServiceDep,
    OptionalEnhancedEmailService,
    TemplateRendererDep,
    get_email_service_dep,
    get_enhanced_email_service_dep,
    get_template_renderer_dep,
    optional_enhanced_email_service,
    require_email_service,
    require_enhanced_email_service,
    require_template_renderer,
)
from example_service.core.dependencies.events import (
    EventPublisherDep,
    get_event_publisher,
)

# Messaging dependencies
from example_service.core.dependencies.messaging import (
    # New Protocol-based API (recommended)
    BusPublisher,
    BusPublisherDep,
    # Legacy API (backward compatibility)
    MessageBroker,
    OptionalMessageBroker,
    RabbitBusPublisher,
    RequiredBusPublisher,
    get_bus_publisher,
    get_message_broker,
    optional_message_broker,
    require_bus_publisher,
    require_message_broker,
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

# Realtime/WebSocket dependencies
from example_service.core.dependencies.realtime import (
    ConnectionManagerDep,
    EventBridgeDep,
    OptionalConnectionManager,
    OptionalEventBridge,
    get_ws_connection_manager,
    get_ws_event_bridge,
    optional_connection_manager,
    optional_event_bridge,
    require_connection_manager,
    require_event_bridge,
)

# Re-export service dependencies
from example_service.core.dependencies.services import (
    HealthService,
    HealthServiceDep,
    get_health_service,
)

# Storage dependencies
from example_service.core.dependencies.storage import (
    OptionalStorage,
    Storage,
    StorageService,
    get_storage_service,
    optional_storage,
    require_storage,
)

# Task dependencies
from example_service.core.dependencies.tasks import (
    OptionalTaskBroker,
    OptionalTaskTracker,
    SchedulerStatusDep,
    TaskBrokerDep,
    TaskTrackerDep,
    get_scheduler_status,
    get_task_broker,
    get_task_tracker,
    optional_task_broker,
    optional_task_tracker,
    require_task_broker,
    require_task_tracker,
)

# Tracing dependencies
from example_service.core.dependencies.tracing import (
    TracerDep,
    add_span_attributes_dep,
    add_span_event_dep,
    get_default_tracer,
    get_tracer_dep,
    tracer_factory,
)
from example_service.infra.cache import get_cache

__all__ = [
    "AILoggerDep",
    "AIMetricsDep",
    "AITracerDep",
    "BudgetServiceDep",
    "BusPublisher",
    "BusPublisherDep",
    "ConnectionManagerDep",
    "DiscoveryServiceDep",
    "EmailServiceDep",
    "EnhancedEmailServiceDep",
    "EventBridgeDep",
    "EventPublisherDep",
    "ExtendedPagination",
    "ExtendedPaginationParams",
    "HealthService",
    "HealthServiceDep",
    "MessageBroker",
    "OptionalConnectionManager",
    "OptionalDiscoveryService",
    "OptionalEnhancedEmailService",
    "OptionalEventBridge",
    "OptionalMessageBroker",
    "OptionalOrchestrator",
    "OptionalStorage",
    "OptionalTaskBroker",
    "OptionalTaskTracker",
    "OrchestratorDep",
    "PaginationParams",
    "RabbitBusPublisher",
    "RateLimited",
    "RequireAuth",
    "RequireBroker",
    "RequireCache",
    "RequireConsul",
    "RequireDatabase",
    "RequireDatabaseAndBroker",
    "RequireDatabaseAndCache",
    "RequireStorage",
    "RequiredBusPublisher",
    "SchedulerStatusDep",
    "SearchPagination",
    "SearchPaginationParams",
    "StandardPagination",
    "Storage",
    "StorageService",
    "StrictRateLimit",
    "TaskBrokerDep",
    "TaskTrackerDep",
    "TemplateRendererDep",
    "TracerDep",
    "UserRateLimit",
    "add_span_attributes_dep",
    "add_span_event_dep",
    "get_ai_budget_service",
    "get_ai_logger_dep",
    "get_ai_metrics_dep",
    "get_ai_tracer_dep",
    "get_bus_publisher",
    "get_cache",
    "get_db_session",
    "get_default_tracer",
    "get_discovery_service_dep",
    "get_email_service_dep",
    "get_enhanced_email_service_dep",
    "get_event_publisher",
    "get_extended_pagination",
    "get_health_service",
    "get_message_broker",
    "get_orchestrator",
    "get_pipeline_dep",
    "get_rate_limiter",
    "get_scheduler_status",
    "get_search_pagination",
    "get_standard_pagination",
    "get_storage_service",
    "get_task_broker",
    "get_task_tracker",
    "get_template_renderer_dep",
    "get_tracer_dep",
    "get_ws_connection_manager",
    "get_ws_event_bridge",
    "optional_connection_manager",
    "optional_discovery_service",
    "optional_enhanced_email_service",
    "optional_event_bridge",
    "optional_message_broker",
    "optional_orchestrator",
    "optional_storage",
    "optional_task_broker",
    "optional_task_tracker",
    "per_api_key_rate_limit",
    "per_user_rate_limit",
    "rate_limit",
    "require_bus_publisher",
    "require_connection_manager",
    "require_discovery_service",
    "require_email_service",
    "require_enhanced_email_service",
    "require_event_bridge",
    "require_message_broker",
    "require_orchestrator",
    "require_services",
    "require_storage",
    "require_task_broker",
    "require_task_tracker",
    "require_template_renderer",
    "tracer_factory",
]
