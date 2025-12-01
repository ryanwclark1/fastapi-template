"""Base schema classes for API responses."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class CustomBase(BaseModel):
    """Base model with common configuration for all schemas.

    Provides standardized datetime serialization and common settings
    that should be applied across all Pydantic models in the application.

    Example:
            class UserResponse(CustomBase):
            id: str
            email: str
            created_at: datetime
    """

    model_config = ConfigDict(
        # Allow creation from ORM models (SQLAlchemy)
        from_attributes=True,
        # Validate on assignment (not just initialization)
        validate_assignment=True,
        # Use enum values instead of names
        use_enum_values=True,
        # Populate models by field name (not alias)
        populate_by_name=True,
        # Ignore extra fields for security (silently drop unexpected data)
        extra="ignore",
        # Strip leading/trailing whitespace from strings
        str_strip_whitespace=True,
    )


class TimestampedBase(CustomBase):
    """Base model with timestamp fields.

    Includes created_at and updated_at timestamp fields
    that are common across many models.
    """

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Creation timestamp",
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Last update timestamp",
    )


class UUIDMixin(BaseModel):
    """Mixin for schemas that include a UUID identifier.

    Example:
        class UserSchema(CustomBase, UUIDMixin):
            username: str

        user = UserSchema(uuid="550e8400-e29b-41d4-a716-446655440000", username="john")
    """

    uuid: str = Field(..., description="Unique identifier (UUID)")


class TenantMixin(BaseModel):
    """Mixin for schemas that include tenant information.

    Example:
        class UserSchema(CustomBase, TenantMixin):
            username: str

        user = UserSchema(tenant_uuid="550e8400-e29b-41d4-a716-446655440000", username="john")
    """

    tenant_uuid: str = Field(..., description="Tenant UUID")


class APIResponse[T](BaseModel):
    """Generic API response wrapper.

    Wraps response data in a consistent structure with metadata.

    Example:
            @router.get("/items", response_model=APIResponse[list[Item]])
        async def list_items() -> APIResponse[list[Item]]:
            items = await get_items()
            return APIResponse(
                data=items,
                message="Items retrieved successfully"
            )
    """

    success: bool = Field(default=True, description="Operation success status")
    message: str | None = Field(default=None, description="Response message")
    data: T | None = Field(default=None, description="Response data")


class PaginatedResponse[T](BaseModel):
    """Paginated response wrapper.

    Wraps paginated data with pagination metadata.

    Example:
            @router.get("/items", response_model=PaginatedResponse[Item])
        async def list_items(page: int = 1, page_size: int = 20):
            items, total = await get_paginated_items(page, page_size)
            return PaginatedResponse.create(
                items=items,
                total=total,
                page=page,
                page_size=page_size
            )
    """

    items: list[T] = Field(default_factory=list, description="Paginated items")
    total: int = Field(ge=0, description="Total number of items")
    page: int = Field(ge=1, description="Current page number")
    page_size: int = Field(ge=1, le=1000, description="Items per page")
    total_pages: int = Field(ge=0, description="Total number of pages")

    @classmethod
    def create(cls, items: list[T], total: int, page: int, page_size: int) -> PaginatedResponse[T]:
        """Create paginated response with calculated total pages.

        Args:
            items: List of items for current page.
            total: Total number of items.
            page: Current page number.
            page_size: Number of items per page.

        Returns:
            PaginatedResponse instance with calculated fields.

        Raises:
            ValueError: If total, page, or page_size are invalid.
        """
        if total < 0:
            raise ValueError("Total must be non-negative")
        if page < 1:
            raise ValueError("Page must be at least 1")
        if page_size < 1 or page_size > 1000:
            raise ValueError("Page size must be between 1 and 1000")

        total_pages = (total + page_size - 1) // page_size if total > 0 else 0
        return cls(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )


__all__ = [
    "APIResponse",
    "CustomBase",
    "PaginatedResponse",
    "TenantMixin",
    "TimestampedBase",
    "UUIDMixin",
]
