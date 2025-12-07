"""Event outbox processor lifespan management."""

from __future__ import annotations

import logging

from example_service.infra.events.outbox.processor import (
    start_outbox_processor,
    stop_outbox_processor,
)

from .registry import lifespan_registry

logger = logging.getLogger(__name__)


@lifespan_registry.register(
    name="outbox",
    startup_order=30,
    requires=["database", "messaging"],
)
async def startup_outbox(
    db_settings: object,
    rabbit_settings: object,
    **kwargs: object,
) -> None:
    """Initialize event outbox processor.

    Requires both database and RabbitMQ to be available.

    Args:
        db_settings: Database settings
        rabbit_settings: RabbitMQ settings
        **kwargs: Additional settings (ignored)
    """
    from example_service.core.settings.database import DBSettings
    from example_service.core.settings.rabbit import RabbitSettings

    db = (
        DBSettings.model_validate(db_settings)
        if not isinstance(db_settings, DBSettings)
        else db_settings
    )
    rabbit = (
        RabbitSettings.model_validate(rabbit_settings)
        if not isinstance(rabbit_settings, RabbitSettings)
        else rabbit_settings
    )

    # Initialize outbox processor for reliable event publishing
    # Requires both database and RabbitMQ to be available
    if db.is_configured and rabbit.is_configured:
        try:
            await start_outbox_processor()
            logger.info("Event outbox processor started")
        except Exception as e:
            logger.warning(
                "Failed to start outbox processor, events will not be published",
                extra={"error": str(e)},
            )


@lifespan_registry.register(name="outbox")
async def shutdown_outbox(
    db_settings: object,
    rabbit_settings: object,
    **kwargs: object,
) -> None:
    """Stop event outbox processor.

    Args:
        db_settings: Database settings
        rabbit_settings: RabbitMQ settings
        **kwargs: Additional settings (ignored)
    """
    from example_service.core.settings.database import DBSettings
    from example_service.core.settings.rabbit import RabbitSettings

    db = (
        DBSettings.model_validate(db_settings)
        if not isinstance(db_settings, DBSettings)
        else db_settings
    )
    rabbit = (
        RabbitSettings.model_validate(rabbit_settings)
        if not isinstance(rabbit_settings, RabbitSettings)
        else rabbit_settings
    )

    # Stop outbox processor (before closing RabbitMQ broker)
    if db.is_configured and rabbit.is_configured:
        await stop_outbox_processor()
        logger.info("Event outbox processor stopped")
