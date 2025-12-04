"""Feature flag database models.

Provides persistent storage for feature flag configurations.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import Boolean, DateTime, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from example_service.core.database.base import Base, TimestampMixin, UUIDv7PKMixin
from example_service.core.database.enums import FlagStatus as FlagStatusEnum


class FlagStatus(StrEnum):
    """Feature flag status."""

    ENABLED = "enabled"
    DISABLED = "disabled"
    PERCENTAGE = "percentage"  # Gradual rollout
    TARGETED = "targeted"  # Specific users/tenants


class FeatureFlag(Base, UUIDv7PKMixin, TimestampMixin):
    """Feature flag configuration.

    Stores feature flags with support for:
    - Simple on/off toggles
    - Percentage-based rollout
    - User/tenant targeting
    - Time-based activation

    Attributes:
        key: Unique flag identifier (e.g., "new_dashboard").
        name: Human-readable name.
        description: Description of what the flag controls.
        status: Current status (enabled, disabled, percentage, targeted).
        enabled: Whether the flag is globally enabled.
        percentage: Rollout percentage (0-100) for gradual rollout.
        targeting_rules: JSON rules for targeted rollout.
        metadata: Additional flag metadata.
        starts_at: Optional start time for time-based activation.
        ends_at: Optional end time for time-based activation.
    """

    __tablename__ = "feature_flags"

    # Flag identification
    key: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
        index=True,
        comment="Unique flag key",
    )
    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        comment="Human-readable name",
    )
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Flag description",
    )

    # Flag state
    status: Mapped[str] = mapped_column(
        FlagStatusEnum,
        nullable=False,
        default="disabled",
        comment="Flag status",
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="Global enabled state",
    )
    percentage: Mapped[int] = mapped_column(
        nullable=False,
        default=0,
        comment="Rollout percentage (0-100)",
    )

    # Targeting configuration
    targeting_rules: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="Targeting rules for selective rollout",
    )

    # Metadata (column name preserved as 'metadata')
    context_data: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
        comment="Additional flag metadata",
    )

    # Time-based activation
    starts_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Activation start time",
    )
    ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Activation end time",
    )

    __table_args__ = (
        Index("ix_feature_flags_status", "status"),
        Index("ix_feature_flags_enabled", "enabled"),
    )

    def is_active(self, now: datetime | None = None) -> bool:
        """Check if the flag is currently active based on time constraints.

        Args:
            now: Current time (defaults to UTC now).

        Returns:
            True if within active time window or no time constraints.
        """
        if now is None:
            now = datetime.utcnow()

        if self.starts_at and now < self.starts_at:
            return False
        return not (self.ends_at and now > self.ends_at)


class FlagOverride(Base, UUIDv7PKMixin, TimestampMixin):
    """User or tenant-specific flag override.

    Allows overriding flag values for specific users or tenants.

    Attributes:
        flag_key: The feature flag key.
        entity_type: Type of entity (user, tenant).
        entity_id: ID of the entity.
        enabled: Override value.
        reason: Why this override was created.
    """

    __tablename__ = "flag_overrides"

    flag_key: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        comment="Feature flag key",
    )
    entity_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="Entity type (user, tenant)",
    )
    entity_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="Entity ID",
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        comment="Override value",
    )
    reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Reason for override",
    )

    __table_args__ = (
        Index("ix_flag_overrides_lookup", "flag_key", "entity_type", "entity_id", unique=True),
        Index("ix_flag_overrides_entity", "entity_type", "entity_id"),
    )


__all__ = ["FeatureFlag", "FlagOverride", "FlagStatus"]
