"""SQLAlchemy models for the webhooks feature."""

from __future__ import annotations

import json
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    TypeDecorator,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from example_service.core.database import TenantMixin, TimestampedBase
from example_service.core.database.enums import DeliveryStatus as DeliveryStatusEnum


class StringArray(TypeDecorator):
    """Cross-database type for string arrays.

    Uses native ARRAY in PostgreSQL, JSON in SQLite/other databases.
    """

    impl = Text
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(ARRAY(String(100)))
        else:
            return dialect.type_descriptor(Text())

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        if dialect.name == "postgresql":
            return value
        return json.dumps(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return []
        if dialect.name == "postgresql":
            return value
        return json.loads(value) if value else []


class Webhook(TimestampedBase, TenantMixin):
    """Webhook configuration persisted in the database.

    Represents a webhook endpoint that will receive HTTP POST notifications
    when subscribed events occur in the system.

    Multi-tenancy is supported via tenant_id to ensure webhook configurations
    and deliveries are isolated per tenant. Webhooks from one tenant should
    never trigger for events in another tenant's data.
    """

    __tablename__ = "webhooks"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(
        String(200), nullable=False, comment="Human-readable webhook name"
    )
    description: Mapped[str | None] = mapped_column(
        Text(), nullable=True, comment="Webhook description"
    )
    url: Mapped[str] = mapped_column(
        String(2048), nullable=False, comment="Target URL for webhook delivery"
    )
    secret: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="HMAC secret for signing payloads"
    )
    event_types: Mapped[list[str]] = mapped_column(
        StringArray(),
        nullable=False,
        default=list,
        comment="List of event types this webhook subscribes to",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean(), default=True, nullable=False, comment="Whether webhook is active"
    )
    max_retries: Mapped[int] = mapped_column(
        Integer(), default=5, nullable=False, comment="Maximum delivery retry attempts"
    )
    timeout_seconds: Mapped[int] = mapped_column(
        Integer(), default=30, nullable=False, comment="HTTP request timeout in seconds"
    )
    custom_headers: Mapped[dict | None] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"),
        nullable=True,
        comment="Additional HTTP headers to include in requests",
    )

    # Relationship to deliveries
    deliveries: Mapped[list[WebhookDelivery]] = relationship(
        "WebhookDelivery",
        back_populates="webhook",
        cascade="all, delete-orphan",
        lazy="select",
    )


class WebhookDelivery(TimestampedBase):
    """Webhook delivery attempt record.

    Tracks individual attempts to deliver webhook events, including
    status, retries, responses, and error information.
    """

    __tablename__ = "webhook_deliveries"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    webhook_id: Mapped[UUID] = mapped_column(
        ForeignKey("webhooks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Reference to webhook configuration",
    )
    event_type: Mapped[str] = mapped_column(
        String(100), nullable=False, index=True, comment="Type of event being delivered"
    )
    event_id: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True, comment="Unique identifier for the event"
    )
    payload: Mapped[dict] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"), nullable=False, comment="Event payload data"
    )
    status: Mapped[str] = mapped_column(
        DeliveryStatusEnum,
        nullable=False,
        default="pending",
        index=True,
        comment="Delivery status: pending, delivered, failed, retrying",
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer(), default=0, nullable=False, comment="Number of delivery attempts made"
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer(), default=5, nullable=False, comment="Maximum attempts allowed"
    )
    next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
        comment="Scheduled time for next retry attempt",
    )
    response_status_code: Mapped[int | None] = mapped_column(
        Integer(), nullable=True, comment="HTTP response status code"
    )
    response_body: Mapped[str | None] = mapped_column(
        Text(), nullable=True, comment="HTTP response body (truncated)"
    )
    response_time_ms: Mapped[int | None] = mapped_column(
        Integer(), nullable=True, comment="Response time in milliseconds"
    )
    error_message: Mapped[str | None] = mapped_column(
        Text(), nullable=True, comment="Error message if delivery failed"
    )

    # Relationship to webhook
    webhook: Mapped[Webhook] = relationship("Webhook", back_populates="deliveries", lazy="select")
