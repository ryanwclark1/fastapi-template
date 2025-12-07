"""Taskiq and APScheduler lifespan management."""

from __future__ import annotations

from importlib import import_module
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import ModuleType

from .registry import lifespan_registry

logger = logging.getLogger(__name__)

# Module-level state to track initialized modules
_taskiq_module: ModuleType | None = None
_scheduler_module: ModuleType | None = None


def _load_taskiq_module() -> ModuleType | None:
    """Import Taskiq broker module lazily to avoid partial initialization."""
    try:
        return import_module("example_service.infra.tasks.broker")
    except ImportError:
        logger.warning("Taskiq optional dependencies missing, skipping Taskiq startup")
        return None


def _load_scheduler_module() -> ModuleType | None:
    """Import APScheduler scheduler module lazily."""
    try:
        return import_module("example_service.infra.tasks.scheduler")
    except ImportError:
        logger.warning("APScheduler dependencies missing, skipping scheduler startup")
        return None


async def _initialize_taskiq_and_scheduler(
    rabbit_settings: object, redis_settings: object
) -> tuple[ModuleType | None, ModuleType | None]:
    """Initialize Taskiq broker and APScheduler for background tasks.

    Args:
        rabbit_settings: RabbitMQ settings object with is_configured attribute.
        redis_settings: Redis settings object with is_configured attribute.

    Returns:
        Tuple of (taskiq_module, scheduler_module), either may be None.
    """
    from example_service.core.settings.rabbit import RabbitSettings
    from example_service.core.settings.redis import RedisSettings

    rabbit = (
        RabbitSettings.model_validate(rabbit_settings)
        if not isinstance(rabbit_settings, RabbitSettings)
        else rabbit_settings
    )
    redis = (
        RedisSettings.model_validate(redis_settings)
        if not isinstance(redis_settings, RedisSettings)
        else redis_settings
    )

    # Early return if dependencies not configured
    if not (rabbit.is_configured and redis.is_configured):
        return None, None

    # Load and start Taskiq broker
    taskiq_module = _load_taskiq_module()
    if taskiq_module is None:
        return None, None

    await taskiq_module.start_taskiq()
    if taskiq_module.broker is None:
        logger.warning("Taskiq broker unavailable, skipping task registration")
        return taskiq_module, None

    # Import workers to register them with the broker
    # Note: scheduler is imported by broker.py and loaded via _load_scheduler_module() below
    import example_service.workers.tasks  # noqa: F401

    logger.info("Taskiq broker initialized (use 'taskiq worker' to run tasks)")

    # Initialize APScheduler (depends on Taskiq)
    scheduler_module = _load_scheduler_module()
    if scheduler_module is None:
        logger.warning("APScheduler unavailable, skipping scheduler startup")
        return taskiq_module, None

    scheduler_module.setup_scheduled_jobs()
    await scheduler_module.start_scheduler()
    logger.info("APScheduler started with scheduled jobs")

    return taskiq_module, scheduler_module


@lifespan_registry.register(
    name="tasks",
    startup_order=35,
    requires=["messaging", "cache"],
)
async def startup_tasks(
    rabbit_settings: object,
    redis_settings: object,
    mock_settings: object,
    **kwargs: object,  # noqa: ARG001
) -> None:
    """Initialize Taskiq broker and APScheduler.

    Taskiq uses its own RabbitMQ connection via taskiq-aio-pika.
    This is independent of FastStream.
    Skips initialization in mock mode.

    Args:
        rabbit_settings: RabbitMQ settings
        redis_settings: Redis settings
        mock_settings: Mock mode settings
        **kwargs: Additional settings (ignored)
    """
    from example_service.core.settings.mock import MockModeSettings

    mock = (
        MockModeSettings.model_validate(mock_settings)
        if not isinstance(mock_settings, MockModeSettings)
        else mock_settings
    )

    # Skip Taskiq/APScheduler initialization in mock mode (not needed for UI development)
    if mock.enabled:
        logger.info(
            "Taskiq/APScheduler initialization skipped in mock mode",
            extra={"mock_mode": True, "persona": mock.persona},
        )
        _taskiq_module, _scheduler_module = None, None
        return

    # Initialize Taskiq broker for background tasks (independent of FastStream)
    initialization = await _initialize_taskiq_and_scheduler(
        rabbit_settings, redis_settings
    )
    if initialization is None:
        initialization = (None, None)
    _taskiq_module, _scheduler_module = initialization


@lifespan_registry.register(name="tasks")
async def shutdown_tasks(
    rabbit_settings: object,
    redis_settings: object,
    mock_settings: object,
    **kwargs: object,  # noqa: ARG001
) -> None:
    """Stop Taskiq broker and APScheduler.

    Skips shutdown in mock mode since it wasn't initialized.

    Args:
        rabbit_settings: RabbitMQ settings
        redis_settings: Redis settings
        mock_settings: Mock mode settings
        **kwargs: Additional settings (ignored)
    """
    from example_service.core.settings.mock import MockModeSettings
    from example_service.core.settings.rabbit import RabbitSettings
    from example_service.core.settings.redis import RedisSettings

    mock = (
        MockModeSettings.model_validate(mock_settings)
        if not isinstance(mock_settings, MockModeSettings)
        else mock_settings
    )

    # Skip shutdown in mock mode since it wasn't started
    if mock.enabled:
        return

    rabbit = (
        RabbitSettings.model_validate(rabbit_settings)
        if not isinstance(rabbit_settings, RabbitSettings)
        else rabbit_settings
    )
    redis = (
        RedisSettings.model_validate(redis_settings)
        if not isinstance(redis_settings, RedisSettings)
        else redis_settings
    )

    # Stop APScheduler first (depends on Taskiq for task execution)
    if _scheduler_module is not None:
        await _scheduler_module.stop_scheduler()
        logger.info("APScheduler stopped")

    # Close Taskiq broker (depends on RabbitMQ and Redis)
    if rabbit.is_configured and redis.is_configured and _taskiq_module:
        await _taskiq_module.stop_taskiq()
        logger.info("Taskiq broker closed")
