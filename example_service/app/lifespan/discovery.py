"""Consul service discovery lifespan management."""

from __future__ import annotations

import logging

from example_service.infra.discovery import start_discovery, stop_discovery

from .registry import lifespan_registry

logger = logging.getLogger(__name__)


@lifespan_registry.register(
    name="discovery",
    startup_order=5,
    requires=["core"],
)
async def startup_discovery(
    consul_settings: object,
    **kwargs: object,
) -> None:
    """Initialize Consul service discovery.

    Optional service that never blocks startup.

    Args:
        consul_settings: Consul settings
        **kwargs: Additional settings (ignored)
    """
    from example_service.core.settings.consul import ConsulSettings

    settings = (
        ConsulSettings.model_validate(consul_settings)
        if not isinstance(consul_settings, ConsulSettings)
        else consul_settings
    )

    if settings.is_configured:
        discovery_started = await start_discovery()
        if discovery_started:
            logger.info(
                "Consul service discovery started",
                extra={"consul_url": settings.base_url},
            )
        else:
            logger.warning(
                "Consul service discovery failed to start, continuing without it",
                extra={"consul_url": settings.base_url},
            )


@lifespan_registry.register(name="discovery")
async def shutdown_discovery(
    consul_settings: object,
    **kwargs: object,
) -> None:
    """Stop Consul service discovery.

    Args:
        consul_settings: Consul settings
        **kwargs: Additional settings (ignored)
    """
    from example_service.core.settings.consul import ConsulSettings

    settings = (
        ConsulSettings.model_validate(consul_settings)
        if not isinstance(consul_settings, ConsulSettings)
        else consul_settings
    )

    if settings.is_configured:
        await stop_discovery()
        logger.info("Consul service discovery stopped")
