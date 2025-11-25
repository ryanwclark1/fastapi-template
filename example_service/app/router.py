"""Router registry and setup."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from example_service.core.settings import get_app_settings
from example_service.features.admin.router import router as admin_router
from example_service.features.health.router import router as health_router
from example_service.features.metrics.router import router as metrics_router
from example_service.features.reminders.router import router as reminders_router
from example_service.infra.messaging.broker import get_router as get_rabbit_router

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)


def setup_routers(app: FastAPI) -> None:
    """Register all feature routers with the application.

    Args:
        app: FastAPI application instance.
    """
    settings = get_app_settings()
    api_prefix = settings.api_prefix

    # Include metrics endpoint (no prefix - accessible at /metrics)
    app.include_router(metrics_router, tags=["observability"])

    # Include feature routers
    app.include_router(reminders_router, prefix=api_prefix, tags=["reminders"])
    app.include_router(health_router, prefix=api_prefix, tags=["health"])
    app.include_router(admin_router, prefix=api_prefix, tags=["Admin"])

    # Include RabbitMQ/FastStream router for messaging + AsyncAPI docs
    # Note: RabbitRouter automatically includes AsyncAPI docs at /asyncapi
    rabbit_router = get_rabbit_router()
    if rabbit_router is not None:
        # Import handlers to register them with the router
        import example_service.infra.messaging.handlers  # noqa: F401

        # Include the router (handles lifespan + auto-includes AsyncAPI docs)
        app.include_router(rabbit_router, tags=["messaging"])
        logger.info("RabbitMQ router included - AsyncAPI docs at /asyncapi")
