"""GraphQL test fixtures.

Provides:
- In-memory SQLite database for testing
- GraphQL test client with context
- Sample reminder data
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

if os.environ.get("RUN_GRAPHQL_TESTS") != "1":  # pragma: no cover - default skip
    pytest.skip("GraphQL tests require RUN_GRAPHQL_TESTS=1", allow_module_level=True)

try:  # pragma: no cover - executed only when dependency missing
    import strawberry  # type: ignore
except ModuleNotFoundError:
    pytest.skip("strawberry is required for GraphQL tests", allow_module_level=True)
else:  # pragma: no cover - stub detection
    if getattr(strawberry, "__example_stub__", False):
        pytest.skip("strawberry is required for GraphQL tests", allow_module_level=True)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from example_service.core.database import Base
from example_service.features.graphql.context import GraphQLContext
from example_service.features.graphql.dataloaders import create_dataloaders
from example_service.features.reminders.models import Reminder

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


@pytest.fixture(scope="session")
def graphql_postgres_container() -> Iterator[str]:
    """Create a PostgreSQL container for GraphQL tests using testcontainers.

    This fixture starts a PostgreSQL container that will be reused across all GraphQL tests
    in the session. The container is automatically stopped after all tests complete.

    Yields:
        Database connection URL for async PostgreSQL (postgresql+psycopg://...).
    """
    pytest.importorskip("testcontainers.postgres", reason="testcontainers.postgres is required")
    from testcontainers.postgres import PostgresContainer

    container = PostgresContainer("postgres:16-alpine")
    try:
        container.start()
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"PostgreSQL container unavailable: {exc}", allow_module_level=True)

    # Convert to async connection URL for psycopg3
    # get_connection_url() may return postgresql:// or postgresql+psycopg2://
    original_url = container.get_connection_url()
    # Replace any psycopg2 reference with psycopg (psycopg3)
    url = original_url.replace("postgresql+psycopg2://", "postgresql+psycopg://").replace(
        "postgresql://", "postgresql+psycopg://"
    )
    yield url
    container.stop()


@pytest.fixture
async def graphql_session(graphql_postgres_container: str) -> AsyncGenerator[AsyncSession]:
    """Create a PostgreSQL session for GraphQL tests.

    Uses testcontainers to provide a real PostgreSQL database that supports all
    PostgreSQL features including JSONB.
    """
    import sqlalchemy as sa

    # Use PostgreSQL via testcontainers
    engine = create_async_engine(
        graphql_postgres_container,
        echo=False,
    )

    # Create enum types before creating tables
    async with engine.begin() as conn:
        # Create all enum types that are used by models
        # These must be created before tables that reference them
        enum_definitions = [
            (["pending", "processing", "ready", "failed", "deleted"], "filestatus"),
            (["smtp", "aws_ses", "sendgrid", "mailgun", "console", "file"], "emailprovidertype"),
            (["pending", "delivered", "failed", "retrying"], "deliverystatus"),
            (["LLM", "TRANSCRIPTION", "EMBEDDING", "IMAGE", "PII_REDACTION"], "aiprovidertype"),
            (
                [
                    "TRANSCRIPTION",
                    "PII_REDACTION",
                    "SUMMARY",
                    "SENTIMENT",
                    "COACHING",
                    "FULL_ANALYSIS",
                ],
                "aijobtype",
            ),
            (["PENDING", "PROCESSING", "COMPLETED", "FAILED", "CANCELLED"], "aijobstatus"),
            (
                [
                    "pending",
                    "queued",
                    "running",
                    "completed",
                    "failed",
                    "cancelled",
                    "retrying",
                    "paused",
                ],
                "jobstatus",
            ),
            (["1", "2", "3", "4"], "jobpriority"),
            (["enabled", "disabled", "percentage", "targeted"], "flagstatus"),
            (
                [
                    "create",
                    "read",
                    "update",
                    "delete",
                    "bulk_create",
                    "bulk_update",
                    "bulk_delete",
                    "export",
                    "import",
                    "login",
                    "logout",
                    "login_failed",
                    "password_change",
                    "token_refresh",
                    "permission_denied",
                    "acl_check",
                    "archive",
                    "restore",
                    "purge",
                ],
                "auditaction",
            ),
        ]

        # Create each enum type if it doesn't exist
        for enum_values, enum_name in enum_definitions:
            result = await conn.execute(
                sa.text(
                    """
                    SELECT EXISTS (
                        SELECT 1 FROM pg_type WHERE typname = :enum_name
                    )
                    """
                ),
                {"enum_name": enum_name},
            )
            exists = result.scalar()

            if not exists:
                # Create the enum type using SQLAlchemy's Enum.create
                # Capture enum in default argument to avoid closure issue
                sa_enum = sa.Enum(*enum_values, name=enum_name)
                await conn.run_sync(
                    lambda sync_conn, e=sa_enum: e.create(sync_conn, checkfirst=False)
                )

        # Now create all tables
        await conn.run_sync(Base.metadata.create_all)

    # Create session
    async_session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with async_session_factory() as session:
        yield session

    # Cleanup
    await engine.dispose()


@pytest.fixture
def graphql_context(graphql_session: AsyncSession) -> GraphQLContext:
    """Create a GraphQL context for testing.

    Note: This is a synchronous fixture because GraphQLContext is a dataclass.
    """
    return GraphQLContext(
        session=graphql_session,
        loaders=create_dataloaders(graphql_session),
        user=None,
        correlation_id="test-correlation-id",
    )


@pytest.fixture
async def sample_reminder(graphql_session: AsyncSession) -> Reminder:
    """Create a single sample reminder for testing."""
    reminder = Reminder(
        id=uuid4(),
        title="Test Reminder",
        description="A test reminder description",
        remind_at=datetime.now(UTC) + timedelta(days=1),
        is_completed=False,
    )
    graphql_session.add(reminder)
    await graphql_session.commit()
    await graphql_session.refresh(reminder)
    return reminder


@pytest.fixture
async def sample_reminders(graphql_session: AsyncSession) -> list[Reminder]:
    """Create multiple sample reminders for pagination testing."""
    now = datetime.now(UTC)
    reminders = [
        Reminder(
            id=uuid4(),
            title=f"Reminder {i}",
            description=f"Description for reminder {i}",
            remind_at=now + timedelta(days=i),
            is_completed=i % 3 == 0,  # Every 3rd reminder is completed
        )
        for i in range(1, 11)  # 10 reminders
    ]

    for reminder in reminders:
        graphql_session.add(reminder)

    await graphql_session.commit()

    # Refresh all to get generated timestamps
    for reminder in reminders:
        await graphql_session.refresh(reminder)

    return reminders


# GraphQL query strings for testing
REMINDER_QUERY = """
    query GetReminder($id: ID!) {
        reminder(id: $id) {
            id
            title
            description
            remindAt
            isCompleted
            createdAt
            updatedAt
        }
    }
"""

REMINDERS_QUERY = """
    query ListReminders($first: Int, $after: String, $includeCompleted: Boolean) {
        reminders(first: $first, after: $after, includeCompleted: $includeCompleted) {
            edges {
                node {
                    id
                    title
                    isCompleted
                }
                cursor
            }
            pageInfo {
                hasNextPage
                hasPreviousPage
                startCursor
                endCursor
                totalCount
            }
        }
    }
"""

CREATE_REMINDER_MUTATION = """
    mutation CreateReminder($input: CreateReminderInput!) {
        createReminder(input: $input) {
            ... on ReminderSuccess {
                reminder {
                    id
                    title
                    description
                    remindAt
                    isCompleted
                }
            }
            ... on ReminderError {
                code
                message
                field
            }
        }
    }
"""

COMPLETE_REMINDER_MUTATION = """
    mutation CompleteReminder($id: ID!) {
        completeReminder(id: $id) {
            ... on ReminderSuccess {
                reminder {
                    id
                    isCompleted
                }
            }
            ... on ReminderError {
                code
                message
            }
        }
    }
"""

DELETE_REMINDER_MUTATION = """
    mutation DeleteReminder($id: ID!) {
        deleteReminder(id: $id) {
            success
            message
        }
    }
"""
