"""SQLAlchemy models for the notifications feature."""

from __future__ import annotations

from datetime import datetime
import json
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from example_service.core.database import TenantMixin, UUIDv7TimestampedBase

if TYPE_CHECKING:
    from sqlalchemy.engine import Dialect
    from sqlalchemy.sql.type_api import TypeEngine


class StringArray(TypeDecorator):
    """Cross-database type for string arrays.

    Uses native ARRAY in PostgreSQL, JSON in SQLite/other databases.
    Ensures consistent behavior across development (SQLite) and production (PostgreSQL).
    """

    impl = Text
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[Any]:
        """Return native ARRAY for Postgres, Text for other dialects."""
        if dialect.name == "postgresql":
            return dialect.type_descriptor(ARRAY(String(100)))
        return dialect.type_descriptor(Text())

    def process_bind_param(self, value: list[str] | None, dialect: Dialect) -> Any:
        """Serialize the array before binding to the database."""
        if value is None:
            return value
        if dialect.name == "postgresql":
            return value
        return json.dumps(value)

    def process_result_value(self, value: Any, dialect: Dialect) -> list[str]:
        """Deserialize the stored array back into Python list."""
        if value is None:
            return []
        if dialect.name == "postgresql":
            return value
        return json.loads(value) if value else []


class NotificationTemplate(UUIDv7TimestampedBase, TenantMixin):
    """Multi-channel notification templates with Jinja2 support.

    Stores reusable templates for different notification types and delivery channels.
    Templates use Jinja2 syntax for variable interpolation and can be customized
    per tenant.

    Supports multiple channels:
    - Email: subject_template, body_template (plain text), body_html_template
    - Webhook: webhook_payload_template (JSONB structure)
    - WebSocket: websocket_event_type, websocket_payload_template

    Template versioning allows schema evolution while maintaining backward compatibility.

    Indexes:
        - (tenant_id, notification_type) for fast lookup
        - (name, channel, version, tenant_id) unique constraint
    """

    __tablename__ = "notification_templates"

    # Identification
    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        comment="Template identifier (e.g., 'reminder_due')",
    )
    notification_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        comment="Category of notification (e.g., 'reminder', 'file')",
    )
    channel: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Delivery channel: email, webhook, websocket, in_app",
    )

    # Email content templates (Jinja2)
    subject_template: Mapped[str | None] = mapped_column(
        Text(),
        nullable=True,
        comment="Jinja2 template for email subject",
    )
    body_template: Mapped[str | None] = mapped_column(
        Text(),
        nullable=True,
        comment="Jinja2 template for plain text email body",
    )
    body_html_template: Mapped[str | None] = mapped_column(
        Text(),
        nullable=True,
        comment="Jinja2 template for HTML email body",
    )

    # Webhook content templates
    webhook_payload_template: Mapped[dict | None] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"),
        nullable=True,
        comment="Jinja2 template structure for webhook payload",
    )

    # WebSocket content templates
    websocket_event_type: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="WebSocket event type for client routing",
    )
    websocket_payload_template: Mapped[dict | None] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"),
        nullable=True,
        comment="Jinja2 template structure for WebSocket payload",
    )

    # Metadata
    description: Mapped[str | None] = mapped_column(
        Text(),
        nullable=True,
        comment="Human-readable template description",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean(),
        default=True,
        nullable=False,
        comment="Whether template is active",
    )
    version: Mapped[int] = mapped_column(
        Integer(),
        default=1,
        nullable=False,
        comment="Template version for schema evolution",
    )
    priority: Mapped[str] = mapped_column(
        String(20),
        default="normal",
        nullable=False,
        comment="Default priority: low, normal, high, urgent",
    )

    # Validation
    required_context_vars: Mapped[list[str]] = mapped_column(
        StringArray(),
        nullable=False,
        default=list,
        comment="Required context variables for rendering",
    )

    __table_args__ = (
        Index("idx_notification_template_type_tenant", "notification_type", "tenant_id"),
        UniqueConstraint("name", "channel", "version", "tenant_id", name="uq_template_name_channel_version_tenant"),
    )


class UserNotificationPreference(UUIDv7TimestampedBase):
    """User preferences for notification channels and delivery settings.

    Stores per-user, per-notification-type preferences for which channels
    should receive notifications. Supports:
    - Channel selection (email, webhook, websocket, in_app)
    - Quiet hours (UTC timezone)
    - Channel-specific settings (JSONB for flexibility)

    Multi-tenant aware via tenant_id for proper isolation.

    Unique constraint: (user_id, tenant_id, notification_type)
    """

    __tablename__ = "user_notification_preferences"

    # User identification
    user_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
        comment="User identifier (from accent-auth or local users)",
    )
    tenant_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
        comment="Tenant ID for multi-tenant isolation",
    )
    notification_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="Type of notification these preferences apply to",
    )

    # Channel preferences
    enabled_channels: Mapped[list[str]] = mapped_column(
        StringArray(),
        nullable=False,
        default=lambda: ["email", "websocket"],  # Default channels
        comment="Enabled delivery channels (e.g., ['email', 'websocket'])",
    )
    channel_settings: Mapped[dict | None] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"),
        nullable=True,
        comment="Channel-specific configuration (JSONB for flexibility)",
    )

    # Quiet hours (UTC)
    quiet_hours_start: Mapped[int | None] = mapped_column(
        Integer(),
        nullable=True,
        comment="Quiet hours start (0-23, UTC)",
    )
    quiet_hours_end: Mapped[int | None] = mapped_column(
        Integer(),
        nullable=True,
        comment="Quiet hours end (0-23, UTC)",
    )

    # Status
    is_active: Mapped[bool] = mapped_column(
        Boolean(),
        default=True,
        nullable=False,
        comment="Whether these preferences are active",
    )

    __table_args__ = (
        UniqueConstraint("user_id", "tenant_id", "notification_type", name="uq_user_tenant_notification_type"),
        Index("idx_preference_user_tenant", "user_id", "tenant_id"),
    )


class Notification(UUIDv7TimestampedBase, TenantMixin):
    """Core notification record.

    Represents a notification instance sent to a user. Tracks:
    - Recipient and content
    - Delivery status and timing
    - Source event tracing
    - UI features (action buttons, progress, grouping)
    - Read status for in-app notifications

    Notifications can be:
    - Immediate (scheduled_for = None)
    - Scheduled (scheduled_for = future datetime)
    - Associated with domain events (source_event_id)

    Multi-channel delivery is tracked via NotificationDelivery relationship.

    Indexes:
        - (user_id, tenant_id, status) for user notification lists
        - (notification_type, status) for type-specific queries
        - (scheduled_for, status) for scheduled processing
        - (source_entity_type, source_entity_id) for source tracking
    """

    __tablename__ = "notifications"

    # Recipient
    user_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
        comment="User identifier (notification recipient)",
    )

    # Type and template
    notification_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        comment="Type/category of notification",
    )
    template_name: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="Template used for rendering (optional)",
    )

    # Rendered content
    title: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        comment="Notification title (rendered)",
    )
    body: Mapped[str | None] = mapped_column(
        Text(),
        nullable=True,
        comment="Plain text body (rendered)",
    )
    body_html: Mapped[str | None] = mapped_column(
        Text(),
        nullable=True,
        comment="HTML body (rendered)",
    )
    context_data: Mapped[dict | None] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"),
        nullable=True,
        comment="Template context variables used for rendering",
    )

    # Scheduling and priority
    priority: Mapped[str] = mapped_column(
        String(20),
        default="normal",
        nullable=False,
        comment="Priority: low, normal, high, urgent",
    )
    scheduled_for: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
        comment="When to send notification (null = immediate)",
    )

    # Status tracking
    status: Mapped[str] = mapped_column(
        String(20),
        default="pending",
        nullable=False,
        index=True,
        comment="Status: pending, dispatched, delivered, failed, cancelled",
    )
    dispatched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When notification was dispatched to channels",
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When all deliveries completed (success or failure)",
    )

    # Source tracking (what triggered this notification)
    source_event_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="ID of domain event that triggered notification",
    )
    source_entity_type: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        index=True,
        comment="Type of entity that triggered notification (e.g., 'reminder', 'file')",
    )
    source_entity_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
        comment="ID of entity that triggered notification",
    )

    # Correlation for distributed tracing
    correlation_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Correlation ID for distributed tracing",
    )
    extra_metadata: Mapped[dict | None] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"),
        nullable=True,
        comment="Additional metadata (flexible JSONB)",
    )

    # UI features (from accent-doc notifications)
    actions: Mapped[list | None] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"),
        nullable=True,
        comment="Action buttons for UI (e.g., [{label, action, variant}])",
    )
    progress: Mapped[int | None] = mapped_column(
        Integer(),
        nullable=True,
        comment="Progress percentage (0-100) for progress notifications",
    )
    group_key: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
        comment="Key for grouping related notifications",
    )
    auto_dismiss: Mapped[bool] = mapped_column(
        Boolean(),
        default=False,
        nullable=False,
        comment="Whether notification auto-dismisses after timeout",
    )
    dismiss_after: Mapped[int | None] = mapped_column(
        Integer(),
        nullable=True,
        comment="Auto-dismiss timeout in milliseconds",
    )

    # Read status (in-app notifications only)
    read: Mapped[bool] = mapped_column(
        Boolean(),
        default=False,
        nullable=False,
        index=True,
        comment="Whether notification has been read (in-app only)",
    )
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When notification was marked as read",
    )

    # Expiration
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
        comment="When notification expires and can be cleaned up",
    )

    # Relationships
    deliveries: Mapped[list[NotificationDelivery]] = relationship(
        "NotificationDelivery",
        back_populates="notification",
        cascade="all, delete-orphan",
        lazy="select",
    )

    __table_args__ = (
        Index("idx_notification_user_tenant_status", "user_id", "tenant_id", "status"),
        Index("idx_notification_type_status", "notification_type", "status"),
        Index("idx_notification_scheduled_status", "scheduled_for", "status"),
        Index("idx_notification_source", "source_entity_type", "source_entity_id"),
    )


class NotificationDelivery(UUIDv7TimestampedBase):
    """Delivery attempt record for a specific channel.

    Tracks individual delivery attempts per channel (email, webhook, websocket, in_app)
    with status, retry management, and response tracking.

    Provides:
    - Delivery status per channel (pending, delivered, failed, retrying)
    - Retry logic with exponential backoff
    - Channel-specific metadata (message IDs, URLs, etc.)
    - Response tracking (status codes, timing, errors)

    One Notification can have multiple NotificationDelivery records (one per channel).

    Indexes:
        - (notification_id, channel) for finding delivery by notification+channel
        - (status, next_retry_at) for retry processing
        - (channel, status) for channel-specific monitoring
    """

    __tablename__ = "notification_deliveries"

    # Parent notification
    notification_id: Mapped[UUID] = mapped_column(
        ForeignKey("notifications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Reference to parent notification",
    )
    channel: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        comment="Delivery channel: email, webhook, websocket, in_app",
    )

    # Status
    status: Mapped[str] = mapped_column(
        String(20),
        default="pending",
        nullable=False,
        index=True,
        comment="Delivery status: pending, delivered, failed, retrying",
    )

    # Retry management
    attempt_count: Mapped[int] = mapped_column(
        Integer(),
        default=0,
        nullable=False,
        comment="Number of delivery attempts made",
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer(),
        default=5,
        nullable=False,
        comment="Maximum attempts allowed before giving up",
    )
    next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
        comment="Scheduled time for next retry attempt",
    )

    # Channel-specific identifiers
    email_message_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Email provider message ID (for email channel)",
    )
    email_recipient: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Email recipient address (for email channel)",
    )
    webhook_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("webhooks.id", ondelete="SET NULL"),
        nullable=True,
        comment="Reference to webhook configuration (for webhook channel)",
    )
    webhook_url: Mapped[str | None] = mapped_column(
        String(2048),
        nullable=True,
        comment="Webhook URL used (for webhook channel)",
    )
    websocket_channel: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="WebSocket channel/room used (for websocket channel)",
    )
    websocket_connection_count: Mapped[int | None] = mapped_column(
        Integer(),
        nullable=True,
        comment="Number of WebSocket connections delivered to",
    )

    # Response tracking
    response_status_code: Mapped[int | None] = mapped_column(
        Integer(),
        nullable=True,
        comment="HTTP response status code (email/webhook)",
    )
    response_body: Mapped[str | None] = mapped_column(
        Text(),
        nullable=True,
        comment="Response body (truncated, for debugging)",
    )
    response_time_ms: Mapped[int | None] = mapped_column(
        Integer(),
        nullable=True,
        comment="Response time in milliseconds",
    )

    # Error tracking
    error_message: Mapped[str | None] = mapped_column(
        Text(),
        nullable=True,
        comment="Error message if delivery failed",
    )
    error_category: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="Error category for classification (network, auth, etc.)",
    )

    # Timestamps
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When delivery succeeded",
    )
    failed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When delivery permanently failed (exhausted retries)",
    )

    # Relationship to parent notification
    notification: Mapped[Notification] = relationship(
        "Notification",
        back_populates="deliveries",
        lazy="select",
    )

    __table_args__ = (
        Index("idx_delivery_notification_channel", "notification_id", "channel"),
        Index("idx_delivery_status_retry", "status", "next_retry_at"),
        Index("idx_delivery_channel_status", "channel", "status"),
    )
