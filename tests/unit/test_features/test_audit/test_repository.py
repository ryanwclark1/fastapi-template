"""Unit tests for AuditRepository."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from example_service.features.audit.models import AuditAction, AuditLog
from example_service.features.audit.repository import (
    AuditRepository,
    get_audit_repository,
)
from example_service.features.audit.schemas import AuditLogQuery

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
def repository() -> AuditRepository:
    """Create AuditRepository instance."""
    return AuditRepository()


@pytest.mark.asyncio
async def test_repository_initialization(repository: AuditRepository) -> None:
    """Test that repository initializes correctly."""
    assert repository is not None
    assert repository.model == AuditLog


@pytest.mark.asyncio
async def test_get_audit_repository_returns_singleton() -> None:
    """Test that get_audit_repository returns singleton instance."""
    repo1 = get_audit_repository()
    repo2 = get_audit_repository()

    assert repo1 is repo2
    assert isinstance(repo1, AuditRepository)


@pytest.mark.asyncio
async def test_create_audit_log(
    db_session: AsyncSession, repository: AuditRepository,
) -> None:
    """Test creating an audit log entry."""
    log = AuditLog(
        action=AuditAction.CREATE,
        entity_type="reminder",
        entity_id="reminder-123",
        user_id="user-456",
        tenant_id="tenant-789",
        new_values={"title": "New Reminder"},
        success=True,
    )

    result = await repository.create(db_session, log)
    await db_session.commit()

    assert result.id is not None
    assert result.action == AuditAction.CREATE
    assert result.entity_type == "reminder"
    assert result.entity_id == "reminder-123"
    assert result.user_id == "user-456"
    assert result.tenant_id == "tenant-789"
    assert result.new_values == {"title": "New Reminder"}
    assert result.success is True
    assert result.timestamp is not None


@pytest.mark.asyncio
async def test_get_audit_log(
    db_session: AsyncSession, repository: AuditRepository,
) -> None:
    """Test retrieving an audit log by ID."""
    log = AuditLog(
        action=AuditAction.UPDATE,
        entity_type="reminder",
        entity_id="reminder-123",
        user_id="user-456",
    )
    log = await repository.create(db_session, log)
    await db_session.commit()

    retrieved = await repository.get(db_session, log.id)

    assert retrieved is not None
    assert retrieved.id == log.id
    assert retrieved.action == AuditAction.UPDATE
    assert retrieved.entity_type == "reminder"


@pytest.mark.asyncio
async def test_query_logs_by_entity_type(
    db_session: AsyncSession, repository: AuditRepository,
) -> None:
    """Test querying logs by entity type."""
    # Create logs for different entity types
    log1 = AuditLog(
        action=AuditAction.CREATE,
        entity_type="reminder",
        entity_id="reminder-1",
        user_id="user-1",
    )
    log2 = AuditLog(
        action=AuditAction.CREATE,
        entity_type="task",
        entity_id="task-1",
        user_id="user-1",
    )
    log3 = AuditLog(
        action=AuditAction.UPDATE,
        entity_type="reminder",
        entity_id="reminder-2",
        user_id="user-1",
    )

    await repository.create(db_session, log1)
    await repository.create(db_session, log2)
    await repository.create(db_session, log3)
    await db_session.commit()

    query = AuditLogQuery(entity_type="reminder", limit=100)
    result = await repository.query_logs(db_session, query)

    assert result.total == 2
    assert len(result.items) == 2
    assert all(log.entity_type == "reminder" for log in result.items)


@pytest.mark.asyncio
async def test_query_logs_by_entity_id(
    db_session: AsyncSession, repository: AuditRepository,
) -> None:
    """Test querying logs by entity ID."""
    log1 = AuditLog(
        action=AuditAction.CREATE,
        entity_type="reminder",
        entity_id="reminder-123",
        user_id="user-1",
    )
    log2 = AuditLog(
        action=AuditAction.UPDATE,
        entity_type="reminder",
        entity_id="reminder-123",
        user_id="user-1",
    )
    log3 = AuditLog(
        action=AuditAction.CREATE,
        entity_type="reminder",
        entity_id="reminder-456",
        user_id="user-1",
    )

    await repository.create(db_session, log1)
    await repository.create(db_session, log2)
    await repository.create(db_session, log3)
    await db_session.commit()

    query = AuditLogQuery(entity_id="reminder-123", limit=100)
    result = await repository.query_logs(db_session, query)

    assert result.total == 2
    assert len(result.items) == 2
    assert all(log.entity_id == "reminder-123" for log in result.items)


@pytest.mark.asyncio
async def test_query_logs_by_user_id(
    db_session: AsyncSession, repository: AuditRepository,
) -> None:
    """Test querying logs by user ID."""
    log1 = AuditLog(
        action=AuditAction.CREATE,
        entity_type="reminder",
        entity_id="reminder-1",
        user_id="user-123",
    )
    log2 = AuditLog(
        action=AuditAction.UPDATE,
        entity_type="reminder",
        entity_id="reminder-2",
        user_id="user-123",
    )
    log3 = AuditLog(
        action=AuditAction.CREATE,
        entity_type="reminder",
        entity_id="reminder-3",
        user_id="user-456",
    )

    await repository.create(db_session, log1)
    await repository.create(db_session, log2)
    await repository.create(db_session, log3)
    await db_session.commit()

    query = AuditLogQuery(user_id="user-123", limit=100)
    result = await repository.query_logs(db_session, query)

    assert result.total == 2
    assert len(result.items) == 2
    assert all(log.user_id == "user-123" for log in result.items)


@pytest.mark.asyncio
async def test_query_logs_by_tenant_id(
    db_session: AsyncSession, repository: AuditRepository,
) -> None:
    """Test querying logs by tenant ID."""
    log1 = AuditLog(
        action=AuditAction.CREATE,
        entity_type="reminder",
        entity_id="reminder-1",
        user_id="user-1",
        tenant_id="tenant-123",
    )
    log2 = AuditLog(
        action=AuditAction.UPDATE,
        entity_type="reminder",
        entity_id="reminder-2",
        user_id="user-1",
        tenant_id="tenant-123",
    )
    log3 = AuditLog(
        action=AuditAction.CREATE,
        entity_type="reminder",
        entity_id="reminder-3",
        user_id="user-1",
        tenant_id="tenant-456",
    )

    await repository.create(db_session, log1)
    await repository.create(db_session, log2)
    await repository.create(db_session, log3)
    await db_session.commit()

    query = AuditLogQuery(tenant_id="tenant-123", limit=100)
    result = await repository.query_logs(db_session, query)

    assert result.total == 2
    assert len(result.items) == 2
    assert all(log.tenant_id == "tenant-123" for log in result.items)


@pytest.mark.asyncio
async def test_query_logs_by_action(
    db_session: AsyncSession, repository: AuditRepository,
) -> None:
    """Test querying logs by action."""
    log1 = AuditLog(
        action=AuditAction.CREATE,
        entity_type="reminder",
        entity_id="reminder-1",
        user_id="user-1",
    )
    log2 = AuditLog(
        action=AuditAction.UPDATE,
        entity_type="reminder",
        entity_id="reminder-2",
        user_id="user-1",
    )
    log3 = AuditLog(
        action=AuditAction.CREATE,
        entity_type="reminder",
        entity_id="reminder-3",
        user_id="user-1",
    )

    await repository.create(db_session, log1)
    await repository.create(db_session, log2)
    await repository.create(db_session, log3)
    await db_session.commit()

    query = AuditLogQuery(action=AuditAction.CREATE, limit=100)
    result = await repository.query_logs(db_session, query)

    assert result.total == 2
    assert len(result.items) == 2
    assert all(log.action == AuditAction.CREATE for log in result.items)


@pytest.mark.asyncio
async def test_query_logs_by_multiple_actions(
    db_session: AsyncSession, repository: AuditRepository,
) -> None:
    """Test querying logs by multiple actions."""
    log1 = AuditLog(
        action=AuditAction.CREATE,
        entity_type="reminder",
        entity_id="reminder-1",
        user_id="user-1",
    )
    log2 = AuditLog(
        action=AuditAction.UPDATE,
        entity_type="reminder",
        entity_id="reminder-2",
        user_id="user-1",
    )
    log3 = AuditLog(
        action=AuditAction.DELETE,
        entity_type="reminder",
        entity_id="reminder-3",
        user_id="user-1",
    )

    await repository.create(db_session, log1)
    await repository.create(db_session, log2)
    await repository.create(db_session, log3)
    await db_session.commit()

    query = AuditLogQuery(actions=[AuditAction.CREATE, AuditAction.UPDATE], limit=100)
    result = await repository.query_logs(db_session, query)

    assert result.total == 2
    assert len(result.items) == 2
    assert all(
        log.action in [AuditAction.CREATE, AuditAction.UPDATE] for log in result.items
    )


@pytest.mark.asyncio
async def test_query_logs_by_success_status(
    db_session: AsyncSession, repository: AuditRepository,
) -> None:
    """Test querying logs by success status."""
    log1 = AuditLog(
        action=AuditAction.CREATE,
        entity_type="reminder",
        entity_id="reminder-1",
        user_id="user-1",
        success=True,
    )
    log2 = AuditLog(
        action=AuditAction.CREATE,
        entity_type="reminder",
        entity_id="reminder-2",
        user_id="user-1",
        success=False,
        error_message="Failed to create",
    )
    log3 = AuditLog(
        action=AuditAction.UPDATE,
        entity_type="reminder",
        entity_id="reminder-3",
        user_id="user-1",
        success=True,
    )

    await repository.create(db_session, log1)
    await repository.create(db_session, log2)
    await repository.create(db_session, log3)
    await db_session.commit()

    query = AuditLogQuery(success=True, limit=100)
    result = await repository.query_logs(db_session, query)

    assert result.total == 2
    assert len(result.items) == 2
    assert all(log.success is True for log in result.items)


@pytest.mark.asyncio
async def test_query_logs_by_request_id(
    db_session: AsyncSession, repository: AuditRepository,
) -> None:
    """Test querying logs by request ID."""
    log1 = AuditLog(
        action=AuditAction.CREATE,
        entity_type="reminder",
        entity_id="reminder-1",
        user_id="user-1",
        request_id="req-123",
    )
    log2 = AuditLog(
        action=AuditAction.UPDATE,
        entity_type="reminder",
        entity_id="reminder-2",
        user_id="user-1",
        request_id="req-123",
    )
    log3 = AuditLog(
        action=AuditAction.CREATE,
        entity_type="reminder",
        entity_id="reminder-3",
        user_id="user-1",
        request_id="req-456",
    )

    await repository.create(db_session, log1)
    await repository.create(db_session, log2)
    await repository.create(db_session, log3)
    await db_session.commit()

    query = AuditLogQuery(request_id="req-123", limit=100)
    result = await repository.query_logs(db_session, query)

    assert result.total == 2
    assert len(result.items) == 2
    assert all(log.request_id == "req-123" for log in result.items)


@pytest.mark.asyncio
async def test_query_logs_by_time_range(
    db_session: AsyncSession, repository: AuditRepository,
) -> None:
    """Test querying logs by time range."""
    now = datetime.now(UTC)
    log1 = AuditLog(
        action=AuditAction.CREATE,
        entity_type="reminder",
        entity_id="reminder-1",
        user_id="user-1",
        timestamp=now - timedelta(hours=2),
    )
    log2 = AuditLog(
        action=AuditAction.UPDATE,
        entity_type="reminder",
        entity_id="reminder-2",
        user_id="user-1",
        timestamp=now - timedelta(hours=1),
    )
    log3 = AuditLog(
        action=AuditAction.CREATE,
        entity_type="reminder",
        entity_id="reminder-3",
        user_id="user-1",
        timestamp=now + timedelta(hours=1),
    )

    await repository.create(db_session, log1)
    await repository.create(db_session, log2)
    await repository.create(db_session, log3)
    await db_session.commit()

    query = AuditLogQuery(
        start_time=now - timedelta(hours=3),
        end_time=now,
        limit=100,
    )
    result = await repository.query_logs(db_session, query)

    assert result.total == 2
    assert len(result.items) == 2
    assert all(log.timestamp <= now for log in result.items)


@pytest.mark.asyncio
async def test_query_logs_pagination(
    db_session: AsyncSession, repository: AuditRepository,
) -> None:
    """Test pagination in query_logs."""
    # Create multiple logs
    for i in range(10):
        log = AuditLog(
            action=AuditAction.CREATE,
            entity_type="reminder",
            entity_id=f"reminder-{i}",
            user_id="user-1",
        )
        await repository.create(db_session, log)
    await db_session.commit()

    # First page
    query1 = AuditLogQuery(limit=5, offset=0)
    result1 = await repository.query_logs(db_session, query1)

    assert result1.total == 10
    assert len(result1.items) == 5

    # Second page
    query2 = AuditLogQuery(limit=5, offset=5)
    result2 = await repository.query_logs(db_session, query2)

    assert result2.total == 10
    assert len(result2.items) == 5
    assert result1.items[0].id != result2.items[0].id


@pytest.mark.asyncio
async def test_query_logs_ordering(
    db_session: AsyncSession, repository: AuditRepository,
) -> None:
    """Test ordering in query_logs."""
    now = datetime.now(UTC)
    log1 = AuditLog(
        action=AuditAction.CREATE,
        entity_type="reminder",
        entity_id="reminder-1",
        user_id="user-1",
        timestamp=now - timedelta(hours=2),
    )
    log2 = AuditLog(
        action=AuditAction.UPDATE,
        entity_type="reminder",
        entity_id="reminder-2",
        user_id="user-1",
        timestamp=now - timedelta(hours=1),
    )
    log3 = AuditLog(
        action=AuditAction.CREATE,
        entity_type="reminder",
        entity_id="reminder-3",
        user_id="user-1",
        timestamp=now,
    )

    await repository.create(db_session, log1)
    await repository.create(db_session, log2)
    await repository.create(db_session, log3)
    await db_session.commit()

    # Descending order (default)
    query_desc = AuditLogQuery(order_by="timestamp", order_desc=True, limit=100)
    result_desc = await repository.query_logs(db_session, query_desc)

    assert len(result_desc.items) == 3
    assert result_desc.items[0].timestamp >= result_desc.items[1].timestamp
    assert result_desc.items[1].timestamp >= result_desc.items[2].timestamp

    # Ascending order
    query_asc = AuditLogQuery(order_by="timestamp", order_desc=False, limit=100)
    result_asc = await repository.query_logs(db_session, query_asc)

    assert len(result_asc.items) == 3
    assert result_asc.items[0].timestamp <= result_asc.items[1].timestamp
    assert result_asc.items[1].timestamp <= result_asc.items[2].timestamp


@pytest.mark.asyncio
async def test_get_entity_history(
    db_session: AsyncSession, repository: AuditRepository,
) -> None:
    """Test getting audit history for a specific entity."""
    entity_type = "reminder"
    entity_id = "reminder-123"

    # Create multiple audit logs for the same entity
    log1 = AuditLog(
        action=AuditAction.CREATE,
        entity_type=entity_type,
        entity_id=entity_id,
        user_id="user-1",
        timestamp=datetime.now(UTC) - timedelta(hours=2),
    )
    log2 = AuditLog(
        action=AuditAction.UPDATE,
        entity_type=entity_type,
        entity_id=entity_id,
        user_id="user-1",
        timestamp=datetime.now(UTC) - timedelta(hours=1),
    )
    log3 = AuditLog(
        action=AuditAction.UPDATE,
        entity_type=entity_type,
        entity_id=entity_id,
        user_id="user-2",
        timestamp=datetime.now(UTC),
    )
    # Different entity
    log4 = AuditLog(
        action=AuditAction.CREATE,
        entity_type=entity_type,
        entity_id="reminder-456",
        user_id="user-1",
    )

    await repository.create(db_session, log1)
    await repository.create(db_session, log2)
    await repository.create(db_session, log3)
    await repository.create(db_session, log4)
    await db_session.commit()

    history = await repository.get_entity_history(db_session, entity_type, entity_id)

    assert len(history) == 3
    assert all(
        log.entity_type == entity_type and log.entity_id == entity_id for log in history
    )
    # Should be ordered by timestamp descending (newest first)
    assert history[0].timestamp >= history[1].timestamp
    assert history[1].timestamp >= history[2].timestamp


@pytest.mark.asyncio
async def test_get_entity_history_respects_limit(
    db_session: AsyncSession, repository: AuditRepository,
) -> None:
    """Test that get_entity_history respects limit parameter."""
    entity_type = "reminder"
    entity_id = "reminder-123"

    # Create more logs than limit
    for _ in range(10):
        log = AuditLog(
            action=AuditAction.UPDATE,
            entity_type=entity_type,
            entity_id=entity_id,
            user_id="user-1",
        )
        await repository.create(db_session, log)
    await db_session.commit()

    history = await repository.get_entity_history(
        db_session, entity_type, entity_id, limit=5,
    )

    assert len(history) == 5


@pytest.mark.asyncio
async def test_get_summary_stats(
    db_session: AsyncSession, repository: AuditRepository,
) -> None:
    """Test getting summary statistics."""
    # Create various audit logs
    logs = [
        AuditLog(
            action=AuditAction.CREATE,
            entity_type="reminder",
            entity_id=f"reminder-{i}",
            user_id="user-1",
            tenant_id="tenant-123",
            success=True,
        )
        for i in range(5)
    ]
    logs.extend([
        AuditLog(
            action=AuditAction.UPDATE,
            entity_type="reminder",
            entity_id=f"reminder-{i}",
            user_id="user-1",
            tenant_id="tenant-123",
            success=True,
        )
        for i in range(3)
    ])
    logs.append(
        AuditLog(
            action=AuditAction.CREATE,
            entity_type="task",
            entity_id="task-1",
            user_id="user-2",
            tenant_id="tenant-123",
            success=False,
        ),
    )

    for log in logs:
        await repository.create(db_session, log)
    await db_session.commit()

    stats = await repository.get_summary_stats(db_session, tenant_id="tenant-123")

    assert stats["total_entries"] == 9
    assert stats["actions_count"][AuditAction.CREATE.value] == 6
    assert stats["actions_count"][AuditAction.UPDATE.value] == 3
    assert stats["entity_types_count"]["reminder"] == 8
    assert stats["entity_types_count"]["task"] == 1
    assert stats["success_count"] == 8
    assert stats["unique_users"] == 2
    assert stats["time_range"][0] is not None
    assert stats["time_range"][1] is not None


@pytest.mark.asyncio
async def test_get_summary_stats_with_time_filter(
    db_session: AsyncSession, repository: AuditRepository,
) -> None:
    """Test summary statistics with time filter."""
    now = datetime.now(UTC)
    log1 = AuditLog(
        action=AuditAction.CREATE,
        entity_type="reminder",
        entity_id="reminder-1",
        user_id="user-1",
        timestamp=now - timedelta(hours=2),
    )
    log2 = AuditLog(
        action=AuditAction.UPDATE,
        entity_type="reminder",
        entity_id="reminder-2",
        user_id="user-1",
        timestamp=now - timedelta(hours=1),
    )
    log3 = AuditLog(
        action=AuditAction.CREATE,
        entity_type="reminder",
        entity_id="reminder-3",
        user_id="user-1",
        timestamp=now + timedelta(hours=1),
    )

    await repository.create(db_session, log1)
    await repository.create(db_session, log2)
    await repository.create(db_session, log3)
    await db_session.commit()

    stats = await repository.get_summary_stats(
        db_session,
        start_time=now - timedelta(hours=3),
        end_time=now,
    )

    assert stats["total_entries"] == 2


@pytest.mark.asyncio
async def test_delete_before(
    db_session: AsyncSession, repository: AuditRepository,
) -> None:
    """Test deleting logs before a specified date."""
    now = datetime.now(UTC)
    log1 = AuditLog(
        action=AuditAction.CREATE,
        entity_type="reminder",
        entity_id="reminder-1",
        user_id="user-1",
        timestamp=now - timedelta(days=10),
    )
    log2 = AuditLog(
        action=AuditAction.UPDATE,
        entity_type="reminder",
        entity_id="reminder-2",
        user_id="user-1",
        timestamp=now - timedelta(days=5),
    )
    log3 = AuditLog(
        action=AuditAction.CREATE,
        entity_type="reminder",
        entity_id="reminder-3",
        user_id="user-1",
        timestamp=now - timedelta(days=1),
    )

    await repository.create(db_session, log1)
    await repository.create(db_session, log2)
    await repository.create(db_session, log3)
    await db_session.commit()

    deleted = await repository.delete_before(db_session, now - timedelta(days=7))
    await db_session.commit()

    assert deleted == 1

    # Verify log1 was deleted
    remaining = await repository.get(db_session, log1.id)
    assert remaining is None

    # Verify log2 and log3 still exist
    assert await repository.get(db_session, log2.id) is not None
    assert await repository.get(db_session, log3.id) is not None


@pytest.mark.asyncio
async def test_delete_before_with_tenant_filter(
    db_session: AsyncSession, repository: AuditRepository,
) -> None:
    """Test deleting logs before date with tenant filter."""
    now = datetime.now(UTC)
    log1 = AuditLog(
        action=AuditAction.CREATE,
        entity_type="reminder",
        entity_id="reminder-1",
        user_id="user-1",
        tenant_id="tenant-123",
        timestamp=now - timedelta(days=10),
    )
    log2 = AuditLog(
        action=AuditAction.CREATE,
        entity_type="reminder",
        entity_id="reminder-2",
        user_id="user-1",
        tenant_id="tenant-456",
        timestamp=now - timedelta(days=10),
    )

    await repository.create(db_session, log1)
    await repository.create(db_session, log2)
    await db_session.commit()

    deleted = await repository.delete_before(
        db_session, now - timedelta(days=7), tenant_id="tenant-123",
    )
    await db_session.commit()

    assert deleted == 1

    # Verify log1 was deleted
    assert await repository.get(db_session, log1.id) is None

    # Verify log2 still exists
    assert await repository.get(db_session, log2.id) is not None


@pytest.mark.asyncio
async def test_query_logs_with_all_filters(
    db_session: AsyncSession, repository: AuditRepository,
) -> None:
    """Test query_logs with all filters combined."""
    now = datetime.now(UTC)
    log = AuditLog(
        action=AuditAction.CREATE,
        entity_type="reminder",
        entity_id="reminder-123",
        user_id="user-456",
        tenant_id="tenant-789",
        request_id="req-123",
        success=True,
        timestamp=now,
    )
    await repository.create(db_session, log)
    await db_session.commit()

    query = AuditLogQuery(
        entity_type="reminder",
        entity_id="reminder-123",
        user_id="user-456",
        tenant_id="tenant-789",
        action=AuditAction.CREATE,
        success=True,
        request_id="req-123",
        start_time=now - timedelta(hours=1),
        end_time=now + timedelta(hours=1),
        limit=100,
    )

    result = await repository.query_logs(db_session, query)

    assert result.total == 1
    assert len(result.items) == 1
    assert result.items[0].id == log.id
