"""add notifications

Revision ID: ba51709f4161
Revises: 0fccb9bc6eb7
Create Date: 2025-12-10 21:12:00.000000+00:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from example_service.features.notifications.models import StringArray
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "ba51709f4161"
down_revision: str | None = "0fccb9bc6eb7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema - add notifications tables."""
    # Create notification_templates table
    op.create_table(
        "notification_templates",
        sa.Column("name", sa.String(length=100), nullable=False, comment="Template identifier"),
        sa.Column("notification_type", sa.String(length=100), nullable=False, comment="Notification category"),
        sa.Column("channel", sa.String(length=50), nullable=False, comment="Delivery channel"),
        sa.Column("subject_template", sa.Text(), nullable=True, comment="Jinja2 template for email subject"),
        sa.Column("body_template", sa.Text(), nullable=True, comment="Jinja2 template for plain text email"),
        sa.Column("body_html_template", sa.Text(), nullable=True, comment="Jinja2 template for HTML email"),
        sa.Column(
            "webhook_payload_template",
            postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite"),
            nullable=True,
            comment="Jinja2 template structure for webhook",
        ),
        sa.Column("websocket_event_type", sa.String(length=100), nullable=True, comment="WebSocket event type"),
        sa.Column(
            "websocket_payload_template",
            postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite"),
            nullable=True,
            comment="Jinja2 template structure for WebSocket",
        ),
        sa.Column("description", sa.Text(), nullable=True, comment="Template description"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true", comment="Whether active"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1", comment="Template version"),
        sa.Column("priority", sa.String(length=20), nullable=False, server_default="normal", comment="Default priority"),
        sa.Column(
            "required_context_vars",
            StringArray(),
            nullable=False,
            server_default="{}",
            comment="Required context variables",
        ),
        sa.Column("id", sa.Uuid(), nullable=False, comment="UUID v7 primary key (time-sortable)"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="Timestamp of record creation",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="Timestamp of last update",
        ),
        sa.Column(
            "tenant_id",
            sa.String(length=255),
            nullable=True,
            comment="Tenant ID for multi-tenant isolation",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notification_templates")),
    )
    op.create_index(
        "idx_notification_template_type_tenant",
        "notification_templates",
        ["notification_type", "tenant_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_notification_templates_name"),
        "notification_templates",
        ["name"],
        unique=False,
    )
    op.create_index(
        op.f("ix_notification_templates_notification_type"),
        "notification_templates",
        ["notification_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_notification_templates_tenant_id"),
        "notification_templates",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        "uq_template_name_channel_version_tenant",
        "notification_templates",
        ["name", "channel", "version", "tenant_id"],
        unique=True,
    )

    # Create user_notification_preferences table
    op.create_table(
        "user_notification_preferences",
        sa.Column("user_id", sa.String(length=255), nullable=False, comment="User identifier"),
        sa.Column("tenant_id", sa.String(length=255), nullable=True, comment="Tenant ID"),
        sa.Column("notification_type", sa.String(length=100), nullable=False, comment="Notification type"),
        sa.Column(
            "enabled_channels",
            StringArray(),
            nullable=False,
            server_default='{"email","websocket"}',
            comment="Enabled delivery channels",
        ),
        sa.Column(
            "channel_settings",
            postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite"),
            nullable=True,
            comment="Channel-specific settings",
        ),
        sa.Column("quiet_hours_start", sa.Integer(), nullable=True, comment="Quiet hours start (0-23, UTC)"),
        sa.Column("quiet_hours_end", sa.Integer(), nullable=True, comment="Quiet hours end (0-23, UTC)"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true", comment="Whether active"),
        sa.Column("id", sa.Uuid(), nullable=False, comment="UUID v7 primary key (time-sortable)"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="Timestamp of record creation",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="Timestamp of last update",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_notification_preferences")),
    )
    op.create_index(
        "idx_preference_user_tenant",
        "user_notification_preferences",
        ["user_id", "tenant_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_user_notification_preferences_tenant_id"),
        "user_notification_preferences",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_user_notification_preferences_user_id"),
        "user_notification_preferences",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "uq_user_tenant_notification_type",
        "user_notification_preferences",
        ["user_id", "tenant_id", "notification_type"],
        unique=True,
    )

    # Create notifications table
    op.create_table(
        "notifications",
        sa.Column("user_id", sa.String(length=255), nullable=False, comment="User identifier (recipient)"),
        sa.Column("notification_type", sa.String(length=100), nullable=False, comment="Type/category of notification"),
        sa.Column("template_name", sa.String(length=100), nullable=True, comment="Template used for rendering"),
        sa.Column("title", sa.String(length=500), nullable=False, comment="Notification title"),
        sa.Column("body", sa.Text(), nullable=True, comment="Plain text body"),
        sa.Column("body_html", sa.Text(), nullable=True, comment="HTML body"),
        sa.Column(
            "context_data",
            postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite"),
            nullable=True,
            comment="Template context variables",
        ),
        sa.Column("priority", sa.String(length=20), nullable=False, server_default="normal", comment="Priority level"),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True, comment="When to send (null = immediate)"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending", comment="Status"),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True, comment="When dispatched to channels"),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True, comment="When all deliveries completed"),
        sa.Column("source_event_id", sa.String(length=255), nullable=True, comment="Domain event ID that triggered this"),
        sa.Column("source_entity_type", sa.String(length=100), nullable=True, comment="Entity type that triggered this"),
        sa.Column("source_entity_id", sa.String(length=255), nullable=True, comment="Entity ID that triggered this"),
        sa.Column("correlation_id", sa.String(length=255), nullable=True, comment="Correlation ID for tracing"),
        sa.Column(
            "extra_metadata",
            postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite"),
            nullable=True,
            comment="Additional metadata",
        ),
        sa.Column(
            "actions",
            postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite"),
            nullable=True,
            comment="Action buttons for UI",
        ),
        sa.Column("progress", sa.Integer(), nullable=True, comment="Progress percentage (0-100)"),
        sa.Column("group_key", sa.String(length=255), nullable=True, comment="Key for grouping notifications"),
        sa.Column("auto_dismiss", sa.Boolean(), nullable=False, server_default="false", comment="Whether auto-dismisses"),
        sa.Column("dismiss_after", sa.Integer(), nullable=True, comment="Auto-dismiss timeout (ms)"),
        sa.Column("read", sa.Boolean(), nullable=False, server_default="false", comment="Whether read (in-app only)"),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True, comment="When marked as read"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True, comment="When notification expires"),
        sa.Column("id", sa.Uuid(), nullable=False, comment="UUID v7 primary key (time-sortable)"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="Timestamp of record creation",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="Timestamp of last update",
        ),
        sa.Column(
            "tenant_id",
            sa.String(length=255),
            nullable=True,
            comment="Tenant ID for multi-tenant isolation",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
    )
    op.create_index(
        "idx_notification_user_tenant_status",
        "notifications",
        ["user_id", "tenant_id", "status"],
        unique=False,
    )
    op.create_index(
        "idx_notification_type_status",
        "notifications",
        ["notification_type", "status"],
        unique=False,
    )
    op.create_index(
        "idx_notification_scheduled_status",
        "notifications",
        ["scheduled_for", "status"],
        unique=False,
    )
    op.create_index(
        "idx_notification_source",
        "notifications",
        ["source_entity_type", "source_entity_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_notifications_expires_at"),
        "notifications",
        ["expires_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_notifications_group_key"),
        "notifications",
        ["group_key"],
        unique=False,
    )
    op.create_index(
        op.f("ix_notifications_notification_type"),
        "notifications",
        ["notification_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_notifications_read"),
        "notifications",
        ["read"],
        unique=False,
    )
    op.create_index(
        op.f("ix_notifications_scheduled_for"),
        "notifications",
        ["scheduled_for"],
        unique=False,
    )
    op.create_index(
        op.f("ix_notifications_source_entity_id"),
        "notifications",
        ["source_entity_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_notifications_source_entity_type"),
        "notifications",
        ["source_entity_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_notifications_status"),
        "notifications",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_notifications_tenant_id"),
        "notifications",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_notifications_user_id"),
        "notifications",
        ["user_id"],
        unique=False,
    )

    # Create notification_deliveries table
    op.create_table(
        "notification_deliveries",
        sa.Column(
            "notification_id",
            sa.Uuid(),
            nullable=False,
            comment="Reference to parent notification",
        ),
        sa.Column("channel", sa.String(length=50), nullable=False, comment="Delivery channel"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending", comment="Delivery status"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0", comment="Number of attempts"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5", comment="Max attempts allowed"),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True, comment="Next retry time"),
        sa.Column("email_message_id", sa.String(length=255), nullable=True, comment="Email provider message ID"),
        sa.Column("email_recipient", sa.String(length=255), nullable=True, comment="Email recipient address"),
        sa.Column("webhook_id", sa.Uuid(), nullable=True, comment="Webhook configuration reference"),
        sa.Column("webhook_url", sa.String(length=2048), nullable=True, comment="Webhook URL used"),
        sa.Column("websocket_channel", sa.String(length=255), nullable=True, comment="WebSocket channel used"),
        sa.Column("websocket_connection_count", sa.Integer(), nullable=True, comment="WebSocket connections delivered to"),
        sa.Column("response_status_code", sa.Integer(), nullable=True, comment="HTTP response status code"),
        sa.Column("response_body", sa.Text(), nullable=True, comment="Response body (truncated)"),
        sa.Column("response_time_ms", sa.Integer(), nullable=True, comment="Response time in milliseconds"),
        sa.Column("error_message", sa.Text(), nullable=True, comment="Error message if failed"),
        sa.Column("error_category", sa.String(length=100), nullable=True, comment="Error category"),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True, comment="When delivery succeeded"),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True, comment="When permanently failed"),
        sa.Column("id", sa.Uuid(), nullable=False, comment="UUID v7 primary key (time-sortable)"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="Timestamp of record creation",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="Timestamp of last update",
        ),
        sa.ForeignKeyConstraint(
            ["notification_id"],
            ["notifications.id"],
            name=op.f("fk_notification_deliveries_notification_id_notifications"),
            ondelete="CASCADE",
        ),
        # Note: webhook_id is a reference field but has no FK constraint
        # since webhooks table may not exist in all deployments
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notification_deliveries")),
    )
    op.create_index(
        "idx_delivery_notification_channel",
        "notification_deliveries",
        ["notification_id", "channel"],
        unique=False,
    )
    op.create_index(
        "idx_delivery_status_retry",
        "notification_deliveries",
        ["status", "next_retry_at"],
        unique=False,
    )
    op.create_index(
        "idx_delivery_channel_status",
        "notification_deliveries",
        ["channel", "status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_notification_deliveries_channel"),
        "notification_deliveries",
        ["channel"],
        unique=False,
    )
    op.create_index(
        op.f("ix_notification_deliveries_next_retry_at"),
        "notification_deliveries",
        ["next_retry_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_notification_deliveries_notification_id"),
        "notification_deliveries",
        ["notification_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_notification_deliveries_status"),
        "notification_deliveries",
        ["status"],
        unique=False,
    )

    # Seed default notification templates
    # Email template: reminder_due
    op.execute(
        """
        INSERT INTO notification_templates (
            id, name, notification_type, channel,
            subject_template, body_template, body_html_template,
            priority, required_context_vars, tenant_id, created_at, updated_at
        ) VALUES (
            gen_random_uuid(),
            'reminder_due',
            'reminder',
            'email',
            'Reminder: {{ title }}',
            'Your reminder "{{ title }}" is due at {{ remind_at }}.',
            '<h2>Reminder Due</h2><p><strong>{{ title }}</strong> is due at {{ remind_at }}.</p>',
            'high',
            '{title,remind_at}',
            NULL,
            NOW(),
            NOW()
        )
        """
    )

    # WebSocket template: reminder_due
    op.execute(
        """
        INSERT INTO notification_templates (
            id, name, notification_type, channel,
            websocket_event_type, websocket_payload_template,
            priority, required_context_vars, tenant_id, created_at, updated_at
        ) VALUES (
            gen_random_uuid(),
            'reminder_due',
            'reminder',
            'websocket',
            'reminder.due',
            '{"reminder_id": "{{ reminder_id }}", "title": "{{ title }}", "remind_at": "{{ remind_at }}"}'::jsonb,
            'high',
            '{reminder_id,title,remind_at}',
            NULL,
            NOW(),
            NOW()
        )
        """
    )

    # Email template: file_uploaded
    op.execute(
        """
        INSERT INTO notification_templates (
            id, name, notification_type, channel,
            subject_template, body_template, body_html_template,
            priority, required_context_vars, tenant_id, created_at, updated_at
        ) VALUES (
            gen_random_uuid(),
            'file_uploaded',
            'file',
            'email',
            'File Uploaded: {{ filename }}',
            'Your file "{{ filename }}" has been uploaded successfully.',
            '<h2>File Uploaded</h2><p>Your file <strong>{{ filename }}</strong> has been uploaded successfully.</p>',
            'normal',
            '{filename}',
            NULL,
            NOW(),
            NOW()
        )
        """
    )

    # WebSocket template: file_uploaded
    op.execute(
        """
        INSERT INTO notification_templates (
            id, name, notification_type, channel,
            websocket_event_type, websocket_payload_template,
            priority, required_context_vars, tenant_id, created_at, updated_at
        ) VALUES (
            gen_random_uuid(),
            'file_uploaded',
            'file',
            'websocket',
            'file.uploaded',
            '{"file_id": "{{ file_id }}", "filename": "{{ filename }}"}'::jsonb,
            'normal',
            '{file_id,filename}',
            NULL,
            NOW(),
            NOW()
        )
        """
    )


def downgrade() -> None:
    """Downgrade database schema - remove notifications tables."""
    op.drop_table("notification_deliveries")
    op.drop_table("notifications")
    op.drop_table("user_notification_preferences")
    op.drop_table("notification_templates")
