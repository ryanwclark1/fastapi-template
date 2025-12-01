"""Pydantic schemas for the tags feature."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TagBase(BaseModel):
    """Shared attributes for tag payloads."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Unique tag name (e.g., 'work', 'urgent')",
    )
    color: str | None = Field(
        default=None,
        pattern=r"^#[0-9A-Fa-f]{6}$",
        description="Hex color code (e.g., '#FF5733')",
    )
    description: str | None = Field(
        default=None,
        max_length=200,
        description="Optional description of the tag's purpose",
    )

    @field_validator("name")
    @classmethod
    def normalize_name(cls, v: str) -> str:
        """Normalize tag name to lowercase with no leading/trailing whitespace."""
        return v.strip().lower()


class TagCreate(TagBase):
    """Payload used when creating a tag."""


class TagUpdate(BaseModel):
    """Payload for updating a tag."""

    name: str | None = Field(default=None, min_length=1, max_length=50)
    color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    description: str | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, v: str | None) -> str | None:
        """Normalize tag name if provided."""
        if v is not None:
            return v.strip().lower()
        return v


class TagResponse(TagBase):
    """Representation returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
    updated_at: datetime


class TagWithCountResponse(TagResponse):
    """Tag response including reminder count."""

    reminder_count: int = Field(
        default=0,
        description="Number of reminders with this tag",
    )


class TagListResponse(BaseModel):
    """Response containing a list of tags."""

    tags: list[TagWithCountResponse]
    total: int


class ReminderTagsUpdate(BaseModel):
    """Payload for updating tags on a reminder."""

    tag_ids: list[UUID] = Field(
        ...,
        description="List of tag IDs to assign to the reminder",
    )


class AddTagsRequest(BaseModel):
    """Payload for adding tags to a reminder."""

    tag_ids: list[UUID] = Field(
        ...,
        min_length=1,
        description="Tag IDs to add",
    )


class RemoveTagsRequest(BaseModel):
    """Payload for removing tags from a reminder."""

    tag_ids: list[UUID] = Field(
        ...,
        min_length=1,
        description="Tag IDs to remove",
    )


__all__ = [
    "TagBase",
    "TagCreate",
    "TagUpdate",
    "TagResponse",
    "TagWithCountResponse",
    "TagListResponse",
    "ReminderTagsUpdate",
    "AddTagsRequest",
    "RemoveTagsRequest",
]
