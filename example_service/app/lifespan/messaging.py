"""RabbitMQ/FastStream broker lifespan management."""

from __future__ import annotations

import logging

from example_service.infra.messaging.broker import start_broker, stop_broker

from .registry import lifespan_registry

logger = logging.getLogger(__name__)


@lifespan_registry.register(
    name="messaging",
    startup_order=25,
    requires=["core"],
)
async def startup_messaging(
    rabbit_settings: object,
    **kwargs: object,
) -> None:
    """Initialize RabbitMQ/FastStream broker.

    Note: RabbitRouter automatically connects when included in FastAPI app.
    We call start_broker() here with timeout protection to ensure connection
    is established (or fails fast) before continuing with startup.

    Args:
        rabbit_settings: RabbitMQ settings
        **kwargs: Additional settings (ignored)
    """
    from example_service.core.settings.rabbit import RabbitSettings

    settings = (
        RabbitSettings.model_validate(rabbit_settings)
        if not isinstance(rabbit_settings, RabbitSettings)
        else rabbit_settings
    )

    if settings.is_configured:
        try:
            await start_broker()
            logger.info("RabbitMQ/FastStream broker initialized")
        except Exception as e:
            if settings.startup_require_rabbit:
                logger.error(
                    "RabbitMQ required but unavailable, failing startup",
                    extra={"error": str(e), "startup_require_rabbit": True},
                )
                raise
            logger.warning(
                "RabbitMQ unavailable, continuing in degraded mode",
                extra={"error": str(e), "startup_require_rabbit": False},
            )


@lifespan_registry.register(name="messaging")
async def shutdown_messaging(
    rabbit_settings: object,
    **kwargs: object,
) -> None:
    """Close RabbitMQ broker.

    Args:
        rabbit_settings: RabbitMQ settings
        **kwargs: Additional settings (ignored)
    """
    from example_service.core.settings.rabbit import RabbitSettings

    settings = (
        RabbitSettings.model_validate(rabbit_settings)
        if not isinstance(rabbit_settings, RabbitSettings)
        else rabbit_settings
    )

    if settings.is_configured:
        await stop_broker()
        logger.info("RabbitMQ broker closed")
