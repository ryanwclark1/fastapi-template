"""PostgreSQL-based task execution tracker.

This module provides a PostgreSQL implementation of the task tracker interface,
storing task execution data persistently in the database.
"""

from __future__ import annotations

import json
import logging
import traceback
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from example_service.infra.results.models import TaskExecution
from example_service.infra.tasks.tracking.base import BaseTaskTracker

logger = logging.getLogger(__name__)


class PostgresTaskTracker(BaseTaskTracker):
    """Task execution tracker using PostgreSQL storage.

    This tracker stores task execution records in PostgreSQL, providing:
    - Persistent storage with SQL-queryable history
    - JSONB columns for flexible return values and arguments
    - Full-featured filtering with SQL WHERE clauses
    - Automatic integration with the TaskExecution model

    Example:
            tracker = PostgresTaskTracker(
            dsn="postgresql+asyncpg://user:pass@localhost/db",
        )
        await tracker.connect()

        # Record task start
        await tracker.on_task_start("task-123", "backup_database")

        # Get task history with filters
        history = await tracker.get_task_history(
            limit=100,
            status="failure",
            task_name="backup_database",
        )
    """

    def __init__(
        self,
        dsn: str,
        *,
        pool_size: int = 5,
        max_overflow: int = 10,
        pool_pre_ping: bool = True,
    ) -> None:
        """Initialize PostgreSQL task tracker.

        Args:
            dsn: PostgreSQL connection DSN.
            pool_size: SQLAlchemy connection pool size.
            max_overflow: Maximum overflow connections.
            pool_pre_ping: Enable connection health checks.
        """
        self.dsn = dsn
        self._pool_size = pool_size
        self._max_overflow = max_overflow
        self._pool_pre_ping = pool_pre_ping

        self._engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker[AsyncSession] | None = None

    async def connect(self) -> None:
        """Establish connection to PostgreSQL."""
        logger.info("Connecting to PostgreSQL for task tracking")

        try:
            self._engine = create_async_engine(
                self.dsn,
                pool_size=self._pool_size,
                max_overflow=self._max_overflow,
                pool_pre_ping=self._pool_pre_ping,
            )

            self._session_factory = async_sessionmaker(
                self._engine,
                class_=AsyncSession,
                expire_on_commit=False,
            )

            # Test connection
            async with self._session_factory() as session:
                await session.execute(select(1))

            logger.info("Task tracking PostgreSQL connection established")
        except Exception as e:
            logger.exception(
                "Failed to connect to PostgreSQL for task tracking",
                extra={"error": str(e)},
            )
            raise

    async def disconnect(self) -> None:
        """Close PostgreSQL connection."""
        logger.info("Disconnecting task tracking PostgreSQL")

        if self._engine:
            await self._engine.dispose()
            self._engine = None
            self._session_factory = None

        logger.info("Task tracking PostgreSQL connection closed")

    @property
    def is_connected(self) -> bool:
        """Check if connected to PostgreSQL."""
        return self._session_factory is not None

    def _get_session(self) -> AsyncSession:
        """Get a new database session."""
        if self._session_factory is None:
            raise RuntimeError("Task tracker not connected. Call connect() first.")
        return self._session_factory()

    async def on_task_start(
        self,
        task_id: str,
        task_name: str,
        worker_id: str | None = None,
        queue_name: str | None = None,
        task_args: tuple[Any, ...] | None = None,
        task_kwargs: dict[str, Any] | None = None,
        labels: dict[str, Any] | None = None,
    ) -> None:
        """Record task start event."""
        if not self.is_connected:
            return

        now = datetime.now(UTC)

        # Serialize args for JSON storage
        args_json = None
        if task_args:
            try:
                args_json = json.loads(json.dumps(list(task_args), default=str))
            except (TypeError, ValueError):
                args_json = {"raw": str(task_args)}

        kwargs_json = None
        if task_kwargs:
            try:
                kwargs_json = json.loads(json.dumps(task_kwargs, default=str))
            except (TypeError, ValueError):
                kwargs_json = {"raw": str(task_kwargs)}

        try:
            async with self._get_session() as session, session.begin():
                execution = TaskExecution(
                    task_id=task_id,
                    task_name=task_name,
                    status="running",
                    worker_id=worker_id,
                    queue_name=queue_name,
                    created_at=now,
                    started_at=now,
                    task_args=args_json,
                    task_kwargs=kwargs_json,
                    labels=labels,
                )
                session.add(execution)

            logger.debug(
                "Task started",
                extra={"task_id": task_id, "task_name": task_name},
            )
        except Exception as e:
            logger.warning(
                "Failed to record task start",
                extra={"task_id": task_id, "error": str(e)},
            )

    async def on_task_finish(
        self,
        task_id: str,
        status: str,
        return_value: Any | None,
        error: Exception | None,
        duration_ms: int,
    ) -> None:
        """Record task completion event."""
        if not self.is_connected:
            return

        now = datetime.now(UTC)

        # Serialize return value for JSON storage
        return_value_json = None
        if return_value is not None:
            try:
                return_value_json = json.loads(json.dumps(return_value, default=str))
            except (TypeError, ValueError):
                return_value_json = {"raw": str(return_value)}

        # Prepare error data
        error_type = None
        error_message = None
        error_tb = None
        if error is not None:
            error_type = type(error).__name__
            error_message = str(error)
            error_tb = "".join(traceback.format_exception(type(error), error, error.__traceback__))

        try:
            async with self._get_session() as session, session.begin():
                stmt = (
                    update(TaskExecution)
                    .where(TaskExecution.task_id == task_id)
                    .values(
                        status=status,
                        finished_at=now,
                        duration_ms=duration_ms,
                        return_value=return_value_json,
                        error_type=error_type,
                        error_message=error_message,
                        error_traceback=error_tb,
                    )
                )
                await session.execute(stmt)

            logger.debug(
                "Task finished",
                extra={
                    "task_id": task_id,
                    "status": status,
                    "duration_ms": duration_ms,
                },
            )
        except Exception as e:
            logger.warning(
                "Failed to record task finish",
                extra={"task_id": task_id, "error": str(e)},
            )

    async def get_running_tasks(self) -> list[dict[str, Any]]:
        """Get all currently running tasks."""
        if not self.is_connected:
            return []

        try:
            async with self._get_session() as session:
                stmt = (
                    select(TaskExecution)
                    .where(TaskExecution.status == "running")
                    .order_by(TaskExecution.started_at.desc())
                )
                result = await session.execute(stmt)
                executions = result.scalars().all()

                now = datetime.now(UTC)
                tasks = []
                for execution in executions:
                    running_for_ms = 0
                    if execution.started_at:
                        running_for_ms = int((now - execution.started_at).total_seconds() * 1000)

                    tasks.append(
                        {
                            "task_id": execution.task_id,
                            "task_name": execution.task_name,
                            "started_at": execution.started_at.isoformat()
                            if execution.started_at
                            else "",
                            "running_for_ms": running_for_ms,
                            "worker_id": execution.worker_id,
                        }
                    )

                return tasks
        except Exception as e:
            logger.warning("Failed to get running tasks", extra={"error": str(e)})
            return []

    def _build_history_conditions(
        self,
        *,
        task_name: str | None = None,
        status: str | None = None,
        worker_id: str | None = None,
        error_type: str | None = None,
        created_after: str | None = None,
        created_before: str | None = None,
        min_duration_ms: int | None = None,
        max_duration_ms: int | None = None,
    ) -> list[Any]:
        """Build SQLAlchemy filter conditions for task history queries."""
        conditions = []

        if task_name:
            conditions.append(TaskExecution.task_name == task_name)
        if status:
            conditions.append(TaskExecution.status == status)
        if worker_id:
            conditions.append(TaskExecution.worker_id == worker_id)
        if error_type:
            conditions.append(TaskExecution.error_type == error_type)
        if created_after:
            after_dt = datetime.fromisoformat(created_after.replace("Z", "+00:00"))
            conditions.append(TaskExecution.created_at >= after_dt)
        if created_before:
            before_dt = datetime.fromisoformat(created_before.replace("Z", "+00:00"))
            conditions.append(TaskExecution.created_at <= before_dt)
        if min_duration_ms is not None:
            conditions.append(TaskExecution.duration_ms >= min_duration_ms)
        if max_duration_ms is not None:
            conditions.append(TaskExecution.duration_ms <= max_duration_ms)

        return conditions

    async def get_task_history(
        self,
        limit: int = 100,
        offset: int = 0,
        task_name: str | None = None,
        status: str | None = None,
        worker_id: str | None = None,
        error_type: str | None = None,
        created_after: str | None = None,
        created_before: str | None = None,
        min_duration_ms: int | None = None,
        max_duration_ms: int | None = None,
    ) -> list[dict[str, Any]]:
        """Get recent task executions with optional filters."""
        if not self.is_connected:
            return []

        try:
            async with self._get_session() as session:
                stmt = select(TaskExecution)

                conditions = self._build_history_conditions(
                    task_name=task_name,
                    status=status,
                    worker_id=worker_id,
                    error_type=error_type,
                    created_after=created_after,
                    created_before=created_before,
                    min_duration_ms=min_duration_ms,
                    max_duration_ms=max_duration_ms,
                )

                if conditions:
                    stmt = stmt.where(and_(*conditions))

                stmt = stmt.order_by(TaskExecution.created_at.desc())
                stmt = stmt.offset(offset).limit(limit)

                result = await session.execute(stmt)
                executions = result.scalars().all()

                return [
                    {
                        "task_id": e.task_id,
                        "task_name": e.task_name,
                        "status": e.status,
                        "started_at": e.started_at.isoformat() if e.started_at else None,
                        "finished_at": e.finished_at.isoformat() if e.finished_at else None,
                        "duration_ms": e.duration_ms,
                        "return_value": e.return_value,
                        "error_message": e.error_message,
                        "error_type": e.error_type,
                        "worker_id": e.worker_id,
                    }
                    for e in executions
                ]
        except Exception as e:
            logger.warning("Failed to get task history", extra={"error": str(e)})
            return []

    async def count_task_history(
        self,
        task_name: str | None = None,
        status: str | None = None,
        worker_id: str | None = None,
        error_type: str | None = None,
        created_after: str | None = None,
        created_before: str | None = None,
        min_duration_ms: int | None = None,
        max_duration_ms: int | None = None,
    ) -> int:
        """Count task executions matching the given filters."""
        if not self.is_connected:
            return 0

        try:
            async with self._get_session() as session:
                stmt = select(func.count()).select_from(TaskExecution)

                conditions = self._build_history_conditions(
                    task_name=task_name,
                    status=status,
                    worker_id=worker_id,
                    error_type=error_type,
                    created_after=created_after,
                    created_before=created_before,
                    min_duration_ms=min_duration_ms,
                    max_duration_ms=max_duration_ms,
                )

                if conditions:
                    stmt = stmt.where(and_(*conditions))

                result = await session.execute(stmt)
                count = result.scalar_one() or 0
                return int(count)
        except Exception as e:
            logger.warning("Failed to count task history", extra={"error": str(e)})
            return 0

    async def get_task_details(self, task_id: str) -> dict[str, Any] | None:
        """Get full details for a specific task execution."""
        if not self.is_connected:
            return None

        try:
            async with self._get_session() as session:
                stmt = select(TaskExecution).where(TaskExecution.task_id == task_id)
                result = await session.execute(stmt)
                execution = result.scalar_one_or_none()

                if not execution:
                    return None

                return {
                    "task_id": execution.task_id,
                    "task_name": execution.task_name,
                    "status": execution.status,
                    "started_at": execution.started_at.isoformat()
                    if execution.started_at
                    else None,
                    "finished_at": execution.finished_at.isoformat()
                    if execution.finished_at
                    else None,
                    "duration_ms": execution.duration_ms,
                    "return_value": execution.return_value,
                    "error_message": execution.error_message,
                    "error_type": execution.error_type,
                    "error_traceback": execution.error_traceback,
                    "retry_count": execution.retry_count,
                    "worker_id": execution.worker_id,
                    "queue_name": execution.queue_name,
                    "task_args": execution.task_args,
                    "task_kwargs": execution.task_kwargs,
                    "labels": execution.labels,
                    "progress": execution.progress,
                }
        except Exception as e:
            logger.warning(
                "Failed to get task details",
                extra={"task_id": task_id, "error": str(e)},
            )
            return None

    async def get_stats(self, hours: int = 24) -> dict[str, Any]:
        """Get summary statistics for task executions."""
        if not self.is_connected:
            return {
                "total_count": 0,
                "success_count": 0,
                "failure_count": 0,
                "running_count": 0,
                "cancelled_count": 0,
                "by_task_name": {},
                "avg_duration_ms": None,
            }

        try:
            async with self._get_session() as session:
                cutoff = datetime.now(UTC) - timedelta(hours=hours)

                # Count by status
                status_counts = {}
                for status in ["running", "success", "failure", "cancelled"]:
                    stmt = (
                        select(func.count())
                        .select_from(TaskExecution)
                        .where(
                            and_(
                                TaskExecution.status == status,
                                TaskExecution.created_at >= cutoff,
                            )
                        )
                    )
                    result = await session.execute(stmt)
                    status_counts[status] = result.scalar() or 0

                # Total count
                stmt = (
                    select(func.count())
                    .select_from(TaskExecution)
                    .where(TaskExecution.created_at >= cutoff)
                )
                result = await session.execute(stmt)
                total_count = result.scalar() or 0

                # Count by task name
                name_counts_stmt = (
                    select(TaskExecution.task_name, func.count())
                    .where(TaskExecution.created_at >= cutoff)
                    .group_by(TaskExecution.task_name)
                )
                result = await session.execute(name_counts_stmt)
                by_task_name = {row[0]: row[1] for row in result.all()}

                # Average duration (successful tasks only)
                stmt = select(func.avg(TaskExecution.duration_ms)).where(
                    and_(
                        TaskExecution.status == "success",
                        TaskExecution.duration_ms.isnot(None),
                        TaskExecution.created_at >= cutoff,
                    )
                )
                result = await session.execute(stmt)
                avg_duration = result.scalar()

                return {
                    "total_count": total_count,
                    "success_count": status_counts.get("success", 0),
                    "failure_count": status_counts.get("failure", 0),
                    "running_count": status_counts.get("running", 0),
                    "cancelled_count": status_counts.get("cancelled", 0),
                    "by_task_name": by_task_name,
                    "avg_duration_ms": float(avg_duration) if avg_duration else None,
                }
        except Exception as e:
            logger.warning("Failed to get task stats", extra={"error": str(e)})
            return {
                "total_count": 0,
                "success_count": 0,
                "failure_count": 0,
                "running_count": 0,
                "cancelled_count": 0,
                "by_task_name": {},
                "avg_duration_ms": None,
            }

    async def cancel_task(self, task_id: str) -> bool:
        """Mark a task as cancelled."""
        if not self.is_connected:
            return False

        try:
            async with self._get_session() as session:
                async with session.begin():
                    # Check current status
                    current_status_stmt = select(TaskExecution.status).where(
                        TaskExecution.task_id == task_id
                    )
                    result = await session.execute(current_status_stmt)
                    current_status = result.scalar_one_or_none()

                    if current_status is None:
                        return False

                    if current_status not in ("pending", "running"):
                        return False  # Can only cancel pending/running tasks

                    # Update to cancelled
                    update_stmt = (
                        update(TaskExecution)
                        .where(TaskExecution.task_id == task_id)
                        .values(
                            status="cancelled",
                            finished_at=datetime.now(UTC),
                        )
                    )
                    await session.execute(update_stmt)

                return True
        except Exception as e:
            logger.warning(
                "Failed to cancel task",
                extra={"task_id": task_id, "error": str(e)},
            )
            return False
