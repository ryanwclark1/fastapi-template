"""PostgreSQL-based result backend for Taskiq task result storage.

This module provides a PostgreSQL backend implementation that stores task
results in a database table instead of Redis. This is useful when:
- You need persistent task history beyond Redis TTL
- You want to query task results with SQL
- You don't have Redis in your infrastructure
- You need ACID guarantees for task results

The backend implements Taskiq's AsyncResultBackend interface for
drop-in compatibility with the task queue system.
"""

from __future__ import annotations

import json
import logging
import traceback
from datetime import UTC, datetime
from typing import Any, TypeVar

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from taskiq import AsyncResultBackend
from taskiq.abc.serializer import TaskiqSerializer
from taskiq.compat import model_dump, model_validate
from taskiq.depends.progress_tracker import TaskProgress
from taskiq.result import TaskiqResult
from taskiq.serializers import PickleSerializer

from example_service.infra.results.exceptions import ResultIsMissingError
from example_service.infra.results.models import TaskExecution

logger = logging.getLogger(__name__)

_ReturnType = TypeVar("_ReturnType")


class PostgresAsyncResultBackend(AsyncResultBackend[_ReturnType]):
    """Async result backend based on PostgreSQL.

    This backend stores task results in a PostgreSQL database, providing:
    - Persistent storage with configurable retention
    - SQL-queryable task history and results
    - JSONB storage for flexible return values
    - Full Taskiq result backend compatibility

    The backend stores both the serialized TaskiqResult (for Taskiq compatibility)
    and extracted fields (for easy querying and display).

    Example:
            from example_service.infra.results import PostgresAsyncResultBackend

        backend = PostgresAsyncResultBackend(
            dsn="postgresql+asyncpg://user:pass@localhost/db",
            keep_results=True,
            result_ttl_seconds=86400,  # 24 hours
        )

        # Use with Taskiq broker
        broker = AioPikaBroker(...).with_result_backend(backend)
    """

    def __init__(
        self,
        dsn: str,
        *,
        keep_results: bool = True,
        result_ttl_seconds: int | None = None,
        serializer: TaskiqSerializer | None = None,
        pool_size: int = 5,
        max_overflow: int = 10,
        pool_pre_ping: bool = True,
    ) -> None:
        """Construct a new PostgreSQL result backend.

        Args:
            dsn: PostgreSQL connection DSN (e.g., "postgresql+asyncpg://...").
            keep_results: If True, results remain after reading. Default: True.
            result_ttl_seconds: Optional TTL for results. Used for cleanup scheduling.
            serializer: Custom serializer for results. Defaults to PickleSerializer.
            pool_size: SQLAlchemy connection pool size. Default: 5.
            max_overflow: Maximum overflow connections. Default: 10.
            pool_pre_ping: Enable connection health checks. Default: True.
        """
        self.dsn = dsn
        self.keep_results = keep_results
        self.result_ttl_seconds = result_ttl_seconds
        self.serializer = serializer or PickleSerializer()

        self._pool_size = pool_size
        self._max_overflow = max_overflow
        self._pool_pre_ping = pool_pre_ping

        self._engine = None
        self._session_factory: async_sessionmaker[AsyncSession] | None = None

    async def startup(self) -> None:
        """Initialize database connection pool.

        Called automatically by Taskiq when the broker starts.
        """
        logger.info("Starting PostgreSQL result backend")

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

        logger.info("PostgreSQL result backend started successfully")

    async def shutdown(self) -> None:
        """Close database connection pool.

        Called automatically by Taskiq when the broker shuts down.
        """
        logger.info("Shutting down PostgreSQL result backend")

        if self._engine:
            await self._engine.dispose()
            self._engine = None
            self._session_factory = None

        logger.info("PostgreSQL result backend shut down successfully")
        await super().shutdown()

    def _get_session(self) -> AsyncSession:
        """Get a new database session.

        Returns:
            AsyncSession instance.

        Raises:
            RuntimeError: If backend not started (startup() not called).
        """
        if self._session_factory is None:
            raise RuntimeError(
                "PostgresAsyncResultBackend not started. Call startup() first."
            )
        return self._session_factory()

    async def set_result(
        self,
        task_id: str,
        result: TaskiqResult[_ReturnType],
    ) -> None:
        """Store task result in PostgreSQL.

        This method stores both the serialized TaskiqResult (for Taskiq
        compatibility) and extracted fields (for querying).

        Args:
            task_id: ID of the task.
            result: TaskiqResult instance containing the task's outcome.
        """
        now = datetime.now(UTC)
        serialized = self.serializer.dumpb(model_dump(result))

        # Extract return value for JSONB storage
        return_value = None
        if result.return_value is not None:
            try:
                # Ensure it's JSON-serializable
                return_value = json.loads(json.dumps(result.return_value, default=str))
            except (TypeError, ValueError):
                return_value = {"raw": str(result.return_value)}

        # Extract error info if present
        error_type = None
        error_message = None
        error_tb = None
        if result.is_err and result.error:
            error_type = type(result.error).__name__
            error_message = str(result.error)
            error_tb = "".join(traceback.format_exception(type(result.error), result.error, result.error.__traceback__))

        async with self._get_session() as session:
            async with session.begin():
                # Check if record exists (created during on_task_start)
                stmt = select(TaskExecution).where(TaskExecution.task_id == task_id)
                existing = (await session.execute(stmt)).scalar_one_or_none()

                if existing:
                    # Update existing record with result
                    existing.status = "failure" if result.is_err else "success"
                    existing.finished_at = now
                    existing.return_value = return_value
                    existing.serialized_result = serialized
                    existing.error_type = error_type
                    existing.error_message = error_message
                    existing.error_traceback = error_tb

                    # Calculate duration if we have started_at
                    if existing.started_at:
                        existing.duration_ms = int(
                            (now - existing.started_at).total_seconds() * 1000
                        )

                    logger.debug(
                        "Updated task result",
                        extra={"task_id": task_id, "status": existing.status},
                    )
                else:
                    # Create new record (task started outside tracking)
                    execution = TaskExecution(
                        task_id=task_id,
                        task_name=result.labels.get("task_name", "unknown") if result.labels else "unknown",
                        status="failure" if result.is_err else "success",
                        created_at=now,
                        finished_at=now,
                        return_value=return_value,
                        serialized_result=serialized,
                        error_type=error_type,
                        error_message=error_message,
                        error_traceback=error_tb,
                        labels=result.labels,
                    )
                    session.add(execution)

                    logger.debug(
                        "Created task result",
                        extra={"task_id": task_id, "status": execution.status},
                    )

    async def is_result_ready(self, task_id: str) -> bool:
        """Check if a task result is available.

        Args:
            task_id: ID of the task.

        Returns:
            True if the result exists and task is complete, False otherwise.
        """
        async with self._get_session() as session:
            stmt = select(TaskExecution.status).where(
                TaskExecution.task_id == task_id,
                TaskExecution.status.in_(["success", "failure"]),
            )
            result = (await session.execute(stmt)).scalar_one_or_none()
            return result is not None

    async def get_result(
        self,
        task_id: str,
        with_logs: bool = False,
    ) -> TaskiqResult[_ReturnType]:
        """Retrieve a task result from PostgreSQL.

        Args:
            task_id: Task's unique identifier.
            with_logs: If True, includes task execution logs in the result.

        Returns:
            The task's result.

        Raises:
            ResultIsMissingError: If no result exists for the given task_id.
        """
        async with self._get_session() as session:
            stmt = select(TaskExecution).where(TaskExecution.task_id == task_id)
            execution = (await session.execute(stmt)).scalar_one_or_none()

            if execution is None or execution.serialized_result is None:
                raise ResultIsMissingError()

            # Deserialize the stored result
            taskiq_result = model_validate(
                TaskiqResult[_ReturnType],
                self.serializer.loadb(execution.serialized_result),
            )

            if not with_logs:
                taskiq_result.log = None

            # Delete if not keeping results
            if not self.keep_results:
                await session.delete(execution)
                await session.commit()

            return taskiq_result

    async def set_progress(
        self,
        task_id: str,
        progress: TaskProgress[_ReturnType],
    ) -> None:
        """Store task progress in PostgreSQL.

        Args:
            task_id: ID of the task.
            progress: TaskProgress instance with current task progress.
        """
        async with self._get_session() as session:
            async with session.begin():
                stmt = (
                    update(TaskExecution)
                    .where(TaskExecution.task_id == task_id)
                    .values(progress=model_dump(progress))
                )
                await session.execute(stmt)

    async def get_progress(
        self,
        task_id: str,
    ) -> TaskProgress[_ReturnType] | None:
        """Retrieve task progress from PostgreSQL.

        Args:
            task_id: Task's unique identifier.

        Returns:
            TaskProgress instance if progress data exists, None otherwise.
        """
        async with self._get_session() as session:
            stmt = select(TaskExecution.progress).where(
                TaskExecution.task_id == task_id
            )
            progress_data = (await session.execute(stmt)).scalar_one_or_none()

            if progress_data is None:
                return None

            return model_validate(TaskProgress[_ReturnType], progress_data)

    # ──────────────────────────────────────────────────────────────
    # Extended methods for task management
    # ──────────────────────────────────────────────────────────────

    async def create_task_record(
        self,
        task_id: str,
        task_name: str,
        *,
        worker_id: str | None = None,
        queue_name: str | None = None,
        task_args: tuple[Any, ...] | None = None,
        task_kwargs: dict[str, Any] | None = None,
        labels: dict[str, Any] | None = None,
    ) -> None:
        """Create a task execution record when a task starts.

        This is called by the tracking middleware to record task start.

        Args:
            task_id: Unique task identifier.
            task_name: Name of the task function.
            worker_id: Optional worker identifier.
            queue_name: Optional queue name.
            task_args: Positional arguments passed to the task.
            task_kwargs: Keyword arguments passed to the task.
            labels: Task labels/metadata.
        """
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

        async with self._get_session() as session:
            async with session.begin():
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
            "Created task record",
            extra={"task_id": task_id, "task_name": task_name},
        )

    async def update_task_status(
        self,
        task_id: str,
        status: str,
        *,
        error: Exception | None = None,
        duration_ms: int | None = None,
    ) -> None:
        """Update task execution status.

        Args:
            task_id: Task identifier.
            status: New status (success, failure, cancelled).
            error: Exception if task failed.
            duration_ms: Execution duration in milliseconds.
        """
        now = datetime.now(UTC)

        values: dict[str, Any] = {
            "status": status,
            "finished_at": now,
        }

        if duration_ms is not None:
            values["duration_ms"] = duration_ms

        if error is not None:
            values["error_type"] = type(error).__name__
            values["error_message"] = str(error)
            values["error_traceback"] = "".join(
                traceback.format_exception(type(error), error, error.__traceback__)
            )

        async with self._get_session() as session:
            async with session.begin():
                stmt = (
                    update(TaskExecution)
                    .where(TaskExecution.task_id == task_id)
                    .values(**values)
                )
                await session.execute(stmt)

        logger.debug(
            "Updated task status",
            extra={"task_id": task_id, "status": status},
        )
