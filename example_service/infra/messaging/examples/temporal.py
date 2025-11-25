"""Temporal-based Faststream examples.

These examples demonstrate time-based scheduled message processing where tasks
run at regular intervals or specific times. This is useful for:
- Periodic health checks
- Data synchronization
- Cleanup tasks
- Report generation
- Monitoring and alerting

Note: Faststream doesn't natively support cron-like scheduling.
For production scheduling, consider combining with:
- APScheduler
- Celery Beat
- Kubernetes CronJobs
- Or using Taskiq scheduler (see taskiq examples)

This example shows how to implement periodic tasks using asyncio.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from example_service.core.settings import get_rabbit_settings
from example_service.infra.messaging.broker import broker

logger = logging.getLogger(__name__)

# Get RabbitMQ settings
rabbit_settings = get_rabbit_settings()


class HealthCheckEvent(BaseModel):
    """Event for periodic health checks."""

    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    service_name: str = Field(description="Service name")
    status: str = Field(description="Health status")
    checks: dict[str, bool] = Field(description="Component health checks")


class PeriodicTaskEvent(BaseModel):
    """Generic periodic task event."""

    task_name: str = Field(description="Task name")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    data: dict = Field(default_factory=dict, description="Task data")


async def scheduled_health_check() -> None:
    """Run a periodic health check and publish results.

    This function demonstrates a temporal task that runs at regular intervals
    to check the health of various components and publish the results.

    Example usage:
            # In application startup or background task
        asyncio.create_task(start_health_check_scheduler())
    """
    if not rabbit_settings.is_configured or broker is None:
        logger.debug("RabbitMQ not configured, skipping health check publishing")
        return

    logger.info("Running scheduled health check")

    try:
        # Perform health checks
        from example_service.infra.cache import redis_client
        from example_service.infra.database import engine

        checks = {}

        # Database health check
        try:
            async with engine.connect() as conn:
                await conn.execute("SELECT 1")
            checks["database"] = True
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            checks["database"] = False

        # Cache health check
        try:
            if redis_client:
                await redis_client.ping()
            checks["cache"] = True
        except Exception as e:
            logger.error(f"Cache health check failed: {e}")
            checks["cache"] = False

        # RabbitMQ health check
        try:
            if broker and broker.started:
                checks["messaging"] = True
            else:
                checks["messaging"] = False
        except Exception:
            checks["messaging"] = False

        # Determine overall status
        status = "healthy" if all(checks.values()) else "degraded"

        # Create and publish health check event
        event = HealthCheckEvent(
            service_name="example-service",
            status=status,
            checks=checks,
        )

        await broker.publish(
            message=event,
            queue=rabbit_settings.get_prefixed_queue("health-checks"),
        )

        logger.info(
            "Health check completed and published",
            extra={"status": status, "checks": checks},
        )

    except Exception as e:
        logger.exception(f"Failed to run scheduled health check: {e}")


async def schedule_periodic_task(
    task_name: str,
    interval_seconds: int = 60,
    **task_data,
) -> None:
    """Schedule a periodic task to run at regular intervals.

    This is a generic function that demonstrates how to implement
    periodic publishing of events at fixed intervals.

    Args:
        task_name: Name of the task
        interval_seconds: Interval between runs in seconds
        **task_data: Additional task data

    Example:
            # Schedule data sync every 5 minutes
        asyncio.create_task(
            schedule_periodic_task(
                task_name="data_sync",
                interval_seconds=300,
                source="external_api",
                target="database",
            )
        )

        # Schedule cleanup every hour
        asyncio.create_task(
            schedule_periodic_task(
                task_name="cleanup_old_records",
                interval_seconds=3600,
                retention_days=30,
            )
        )
    """
    if not rabbit_settings.is_configured or broker is None:
        logger.warning(f"RabbitMQ not configured, skipping periodic task: {task_name}")
        return

    logger.info(
        "Starting periodic task scheduler",
        extra={"task_name": task_name, "interval_seconds": interval_seconds},
    )

    while True:
        try:
            # Create and publish periodic task event
            event = PeriodicTaskEvent(
                task_name=task_name,
                data=task_data,
            )

            await broker.publish(
                message=event,
                queue=rabbit_settings.get_prefixed_queue("periodic-tasks"),
            )

            logger.info(
                "Periodic task published",
                extra={"task_name": task_name},
            )

        except Exception as e:
            logger.exception(
                "Failed to publish periodic task",
                extra={"task_name": task_name, "error": str(e)},
            )

        # Wait for the next interval
        await asyncio.sleep(interval_seconds)


async def start_health_check_scheduler(interval_seconds: int = 300) -> None:
    """Start the health check scheduler.

    Args:
        interval_seconds: Interval between health checks (default: 5 minutes)

    Example:
            # In application startup (lifespan)
        @asynccontextmanager
        async def lifespan(app: FastAPI):
            # Start health check scheduler
            health_check_task = asyncio.create_task(
                start_health_check_scheduler(interval_seconds=300)
            )

            yield

            # Cancel on shutdown
            health_check_task.cancel()
            try:
                await health_check_task
            except asyncio.CancelledError:
                pass
    """
    logger.info(
        "Starting health check scheduler",
        extra={"interval_seconds": interval_seconds},
    )

    while True:
        await scheduled_health_check()
        await asyncio.sleep(interval_seconds)


async def start_periodic_task_scheduler() -> None:
    """Start all periodic task schedulers.

    This function demonstrates how to start multiple periodic tasks
    concurrently using asyncio.gather.

    Example:
            # In application startup
        asyncio.create_task(start_periodic_task_scheduler())
    """
    logger.info("Starting all periodic task schedulers")

    try:
        await asyncio.gather(
            # Health checks every 5 minutes
            start_health_check_scheduler(interval_seconds=300),
            # Data sync every 15 minutes
            schedule_periodic_task(
                task_name="data_sync",
                interval_seconds=900,
                source="external_api",
            ),
            # Cleanup every hour
            schedule_periodic_task(
                task_name="cleanup_old_records",
                interval_seconds=3600,
                retention_days=30,
            ),
            # Report generation every day
            schedule_periodic_task(
                task_name="generate_daily_report",
                interval_seconds=86400,
                report_type="daily_summary",
            ),
        )
    except asyncio.CancelledError:
        logger.info("Periodic task schedulers cancelled")
    except Exception as e:
        logger.exception(f"Error in periodic task schedulers: {e}")


# Example: How to use this in your FastAPI application
"""
from contextlib import asynccontextmanager
import asyncio
from fastapi import FastAPI

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Start periodic tasks
    scheduler_task = asyncio.create_task(start_periodic_task_scheduler())

    yield

    # Shutdown: Cancel periodic tasks
    scheduler_task.cancel()
    try:
        await scheduler_task
    except asyncio.CancelledError:
        pass

app = FastAPI(lifespan=lifespan)
"""
