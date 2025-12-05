"""Taskiq broker configuration for background task processing.

This module provides two separate Taskiq integrations:

1. **Background Tasks (taskiq-aio-pika)**
   - For executing async background tasks
   - Uses RabbitMQ directly for task distribution
   - Run worker: `taskiq worker example_service.infra.tasks.broker:broker`

2. **Scheduled Message Publishing (taskiq-faststream)**
   - For publishing messages on a schedule (cron-like)
   - Wraps FastStream broker to publish messages at scheduled times
   - Run scheduler: `taskiq scheduler example_service.infra.tasks.broker:stream_scheduler`

Architecture Decision: Two-Tier Task System
============================================

We use APScheduler + Taskiq instead of Taskiq's native scheduler because:

1. **Runtime Control**: APScheduler allows pausing/resuming/rescheduling jobs
   without code changes or restarts. This is critical for production operations.

2. **Sophisticated Scheduling**: APScheduler provides:
   - Job coalescing (multiple missed runs → single execution)
   - Misfire handling with configurable grace periods
   - Per-job timezone support
   - Multiple triggers per job
   - Job persistence across restarts

3. **Monitoring & Observability**: APScheduler exposes job status, next run times,
   and execution history through a rich API for operational visibility.

4. **Separation of Concerns**:
   - APScheduler: "WHEN to run" (scheduling logic, cron triggers)
   - Taskiq: "HOW to run" (execution, retries, results, distributed processing)
   - RabbitMQ: "WHERE to run" (task distribution, queue management)

5. **Battle-Tested Maturity**: APScheduler has been production-proven since 2009
   with extensive enterprise deployments.

Alternative Approach (Not Used):
---------------------------------
Taskiq's native scheduler is simpler but less flexible:

```python
@broker.task(schedule=[{"cron": "0 2 * * *"}])
async def my_task():
    pass
```

This works well for:
- Small applications with few scheduled tasks
- Static schedules that rarely change
- Simple deployments without operational complexity

We chose APScheduler because this template targets production use cases
requiring operational flexibility and enterprise-grade scheduling.

RabbitMQ vs Redis for Message Broker
=====================================

We use RabbitMQ (taskiq-aio-pika) instead of Redis because:

1. **Message Durability**: RabbitMQ persists messages to disk, surviving restarts
2. **Delivery Guarantees**: At-least-once delivery with acknowledgments
3. **Backpressure**: Automatic flow control prevents overwhelming slow consumers
4. **High Availability**: Built-in clustering, mirroring, and failover
5. **Dead Letter Exchanges**: Failed messages automatically routed to DLX for analysis
6. **Priority Queues**: Native support for task prioritization
7. **Enterprise Features**: SSL/TLS, fine-grained permissions, monitoring

Redis is faster (lower latency) but lacks these enterprise features.
For high-throughput, low-latency scenarios, consider Redis with careful
attention to persistence configuration (AOF, snapshots).

Result Backend Choice
=====================

We support both Redis and PostgreSQL result backends:

**Redis** (default):
- Ultra-fast result retrieval (~1ms latency)
- Best for high-throughput systems (>1000 tasks/sec)
- In-memory storage with optional persistence
- Automatic TTL-based cleanup

**PostgreSQL**:
- Queryable task history with full SQL capabilities
- Persistent storage for audit trails
- Better for analytics and long-term debugging
- No additional infrastructure if you already use PostgreSQL

Configure via: TASK_RESULT_BACKEND=redis|postgres

Middleware Stack
================

Middleware order is critical! Each middleware wraps the next:

1. SimpleRetryMiddleware (outermost) - Must be first to wrap entire execution
2. MetricsMiddleware - Records metrics for all attempts including retries
3. TracingMiddleware - Creates OpenTelemetry spans for distributed tracing
4. TrackingMiddleware (innermost) - Stores final execution state

Changing this order can break retry logic or metrics accuracy.

Task Discovery
==============

Tasks are registered by importing their modules at the bottom of this file.
The worker process imports this module:

    taskiq worker example_service.infra.tasks.broker:broker

So all imports here are executed, registering tasks with the broker.
If you add new task modules, import them at the bottom of this file.

FastStream Integration
======================

The optional FastStream integration allows scheduled message publishing:
- stream_scheduler publishes messages to FastStream broker on a schedule
- Useful for event-driven architectures where scheduled events trigger workflows
- Example: publish "daily_report_due" event at 8 AM, consumed by multiple services

This is separate from the main Taskiq broker and is optional.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from example_service.infra.logging.config import setup_logging
from example_service.infra.results import RedisAsyncResultBackend

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from taskiq_aio_pika import AioPikaBroker as AioPikaBrokerType
else:
    AioPikaBrokerType = Any

# Import taskiq-aio-pika for background tasks
try:
    from taskiq_aio_pika import AioPikaBroker
except ImportError:
    AioPikaBroker = None  # type: ignore[misc,assignment]

# Import taskiq-faststream for scheduled message publishing
try:
    from taskiq.schedule_sources import LabelScheduleSource
    from taskiq_faststream import BrokerWrapper, StreamScheduler
except ImportError:
    BrokerWrapper = None  # type: ignore[misc,assignment]
    StreamScheduler = None  # type: ignore[misc,assignment]
    LabelScheduleSource = None  # type: ignore[misc,assignment]

from example_service.core.settings import (
    get_db_settings,
    get_rabbit_settings,
    get_redis_settings,
    get_task_settings,
)

logger = logging.getLogger(__name__)

# Get settings from modular configuration
redis_settings = get_redis_settings()
rabbit_settings = get_rabbit_settings()
task_settings = get_task_settings()
setup_logging()

# =============================================================================
# Background Task Broker (taskiq-aio-pika)
# =============================================================================
# This broker is for executing background tasks asynchronously.
# Tasks are defined with @broker.task() decorator.
# Run worker: taskiq worker example_service.infra.tasks.broker:broker

broker: AioPikaBrokerType | None = None


def _create_result_backend() -> Any:
    """Create the appropriate result backend based on settings.

    Returns:
        Result backend instance (Redis or Postgres).
    """
    if task_settings.is_postgres_backend:
        from example_service.infra.results import PostgresAsyncResultBackend

        db_settings = get_db_settings()
        logger.info(
            "Using PostgreSQL result backend for tasks",
            extra={"retention_hours": task_settings.tracking_retention_hours},
        )
        return PostgresAsyncResultBackend(
            dsn=db_settings.get_sqlalchemy_url(),
            keep_results=True,
            result_ttl_seconds=task_settings.tracking_retention_seconds,
        )
    else:
        logger.info(
            "Using Redis result backend for tasks",
            extra={"ttl_seconds": task_settings.redis_result_ttl_seconds},
        )
        return RedisAsyncResultBackend(
            redis_url=redis_settings.get_url(),
            result_ex_time=task_settings.redis_result_ttl_seconds,
            prefix_str=task_settings.redis_key_prefix,
        )


def _can_create_broker() -> bool:
    """Check if broker can be created based on configuration."""
    if AioPikaBroker is None:
        logger.warning("taskiq-aio-pika not installed - background tasks disabled")
        return False

    if not rabbit_settings.is_configured:
        logger.warning("RabbitMQ not configured - background tasks disabled")
        return False

    # For Redis backend, we need Redis configured
    if task_settings.is_redis_backend and not redis_settings.is_configured:
        logger.warning(
            "Redis not configured but TASK_RESULT_BACKEND=redis - background tasks disabled"
        )
        return False

    # For Postgres backend, we need database configured
    if task_settings.is_postgres_backend:
        db_settings = get_db_settings()
        if not db_settings.is_configured:
            logger.warning(
                "PostgreSQL not configured but TASK_RESULT_BACKEND=postgres - background tasks disabled"
            )
            return False

    return True


if _can_create_broker():
    from taskiq.middlewares import SimpleRetryMiddleware

    from example_service.infra.tasks.middleware import (
        MetricsMiddleware,
        TracingMiddleware,
        TrackingMiddleware,
    )

    result_backend = _create_result_backend()

    # Middleware order matters:
    # 1. SimpleRetryMiddleware - handles retry_on_error=True on tasks (must be first)
    # 2. MetricsMiddleware - records Prometheus metrics (uses existing FastAPI registry)
    # 3. TracingMiddleware - creates OpenTelemetry spans for distributed tracing
    # 4. TrackingMiddleware - records task history in Redis/PostgreSQL
    broker = (
        AioPikaBroker(
            url=rabbit_settings.get_url(),
            queue_name=rabbit_settings.get_prefixed_queue("taskiq-tasks"),
            declare_exchange=True,
            declare_queues=True,
        )
        .with_result_backend(result_backend)
        .with_middlewares(
            SimpleRetryMiddleware(),
            MetricsMiddleware(),  # Uses existing Prometheus registry - no separate server
            TracingMiddleware(),
            TrackingMiddleware(),
        )
    )

    logger.info(
        "Taskiq background task broker configured",
        extra={
            "queue": rabbit_settings.get_prefixed_queue("taskiq-tasks"),
            "result_backend": task_settings.result_backend,
            "middlewares": ["SimpleRetryMiddleware", "MetricsMiddleware", "TracingMiddleware", "TrackingMiddleware"],
        },
    )


# =============================================================================
# Scheduled Message Publisher (taskiq-faststream)
# =============================================================================
# This wraps the FastStream broker for scheduled message publishing.
# Messages are defined with stream_broker.task(message=..., schedule=[...])
# Run scheduler: taskiq scheduler example_service.infra.tasks.broker:stream_scheduler

stream_broker: Any = None
stream_scheduler: Any = None

if BrokerWrapper is not None and StreamScheduler is not None and LabelScheduleSource is not None:
    # Import FastStream broker to wrap it
    from example_service.infra.messaging.broker import broker as faststream_broker

    if faststream_broker is not None and rabbit_settings.is_configured:
        stream_broker = BrokerWrapper(faststream_broker)
        stream_scheduler = StreamScheduler(
            broker=stream_broker,
            sources=[LabelScheduleSource(stream_broker)],
        )

        logger.info("Taskiq scheduled message publisher configured")
    else:
        logger.warning("FastStream broker not available - scheduled publishing disabled")
else:
    if BrokerWrapper is None:
        logger.debug("taskiq-faststream not installed - scheduled publishing disabled")


async def get_broker() -> AsyncIterator[AioPikaBrokerType | None]:
    """Get the Taskiq background task broker instance.

    This is a dependency that can be used in FastAPI endpoints
    to access the broker for scheduling background tasks.

    Yields:
        Taskiq broker instance.

    Example:
            from example_service.workers.tasks import example_task

        @router.post("/schedule")
        async def schedule_task():
            task = await example_task.kiq(data="test")
            return {"task_id": task.task_id}
    """
    yield broker


async def start_taskiq() -> None:
    """Start the Taskiq broker.

    This should be called during application startup in the lifespan context.
    It initializes the connection to RabbitMQ and the result backend.

    Note: This only initializes the broker for ENQUEUING tasks from the FastAPI app.
    To actually EXECUTE tasks, you need to run a separate worker process:
        taskiq worker example_service.infra.tasks.broker:broker

    Raises:
        ConnectionError: If unable to connect to RabbitMQ or result backend.
    """
    if broker is None:
        logger.warning("Taskiq broker not configured, skipping startup")
        return

    logger.info("Starting Taskiq broker")

    try:
        await broker.startup()
        logger.info("Taskiq broker started successfully")
    except Exception as e:
        logger.exception("Failed to start Taskiq broker", extra={"error": str(e)})
        raise


async def stop_taskiq() -> None:
    """Stop the Taskiq broker.

    This should be called during application shutdown in the lifespan context.
    It gracefully closes connections to RabbitMQ and the result backend.
    """
    if broker is None:
        logger.debug("Taskiq broker not configured, skipping shutdown")
        return

    logger.info("Stopping Taskiq broker")

    try:
        await broker.shutdown()
        logger.info("Taskiq broker stopped successfully")
    except Exception as e:
        logger.exception("Error stopping Taskiq broker", extra={"error": str(e)})


# =============================================================================
# Task Module Imports
# =============================================================================
# Import all task modules when broker is loaded to ensure tasks are registered.
# This is critical for the worker to discover all tasks.
# The worker imports: taskiq worker example_service.infra.tasks.broker:broker
# So importing here ensures all tasks are available to the worker.

if broker is not None:
    # Import worker task modules to register them with the broker
    # Import scheduler for scheduled jobs
    import example_service.infra.tasks.scheduler
    import example_service.workers.analytics.tasks
    import example_service.workers.backup.tasks
    import example_service.workers.cache.tasks
    import example_service.workers.cleanup.tasks
    import example_service.workers.export.tasks
    import example_service.workers.files.tasks
    import example_service.workers.notifications.tasks
    import example_service.workers.reports.tasks
    import example_service.workers.tasks
    import example_service.workers.webhooks.tasks  # noqa: F401

    logger.debug("All task modules imported and registered with broker")
