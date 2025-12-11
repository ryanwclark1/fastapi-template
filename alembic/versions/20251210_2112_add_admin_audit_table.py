"""add admin audit table

Revision ID: add_admin_audit_table
Revises: 0fccb9bc6eb7
Create Date: 2025-12-10 21:12:00.000000+00:00

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'add_admin_audit_table'
down_revision: str | None = '0fccb9bc6eb7'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.create_table(
        'admin_audit_log',
        sa.Column(
            'action',
            sa.String(length=100),
            nullable=False,
            comment='Operation name (e.g., reindex, vacuum, analyze)',
        ),
        sa.Column(
            'target',
            sa.String(length=255),
            nullable=False,
            comment='Target resource (table name, index name, etc.)',
        ),
        sa.Column(
            'user_id',
            sa.String(length=255),
            nullable=False,
            comment='User who performed the action',
        ),
        sa.Column(
            'tenant_id',
            sa.String(length=255),
            nullable=True,
            comment='Tenant context if applicable',
        ),
        sa.Column(
            'result',
            sa.String(length=50),
            nullable=False,
            comment='Operation result: success, failure, or dry_run',
        ),
        sa.Column(
            'duration_seconds',
            sa.Float(),
            nullable=True,
            comment='Operation duration in seconds',
        ),
        sa.Column(
            'metadata',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment='Additional context data (parameters, errors, stats)',
        ),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
            comment='Timestamp when action was performed',
        ),
        sa.Column(
            'id',
            sa.Uuid(),
            nullable=False,
            comment='UUID v7 primary key (time-sortable)',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_admin_audit_log')),
    )

    # Composite indexes for common query patterns
    op.create_index(
        'ix_admin_audit_action_time',
        'admin_audit_log',
        ['action', 'created_at'],
        unique=False,
    )
    op.create_index(
        'ix_admin_audit_user_time',
        'admin_audit_log',
        ['user_id', 'created_at'],
        unique=False,
    )
    op.create_index(
        'ix_admin_audit_tenant_time',
        'admin_audit_log',
        ['tenant_id', 'created_at'],
        unique=False,
    )

    # Single column indexes for flexible filtering
    op.create_index(
        op.f('ix_admin_audit_log_action'),
        'admin_audit_log',
        ['action'],
        unique=False,
    )
    op.create_index(
        op.f('ix_admin_audit_log_result'),
        'admin_audit_log',
        ['result'],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_index(op.f('ix_admin_audit_log_result'), table_name='admin_audit_log')
    op.drop_index(op.f('ix_admin_audit_log_action'), table_name='admin_audit_log')
    op.drop_index('ix_admin_audit_tenant_time', table_name='admin_audit_log')
    op.drop_index('ix_admin_audit_user_time', table_name='admin_audit_log')
    op.drop_index('ix_admin_audit_action_time', table_name='admin_audit_log')
    op.drop_table('admin_audit_log')
