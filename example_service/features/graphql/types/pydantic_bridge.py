"""Bridge utilities for converting Pydantic models to Strawberry GraphQL types.

This module provides centralized patterns for the experimental Pydantic integration,
making it easy to maintain consistency and upgrade Strawberry versions in the future.

Usage:
    from example_service.features.graphql.types.pydantic_bridge import pydantic_type, pydantic_input

    @pydantic_type(model=MyPydanticModel)
    class MyGraphQLType:
        '''Auto-generated from MyPydanticModel'''
        pass
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypeVar
from uuid import UUID as PyUUID

import strawberry
from strawberry.experimental import pydantic

if TYPE_CHECKING:
    from pydantic import BaseModel

__all__ = [
    "UUIDScalar",
    "create_connection_type",
    "create_edge_type",
    "pydantic_field",
    "pydantic_input",
    "pydantic_interface",
    "pydantic_type",
]

# Type variables
T = TypeVar("T", bound="BaseModel")

# ============================================================================
# Re-export experimental Pydantic decorators for convenience
# ============================================================================

pydantic_type = pydantic.type
"""Decorator to create Strawberry type from Pydantic model.

Example:
    @pydantic_type(model=ReminderResponse, all_fields=True)
    class ReminderType:
        pass
"""

pydantic_input = pydantic.input
"""Decorator to create Strawberry input type from Pydantic model.

Example:
    @pydantic_input(model=ReminderCreate)
    class CreateReminderInput:
        pass
"""

pydantic_interface = pydantic.interface
"""Decorator to create Strawberry interface from Pydantic model."""

# Note: strawberry.experimental.pydantic doesn't have a .field attribute
# Use strawberry.field directly for field overrides
pydantic_field = strawberry.field
"""Field configuration for Pydantic-generated Strawberry types.

Example:
    @pydantic_type(model=ReminderResponse)
    class ReminderType:
        id: strawberry.ID = pydantic_field(description="Unique identifier")
"""

# ============================================================================
# Custom Scalars
# ============================================================================

UUIDScalar = strawberry.scalar(
    PyUUID,
    serialize=lambda v: str(v),
    parse_value=lambda v: PyUUID(str(v)),
    description="UUID scalar type that serializes to string",
    name="UUID",
)
"""Custom UUID scalar for GraphQL that automatically converts to/from strings.

This scalar handles the conversion between Python UUID objects and GraphQL
string representations, making it easier to work with UUIDs in resolvers.

Example:
    @strawberry.type
    class SomeType:
        id: UUIDScalar
"""

# ============================================================================
# Field Configuration Helpers
# ============================================================================


def custom_field(
    *,
    description: str | None = None,
    deprecation_reason: str | None = None,
    permission_classes: list | None = None,
) -> Any:
    """Configure a field in a Pydantic-generated type with GraphQL-specific options.

    This helper makes it easier to add GraphQL-specific configuration to fields
    that are auto-generated from Pydantic models.

    Args:
        description: GraphQL field description
        deprecation_reason: Deprecation message for the field
        permission_classes: Strawberry permission classes for field-level auth

    Returns:
        Configured Strawberry field

    Example:
        @pydantic_type(model=UserResponse)
        class UserType:
            email: str = custom_field(
                description="User email address",
                permission_classes=[IsAuthenticated]
            )
    """
    return strawberry.field(
        description=description,
        deprecation_reason=deprecation_reason,
        permission_classes=permission_classes or [],
    )


# ============================================================================
# Pagination Helpers
# ============================================================================


def create_edge_type(node_type: type, type_name: str | None = None) -> type:
    """Create a Relay-compliant Edge type for a given node type.

    Args:
        node_type: The Strawberry type to create an edge for
        type_name: Optional custom name for the edge type (default: {NodeType}Edge)

    Returns:
        A Strawberry type representing an edge in the connection

    Example:
        ReminderEdge = create_edge_type(ReminderType)

        # Produces:
        # @strawberry.type
        # class ReminderEdge:
        #     node: ReminderType
        #     cursor: str
    """
    if type_name is None:
        type_name = f"{node_type.__name__}Edge"

    @strawberry.type(name=type_name, description=f"Edge for {node_type.__name__}")
    class Edge:
        node: node_type = strawberry.field(description="The node containing the data")
        cursor: str = strawberry.field(description="Cursor for this edge")

    return Edge


def create_connection_type(
    node_type: type,
    page_info_type: type,
    type_name: str | None = None,
) -> type:
    """Create a Relay-compliant Connection type for a given node type.

    Args:
        node_type: The Strawberry type to create a connection for
        page_info_type: The PageInfo type to use (typically PageInfoType)
        type_name: Optional custom name (default: {NodeType}Connection)

    Returns:
        A Strawberry type representing a connection

    Example:
        from example_service.features.graphql.types.base import PageInfoType

        ReminderConnection = create_connection_type(ReminderType, PageInfoType)

        # Produces:
        # @strawberry.type
        # class ReminderConnection:
        #     edges: list[ReminderEdge]
        #     page_info: PageInfoType
    """
    if type_name is None:
        type_name = f"{node_type.__name__}Connection"

    edge_type = create_edge_type(node_type)

    @strawberry.type(name=type_name, description=f"Connection for {node_type.__name__}")
    class Connection:
        edges: list[edge_type] = strawberry.field(
            description="List of edges containing nodes and cursors",
        )
        page_info: page_info_type = strawberry.field(
            description="Information about pagination",
        )

    return Connection


# ============================================================================
# Conversion Helpers
# ============================================================================


def pydantic_to_strawberry(
    pydantic_obj: BaseModel,
    strawberry_type: type,
) -> Any:
    """Convert a Pydantic model instance to a Strawberry type instance.

    This is a convenience wrapper around the from_pydantic() method that's
    automatically generated by @pydantic.type.

    Args:
        pydantic_obj: The Pydantic model instance to convert
        strawberry_type: The target Strawberry type (must be decorated with @pydantic.type)

    Returns:
        An instance of the Strawberry type

    Example:
        reminder = ReminderResponse(id=uuid4(), title="Test")
        reminder_gql = pydantic_to_strawberry(reminder, ReminderType)
    """
    if not hasattr(strawberry_type, "from_pydantic"):
        msg = (
            f"{strawberry_type.__name__} must be decorated with @pydantic.type "
            "to use pydantic_to_strawberry()"
        )
        raise ValueError(
            msg,
        )

    return strawberry_type.from_pydantic(pydantic_obj)


def strawberry_to_pydantic(
    strawberry_obj: Any,
) -> BaseModel:
    """Convert a Strawberry type instance to a Pydantic model instance.

    This is a convenience wrapper around the to_pydantic() method that's
    automatically generated by @pydantic.input or @pydantic.type.

    Args:
        strawberry_obj: The Strawberry instance to convert (must be from a @pydantic decorated type)

    Returns:
        An instance of the Pydantic model

    Example:
        input = CreateReminderInput(title="Test", description="...")
        reminder_create = strawberry_to_pydantic(input)  # Returns ReminderCreate
    """
    if not hasattr(strawberry_obj, "to_pydantic"):
        msg = (
            f"{type(strawberry_obj).__name__} must be decorated with @pydantic.input or @pydantic.type "
            "to use strawberry_to_pydantic()"
        )
        raise ValueError(
            msg,
        )

    return strawberry_obj.to_pydantic()


# ============================================================================
# Type Mapping Utilities
# ============================================================================


def get_scalar_for_type(python_type: type) -> Any:
    """Get the appropriate Strawberry scalar for a Python type.

    This helper maps Python types to GraphQL scalars, handling common cases
    like UUID, datetime, etc.

    Args:
        python_type: The Python type to get a scalar for

    Returns:
        The appropriate Strawberry scalar

    Example:
        uuid_scalar = get_scalar_for_type(UUID)  # Returns UUIDScalar
    """
    # Mapping of Python types to Strawberry scalars
    type_mapping = {
        PyUUID: UUIDScalar,
        # Add more mappings as needed
    }

    return type_mapping.get(python_type, python_type)  # type: ignore[arg-type]


# ============================================================================
# Documentation
# ============================================================================

"""
Migration Guide: Converting Manual Types to Pydantic

1. Identify the source Pydantic model:
   - Look for the corresponding schema in features/{feature}/schemas.py
   - Example: ReminderResponse for the Reminder GraphQL type

2. Replace manual @strawberry.type with @pydantic.type:

   Before:
       @strawberry.type
       class ReminderType:
           id: strawberry.ID
           title: str
           description: str | None
           # ... all fields manually defined

           @classmethod
           def from_model(cls, reminder: Reminder) -> ReminderType:
               return cls(id=strawberry.ID(str(reminder.id)), ...)

   After:
       @pydantic_type(model=ReminderResponse)
       class ReminderType:
           '''Auto-generated from ReminderResponse'''
           pass

3. Override fields that need custom behavior:

   @pydantic_type(model=ReminderResponse)
   class ReminderType:
       '''Auto-generated from ReminderResponse'''

       # Override UUID -> strawberry.ID conversion
       id: strawberry.ID = pydantic_field(description="Unique identifier")

       # Add computed fields
       @strawberry.field(description="Whether this reminder is overdue")
       def is_overdue(self) -> bool:
           if not self.remind_at or self.is_completed:
               return False
           from datetime import datetime, UTC
           return self.remind_at < datetime.now(UTC)

4. Update resolvers to use from_pydantic():

   Before:
       return ReminderType.from_model(reminder)

   After:
       pydantic_obj = ReminderResponse.from_model(reminder)
       return ReminderType.from_pydantic(pydantic_obj)

5. For input types, use to_pydantic() in mutations:

   Before:
       reminder = Reminder(
           title=input.title,
           description=input.description,
           ...
       )

   After:
       create_data = input.to_pydantic()  # Returns ReminderCreate
       reminder = Reminder(**create_data.model_dump())

Benefits:
- Eliminates manual field duplication
- Changes to Pydantic schemas automatically propagate to GraphQL
- Type safety maintained end-to-end
- Reduces code by 40-60%
"""
