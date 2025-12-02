"""create_audit_logs

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2025-12-01 14:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5f6a7b8c9d0"
down_revision: str | None = "d4e5f6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create audit_logs table for centralized audit logging."""
    # Create audit_logs table
    op.create_table(
        "audit_logs",
        # Primary key (UUID v7 for time-ordering)
        sa.Column("id", sa.Uuid(), nullable=False),
        # Timestamp (when the action occurred)
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        # Action type (create, read, update, delete, etc.)
        sa.Column("action", sa.String(length=50), nullable=False),
        # Entity identification
        sa.Column("entity_type", sa.String(length=100), nullable=False),
        sa.Column("entity_id", sa.String(length=100), nullable=True),
        # Actor identification
        sa.Column("user_id", sa.String(length=100), nullable=True),
        sa.Column("tenant_id", sa.String(length=100), nullable=True),
        # Change tracking (JSONB for efficient querying)
        sa.Column("old_values", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("new_values", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("changes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        # Request context
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("request_id", sa.String(length=36), nullable=True),
        sa.Column("endpoint", sa.String(length=500), nullable=True),
        sa.Column("method", sa.String(length=10), nullable=True),
        # Additional metadata (JSONB for flexibility)
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        # Outcome
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("error_message", sa.Text(), nullable=True),
        # Performance
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        # Primary key constraint
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_logs")),
    )

    # Indexes for common query patterns

    # By timestamp (most common query pattern - recent logs)
    op.create_index("ix_audit_logs_timestamp", "audit_logs", ["timestamp"], unique=False)

    # By entity (get history for specific entity)
    op.create_index(
        "ix_audit_logs_entity",
        "audit_logs",
        ["entity_type", "entity_id", "timestamp"],
        unique=False,
    )

    # By user (user activity tracking)
    op.create_index(
        "ix_audit_logs_user",
        "audit_logs",
        ["user_id", "timestamp"],
        unique=False,
    )

    # By tenant (multi-tenant queries)
    op.create_index(
        "ix_audit_logs_tenant",
        "audit_logs",
        ["tenant_id", "timestamp"],
        unique=False,
    )

    # By action type
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"], unique=False)

    # By request ID (correlate logs with specific request)
    op.create_index("ix_audit_logs_request_id", "audit_logs", ["request_id"], unique=False)

    # Composite index for entity type + action (common filter combination)
    op.create_index(
        "ix_audit_logs_entity_action",
        "audit_logs",
        ["entity_type", "action"],
        unique=False,
    )

    # Partial index for failed operations (compliance/debugging)
    op.execute("""
        CREATE INDEX ix_audit_logs_failed
        ON audit_logs (timestamp, entity_type, action)
        WHERE success = false
    """)


def downgrade() -> None:
    """Drop audit_logs table."""
    # Drop indexes
    op.execute("DROP INDEX IF EXISTS ix_audit_logs_failed")
    op.drop_index("ix_audit_logs_entity_action", table_name="audit_logs")
    op.drop_index("ix_audit_logs_request_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_action", table_name="audit_logs")
    op.drop_index("ix_audit_logs_tenant", table_name="audit_logs")
    op.drop_index("ix_audit_logs_user", table_name="audit_logs")
    op.drop_index("ix_audit_logs_entity", table_name="audit_logs")
    op.drop_index("ix_audit_logs_timestamp", table_name="audit_logs")

    # Drop table
    op.drop_table("audit_logs")
