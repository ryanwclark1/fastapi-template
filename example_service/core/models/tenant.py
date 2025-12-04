"""Tenant model for multi-tenancy support.

This is a basic tenant model that can be extended with additional fields
as needed for your specific use case.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from example_service.core.database import Base, TimestampMixin

if TYPE_CHECKING:
    from example_service.core.models.email_config import EmailConfig
    from example_service.features.ai.models import (
        TenantAIConfig,
        TenantAIFeature,
    )


class Tenant(Base, TimestampMixin):
    """Tenant model for multi-tenant application.

    Represents an organization or customer using the system.
    All tenant-specific data should be linked via tenant_id.

    Attributes:
        id: Unique tenant identifier (string for flexibility)
        name: Tenant display name
        is_active: Whether tenant is currently active
        ai_configs: Tenant-specific AI provider configurations
        ai_features: AI feature flags and settings
        email_configs: Tenant-specific email provider configuration
    """

    __tablename__ = "tenants"

    # Use string ID for tenant to support external IDs from accent-auth
    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)

    # AI-related relationships
    ai_configs: Mapped[list["TenantAIConfig"]] = relationship(
        "TenantAIConfig",
        back_populates="tenant",
        cascade="all, delete-orphan",
        lazy="select",
    )
    ai_features: Mapped["TenantAIFeature | None"] = relationship(
        "TenantAIFeature",
        back_populates="tenant",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="select",
    )
    # Note: AIJob and AIUsageLog have relationships to Tenant but not vice versa
    # to avoid circular dependencies and unnecessary loading

    # Email configuration (one config per tenant)
    email_configs: Mapped["EmailConfig | None"] = relationship(
        "EmailConfig",
        back_populates="tenant",
        uselist=False,  # One-to-one: one config per tenant
        cascade="all, delete-orphan",
        lazy="select",
    )

    def __repr__(self) -> str:
        return f"<Tenant(id={self.id}, name={self.name})>"
