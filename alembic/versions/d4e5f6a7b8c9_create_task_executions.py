"""create_task_executions

Revision ID: d4e5f6a7b8c9
Revises: 0fae80f19092
Create Date: 2025-12-01 12:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9"
down_revision: str | None = "0fae80f19092"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create task_executions table for task management backend."""
    # Create task_executions table
    op.create_table(
        "task_executions",
        # Primary key
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        # Task identification
        sa.Column("task_id", sa.String(length=255), nullable=False),
        sa.Column("task_name", sa.String(length=255), nullable=False),
        # Execution status
        sa.Column("status", sa.String(length=50), nullable=False, server_default="pending"),
        # Worker information
        sa.Column("worker_id", sa.String(length=255), nullable=True),
        sa.Column("queue_name", sa.String(length=255), nullable=True),
        # Timing
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        # Result data (JSONB for flexible querying)
        sa.Column("return_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        # Error information
        sa.Column("error_type", sa.String(length=255), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("error_traceback", sa.Text(), nullable=True),
        # Task metadata (JSONB)
        sa.Column("task_args", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("task_kwargs", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("labels", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        # Retry information
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_retries", sa.Integer(), nullable=True),
        # Progress tracking (JSONB)
        sa.Column("progress", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        # Taskiq result backend compatibility
        sa.Column("serialized_result", sa.LargeBinary(), nullable=True),
        # Primary key constraint
        sa.PrimaryKeyConstraint("id", name=op.f("pk_task_executions")),
        # Unique constraint on task_id
        sa.UniqueConstraint("task_id", name=op.f("uq_task_executions_task_id")),
    )

    # Individual column indexes for common lookups
    op.create_index("ix_task_executions_task_id", "task_executions", ["task_id"], unique=True)
    op.create_index("ix_task_executions_task_name", "task_executions", ["task_name"], unique=False)
    op.create_index("ix_task_executions_status", "task_executions", ["status"], unique=False)
    op.create_index("ix_task_executions_worker_id", "task_executions", ["worker_id"], unique=False)
    op.create_index("ix_task_executions_created_at", "task_executions", ["created_at"], unique=False)
    op.create_index("ix_task_executions_error_type", "task_executions", ["error_type"], unique=False)

    # Composite indexes for common query patterns
    op.create_index(
        "ix_task_exec_status_created",
        "task_executions",
        ["status", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_task_exec_name_status",
        "task_executions",
        ["task_name", "status"],
        unique=False,
    )
    op.create_index(
        "ix_task_exec_worker_status",
        "task_executions",
        ["worker_id", "status"],
        unique=False,
    )

    # Partial index for running tasks (efficient lookup)
    op.execute("""
        CREATE INDEX ix_task_exec_running
        ON task_executions (task_id, started_at)
        WHERE status = 'running'
    """)

    # Index for cleanup queries (old completed/failed tasks)
    op.execute("""
        CREATE INDEX ix_task_exec_cleanup
        ON task_executions (created_at)
        WHERE status IN ('success', 'failure', 'cancelled')
    """)


def downgrade() -> None:
    """Drop task_executions table."""
    # Drop partial indexes first
    op.execute("DROP INDEX IF EXISTS ix_task_exec_cleanup")
    op.execute("DROP INDEX IF EXISTS ix_task_exec_running")

    # Drop composite indexes
    op.drop_index("ix_task_exec_worker_status", table_name="task_executions")
    op.drop_index("ix_task_exec_name_status", table_name="task_executions")
    op.drop_index("ix_task_exec_status_created", table_name="task_executions")

    # Drop individual column indexes
    op.drop_index("ix_task_executions_error_type", table_name="task_executions")
    op.drop_index("ix_task_executions_created_at", table_name="task_executions")
    op.drop_index("ix_task_executions_worker_id", table_name="task_executions")
    op.drop_index("ix_task_executions_status", table_name="task_executions")
    op.drop_index("ix_task_executions_task_name", table_name="task_executions")
    op.drop_index("ix_task_executions_task_id", table_name="task_executions")

    # Drop table
    op.drop_table("task_executions")
