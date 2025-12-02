"""add_recurrence_fields_to_reminders

Revision ID: dd5ec4279527
Revises: d4e5f6a7b8c9
Create Date: 2025-12-02 00:59:56.405188+00:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "dd5ec4279527"
down_revision: str | None = "d4e5f6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add recurrence fields to reminders table.

    This migration adds the following columns to support recurring reminders:
    - recurrence_rule: iCalendar RRULE string (e.g., "FREQ=WEEKLY;BYDAY=MO,WE,FR")
    - recurrence_end_at: When the recurrence series ends
    - parent_id: Self-referential foreign key for broken-out occurrences
    - occurrence_date: Specific occurrence date for broken-out instances

    These fields are defined in example_service.features.reminders.models.Reminder
    and match the model definition exactly.
    """
    # Add recurrence_rule column
    op.add_column(
        "reminders",
        sa.Column(
            "recurrence_rule",
            sa.String(length=255),
            nullable=True,
            comment="iCalendar RRULE string for recurring reminders",
        ),
    )

    # Add recurrence_end_at column
    op.add_column(
        "reminders",
        sa.Column(
            "recurrence_end_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="When the recurrence series ends",
        ),
    )

    # Add parent_id column (self-referential foreign key)
    op.add_column(
        "reminders",
        sa.Column(
            "parent_id",
            sa.Uuid(),
            nullable=True,
            comment="Parent reminder ID for occurrences broken out from a series",
        ),
    )

    # Add occurrence_date column
    op.add_column(
        "reminders",
        sa.Column(
            "occurrence_date",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Specific occurrence date for broken-out instances",
        ),
    )

    # Create foreign key constraint for parent_id
    op.create_foreign_key(
        op.f("fk_reminders_parent_id_reminders"),
        "reminders",
        "reminders",
        ["parent_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # Create index on parent_id (already defined in model with index=True)
    op.create_index(
        op.f("ix_reminders_parent_id"),
        "reminders",
        ["parent_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove recurrence fields from reminders table."""
    # Drop index
    op.drop_index(op.f("ix_reminders_parent_id"), table_name="reminders")

    # Drop foreign key constraint
    op.drop_constraint(
        op.f("fk_reminders_parent_id_reminders"),
        "reminders",
        type_="foreignkey",
    )

    # Drop columns
    op.drop_column("reminders", "occurrence_date")
    op.drop_column("reminders", "parent_id")
    op.drop_column("reminders", "recurrence_end_at")
    op.drop_column("reminders", "recurrence_rule")
