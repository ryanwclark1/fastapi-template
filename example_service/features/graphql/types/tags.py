"""GraphQL types for tags feature.

Provides Strawberry GraphQL types for tag management with full Pydantic integration.
Tags can be used to categorize and organize reminders.

Auto-generated from Pydantic schemas:
- TagType: Auto-generated from TagResponse
- CreateTagInput: Auto-generated from TagCreate
- UpdateTagInput: Auto-generated from TagUpdate
"""

from __future__ import annotations

from enum import Enum

import strawberry

from example_service.features.graphql.types.base import PageInfoType
from example_service.features.graphql.types.pydantic_bridge import (
    pydantic_field,
    pydantic_input,
    pydantic_type,
)
from example_service.features.tags.schemas import TagCreate, TagResponse, TagUpdate
from example_service.utils.runtime_dependencies import require_runtime_dependency

require_runtime_dependency(PageInfoType)

# ============================================================================
# Tag Type (Output)
# ============================================================================


@pydantic_type(model=TagResponse, description="A tag for categorizing reminders")
class TagType:
    """Tag type auto-generated from TagResponse Pydantic schema.

    Tags allow organizing reminders into categories like:
    - "work", "personal", "health"
    - "urgent", "low-priority"
    - "project-alpha", "quarterly-review"

    A reminder can have multiple tags, and a tag can be applied to many reminders.

    All fields are auto-generated from the Pydantic TagResponse schema.
    Changes to the Pydantic schema automatically propagate here.
    """

    # Override ID field to use Strawberry's ID scalar
    id: strawberry.ID = pydantic_field(description="Unique identifier for the tag")

    # Computed fields
    @strawberry.field(description="Number of reminders with this tag")
    def reminder_count(self) -> int:
        """Get count of reminders with this tag.

        Note: This is computed on-demand. For efficiency with lists,
        use the TagWithCountResponse schema which includes the count.
        """
        if hasattr(self, "reminders"):
            return len(self.reminders)
        return 0


# ============================================================================
# Input Types
# ============================================================================


@pydantic_input(
    model=TagCreate,
    fields=["name", "color", "description"],
    description="Input for creating a new tag",
)
class CreateTagInput:
    """Input for creating a new tag.

    Auto-generated from TagCreate Pydantic schema.
    Pydantic validators run automatically:
    - name: normalized to lowercase, stripped
    - color: validated as hex color (#RRGGBB)
    - description: max 200 characters
    """


@pydantic_input(
    model=TagUpdate,
    fields=["name", "color", "description"],
    description="Input for updating an existing tag",
)
class UpdateTagInput:
    """Input for updating an existing tag.

    All fields are optional - only provided fields are updated.
    Auto-generated from TagUpdate Pydantic schema.
    """


# ============================================================================
# Union Types for Responses
# ============================================================================


@strawberry.type(description="Tag created or updated successfully")
class TagSuccess:
    """Successful tag operation response."""

    tag: TagType


@strawberry.enum(description="Tag error codes")
class TagErrorCode(str, Enum):
    """Error codes for tag operations."""

    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOT_FOUND = "NOT_FOUND"
    DUPLICATE_NAME = "DUPLICATE_NAME"
    IN_USE = "IN_USE"  # Tag is in use and cannot be deleted
    INTERNAL_ERROR = "INTERNAL_ERROR"


@strawberry.type(description="Tag operation error")
class TagError:
    """Error response for tag operations."""

    code: TagErrorCode
    message: str
    field: str | None = None


# Union type for mutations
TagPayload = strawberry.union("TagPayload", (TagSuccess, TagError))


@strawberry.type(description="Generic success/failure response")
class DeletePayload:
    """Response for delete operations."""

    success: bool
    message: str


# ============================================================================
# Edge and Connection Types for Pagination
# ============================================================================


@strawberry.type(description="Edge containing a tag node and cursor")
class TagEdge:
    """Edge in a Relay-style connection."""

    node: TagType
    cursor: str


@strawberry.type(description="Paginated list of tags")
class TagConnection:
    """Relay-style connection for tag pagination."""

    edges: list[TagEdge]
    page_info: PageInfoType


# ============================================================================
# Migration Notes
# ============================================================================

"""
Migration from Manual Types to Pydantic Integration:

BEFORE (Manual Field Definitions):
    @strawberry.type
    class TagType:
        id: strawberry.ID
        name: str
        color: str | None
        description: str | None
        created_at: datetime
        updated_at: datetime

        @classmethod
        def from_model(cls, tag: Tag) -> TagType:
            return cls(
                id=strawberry.ID(str(tag.id)),
                name=tag.name,
                color=tag.color,
                description=tag.description,
                created_at=tag.created_at,
                updated_at=tag.updated_at,
            )

AFTER (Pydantic Auto-Generation):
    @pydantic_type(model=TagResponse)
    class TagType:
        id: strawberry.ID = pydantic_field(...)

Benefits:
1. ~60% less code (5 lines vs 15 lines for type definition)
2. Single source of truth (Pydantic schema)
3. Automatic validation propagation
4. Type safety guaranteed
5. No manual conversion methods needed

Usage in Resolvers:
    # Two-stage conversion: SQLAlchemy → Pydantic → GraphQL
    tag_pydantic = TagResponse.from_model(tag)
    return TagType.from_pydantic(tag_pydantic)

Computed Fields:
    Computed fields (like reminder_count) are added as @strawberry.field
    methods on the auto-generated type. These don't exist in the Pydantic
    schema but provide rich functionality in GraphQL.
"""


# ============================================================================
# Subscription Event Types
# ============================================================================


@strawberry.enum(description="Types of tag events for subscriptions")
class TagEventType(str, Enum):
    """Event types for tag subscriptions.

    Clients can subscribe to specific event types or all events.
    """

    CREATED = "CREATED"
    UPDATED = "UPDATED"
    DELETED = "DELETED"


@strawberry.type(description="Real-time tag event via subscription")
class TagEvent:
    """Event payload for tag subscriptions.

    Pushed to subscribed clients when tags are created, updated, or deleted.
    """

    event_type: TagEventType = strawberry.field(description="Type of event that occurred")
    tag: TagType | None = strawberry.field(
        default=None,
        description="Tag data (null for DELETED events)",
    )
    tag_id: strawberry.ID = strawberry.field(description="Tag ID")


__all__ = [
    "CreateTagInput",
    "DeletePayload",
    "TagConnection",
    "TagEdge",
    "TagError",
    "TagErrorCode",
    "TagEvent",
    "TagEventType",
    "TagPayload",
    "TagSuccess",
    "TagType",
    "UpdateTagInput",
]
