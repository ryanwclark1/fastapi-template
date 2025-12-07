"""Task execution tracker lifespan management."""

from __future__ import annotations

import logging

from example_service.infra.tasks.tracking import start_tracker, stop_tracker

from .registry import lifespan_registry

logger = logging.getLogger(__name__)

# Track if tracker was started
_tracker_started = False


@lifespan_registry.register(
    name="task_tracking",
    startup_order=28,
    requires=["database", "cache"],
)
async def startup_task_tracking(
    task_settings: object,
    redis_settings: object,
    db_settings: object,
    mock_settings: object,
    **kwargs: object,  # noqa: ARG001
) -> None:
    """Initialize task execution tracker.

    Supports both Redis and PostgreSQL backends based on TASK_RESULT_BACKEND setting.
    Skips initialization in mock mode.

    Args:
        task_settings: Task settings
        redis_settings: Redis settings
        db_settings: Database settings
        mock_settings: Mock mode settings
        **kwargs: Additional settings (ignored)
    """
    global _tracker_started

    from example_service.core.settings.database import DBSettings
    from example_service.core.settings.mock import MockModeSettings
    from example_service.core.settings.redis import RedisSettings
    from example_service.core.settings.tasks import TaskSettings

    task = (
        TaskSettings.model_validate(task_settings)
        if not isinstance(task_settings, TaskSettings)
        else task_settings
    )
    redis = (
        RedisSettings.model_validate(redis_settings)
        if not isinstance(redis_settings, RedisSettings)
        else redis_settings
    )
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

    _tracker_started = False
    # Skip task tracking in mock mode (not needed for UI development)
    if task.tracking_enabled and not mock.enabled:
        # Check if the required backend is configured
        can_start_tracker = (task.is_redis_backend and redis.is_configured) or (
            task.is_postgres_backend and db.is_configured
        )
        if can_start_tracker:
            try:
                await start_tracker()
                _tracker_started = True
                logger.info(
                    "Task execution tracker initialized",
                    extra={"backend": task.result_backend},
                )

                # Register task tracker health provider
                try:
                    from example_service.features.health.providers import (
                        TaskTrackerHealthProvider,
                    )
                    from example_service.features.health.service import (
                        get_health_aggregator,
                    )

                    aggregator = get_health_aggregator()
                    if aggregator:
                        aggregator.add_provider(TaskTrackerHealthProvider())
                        logger.info("Task tracker health provider registered")
                except Exception as health_err:
                    logger.warning(
                        "Failed to register task tracker health provider",
                        extra={"error": str(health_err)},
                    )
            except Exception as e:
                logger.warning(
                    "Failed to start task execution tracker",
                    extra={"error": str(e), "backend": task.result_backend},
                )
        else:
            logger.warning(
                "Task tracking enabled but required backend not configured",
                extra={
                    "backend": task.result_backend,
                    "redis_configured": redis.is_configured,
                    "db_configured": db.is_configured,
                },
            )
    elif mock.enabled:
        logger.info(
            "Task execution tracker initialization skipped in mock mode",
            extra={"mock_mode": True, "persona": mock.persona},
        )


@lifespan_registry.register(name="task_tracking")
async def shutdown_task_tracking(
    task_settings: object,  # noqa: ARG001
    mock_settings: object,
    **kwargs: object,  # noqa: ARG001
) -> None:
    """Stop task execution tracker.

    Skips shutdown in mock mode since it wasn't started.

    Args:
        task_settings: Task settings
        mock_settings: Mock mode settings
        **kwargs: Additional settings (ignored)
    """
    global _tracker_started

    from example_service.core.settings.mock import MockModeSettings

    mock = (
        MockModeSettings.model_validate(mock_settings)
        if not isinstance(mock_settings, MockModeSettings)
        else mock_settings
    )

    # Close task execution tracker (before Redis since Redis tracker depends on Redis)
    # Skip in mock mode since it wasn't started
    if _tracker_started and not mock.enabled:
        await stop_tracker()
        logger.info("Task execution tracker closed")


def get_tracker_started() -> bool:
    """Get whether task tracker was successfully started.

    Returns:
        True if task tracker is started, False otherwise.
    """
    return _tracker_started
