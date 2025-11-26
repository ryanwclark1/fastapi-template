"""add_event_outbox

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2025-11-25 12:00:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: str | None = 'a1b2c3d4e5f6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create event_outbox table for transactional outbox pattern."""
    # Create event_outbox table
    op.create_table(
        'event_outbox',
        # Primary key (UUID v7 for time-ordering)
        sa.Column('id', sa.Uuid(), nullable=False),

        # Event identification
        sa.Column('event_type', sa.String(length=100), nullable=False),
        sa.Column('event_version', sa.Integer(), nullable=False, server_default='1'),

        # Event payload (JSON)
        sa.Column('payload', sa.Text(), nullable=False),

        # Tracing and context
        sa.Column('correlation_id', sa.String(length=36), nullable=True),

        # Aggregate context (for ordered delivery per entity)
        sa.Column('aggregate_type', sa.String(length=100), nullable=True),
        sa.Column('aggregate_id', sa.String(length=100), nullable=True),

        # Processing state
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('retry_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('next_retry_at', sa.DateTime(timezone=True), nullable=True),

        # Timestamps
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),

        # Primary key constraint
        sa.PrimaryKeyConstraint('id', name=op.f('pk_event_outbox'))
    )

    # Standard indexes
    op.create_index('ix_event_outbox_event_type', 'event_outbox', ['event_type'], unique=False)
    op.create_index('ix_event_outbox_correlation_id', 'event_outbox', ['correlation_id'], unique=False)
    op.create_index('ix_event_outbox_processed_at', 'event_outbox', ['processed_at'], unique=False)
    op.create_index('ix_event_outbox_next_retry_at', 'event_outbox', ['next_retry_at'], unique=False)

    # Composite index for fetching pending events efficiently
    # Note: PostgreSQL partial indexes require raw SQL
    op.execute("""
        CREATE INDEX ix_event_outbox_pending
        ON event_outbox (processed_at, next_retry_at, created_at)
        WHERE processed_at IS NULL
    """)

    # Composite index for ordered delivery per aggregate
    op.create_index(
        'ix_event_outbox_aggregate',
        'event_outbox',
        ['aggregate_type', 'aggregate_id', 'created_at'],
        unique=False
    )


def downgrade() -> None:
    """Drop event_outbox table."""
    # Drop indexes
    op.drop_index('ix_event_outbox_aggregate', table_name='event_outbox')
    op.execute("DROP INDEX IF EXISTS ix_event_outbox_pending")
    op.drop_index('ix_event_outbox_next_retry_at', table_name='event_outbox')
    op.drop_index('ix_event_outbox_processed_at', table_name='event_outbox')
    op.drop_index('ix_event_outbox_correlation_id', table_name='event_outbox')
    op.drop_index('ix_event_outbox_event_type', table_name='event_outbox')

    # Drop table
    op.drop_table('event_outbox')
