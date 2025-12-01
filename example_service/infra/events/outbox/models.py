"""EventOutbox SQLAlchemy model for the transactional outbox pattern.

The outbox table stores events that need to be published to the message broker.
Events are written to this table in the same transaction as domain changes,
ensuring that either both succeed or both fail.

A background processor reads from this table and publishes events to RabbitMQ,
marking them as processed upon successful delivery.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from example_service.core.database.base import Base, TimestampMixin, UUIDv7PKMixin


class EventOutbox(Base, UUIDv7PKMixin, TimestampMixin):
    """Outbox table for reliable event publishing.

    Events are staged here before being published to the message broker.
    The background processor polls this table and publishes pending events.

    Attributes:
        id: UUID v7 primary key (time-sortable for FIFO processing)
        event_type: Event type identifier (e.g., "user.created")
        event_version: Schema version for the event
        payload: JSON-serialized event data
        correlation_id: Distributed tracing correlation ID
        aggregate_type: Optional aggregate type (e.g., "User", "Order")
        aggregate_id: Optional aggregate ID for partitioning
        processed_at: When the event was successfully published
        retry_count: Number of failed publish attempts
        error_message: Last error message if publishing failed
        next_retry_at: Scheduled time for next retry attempt

    The table uses indexes optimized for the processor's query patterns:
    - Unprocessed events ordered by creation time
    - Events by aggregate for ordered delivery per entity
    """

    __tablename__ = "event_outbox"

    # Event identification
    event_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        comment="Event type identifier",
    )
    event_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        comment="Event schema version",
    )

    # Event payload (JSON)
    payload: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="JSON-serialized event data",
    )

    # Tracing and context
    correlation_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
        index=True,
        comment="Distributed tracing correlation ID",
    )

    # Aggregate context (for ordered delivery per entity)
    aggregate_type: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="Aggregate type (e.g., User, Order)",
    )
    aggregate_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="Aggregate ID for partitioned processing",
    )

    # Processing state
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
        comment="When the event was successfully published",
    )
    retry_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Number of failed publish attempts",
    )
    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Last error message if publishing failed",
    )
    next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
        comment="Scheduled time for next retry attempt",
    )

    # Composite indexes for efficient queries
    __table_args__ = (
        # Index for fetching unprocessed events in order
        Index(
            "ix_event_outbox_pending",
            "processed_at",
            "next_retry_at",
            "created_at",
            postgresql_where=(processed_at.is_(None)),  # Partial index
        ),
        # Index for ordered delivery per aggregate
        Index(
            "ix_event_outbox_aggregate",
            "aggregate_type",
            "aggregate_id",
            "created_at",
        ),
    )

    @property
    def is_processed(self) -> bool:
        """Check if event has been successfully published."""
        return self.processed_at is not None

    @property
    def can_retry(self) -> bool:
        """Check if event is eligible for retry."""
        if self.is_processed:
            return False
        if self.next_retry_at is None:
            return True
        from datetime import UTC, datetime as dt

        return dt.now(UTC) >= self.next_retry_at

    def __repr__(self) -> str:
        """Human-readable representation."""
        status = "processed" if self.is_processed else f"pending (retries={self.retry_count})"
        return (
            f"EventOutbox("
            f"id={self.id}, "
            f"event_type={self.event_type!r}, "
            f"status={status}"
            f")"
        )


__all__ = ["EventOutbox"]
