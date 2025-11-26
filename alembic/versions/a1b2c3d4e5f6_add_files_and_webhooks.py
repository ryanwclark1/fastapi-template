"""add_files_and_webhooks

Revision ID: a1b2c3d4e5f6
Revises: 6c70eb111478
Create Date: 2025-11-25 10:00:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: str | None = '6c70eb111478'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    # Create file status enum
    file_status_enum = postgresql.ENUM(
        'pending', 'processing', 'ready', 'failed', 'deleted',
        name='filestatus',
        create_type=True
    )
    file_status_enum.create(op.get_bind(), checkfirst=True)

    # Create delivery status enum
    delivery_status_enum = postgresql.ENUM(
        'pending', 'delivered', 'failed', 'retrying',
        name='deliverystatus',
        create_type=True
    )
    delivery_status_enum.create(op.get_bind(), checkfirst=True)

    # Create files table
    op.create_table(
        'files',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('original_filename', sa.String(length=255), nullable=False),
        sa.Column('storage_key', sa.String(length=512), nullable=False),
        sa.Column('bucket', sa.String(length=63), nullable=False),
        sa.Column('content_type', sa.String(length=255), nullable=False),
        sa.Column('size_bytes', sa.BigInteger(), nullable=False),
        sa.Column('checksum_sha256', sa.String(length=64), nullable=True),
        sa.Column('etag', sa.String(length=255), nullable=True),
        sa.Column(
            'status',
            file_status_enum,
            nullable=False,
            server_default='pending'
        ),
        sa.Column('owner_id', sa.String(length=255), nullable=True),
        sa.Column('is_public', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_files'))
    )
    op.create_index(op.f('ix_files_storage_key'), 'files', ['storage_key'], unique=True)
    op.create_index('ix_files_owner_id', 'files', ['owner_id'], unique=False)
    op.create_index('ix_files_status', 'files', ['status'], unique=False)
    op.create_index('ix_files_expires_at', 'files', ['expires_at'], unique=False)
    op.create_index('ix_files_content_type', 'files', ['content_type'], unique=False)

    # Create file_thumbnails table
    op.create_table(
        'file_thumbnails',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('file_id', sa.Uuid(), nullable=False),
        sa.Column('storage_key', sa.String(length=512), nullable=False),
        sa.Column('width', sa.Integer(), nullable=False),
        sa.Column('height', sa.Integer(), nullable=False),
        sa.Column('size_bytes', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ['file_id'], ['files.id'],
            name=op.f('fk_file_thumbnails_file_id_files'),
            ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_file_thumbnails'))
    )
    op.create_index('ix_file_thumbnails_file_id', 'file_thumbnails', ['file_id'], unique=False)

    # Create webhooks table
    op.create_table(
        'webhooks',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('url', sa.String(length=2048), nullable=False),
        sa.Column('secret', sa.String(length=255), nullable=False),
        sa.Column('event_types', postgresql.ARRAY(sa.String(length=100)), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('max_retries', sa.Integer(), nullable=False, server_default='5'),
        sa.Column('timeout_seconds', sa.Integer(), nullable=False, server_default='30'),
        sa.Column('custom_headers', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('total_deliveries', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('successful_deliveries', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('failed_deliveries', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_webhooks'))
    )
    op.create_index('ix_webhooks_is_active', 'webhooks', ['is_active'], unique=False)
    op.create_index(
        'ix_webhooks_event_types',
        'webhooks',
        ['event_types'],
        unique=False,
        postgresql_using='gin'
    )

    # Create webhook_deliveries table
    op.create_table(
        'webhook_deliveries',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('webhook_id', sa.Uuid(), nullable=False),
        sa.Column('event_type', sa.String(length=100), nullable=False),
        sa.Column('event_id', sa.String(length=255), nullable=False),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            'status',
            delivery_status_enum,
            nullable=False,
            server_default='pending'
        ),
        sa.Column('attempt_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('max_attempts', sa.Integer(), nullable=False, server_default='5'),
        sa.Column('next_retry_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('response_status_code', sa.Integer(), nullable=True),
        sa.Column('response_body', sa.Text(), nullable=True),
        sa.Column('response_time_ms', sa.Integer(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ['webhook_id'], ['webhooks.id'],
            name=op.f('fk_webhook_deliveries_webhook_id_webhooks'),
            ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_webhook_deliveries'))
    )
    op.create_index('ix_webhook_deliveries_webhook_id', 'webhook_deliveries', ['webhook_id'], unique=False)
    op.create_index('ix_webhook_deliveries_status', 'webhook_deliveries', ['status'], unique=False)
    op.create_index('ix_webhook_deliveries_event_type', 'webhook_deliveries', ['event_type'], unique=False)
    op.create_index('ix_webhook_deliveries_next_retry_at', 'webhook_deliveries', ['next_retry_at'], unique=False)
    op.create_index(
        'ix_webhook_deliveries_status_next_retry',
        'webhook_deliveries',
        ['status', 'next_retry_at'],
        unique=False
    )


def downgrade() -> None:
    """Downgrade database schema."""
    # Drop webhook_deliveries table and indexes
    op.drop_index('ix_webhook_deliveries_status_next_retry', table_name='webhook_deliveries')
    op.drop_index('ix_webhook_deliveries_next_retry_at', table_name='webhook_deliveries')
    op.drop_index('ix_webhook_deliveries_event_type', table_name='webhook_deliveries')
    op.drop_index('ix_webhook_deliveries_status', table_name='webhook_deliveries')
    op.drop_index('ix_webhook_deliveries_webhook_id', table_name='webhook_deliveries')
    op.drop_table('webhook_deliveries')

    # Drop webhooks table and indexes
    op.drop_index('ix_webhooks_event_types', table_name='webhooks')
    op.drop_index('ix_webhooks_is_active', table_name='webhooks')
    op.drop_table('webhooks')

    # Drop file_thumbnails table and indexes
    op.drop_index('ix_file_thumbnails_file_id', table_name='file_thumbnails')
    op.drop_table('file_thumbnails')

    # Drop files table and indexes
    op.drop_index('ix_files_content_type', table_name='files')
    op.drop_index('ix_files_expires_at', table_name='files')
    op.drop_index('ix_files_status', table_name='files')
    op.drop_index('ix_files_owner_id', table_name='files')
    op.drop_index(op.f('ix_files_storage_key'), table_name='files')
    op.drop_table('files')

    # Drop enums
    delivery_status_enum = postgresql.ENUM(
        'pending', 'delivered', 'failed', 'retrying',
        name='deliverystatus'
    )
    delivery_status_enum.drop(op.get_bind(), checkfirst=True)

    file_status_enum = postgresql.ENUM(
        'pending', 'processing', 'ready', 'failed', 'deleted',
        name='filestatus'
    )
    file_status_enum.drop(op.get_bind(), checkfirst=True)
