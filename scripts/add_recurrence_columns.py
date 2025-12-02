#!/usr/bin/env python3
"""Add missing recurrence columns to reminders table.

⚠️ NOTE: This script is a one-time workaround utility.
The proper way to add these columns is via Alembic migrations:
- Migration: alembic/versions/20251202_0059_dd5ec4279527_add_recurrence_fields_to_reminders.py
- Model: example_service.features.reminders.models.Reminder

This script was created to work around migration system issues and should only
be used if migrations cannot be run normally. For fresh databases, always use:
    alembic upgrade head

The model and migration are the source of truth for the schema.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from example_service.core.settings import get_db_settings


async def add_recurrence_columns() -> None:
    """Add missing recurrence columns to reminders table."""
    db_settings = get_db_settings()

    if not db_settings.enabled:
        print("Database is disabled. Exiting.")
        return

    # Create engine using the same settings as the application
    engine = create_async_engine(
        db_settings.url,
        echo=False,
        pool_pre_ping=True,
    )

    async with engine.begin() as conn:
        # Check if columns already exist
        check_query = text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'reminders'
            AND column_name IN ('recurrence_rule', 'recurrence_end_at', 'parent_id', 'occurrence_date')
        """)

        result = await conn.execute(check_query)
        existing_columns = {row[0] for row in result}

        print(f"Existing recurrence columns: {existing_columns}")

        # Add recurrence_rule if it doesn't exist
        if "recurrence_rule" not in existing_columns:
            print("Adding recurrence_rule column...")
            await conn.execute(
                text("""
                ALTER TABLE reminders
                ADD COLUMN recurrence_rule VARCHAR(255) NULL
            """)
            )
            await conn.execute(
                text("""
                COMMENT ON COLUMN reminders.recurrence_rule IS 'iCalendar RRULE string for recurring reminders'
            """)
            )
            print("✓ Added recurrence_rule column")
        else:
            print("✓ recurrence_rule column already exists")

        # Add recurrence_end_at if it doesn't exist
        if "recurrence_end_at" not in existing_columns:
            print("Adding recurrence_end_at column...")
            await conn.execute(
                text("""
                ALTER TABLE reminders
                ADD COLUMN recurrence_end_at TIMESTAMP WITH TIME ZONE NULL
            """)
            )
            await conn.execute(
                text("""
                COMMENT ON COLUMN reminders.recurrence_end_at IS 'When the recurrence series ends'
            """)
            )
            print("✓ Added recurrence_end_at column")
        else:
            print("✓ recurrence_end_at column already exists")

        # Add parent_id if it doesn't exist
        if "parent_id" not in existing_columns:
            print("Adding parent_id column...")
            await conn.execute(
                text("""
                ALTER TABLE reminders
                ADD COLUMN parent_id UUID NULL
            """)
            )
            await conn.execute(
                text("""
                COMMENT ON COLUMN reminders.parent_id IS 'Parent reminder ID for occurrences broken out from a series'
            """)
            )

            # Add foreign key constraint
            print("Adding foreign key constraint for parent_id...")
            await conn.execute(
                text("""
                ALTER TABLE reminders
                ADD CONSTRAINT fk_reminders_parent_id_reminders
                FOREIGN KEY (parent_id) REFERENCES reminders(id)
                ON DELETE SET NULL
            """)
            )

            # Add index
            print("Adding index on parent_id...")
            await conn.execute(
                text("""
                CREATE INDEX IF NOT EXISTS ix_reminders_parent_id
                ON reminders(parent_id)
            """)
            )
            print("✓ Added parent_id column, foreign key, and index")
        else:
            print("✓ parent_id column already exists")

        # Add occurrence_date if it doesn't exist
        if "occurrence_date" not in existing_columns:
            print("Adding occurrence_date column...")
            await conn.execute(
                text("""
                ALTER TABLE reminders
                ADD COLUMN occurrence_date TIMESTAMP WITH TIME ZONE NULL
            """)
            )
            await conn.execute(
                text("""
                COMMENT ON COLUMN reminders.occurrence_date IS 'Specific occurrence date for broken-out instances'
            """)
            )
            print("✓ Added occurrence_date column")
        else:
            print("✓ occurrence_date column already exists")

    await engine.dispose()
    print("\n✅ All recurrence columns have been added successfully!")


if __name__ == "__main__":
    asyncio.run(add_recurrence_columns())
