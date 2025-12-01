"""SQLAlchemy models for task execution storage.

This module provides the TaskExecution model for storing task results
and execution history in PostgreSQL when using the postgres backend.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, LargeBinary, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from example_service.core.database import Base


class TaskExecution(Base):
    """Task execution record for PostgreSQL storage.

    Stores both Taskiq result backend data and execution tracking data,
    providing a unified storage model for task management.

    This model supports:
    - Full Taskiq result backend compatibility (serialized_result)
    - Rich execution metadata for querying and analytics
    - JSONB columns for flexible return values and arguments
    - Composite indexes for common query patterns

    Example:
            # Query recent failed tasks
        stmt = (
            select(TaskExecution)
            .where(TaskExecution.status == "failure")
            .order_by(TaskExecution.created_at.desc())
            .limit(10)
        )

        # Search by task name with date range
        stmt = (
            select(TaskExecution)
            .where(TaskExecution.task_name == "backup_database")
            .where(TaskExecution.created_at >= start_date)
        )
    """

    __tablename__ = "task_executions"

    # ──────────────────────────────────────────────────────────────
    # Primary key
    # ──────────────────────────────────────────────────────────────

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
        comment="Auto-incrementing primary key",
    )

    # ──────────────────────────────────────────────────────────────
    # Task identification
    # ──────────────────────────────────────────────────────────────

    task_id: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
        comment="Unique task execution ID from Taskiq",
    )

    task_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
        comment="Task function name (e.g., 'backup_database')",
    )

    # ──────────────────────────────────────────────────────────────
    # Execution status
    # ──────────────────────────────────────────────────────────────

    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="pending",
        index=True,
        comment="Status: pending, running, success, failure, cancelled",
    )

    # ──────────────────────────────────────────────────────────────
    # Worker information
    # ──────────────────────────────────────────────────────────────

    worker_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
        comment="Worker that executed/is executing the task",
    )

    queue_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Queue the task was sent to",
    )

    # ──────────────────────────────────────────────────────────────
    # Timing
    # ──────────────────────────────────────────────────────────────

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
        comment="When the task was enqueued",
    )

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When execution started",
    )

    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When execution finished",
    )

    duration_ms: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Execution duration in milliseconds",
    )

    # ──────────────────────────────────────────────────────────────
    # Result data
    # ──────────────────────────────────────────────────────────────

    return_value: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="Task return value (JSON serialized)",
    )

    # ──────────────────────────────────────────────────────────────
    # Error information
    # ──────────────────────────────────────────────────────────────

    error_type: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
        comment="Exception class name if failed",
    )

    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Error message if failed",
    )

    error_traceback: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Full traceback if failed",
    )

    # ──────────────────────────────────────────────────────────────
    # Task metadata
    # ──────────────────────────────────────────────────────────────

    task_args: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="Task positional arguments (JSON)",
    )

    task_kwargs: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="Task keyword arguments (JSON)",
    )

    labels: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="Task labels/metadata for categorization",
    )

    # ──────────────────────────────────────────────────────────────
    # Retry information
    # ──────────────────────────────────────────────────────────────

    retry_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        comment="Number of retry attempts",
    )

    max_retries: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Maximum retry attempts configured",
    )

    # ──────────────────────────────────────────────────────────────
    # Progress tracking
    # ──────────────────────────────────────────────────────────────

    progress: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="Task progress data for long-running tasks",
    )

    # ──────────────────────────────────────────────────────────────
    # Taskiq result backend compatibility
    # ──────────────────────────────────────────────────────────────

    serialized_result: Mapped[bytes | None] = mapped_column(
        LargeBinary,
        nullable=True,
        comment="Full serialized TaskiqResult for backend compatibility",
    )

    # ──────────────────────────────────────────────────────────────
    # Composite indexes for common query patterns
    # ──────────────────────────────────────────────────────────────

    __table_args__ = (
        # Status + created_at: "Show me recent failed tasks"
        Index("ix_task_exec_status_created", "status", "created_at"),
        # Task name + status: "Show me all running backup_database tasks"
        Index("ix_task_exec_name_status", "task_name", "status"),
        # Worker + status: "What tasks is worker-1 running?"
        Index("ix_task_exec_worker_status", "worker_id", "status"),
        # Created_at desc for recent tasks queries
        Index("ix_task_exec_created_desc", "created_at", postgresql_using="btree"),
    )

    def __repr__(self) -> str:
        """Return string representation."""
        return (
            f"<TaskExecution(id={self.id}, task_id='{self.task_id}', "
            f"task_name='{self.task_name}', status='{self.status}')>"
        )
