"""add_reminder_search_vector

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2025-11-25 14:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import TSVECTOR

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: str | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add full-text search capability to reminders table."""
    # Add search_vector column
    op.add_column("reminders", sa.Column("search_vector", TSVECTOR(), nullable=True))

    # Create GIN index for fast full-text search
    op.create_index(
        "ix_reminders_search_vector",
        "reminders",
        ["search_vector"],
        unique=False,
        postgresql_using="gin",
    )

    # Create trigger function to auto-update search vector
    op.execute("""
        CREATE OR REPLACE FUNCTION reminders_search_vector_update() RETURNS trigger AS $$
        BEGIN
            NEW.search_vector :=
                setweight(to_tsvector('english', coalesce(NEW.title, '')), 'A') ||
                setweight(to_tsvector('english', coalesce(NEW.description, '')), 'B');
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # Create trigger to call the function before insert/update
    op.execute("""
        CREATE TRIGGER reminders_search_update
            BEFORE INSERT OR UPDATE ON reminders
            FOR EACH ROW
            EXECUTE FUNCTION reminders_search_vector_update();
    """)

    # Backfill existing records with search vectors
    op.execute("""
        UPDATE reminders SET search_vector =
            setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
            setweight(to_tsvector('english', coalesce(description, '')), 'B');
    """)


def downgrade() -> None:
    """Remove full-text search from reminders table."""
    # Drop trigger
    op.execute("DROP TRIGGER IF EXISTS reminders_search_update ON reminders")

    # Drop trigger function
    op.execute("DROP FUNCTION IF EXISTS reminders_search_vector_update()")

    # Drop index
    op.drop_index("ix_reminders_search_vector", table_name="reminders")

    # Drop column
    op.drop_column("reminders", "search_vector")
