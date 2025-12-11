"""Tests for GraphQL mutation resolvers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from example_service.features.graphql.schema import schema
from tests.graphql.conftest import (
    COMPLETE_REMINDER_MUTATION,
    CREATE_REMINDER_MUTATION,
    DELETE_REMINDER_MUTATION,
)

if TYPE_CHECKING:
    from example_service.features.graphql.context import GraphQLContext
    from example_service.features.reminders.models import Reminder


@pytest.mark.asyncio
async def test_create_reminder_success(
    graphql_context: GraphQLContext,
) -> None:
    """Test that createReminder mutation creates a reminder successfully."""
    remind_at = (datetime.now(UTC) + timedelta(days=1)).isoformat()

    result = await schema.execute(
        CREATE_REMINDER_MUTATION,
        variable_values={
            "input": {
                "title": "New Test Reminder",
                "description": "A test description",
                "remindAt": remind_at,
            },
        },
        context_value=graphql_context,
    )

    assert result.errors is None
    assert result.data is not None

    payload = result.data["createReminder"]
    assert "reminder" in payload  # ReminderSuccess
    assert payload["reminder"]["title"] == "New Test Reminder"
    assert payload["reminder"]["description"] == "A test description"
    assert payload["reminder"]["isCompleted"] is False


@pytest.mark.asyncio
async def test_create_reminder_validation_error_empty_title(
    graphql_context: GraphQLContext,
) -> None:
    """Test that createReminder returns error for empty title."""
    result = await schema.execute(
        CREATE_REMINDER_MUTATION,
        variable_values={
            "input": {
                "title": "",
                "description": "A test description",
            },
        },
        context_value=graphql_context,
    )

    assert result.errors is None
    assert result.data is not None

    payload = result.data["createReminder"]
    assert "code" in payload  # ReminderError
    assert payload["code"] == "VALIDATION_ERROR"
    assert payload["field"] == "title"


@pytest.mark.asyncio
async def test_create_reminder_validation_error_long_title(
    graphql_context: GraphQLContext,
) -> None:
    """Test that createReminder returns error for title over 200 chars."""
    result = await schema.execute(
        CREATE_REMINDER_MUTATION,
        variable_values={
            "input": {
                "title": "x" * 201,
                "description": "A test description",
            },
        },
        context_value=graphql_context,
    )

    assert result.errors is None
    assert result.data is not None

    payload = result.data["createReminder"]
    assert "code" in payload  # ReminderError
    assert payload["code"] == "VALIDATION_ERROR"
    assert payload["field"] == "title"
    assert "200" in payload["message"]


@pytest.mark.asyncio
async def test_complete_reminder_success(
    graphql_context: GraphQLContext,
    sample_reminder: Reminder,
) -> None:
    """Test that completeReminder marks a reminder as completed."""
    assert sample_reminder.is_completed is False

    result = await schema.execute(
        COMPLETE_REMINDER_MUTATION,
        variable_values={"id": str(sample_reminder.id)},
        context_value=graphql_context,
    )

    assert result.errors is None
    assert result.data is not None

    payload = result.data["completeReminder"]
    assert "reminder" in payload  # ReminderSuccess
    assert payload["reminder"]["id"] == str(sample_reminder.id)
    assert payload["reminder"]["isCompleted"] is True


@pytest.mark.asyncio
async def test_complete_reminder_not_found(
    graphql_context: GraphQLContext,
) -> None:
    """Test that completeReminder returns error for non-existent ID."""
    result = await schema.execute(
        COMPLETE_REMINDER_MUTATION,
        variable_values={"id": str(uuid4())},
        context_value=graphql_context,
    )

    assert result.errors is None
    assert result.data is not None

    payload = result.data["completeReminder"]
    assert "code" in payload  # ReminderError
    assert payload["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_delete_reminder_success(
    graphql_context: GraphQLContext,
    sample_reminder: Reminder,
) -> None:
    """Test that deleteReminder deletes a reminder successfully."""
    result = await schema.execute(
        DELETE_REMINDER_MUTATION,
        variable_values={"id": str(sample_reminder.id)},
        context_value=graphql_context,
    )

    assert result.errors is None
    assert result.data is not None

    payload = result.data["deleteReminder"]
    assert payload["success"] is True


@pytest.mark.asyncio
async def test_delete_reminder_not_found(
    graphql_context: GraphQLContext,
) -> None:
    """Test that deleteReminder returns failure for non-existent ID."""
    result = await schema.execute(
        DELETE_REMINDER_MUTATION,
        variable_values={"id": str(uuid4())},
        context_value=graphql_context,
    )

    assert result.errors is None
    assert result.data is not None

    payload = result.data["deleteReminder"]
    assert payload["success"] is False
    assert "not found" in payload["message"].lower()


@pytest.mark.asyncio
async def test_delete_reminder_invalid_id(
    graphql_context: GraphQLContext,
) -> None:
    """Test that deleteReminder handles invalid UUID gracefully."""
    result = await schema.execute(
        DELETE_REMINDER_MUTATION,
        variable_values={"id": "not-a-uuid"},
        context_value=graphql_context,
    )

    assert result.errors is None
    assert result.data is not None

    payload = result.data["deleteReminder"]
    assert payload["success"] is False
    assert "invalid" in payload["message"].lower()
