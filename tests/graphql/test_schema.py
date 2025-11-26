"""Tests for GraphQL schema validation."""

from __future__ import annotations

import pytest
from strawberry.printer import print_schema

from example_service.features.graphql.schema import schema


def test_schema_has_query_type() -> None:
    """Test that the schema has a Query type."""
    assert schema.query is not None


def test_schema_has_mutation_type() -> None:
    """Test that the schema has a Mutation type."""
    assert schema.mutation is not None


def test_schema_has_subscription_type() -> None:
    """Test that the schema has a Subscription type."""
    assert schema.subscription is not None


def test_schema_exports_valid_sdl() -> None:
    """Test that the schema can be exported as valid SDL."""
    sdl = print_schema(schema)
    assert sdl is not None
    assert len(sdl) > 0


def test_schema_contains_reminder_type() -> None:
    """Test that the schema contains ReminderType."""
    sdl = print_schema(schema)
    assert "type ReminderType" in sdl


def test_schema_contains_reminder_connection() -> None:
    """Test that the schema contains ReminderConnection for pagination."""
    sdl = print_schema(schema)
    assert "type ReminderConnection" in sdl
    assert "type ReminderEdge" in sdl
    assert "type PageInfoType" in sdl


def test_schema_contains_reminder_mutations() -> None:
    """Test that the schema contains reminder mutation fields."""
    sdl = print_schema(schema)
    assert "createReminder" in sdl
    assert "updateReminder" in sdl
    assert "completeReminder" in sdl
    assert "deleteReminder" in sdl


def test_schema_contains_union_payload() -> None:
    """Test that the schema contains union types for error handling."""
    sdl = print_schema(schema)
    assert "union ReminderPayload" in sdl
    assert "type ReminderSuccess" in sdl
    assert "type ReminderError" in sdl


def test_schema_contains_subscription() -> None:
    """Test that the schema contains subscription fields."""
    sdl = print_schema(schema)
    assert "reminderEvents" in sdl


def test_schema_contains_error_codes() -> None:
    """Test that the schema contains error code enum."""
    sdl = print_schema(schema)
    assert "enum ErrorCode" in sdl
    assert "NOT_FOUND" in sdl
    assert "VALIDATION_ERROR" in sdl


def test_schema_introspection() -> None:
    """Test that schema introspection works."""
    # Schema should have query, mutation, and subscription types
    sdl = print_schema(schema)

    # Check that the root types are defined
    assert "type Query {" in sdl
    assert "type Mutation {" in sdl
    assert "type Subscription {" in sdl
