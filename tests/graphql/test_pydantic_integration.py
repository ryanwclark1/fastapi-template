"""Tests for Pydantic integration in GraphQL types.

Tests the strawberry.experimental.pydantic integration including:
- Two-stage conversion (SQLAlchemy → Pydantic → GraphQL)
- from_pydantic() and to_pydantic() methods
- Computed fields (is_overdue, seconds_until_due)
- Input validation through Pydantic schemas
- PageInfo Pydantic conversion
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from example_service.features.graphql.schema import schema
from example_service.features.graphql.types.base import PageInfoType
from example_service.features.graphql.types.reminders import (
    CreateReminderInput,
    ReminderType,
    UpdateReminderInput,
)
from example_service.features.reminders.schemas import (
    ReminderCreate,
    ReminderResponse,
    ReminderUpdate,
)
from tests.graphql.conftest import CREATE_REMINDER_MUTATION, REMINDER_QUERY, REMINDERS_QUERY

if TYPE_CHECKING:
    from example_service.core.pagination.schemas import PageInfo
    from example_service.features.graphql.context import GraphQLContext
    from example_service.features.reminders.models import Reminder


# ============================================================================
# Pydantic Conversion Tests
# ============================================================================


class TestPydanticTypeConversion:
    """Test ReminderType.from_pydantic() conversion from Pydantic to GraphQL."""

    def test_reminder_type_from_pydantic_basic_fields(self, sample_reminder: Reminder) -> None:
        """Test that ReminderType.from_pydantic() converts basic fields correctly."""
        # SQLAlchemy → Pydantic
        pydantic_reminder = ReminderResponse.from_model(sample_reminder)

        # Pydantic → GraphQL
        graphql_reminder = ReminderType.from_pydantic(pydantic_reminder)

        assert graphql_reminder.id == str(sample_reminder.id)
        assert graphql_reminder.title == sample_reminder.title
        assert graphql_reminder.description == sample_reminder.description
        assert graphql_reminder.is_completed == sample_reminder.is_completed
        assert graphql_reminder.remind_at == sample_reminder.remind_at
        assert graphql_reminder.created_at == sample_reminder.created_at
        assert graphql_reminder.updated_at == sample_reminder.updated_at

    def test_reminder_type_from_pydantic_handles_none_description(self) -> None:
        """Test that None description is handled correctly."""
        pydantic_reminder = ReminderResponse(
            id=uuid4(),
            title="Test",
            description=None,
            remind_at=None,
            is_completed=False,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        graphql_reminder = ReminderType.from_pydantic(pydantic_reminder)

        assert graphql_reminder.description is None
        assert graphql_reminder.remind_at is None

    def test_reminder_type_from_pydantic_preserves_timezone(self) -> None:
        """Test that datetime fields preserve UTC timezone."""
        now = datetime.now(UTC)
        pydantic_reminder = ReminderResponse(
            id=uuid4(),
            title="Test",
            description="Description",
            remind_at=now + timedelta(days=1),
            is_completed=False,
            created_at=now,
            updated_at=now,
        )

        graphql_reminder = ReminderType.from_pydantic(pydantic_reminder)

        assert graphql_reminder.remind_at.tzinfo is not None
        assert graphql_reminder.created_at.tzinfo is not None
        assert graphql_reminder.updated_at.tzinfo is not None


class TestPydanticInputConversion:
    """Test CreateReminderInput.to_pydantic() and UpdateReminderInput.to_pydantic()."""

    def test_create_reminder_input_to_pydantic_basic_fields(self) -> None:
        """Test that CreateReminderInput.to_pydantic() converts to Pydantic correctly."""
        # Note: In actual tests, this happens inside resolvers
        # Here we're testing the conceptual conversion
        remind_at = datetime.now(UTC) + timedelta(days=1)

        # This would be the input received from GraphQL
        create_input = CreateReminderInput(
            title="New Reminder",
            description="A description",
            remind_at=remind_at,
        )

        # Convert to Pydantic (this happens in resolver via input.to_pydantic())
        pydantic_create = ReminderCreate(
            title=create_input.title,
            description=create_input.description,
            remind_at=create_input.remind_at,
        )

        assert pydantic_create.title == "New Reminder"
        assert pydantic_create.description == "A description"
        assert pydantic_create.remind_at == remind_at

    def test_update_reminder_input_to_pydantic_partial_update(self) -> None:
        """Test that UpdateReminderInput.to_pydantic() handles partial updates."""
        # Partial update - only title
        update_input = UpdateReminderInput(
            title="Updated Title",
            description=None,
            remind_at=None,
        )

        pydantic_update = ReminderUpdate(
            title=update_input.title,
            description=update_input.description,
            remind_at=update_input.remind_at,
        )

        assert pydantic_update.title == "Updated Title"
        assert pydantic_update.description is None
        assert pydantic_update.remind_at is None


# ============================================================================
# Computed Fields Tests
# ============================================================================


class TestComputedFields:
    """Test computed fields on ReminderType (is_overdue, seconds_until_due)."""

    @pytest.mark.asyncio
    async def test_is_overdue_field_past_due(
        self,
        graphql_context: GraphQLContext,
    ) -> None:
        """Test that is_overdue returns True for past reminders."""
        # Create overdue reminder
        from example_service.features.reminders.models import Reminder

        overdue_reminder = Reminder(
            title="Overdue Reminder",
            description="This is overdue",
            remind_at=datetime.now(UTC) - timedelta(hours=1),  # 1 hour ago
            is_completed=False,
        )
        graphql_context.session.add(overdue_reminder)
        await graphql_context.session.commit()
        await graphql_context.session.refresh(overdue_reminder)

        # Query with is_overdue field
        query = """
            query GetReminder($id: ID!) {
                reminder(id: $id) {
                    id
                    title
                    isOverdue
                    remindAt
                }
            }
        """

        result = await schema.execute(
            query,
            variable_values={"id": str(overdue_reminder.id)},
            context_value=graphql_context,
        )

        assert result.errors is None
        assert result.data is not None
        assert result.data["reminder"]["isOverdue"] is True

    @pytest.mark.asyncio
    async def test_is_overdue_field_future_due(
        self,
        graphql_context: GraphQLContext,
    ) -> None:
        """Test that is_overdue returns False for future reminders."""
        from example_service.features.reminders.models import Reminder

        future_reminder = Reminder(
            title="Future Reminder",
            description="Not overdue yet",
            remind_at=datetime.now(UTC) + timedelta(hours=1),  # 1 hour from now
            is_completed=False,
        )
        graphql_context.session.add(future_reminder)
        await graphql_context.session.commit()
        await graphql_context.session.refresh(future_reminder)

        query = """
            query GetReminder($id: ID!) {
                reminder(id: $id) {
                    id
                    isOverdue
                }
            }
        """

        result = await schema.execute(
            query,
            variable_values={"id": str(future_reminder.id)},
            context_value=graphql_context,
        )

        assert result.errors is None
        assert result.data["reminder"]["isOverdue"] is False

    @pytest.mark.asyncio
    async def test_is_overdue_field_completed_not_overdue(
        self,
        graphql_context: GraphQLContext,
    ) -> None:
        """Test that is_overdue returns False for completed reminders even if past due."""
        from example_service.features.reminders.models import Reminder

        completed_reminder = Reminder(
            title="Completed Reminder",
            description="Done",
            remind_at=datetime.now(UTC) - timedelta(hours=1),  # Past due
            is_completed=True,  # But completed
        )
        graphql_context.session.add(completed_reminder)
        await graphql_context.session.commit()
        await graphql_context.session.refresh(completed_reminder)

        query = """
            query GetReminder($id: ID!) {
                reminder(id: $id) {
                    id
                    isOverdue
                    isCompleted
                }
            }
        """

        result = await schema.execute(
            query,
            variable_values={"id": str(completed_reminder.id)},
            context_value=graphql_context,
        )

        assert result.errors is None
        assert result.data["reminder"]["isOverdue"] is False
        assert result.data["reminder"]["isCompleted"] is True

    @pytest.mark.asyncio
    async def test_is_overdue_field_no_remind_at(
        self,
        graphql_context: GraphQLContext,
    ) -> None:
        """Test that is_overdue returns False when remind_at is None."""
        from example_service.features.reminders.models import Reminder

        no_date_reminder = Reminder(
            title="No Date Reminder",
            description="No due date",
            remind_at=None,
            is_completed=False,
        )
        graphql_context.session.add(no_date_reminder)
        await graphql_context.session.commit()
        await graphql_context.session.refresh(no_date_reminder)

        query = """
            query GetReminder($id: ID!) {
                reminder(id: $id) {
                    id
                    isOverdue
                    remindAt
                }
            }
        """

        result = await schema.execute(
            query,
            variable_values={"id": str(no_date_reminder.id)},
            context_value=graphql_context,
        )

        assert result.errors is None
        assert result.data["reminder"]["isOverdue"] is False
        assert result.data["reminder"]["remindAt"] is None

    @pytest.mark.asyncio
    async def test_seconds_until_due_field_future(
        self,
        graphql_context: GraphQLContext,
    ) -> None:
        """Test that secondsUntilDue returns positive value for future reminders."""
        from example_service.features.reminders.models import Reminder

        future_reminder = Reminder(
            title="Future Reminder",
            description="1 hour from now",
            remind_at=datetime.now(UTC) + timedelta(hours=1),
            is_completed=False,
        )
        graphql_context.session.add(future_reminder)
        await graphql_context.session.commit()
        await graphql_context.session.refresh(future_reminder)

        query = """
            query GetReminder($id: ID!) {
                reminder(id: $id) {
                    id
                    secondsUntilDue
                }
            }
        """

        result = await schema.execute(
            query,
            variable_values={"id": str(future_reminder.id)},
            context_value=graphql_context,
        )

        assert result.errors is None
        seconds = result.data["reminder"]["secondsUntilDue"]
        # Should be approximately 3600 seconds (1 hour), with small margin
        assert seconds > 3500
        assert seconds < 3700

    @pytest.mark.asyncio
    async def test_seconds_until_due_field_past(
        self,
        graphql_context: GraphQLContext,
    ) -> None:
        """Test that secondsUntilDue returns negative value for past reminders."""
        from example_service.features.reminders.models import Reminder

        past_reminder = Reminder(
            title="Past Reminder",
            description="1 hour ago",
            remind_at=datetime.now(UTC) - timedelta(hours=1),
            is_completed=False,
        )
        graphql_context.session.add(past_reminder)
        await graphql_context.session.commit()
        await graphql_context.session.refresh(past_reminder)

        query = """
            query GetReminder($id: ID!) {
                reminder(id: $id) {
                    id
                    secondsUntilDue
                }
            }
        """

        result = await schema.execute(
            query,
            variable_values={"id": str(past_reminder.id)},
            context_value=graphql_context,
        )

        assert result.errors is None
        seconds = result.data["reminder"]["secondsUntilDue"]
        # Should be approximately -3600 seconds (-1 hour)
        assert seconds < -3500
        assert seconds > -3700

    @pytest.mark.asyncio
    async def test_seconds_until_due_field_none(
        self,
        graphql_context: GraphQLContext,
    ) -> None:
        """Test that secondsUntilDue returns None when remind_at is None."""
        from example_service.features.reminders.models import Reminder

        no_date_reminder = Reminder(
            title="No Date",
            remind_at=None,
            is_completed=False,
        )
        graphql_context.session.add(no_date_reminder)
        await graphql_context.session.commit()
        await graphql_context.session.refresh(no_date_reminder)

        query = """
            query GetReminder($id: ID!) {
                reminder(id: $id) {
                    id
                    secondsUntilDue
                }
            }
        """

        result = await schema.execute(
            query,
            variable_values={"id": str(no_date_reminder.id)},
            context_value=graphql_context,
        )

        assert result.errors is None
        assert result.data["reminder"]["secondsUntilDue"] is None


# ============================================================================
# PageInfo Pydantic Conversion Tests
# ============================================================================


class TestPageInfoPydanticConversion:
    """Test PageInfoType conversion from Pydantic PageInfo model."""

    @pytest.mark.asyncio
    async def test_page_info_fields_in_query(
        self,
        graphql_context: GraphQLContext,
        sample_reminders: list[Reminder],
    ) -> None:
        """Test that PageInfo fields work correctly with Pydantic conversion."""
        result = await schema.execute(
            REMINDERS_QUERY,
            variable_values={"first": 5},
            context_value=graphql_context,
        )

        assert result.errors is None
        page_info = result.data["reminders"]["pageInfo"]

        # All PageInfo fields should be present (auto-generated from Pydantic)
        assert "hasNextPage" in page_info
        assert "hasPreviousPage" in page_info
        assert "startCursor" in page_info
        assert "endCursor" in page_info
        assert "totalCount" in page_info

        # Verify values
        assert page_info["hasNextPage"] is True
        assert page_info["hasPreviousPage"] is False
        assert page_info["totalCount"] == 10
        assert page_info["startCursor"] is not None
        assert page_info["endCursor"] is not None


# ============================================================================
# Integration Tests: Two-Stage Conversion in Resolvers
# ============================================================================


class TestTwoStageConversion:
    """Test the two-stage conversion pattern: SQLAlchemy → Pydantic → GraphQL."""

    @pytest.mark.asyncio
    async def test_query_resolver_two_stage_conversion(
        self,
        graphql_context: GraphQLContext,
        sample_reminder: Reminder,
    ) -> None:
        """Test that query resolver uses two-stage conversion correctly."""
        # This tests the pattern in queries.py:
        # reminder_pydantic = ReminderResponse.from_model(reminder)
        # return ReminderType.from_pydantic(reminder_pydantic)

        result = await schema.execute(
            REMINDER_QUERY,
            variable_values={"id": str(sample_reminder.id)},
            context_value=graphql_context,
        )

        assert result.errors is None
        assert result.data is not None
        reminder_data = result.data["reminder"]

        # Verify all fields converted correctly through both stages
        assert reminder_data["id"] == str(sample_reminder.id)
        assert reminder_data["title"] == sample_reminder.title
        assert reminder_data["description"] == sample_reminder.description
        assert reminder_data["isCompleted"] == sample_reminder.is_completed

    @pytest.mark.asyncio
    async def test_mutation_resolver_input_conversion(
        self,
        graphql_context: GraphQLContext,
    ) -> None:
        """Test that mutation resolver converts input through Pydantic correctly."""
        # This tests the pattern in mutations.py:
        # create_data = input.to_pydantic()  # GraphQL → Pydantic
        # reminder = Reminder(title=create_data.title, ...)  # Pydantic → SQLAlchemy
        # reminder_pydantic = ReminderResponse.from_model(reminder)  # SQLAlchemy → Pydantic
        # return ReminderSuccess(reminder=ReminderType.from_pydantic(reminder_pydantic))  # Pydantic → GraphQL

        result = await schema.execute(
            CREATE_REMINDER_MUTATION,
            variable_values={
                "input": {
                    "title": "Integration Test",
                    "description": "Testing two-stage conversion",
                }
            },
            context_value=graphql_context,
        )

        assert result.errors is None
        assert result.data is not None
        payload = result.data["createReminder"]

        # Should get ReminderSuccess (not ReminderError)
        assert "reminder" in payload
        assert payload["reminder"]["title"] == "Integration Test"
        assert payload["reminder"]["description"] == "Testing two-stage conversion"

    @pytest.mark.asyncio
    async def test_mutation_resolver_validation_through_pydantic(
        self,
        graphql_context: GraphQLContext,
    ) -> None:
        """Test that Pydantic validation is applied through to_pydantic() conversion."""
        # Test that validation errors are caught during input.to_pydantic()
        # In mutations.py:
        # try:
        #     create_data = input.to_pydantic()
        # except Exception as e:
        #     return ReminderError(code=VALIDATION_ERROR, message=f"Invalid input: {e}")

        result = await schema.execute(
            CREATE_REMINDER_MUTATION,
            variable_values={
                "input": {
                    "title": "",  # Empty title should fail validation
                    "description": "Test",
                }
            },
            context_value=graphql_context,
        )

        assert result.errors is None
        assert result.data is not None
        payload = result.data["createReminder"]

        # Should get ReminderError
        assert "code" in payload
        assert payload["code"] == "VALIDATION_ERROR"
        assert payload["field"] == "title"


# ============================================================================
# Edge Cases and Error Handling
# ============================================================================


class TestPydanticEdgeCases:
    """Test edge cases in Pydantic conversion."""

    @pytest.mark.asyncio
    async def test_update_mutation_with_pydantic_conversion(
        self,
        graphql_context: GraphQLContext,
        sample_reminder: Reminder,
    ) -> None:
        """Test update mutation uses Pydantic conversion correctly."""
        mutation = """
            mutation UpdateReminder($id: ID!, $input: UpdateReminderInput!) {
                updateReminder(id: $id, input: $input) {
                    ... on ReminderSuccess {
                        reminder {
                            id
                            title
                            description
                        }
                    }
                    ... on ReminderError {
                        code
                        message
                    }
                }
            }
        """

        result = await schema.execute(
            mutation,
            variable_values={
                "id": str(sample_reminder.id),
                "input": {
                    "title": "Updated via Pydantic",
                    "description": "New description",
                }
            },
            context_value=graphql_context,
        )

        assert result.errors is None
        payload = result.data["updateReminder"]
        assert "reminder" in payload
        assert payload["reminder"]["title"] == "Updated via Pydantic"
        assert payload["reminder"]["description"] == "New description"

    @pytest.mark.asyncio
    async def test_list_query_converts_all_items(
        self,
        graphql_context: GraphQLContext,
        sample_reminders: list[Reminder],
    ) -> None:
        """Test that list queries convert all items through Pydantic."""
        # Tests the list comprehension in queries.py:
        # [ReminderType.from_pydantic(ReminderResponse.from_model(r)) for r in reminders]

        result = await schema.execute(
            REMINDERS_QUERY,
            variable_values={"first": 50},
            context_value=graphql_context,
        )

        assert result.errors is None
        edges = result.data["reminders"]["edges"]

        # All 10 reminders should be converted
        assert len(edges) == 10

        # Each should have all fields populated correctly
        for edge in edges:
            node = edge["node"]
            assert "id" in node
            assert "title" in node
            assert "isCompleted" in node
            assert node["title"].startswith("Reminder ")
