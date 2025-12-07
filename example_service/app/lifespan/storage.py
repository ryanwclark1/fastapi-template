"""Storage service lifespan management."""

from __future__ import annotations

import logging

from .registry import lifespan_registry

logger = logging.getLogger(__name__)


@lifespan_registry.register(
    name="storage",
    startup_order=20,
    requires=["core"],
)
async def startup_storage(
    storage_settings: object,
    **kwargs: object,
) -> None:
    """Initialize storage service.

    Args:
        storage_settings: Storage settings
        **kwargs: Additional settings (ignored)
    """
    from example_service.core.settings.storage import StorageSettings

    settings = (
        StorageSettings.model_validate(storage_settings)
        if not isinstance(storage_settings, StorageSettings)
        else storage_settings
    )

    if settings.is_configured:
        try:
            from example_service.infra.storage import get_storage_service

            storage_service = get_storage_service()
            await storage_service.startup()
            logger.info(
                "Storage service initialized",
                extra={
                    "bucket": settings.bucket,
                    "endpoint": settings.endpoint,
                    "health_checks_enabled": settings.health_check_enabled,
                },
            )
        except Exception as e:
            if settings.startup_require_storage:
                logger.error(
                    "Storage service required but unavailable, failing startup",
                    extra={"error": str(e)},
                )
                raise
            logger.warning(
                "Storage service unavailable, continuing in degraded mode",
                extra={"error": str(e)},
            )


@lifespan_registry.register(name="storage")
async def shutdown_storage(
    storage_settings: object,
    **kwargs: object,
) -> None:
    """Shutdown storage service.

    Args:
        storage_settings: Storage settings
        **kwargs: Additional settings (ignored)
    """
    from example_service.core.settings.storage import StorageSettings

    settings = (
        StorageSettings.model_validate(storage_settings)
        if not isinstance(storage_settings, StorageSettings)
        else storage_settings
    )

    if settings.is_configured:
        try:
            from example_service.infra.storage import get_storage_service

            storage_service = get_storage_service()
            if storage_service.is_ready:
                await storage_service.shutdown()
                logger.info("Storage service shutdown complete")
        except Exception as e:
            logger.warning(
                "Error during storage service shutdown",
                extra={"error": str(e)},
            )
