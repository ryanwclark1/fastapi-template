"""Database connection lifespan management."""

from __future__ import annotations

import logging

from example_service.infra.database.session import close_database, init_database
from example_service.infra.metrics.prometheus import (
    database_pool_max_overflow,
    database_pool_size,
)

from .registry import lifespan_registry

logger = logging.getLogger(__name__)


@lifespan_registry.register(
    name="database",
    startup_order=10,
    requires=["core"],
)
async def startup_database(
    db_settings: object,
    mock_settings: object,
    **kwargs: object,
) -> None:
    """Initialize database connection.

    Skips initialization in mock mode.

    Args:
        db_settings: Database settings
        mock_settings: Mock mode settings
        **kwargs: Additional settings (ignored)
    """
    from example_service.core.settings.database import DBSettings
    from example_service.core.settings.mock import MockModeSettings

    db = (
        DBSettings.model_validate(db_settings)
        if not isinstance(db_settings, DBSettings)
        else db_settings
    )
    mock = (
        MockModeSettings.model_validate(mock_settings)
        if not isinstance(mock_settings, MockModeSettings)
        else mock_settings
    )

    # Skip database initialization in mock mode (not needed for UI development)
    if db.is_configured and not mock.enabled:
        try:
            await init_database()
            logger.info("Database connection initialized")

            # Set database pool configuration gauges for monitoring
            # These are static values set once at startup
            database_pool_size.set(db.pool_size)
            database_pool_max_overflow.set(db.max_overflow)
            logger.debug(
                "Database pool metrics initialized",
                extra={
                    "pool_size": db.pool_size,
                    "max_overflow": db.max_overflow,
                    "pool_timeout": db.pool_timeout,
                    "pool_recycle": db.pool_recycle,
                },
            )
        except Exception as e:
            if db.startup_require_db:
                logger.exception(
                    "Database required but unavailable, failing startup",
                    extra={"error": str(e), "startup_require_db": True},
                )
                raise
            logger.warning(
                "Database unavailable, continuing in degraded mode",
                extra={"error": str(e), "startup_require_db": False},
            )
    elif mock.enabled:
        logger.info(
            "Database initialization skipped in mock mode",
            extra={"mock_mode": True, "persona": mock.persona},
        )


@lifespan_registry.register(name="database")
async def shutdown_database(
    db_settings: object,
    mock_settings: object,
    **kwargs: object,
) -> None:
    """Close database connection.

    Skips shutdown in mock mode since it wasn't initialized.

    Args:
        db_settings: Database settings
        mock_settings: Mock mode settings
        **kwargs: Additional settings (ignored)
    """
    from example_service.core.settings.database import DBSettings
    from example_service.core.settings.mock import MockModeSettings

    db = (
        DBSettings.model_validate(db_settings)
        if not isinstance(db_settings, DBSettings)
        else db_settings
    )
    mock = (
        MockModeSettings.model_validate(mock_settings)
        if not isinstance(mock_settings, MockModeSettings)
        else mock_settings
    )

    # Close database connection (skip in mock mode since it wasn't initialized)
    if db.is_configured and not mock.enabled:
        await close_database()
        logger.info("Database connection closed")
