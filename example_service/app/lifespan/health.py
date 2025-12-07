"""Service availability health monitor lifespan management."""

from __future__ import annotations

import logging

from .registry import lifespan_registry

logger = logging.getLogger(__name__)

# Track if health monitor was started
_health_monitor_started = False


@lifespan_registry.register(
    name="health",
    startup_order=45,
    requires=["database", "cache", "messaging", "storage"],
)
async def startup_health(
    health_settings: object,
    db_settings: object,
    redis_settings: object,
    rabbit_settings: object,
    storage_settings: object,
    **kwargs: object,
) -> None:
    """Initialize service availability health monitor.

    This provides background health checking of external services and
    enables RequireX dependencies to gate endpoints based on service health.

    Args:
        health_settings: Health monitor settings
        db_settings: Database settings
        redis_settings: Redis settings
        rabbit_settings: RabbitMQ settings
        storage_settings: Storage settings
        **kwargs: Additional settings (ignored)
    """
    global _health_monitor_started

    from example_service.core.settings.database import DBSettings
    from example_service.core.settings.health import HealthSettings
    from example_service.core.settings.rabbit import RabbitSettings
    from example_service.core.settings.redis import RedisSettings
    from example_service.core.settings.storage import StorageSettings

    health = (
        HealthSettings.model_validate(health_settings)
        if not isinstance(health_settings, HealthSettings)
        else health_settings
    )
    db = (
        DBSettings.model_validate(db_settings)
        if not isinstance(db_settings, DBSettings)
        else db_settings
    )
    redis = (
        RedisSettings.model_validate(redis_settings)
        if not isinstance(redis_settings, RedisSettings)
        else redis_settings
    )
    rabbit = (
        RabbitSettings.model_validate(rabbit_settings)
        if not isinstance(rabbit_settings, RabbitSettings)
        else rabbit_settings
    )
    storage = (
        StorageSettings.model_validate(storage_settings)
        if not isinstance(storage_settings, StorageSettings)
        else storage_settings
    )

    _health_monitor_started = False
    if health.service_availability_enabled:
        try:
            from example_service.core.services.availability import (
                ServiceName,
                get_service_registry,
            )
            from example_service.core.services.health_monitor import get_health_monitor

            health_monitor = get_health_monitor()

            # Register health check functions for configured services
            # These are async functions that return True if service is healthy

            if db.is_configured:

                async def check_database() -> bool:
                    try:
                        from example_service.infra.database.session import (
                            get_async_engine,
                        )

                        engine = get_async_engine()
                        if engine:
                            async with engine.connect() as conn:
                                await conn.execute(
                                    __import__("sqlalchemy").text("SELECT 1")
                                )
                            return True
                    except Exception:
                        pass
                    return False

                health_monitor.register_health_check(
                    ServiceName.DATABASE, check_database
                )

            if redis.is_configured:

                async def check_cache() -> bool:
                    try:
                        from example_service.infra.cache.redis import get_redis_client

                        client = await get_redis_client()
                        if client:
                            await client.ping()
                            return True
                    except Exception:
                        pass
                    return False

                health_monitor.register_health_check(ServiceName.CACHE, check_cache)

            if rabbit.is_configured:

                async def check_broker() -> bool:
                    try:
                        from example_service.infra.messaging.broker import broker

                        return broker is not None and broker._connection is not None
                    except Exception:
                        pass
                    return False

                health_monitor.register_health_check(ServiceName.BROKER, check_broker)

            if storage.is_configured:

                async def check_storage() -> bool:
                    try:
                        from example_service.infra.storage import get_storage_service

                        storage_service = get_storage_service()
                        return storage_service.is_ready
                    except Exception:
                        pass
                    return False

                health_monitor.register_health_check(ServiceName.STORAGE, check_storage)

            # Start the background health monitor
            await health_monitor.start()
            _health_monitor_started = True
            logger.info(
                "Service availability health monitor started",
                extra={
                    "check_interval": health.service_check_interval,
                    "check_timeout": health.service_check_timeout,
                },
            )

            # Mark services as initially available (first check already ran in start())
            registry = get_service_registry()
            await registry.mark_all_available()

        except Exception as e:
            logger.warning(
                "Failed to start service availability health monitor",
                extra={"error": str(e)},
            )


@lifespan_registry.register(name="health")
async def shutdown_health(**kwargs: object) -> None:
    """Stop service availability health monitor.

    Args:
        **kwargs: Settings (ignored)
    """
    global _health_monitor_started

    # Stop service availability health monitor first (no external dependencies)
    if _health_monitor_started:
        try:
            from example_service.core.services.health_monitor import stop_health_monitor

            await stop_health_monitor()
            logger.info("Service availability health monitor stopped")
        except Exception as e:
            logger.warning(
                "Error stopping service availability health monitor",
                extra={"error": str(e)},
            )


def get_health_monitor_started() -> bool:
    """Get whether health monitor was successfully started.

    Returns:
        True if health monitor is started, False otherwise.
    """
    return _health_monitor_started
