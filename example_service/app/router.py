"""Router registry and setup."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from example_service.core.settings import (
    get_app_settings,
    get_graphql_settings,
    get_websocket_settings,
)
from example_service.features.admin.email import router as admin_email_router
from example_service.features.ai.agents.config_router import (
    router as agent_config_router,
)
from example_service.features.ai.pipeline.router import router as ai_pipeline_router
from example_service.features.audit.router import router as audit_router
from example_service.features.datatransfer.router import router as datatransfer_router
from example_service.features.email.router import router as email_router
from example_service.features.featureflags.router import router as featureflags_router
from example_service.features.files.router import router as files_router
from example_service.features.health.router import router as health_router
from example_service.features.metrics.router import router as metrics_router
from example_service.features.notifications.router import (
    admin_router as notifications_admin_router,
)
from example_service.features.notifications.router import router as notifications_router
from example_service.features.reminders.router import router as reminders_router
from example_service.features.search.router import router as search_router
from example_service.features.storage.router import router as storage_router
from example_service.features.tags.router import reminder_tags_router
from example_service.features.tags.router import router as tags_router
from example_service.features.tasks.router import router as tasks_router
from example_service.features.webhooks.router import router as webhooks_router
from example_service.infra.messaging.broker import get_router as get_rabbit_router

if TYPE_CHECKING:
    from fastapi import FastAPI

    from example_service.core.settings.app import AppSettings
    from example_service.core.settings.graphql import GraphQLSettings
    from example_service.core.settings.websocket import WebSocketSettings

logger = logging.getLogger(__name__)


def setup_routers(
    app: FastAPI,
    app_settings: AppSettings | None = None,
    graphql_settings: GraphQLSettings | None = None,
    websocket_settings: WebSocketSettings | None = None,
) -> None:
    """Register all feature routers with the application.

    Args:
        app: FastAPI application instance.
        app_settings: Optional application settings override for API prefixes
            and feature flags.
        graphql_settings: Optional override controlling GraphQL availability.
        websocket_settings: Optional override for realtime/WebSocket behavior.
    """
    app_settings = app_settings or get_app_settings()
    graphql_settings = graphql_settings or get_graphql_settings()
    websocket_settings = websocket_settings or get_websocket_settings()

    api_prefix = app_settings.api_prefix

    # Include metrics endpoint (no prefix - accessible at /metrics)
    app.include_router(metrics_router, tags=["observability"])

    # Include feature routers
    app.include_router(reminders_router, prefix=api_prefix, tags=["reminders"])
    app.include_router(notifications_router, prefix=api_prefix, tags=["notifications"])
    app.include_router(notifications_admin_router, prefix=api_prefix, tags=["notifications-admin"])
    app.include_router(tags_router, prefix=api_prefix, tags=["tags"])
    app.include_router(
        reminder_tags_router, prefix=api_prefix, tags=["reminders", "tags"],
    )
    app.include_router(health_router, prefix=api_prefix, tags=["health"])
    app.include_router(files_router, prefix=api_prefix, tags=["files"])
    app.include_router(webhooks_router, prefix=api_prefix, tags=["webhooks"])
    app.include_router(tasks_router, prefix=api_prefix, tags=["tasks"])
    app.include_router(audit_router, prefix=api_prefix, tags=["audit"])
    app.include_router(datatransfer_router, prefix=api_prefix, tags=["data-transfer"])
    app.include_router(featureflags_router, prefix=api_prefix, tags=["feature-flags"])
    app.include_router(search_router, prefix=api_prefix, tags=["search"])
    app.include_router(storage_router, prefix=api_prefix, tags=["storage"])

    # Email configuration management (Phase 4)
    app.include_router(email_router, prefix=api_prefix, tags=["email-configuration"])
    app.include_router(admin_email_router, prefix=api_prefix, tags=["admin-email"])
    logger.info(
        "Email configuration endpoints registered at %s/email and %s/admin/email",
        api_prefix,
        api_prefix,
    )

    # AI pipeline endpoints (capability-based API with observability)
    app.include_router(ai_pipeline_router, prefix=api_prefix, tags=["AI Pipelines"])
    logger.info("AI pipeline router registered at %s/ai/pipelines", api_prefix)

    # AI agent configuration endpoints (manage agent templates and customization)
    app.include_router(agent_config_router, prefix=api_prefix, tags=["AI Agent Configuration"])
    logger.info("AI agent configuration router registered at %s/agents", api_prefix)

    # Include GraphQL endpoint if enabled (follows same pattern as /docs, /redoc, /asyncapi)
    if graphql_settings.enabled:
        graphql_prefix = graphql_settings.path or "/graphql"
        try:
            # Check if strawberry is available before importing
            import strawberry  # noqa: F401

            from example_service.features.graphql.router import router as graphql_router

            if graphql_router is not None:
                app.include_router(
                    graphql_router, prefix=graphql_prefix, tags=["graphql"],
                )
                playground_status = (
                    "enabled" if graphql_settings.playground_enabled else "disabled"
                )
                logger.info(
                    "GraphQL endpoint enabled at %s (playground: %s)",
                    graphql_prefix,
                    playground_status,
                )
        except ImportError as exc:  # pragma: no cover - optional dependency
            logger.warning(
                "GraphQL endpoint disabled (strawberry not available): %s", exc,
            )

    # Include WebSocket realtime router if enabled
    if websocket_settings.enabled:
        from example_service.features.realtime.router import router as realtime_router

        app.include_router(realtime_router, prefix=api_prefix, tags=["realtime"])
        logger.info(
            "WebSocket realtime router included - endpoints at %s/ws", api_prefix,
        )

    # Include RabbitMQ/FastStream router for messaging + AsyncAPI docs
    # Note: RabbitRouter automatically includes AsyncAPI docs at /asyncapi
    rabbit_router = get_rabbit_router()
    rabbit_enabled = False
    if rabbit_router is not None:
        # Import handlers to register them with the router
        import example_service.infra.messaging.handlers  # noqa: F401

        # Include the router (handles lifespan + auto-includes AsyncAPI docs)
        app.include_router(rabbit_router, tags=["messaging"])
        rabbit_enabled = True
        logger.info("RabbitMQ router included - AsyncAPI docs at /asyncapi")

    # Log conditional feature status summary
    logger.info(
        "Router setup complete - conditional features status",
        extra={
            "graphql_enabled": graphql_settings.enabled,
            "websocket_enabled": websocket_settings.enabled,
            "rabbitmq_enabled": rabbit_enabled,
        },
    )
