"""Tenant-related schemas and models."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field


class TenantContext(BaseModel):
    """Tenant context for the current request.

    This model holds tenant information that is propagated
    throughout the request lifecycle via context variables.
    """

    tenant_id: str = Field(description="Tenant identifier")
    identified_by: str | None = Field(
        default=None,
        description="How the tenant was identified (header, subdomain, jwt, etc.)",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="When the context was created",
    )

    class Config:
        """Pydantic model configuration."""

        frozen = True  # Make immutable


class TenantInfo(BaseModel):
    """Tenant information model."""

    tenant_id: str = Field(description="Unique tenant identifier")
    name: str = Field(description="Tenant display name")
    slug: str = Field(description="URL-safe tenant slug")
    is_active: bool = Field(default=True, description="Whether tenant is active")
    created_at: datetime = Field(description="Creation timestamp")
    updated_at: datetime = Field(description="Last update timestamp")
    metadata: dict = Field(default_factory=dict, description="Additional tenant metadata")


class TenantCreate(BaseModel):
    """Schema for creating a new tenant."""

    name: str = Field(min_length=1, max_length=255, description="Tenant display name")
    slug: str = Field(
        min_length=1,
        max_length=63,
        pattern=r"^[a-z0-9-]+$",
        description="URL-safe tenant slug",
    )
    metadata: dict = Field(default_factory=dict, description="Additional tenant metadata")


class TenantUpdate(BaseModel):
    """Schema for updating a tenant."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    is_active: bool | None = Field(default=None)
    metadata: dict | None = Field(default=None)
