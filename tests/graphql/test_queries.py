"""Tests for GraphQL query resolvers."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from example_service.features.graphql.schema import schema
from tests.graphql.conftest import REMINDER_QUERY, REMINDERS_QUERY

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from example_service.features.graphql.context import GraphQLContext
    from example_service.features.reminders.models import Reminder


@pytest.mark.asyncio
async def test_reminder_query_returns_reminder(
    graphql_context: GraphQLContext,
    sample_reminder: Reminder,
) -> None:
    """Test that reminder query returns a single reminder by ID."""
    result = await schema.execute(
        REMINDER_QUERY,
        variable_values={"id": str(sample_reminder.id)},
        context_value=graphql_context,
    )

    assert result.errors is None
    assert result.data is not None
    assert result.data["reminder"] is not None
    assert result.data["reminder"]["id"] == str(sample_reminder.id)
    assert result.data["reminder"]["title"] == sample_reminder.title
    assert result.data["reminder"]["description"] == sample_reminder.description
    assert result.data["reminder"]["isCompleted"] == sample_reminder.is_completed


@pytest.mark.asyncio
async def test_reminder_query_returns_none_for_missing(
    graphql_context: GraphQLContext,
) -> None:
    """Test that reminder query returns None for non-existent ID."""
    result = await schema.execute(
        REMINDER_QUERY,
        variable_values={"id": str(uuid4())},
        context_value=graphql_context,
    )

    assert result.errors is None
    assert result.data is not None
    assert result.data["reminder"] is None


@pytest.mark.asyncio
async def test_reminder_query_returns_none_for_invalid_id(
    graphql_context: GraphQLContext,
) -> None:
    """Test that reminder query returns None for invalid UUID format."""
    result = await schema.execute(
        REMINDER_QUERY,
        variable_values={"id": "not-a-uuid"},
        context_value=graphql_context,
    )

    assert result.errors is None
    assert result.data is not None
    assert result.data["reminder"] is None


@pytest.mark.asyncio
async def test_reminders_query_returns_paginated_list(
    graphql_context: GraphQLContext,
    sample_reminders: list[Reminder],
) -> None:
    """Test that reminders query returns paginated results."""
    result = await schema.execute(
        REMINDERS_QUERY,
        variable_values={"first": 5},
        context_value=graphql_context,
    )

    assert result.errors is None
    assert result.data is not None

    connection = result.data["reminders"]
    assert len(connection["edges"]) == 5
    assert connection["pageInfo"]["hasNextPage"] is True
    assert connection["pageInfo"]["totalCount"] == 10


@pytest.mark.asyncio
async def test_reminders_query_filters_completed(
    graphql_context: GraphQLContext,
    sample_reminders: list[Reminder],
) -> None:
    """Test that reminders query can filter out completed reminders."""
    result = await schema.execute(
        REMINDERS_QUERY,
        variable_values={"first": 50, "includeCompleted": False},
        context_value=graphql_context,
    )

    assert result.errors is None
    assert result.data is not None

    connection = result.data["reminders"]
    # Every 3rd reminder is completed (0, 3, 6, 9 indices), so 6 are not completed
    # But indices are 1-10, so completed are 3, 6, 9 = 3 completed, 7 not completed
    for edge in connection["edges"]:
        assert edge["node"]["isCompleted"] is False


@pytest.mark.asyncio
async def test_reminders_query_pagination_cursor(
    graphql_context: GraphQLContext,
    sample_reminders: list[Reminder],
) -> None:
    """Test that cursor pagination works correctly."""
    # Get first page
    first_result = await schema.execute(
        REMINDERS_QUERY,
        variable_values={"first": 3},
        context_value=graphql_context,
    )

    assert first_result.errors is None
    first_page = first_result.data["reminders"]
    assert len(first_page["edges"]) == 3
    end_cursor = first_page["pageInfo"]["endCursor"]
    assert end_cursor is not None

    # Get second page using cursor
    second_result = await schema.execute(
        REMINDERS_QUERY,
        variable_values={"first": 3, "after": end_cursor},
        context_value=graphql_context,
    )

    assert second_result.errors is None
    second_page = second_result.data["reminders"]
    assert len(second_page["edges"]) == 3

    # Ensure pages don't overlap
    first_page_ids = {edge["node"]["id"] for edge in first_page["edges"]}
    second_page_ids = {edge["node"]["id"] for edge in second_page["edges"]}
    assert first_page_ids.isdisjoint(second_page_ids)


@pytest.mark.asyncio
async def test_reminders_query_empty_list(
    graphql_context: GraphQLContext,
) -> None:
    """Test that reminders query returns empty list when no reminders exist."""
    result = await schema.execute(
        REMINDERS_QUERY,
        variable_values={"first": 10},
        context_value=graphql_context,
    )

    assert result.errors is None
    assert result.data is not None

    connection = result.data["reminders"]
    assert len(connection["edges"]) == 0
    assert connection["pageInfo"]["hasNextPage"] is False
    assert connection["pageInfo"]["hasPreviousPage"] is False
    assert connection["pageInfo"]["totalCount"] == 0
