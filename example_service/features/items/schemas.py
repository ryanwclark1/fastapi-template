"""Pydantic schemas for Items API."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ItemBase(BaseModel):
    """Base schema for Item with common fields."""

    title: str = Field(..., min_length=1, max_length=200, description="Item title")
    description: str | None = Field(None, description="Item description")
    is_completed: bool = Field(default=False, description="Completion status")


class ItemCreate(ItemBase):
    """Schema for creating a new item.

    Example:
        ```json
        {
            "title": "Buy groceries",
            "description": "Milk, eggs, bread",
            "is_completed": false
        }
        ```
    """

    pass


class ItemUpdate(BaseModel):
    """Schema for updating an existing item.

    All fields are optional for partial updates.

    Example:
        ```json
        {
            "title": "Buy groceries (updated)",
            "is_completed": true
        }
        ```
    """

    title: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = None
    is_completed: bool | None = None


class ItemResponse(ItemBase):
    """Schema for item responses.

    Includes all fields plus metadata.

    Example:
        ```json
        {
            "id": "123e4567-e89b-12d3-a456-426614174000",
            "title": "Buy groceries",
            "description": "Milk, eggs, bread",
            "is_completed": false,
            "owner_id": "user-123",
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-01T00:00:00Z"
        }
        ```
    """

    id: UUID
    owner_id: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ItemListResponse(BaseModel):
    """Schema for paginated item list responses.

    Example:
        ```json
        {
            "items": [...],
            "total": 42,
            "page": 1,
            "page_size": 10,
            "pages": 5
        }
        ```
    """

    items: list[ItemResponse]
    total: int
    page: int = 1
    page_size: int = 10
    pages: int

    model_config = ConfigDict(from_attributes=True)
