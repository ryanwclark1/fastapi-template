"""Unit tests for AuditService."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from example_service.features.audit.models import AuditAction, AuditLog
from example_service.features.audit.schemas import (
    AuditLogCreate,
    AuditLogQuery,
)
from example_service.features.audit.service import AuditService, get_audit_service_with_session


@pytest.fixture
def service(db_session: AsyncSession) -> AuditService:
    """Create AuditService instance."""
    return AuditService(db_session)


@pytest.mark.asyncio
async def test_service_initialization(service: AuditService) -> None:
    """Test that service initializes correctly."""
    assert service is not None
    assert service.session is not None


@pytest.mark.asyncio
async def test_get_audit_service_with_session(db_session: AsyncSession) -> None:
    """Test get_audit_service_with_session helper."""
    service = get_audit_service_with_session(db_session)
    assert isinstance(service, AuditService)
    assert service.session is db_session


@pytest.mark.asyncio
async def test_log_creates_audit_entry(service: AuditService) -> None:
    """Test that log() creates an audit log entry."""
    log = await service.log(
        action=AuditAction.CREATE,
        entity_type="reminder",
        entity_id="reminder-123",
        user_id="user-456",
        tenant_id="tenant-789",
        new_values={"title": "New Reminder"},
        success=True,
    )

    assert log.id is not None
    assert log.action == AuditAction.CREATE.value
    assert log.entity_type == "reminder"
    assert log.entity_id == "reminder-123"
    assert log.user_id == "user-456"
    assert log.tenant_id == "tenant-789"
    assert log.new_values == {"title": "New Reminder"}
    assert log.success is True
    assert log.timestamp is not None


@pytest.mark.asyncio
async def test_log_computes_changes(service: AuditService) -> None:
    """Test that log() computes changes when both old and new values provided."""
    old_values = {"title": "Old Title", "status": "pending"}
    new_values = {"title": "New Title", "status": "pending", "priority": "high"}

    log = await service.log(
        action=AuditAction.UPDATE,
        entity_type="reminder",
        entity_id="reminder-123",
        old_values=old_values,
        new_values=new_values,
    )

    assert log.changes is not None
    assert "title" in log.changes
    assert log.changes["title"]["old"] == "Old Title"
    assert log.changes["title"]["new"] == "New Title"
    assert "priority" in log.changes
    assert log.changes["priority"]["old"] is None
    assert log.changes["priority"]["new"] == "high"
    # Unchanged field should not be in changes
    assert "status" not in log.changes


@pytest.mark.asyncio
async def test_log_with_all_fields(service: AuditService) -> None:
    """Test log() with all optional fields."""
    log = await service.log(
        action=AuditAction.CREATE,
        entity_type="reminder",
        entity_id="reminder-123",
        user_id="user-456",
        tenant_id="tenant-789",
        old_values={"old": "value"},
        new_values={"new": "value"},
        ip_address="192.168.1.1",
        user_agent="Mozilla/5.0",
        request_id="req-123",
        endpoint="/api/reminders",
        method="POST",
        metadata={"key": "value"},
        success=True,
        error_message=None,
        duration_ms=150,
    )

    assert log.ip_address == "192.168.1.1"
    assert log.user_agent == "Mozilla/5.0"
    assert log.request_id == "req-123"
    assert log.endpoint == "/api/reminders"
    assert log.method == "POST"
    assert log.context_data == {"key": "value"}
    assert log.success is True
    assert log.error_message is None
    assert log.duration_ms == 150


@pytest.mark.asyncio
async def test_log_with_error(service: AuditService) -> None:
    """Test log() with error information."""
    log = await service.log(
        action=AuditAction.CREATE,
        entity_type="reminder",
        entity_id="reminder-123",
        success=False,
        error_message="Validation failed",
    )

    assert log.success is False
    assert log.error_message == "Validation failed"


@pytest.mark.asyncio
async def test_log_from_schema(service: AuditService) -> None:
    """Test log_from_schema() method."""
    data = AuditLogCreate(
        action=AuditAction.UPDATE,
        entity_type="reminder",
        entity_id="reminder-123",
        user_id="user-456",
        new_values={"title": "Updated"},
    )

    log = await service.log_from_schema(data)

    assert log.action == AuditAction.UPDATE.value
    assert log.entity_type == "reminder"
    assert log.entity_id == "reminder-123"
    assert log.user_id == "user-456"
    assert log.new_values == {"title": "Updated"}


@pytest.mark.asyncio
async def test_get_by_id_found(service: AuditService) -> None:
    """Test get_by_id() when log exists."""
    created_log = await service.log(
        action=AuditAction.CREATE,
        entity_type="reminder",
        entity_id="reminder-123",
    )

    retrieved = await service.get_by_id(created_log.id)

    assert retrieved is not None
    assert retrieved.id == created_log.id
    assert retrieved.action == AuditAction.CREATE.value


@pytest.mark.asyncio
async def test_get_by_id_not_found(service: AuditService) -> None:
    """Test get_by_id() when log doesn't exist."""
    from uuid import uuid4

    fake_id = uuid4()
    retrieved = await service.get_by_id(fake_id)

    assert retrieved is None


@pytest.mark.asyncio
async def test_query_with_filters(service: AuditService) -> None:
    """Test query() with various filters."""
    # Create test logs
    await service.log(
        action=AuditAction.CREATE,
        entity_type="reminder",
        entity_id="reminder-1",
        user_id="user-123",
        tenant_id="tenant-123",
        success=True,
    )
    await service.log(
        action=AuditAction.UPDATE,
        entity_type="reminder",
        entity_id="reminder-2",
        user_id="user-123",
        tenant_id="tenant-123",
        success=True,
    )
    await service.log(
        action=AuditAction.CREATE,
        entity_type="task",
        entity_id="task-1",
        user_id="user-456",
        tenant_id="tenant-123",
        success=False,
    )

    # Query with filters
    query = AuditLogQuery(
        entity_type="reminder",
        user_id="user-123",
        tenant_id="tenant-123",
        success=True,
        limit=100,
    )

    result = await service.query(query)

    assert result.total == 2
    assert len(result.items) == 2
    assert all(
        item.entity_type == "reminder"
        and item.user_id == "user-123"
        and item.tenant_id == "tenant-123"
        and item.success is True
        for item in result.items
    )


@pytest.mark.asyncio
async def test_query_pagination(service: AuditService) -> None:
    """Test query() pagination."""
    # Create multiple logs
    for i in range(10):
        await service.log(
            action=AuditAction.CREATE,
            entity_type="reminder",
            entity_id=f"reminder-{i}",
        )

    # First page
    query1 = AuditLogQuery(limit=5, offset=0)
    result1 = await service.query(query1)

    assert result1.total == 10
    assert len(result1.items) == 5
    assert result1.limit == 5
    assert result1.offset == 0
    assert result1.has_more is True

    # Second page
    query2 = AuditLogQuery(limit=5, offset=5)
    result2 = await service.query(query2)

    assert result2.total == 10
    assert len(result2.items) == 5
    assert result2.has_more is False


@pytest.mark.asyncio
async def test_query_ordering(service: AuditService) -> None:
    """Test query() ordering."""
    now = datetime.now(UTC)
    # Create logs with different timestamps
    log1 = await service.log(
        action=AuditAction.CREATE,
        entity_type="reminder",
        entity_id="reminder-1",
    )
    # Manually set timestamp for testing
    log1.timestamp = now - timedelta(hours=2)
    await service.session.commit()
    await service.session.refresh(log1)

    log2 = await service.log(
        action=AuditAction.CREATE,
        entity_type="reminder",
        entity_id="reminder-2",
    )
    log2.timestamp = now - timedelta(hours=1)
    await service.session.commit()
    await service.session.refresh(log2)

    # Descending order (default)
    query_desc = AuditLogQuery(order_by="timestamp", order_desc=True, limit=100)
    result_desc = await service.query(query_desc)

    assert len(result_desc.items) >= 2
    # Newest first
    timestamps = [item.timestamp for item in result_desc.items[:2]]
    assert timestamps[0] >= timestamps[1]

    # Ascending order
    query_asc = AuditLogQuery(order_by="timestamp", order_desc=False, limit=100)
    result_asc = await service.query(query_asc)

    assert len(result_asc.items) >= 2
    # Oldest first
    timestamps_asc = [item.timestamp for item in result_asc.items[:2]]
    assert timestamps_asc[0] <= timestamps_asc[1]


@pytest.mark.asyncio
async def test_query_by_action(service: AuditService) -> None:
    """Test query() filtering by action."""
    await service.log(
        action=AuditAction.CREATE,
        entity_type="reminder",
        entity_id="reminder-1",
    )
    await service.log(
        action=AuditAction.UPDATE,
        entity_type="reminder",
        entity_id="reminder-2",
    )
    await service.log(
        action=AuditAction.CREATE,
        entity_type="reminder",
        entity_id="reminder-3",
    )

    query = AuditLogQuery(action=AuditAction.CREATE, limit=100)
    result = await service.query(query)

    assert result.total == 2
    assert all(item.action == AuditAction.CREATE.value for item in result.items)


@pytest.mark.asyncio
async def test_query_by_multiple_actions(service: AuditService) -> None:
    """Test query() filtering by multiple actions."""
    await service.log(
        action=AuditAction.CREATE,
        entity_type="reminder",
        entity_id="reminder-1",
    )
    await service.log(
        action=AuditAction.UPDATE,
        entity_type="reminder",
        entity_id="reminder-2",
    )
    await service.log(
        action=AuditAction.DELETE,
        entity_type="reminder",
        entity_id="reminder-3",
    )

    query = AuditLogQuery(actions=[AuditAction.CREATE, AuditAction.UPDATE], limit=100)
    result = await service.query(query)

    assert result.total == 2
    assert all(
        item.action in [AuditAction.CREATE.value, AuditAction.UPDATE.value] for item in result.items
    )


@pytest.mark.asyncio
async def test_query_by_time_range(service: AuditService) -> None:
    """Test query() filtering by time range."""
    now = datetime.now(UTC)
    # Create logs with different timestamps
    log1 = await service.log(
        action=AuditAction.CREATE,
        entity_type="reminder",
        entity_id="reminder-1",
    )
    log1.timestamp = now - timedelta(hours=2)
    await service.session.commit()
    await service.session.refresh(log1)

    log2 = await service.log(
        action=AuditAction.CREATE,
        entity_type="reminder",
        entity_id="reminder-2",
    )
    log2.timestamp = now - timedelta(hours=1)
    await service.session.commit()
    await service.session.refresh(log2)

    log3 = await service.log(
        action=AuditAction.CREATE,
        entity_type="reminder",
        entity_id="reminder-3",
    )
    log3.timestamp = now + timedelta(hours=1)
    await service.session.commit()
    await service.session.refresh(log3)

    query = AuditLogQuery(
        start_time=now - timedelta(hours=3),
        end_time=now,
        limit=100,
    )
    result = await service.query(query)

    assert result.total == 2
    assert all(item.timestamp <= now for item in result.items)


@pytest.mark.asyncio
async def test_get_entity_history(service: AuditService) -> None:
    """Test get_entity_history() returns complete history."""
    entity_type = "reminder"
    entity_id = "reminder-123"

    # Create history
    log1 = await service.log(
        action=AuditAction.CREATE,
        entity_type=entity_type,
        entity_id=entity_id,
        user_id="user-1",
    )
    log1.timestamp = datetime.now(UTC) - timedelta(hours=2)
    await service.session.commit()
    await service.session.refresh(log1)

    log2 = await service.log(
        action=AuditAction.UPDATE,
        entity_type=entity_type,
        entity_id=entity_id,
        user_id="user-2",
    )
    log2.timestamp = datetime.now(UTC) - timedelta(hours=1)
    await service.session.commit()
    await service.session.refresh(log2)

    log3 = await service.log(
        action=AuditAction.UPDATE,
        entity_type=entity_type,
        entity_id=entity_id,
        user_id="user-3",
    )

    history = await service.get_entity_history(entity_type, entity_id)

    assert history.entity_type == entity_type
    assert history.entity_id == entity_id
    assert len(history.entries) == 3
    assert history.created_at == log1.timestamp
    assert history.created_by == "user-1"
    assert history.last_modified_at == log3.timestamp
    assert history.last_modified_by == "user-3"
    assert history.total_changes == 3
    # Should be ordered newest first
    assert history.entries[0].timestamp >= history.entries[1].timestamp


@pytest.mark.asyncio
async def test_get_entity_history_respects_limit(service: AuditService) -> None:
    """Test that get_entity_history() respects limit."""
    entity_type = "reminder"
    entity_id = "reminder-123"

    # Create more logs than limit
    for _ in range(10):
        await service.log(
            action=AuditAction.UPDATE,
            entity_type=entity_type,
            entity_id=entity_id,
        )

    history = await service.get_entity_history(entity_type, entity_id, limit=5)

    assert len(history.entries) == 5


@pytest.mark.asyncio
async def test_get_entity_history_without_create_action(service: AuditService) -> None:
    """Test get_entity_history() when no CREATE action exists."""
    entity_type = "reminder"
    entity_id = "reminder-123"

    await service.log(
        action=AuditAction.UPDATE,
        entity_type=entity_type,
        entity_id=entity_id,
        user_id="user-1",
    )

    history = await service.get_entity_history(entity_type, entity_id)

    assert history.created_at is None
    assert history.created_by is None
    assert history.last_modified_at is not None
    assert history.last_modified_by == "user-1"


@pytest.mark.asyncio
async def test_get_summary(service: AuditService) -> None:
    """Test get_summary() returns statistics."""
    # Create various audit logs
    for i in range(5):
        await service.log(
            action=AuditAction.CREATE,
            entity_type="reminder",
            entity_id=f"reminder-{i}",
            user_id="user-1",
            tenant_id="tenant-123",
            success=True,
        )
    for i in range(3):
        await service.log(
            action=AuditAction.UPDATE,
            entity_type="reminder",
            entity_id=f"reminder-{i}",
            user_id="user-1",
            tenant_id="tenant-123",
            success=True,
        )
    await service.log(
        action=AuditAction.CREATE,
        entity_type="task",
        entity_id="task-1",
        user_id="user-2",
        tenant_id="tenant-123",
        success=False,
    )

    summary = await service.get_summary(tenant_id="tenant-123")

    assert summary.total_entries == 9
    assert summary.actions_count[AuditAction.CREATE.value] == 6
    assert summary.actions_count[AuditAction.UPDATE.value] == 3
    assert summary.entity_types_count["reminder"] == 8
    assert summary.entity_types_count["task"] == 1
    assert summary.success_rate == pytest.approx(88.89, abs=0.01)  # 8/9 * 100
    assert summary.unique_users == 2
    assert summary.time_range_start is not None
    assert summary.time_range_end is not None


@pytest.mark.asyncio
async def test_get_summary_with_time_filter(service: AuditService) -> None:
    """Test get_summary() with time filter."""
    now = datetime.now(UTC)
    log1 = await service.log(
        action=AuditAction.CREATE,
        entity_type="reminder",
        entity_id="reminder-1",
    )
    log1.timestamp = now - timedelta(hours=2)
    await service.session.commit()
    await service.session.refresh(log1)

    log2 = await service.log(
        action=AuditAction.CREATE,
        entity_type="reminder",
        entity_id="reminder-2",
    )
    log2.timestamp = now - timedelta(hours=1)
    await service.session.commit()
    await service.session.refresh(log2)

    log3 = await service.log(
        action=AuditAction.CREATE,
        entity_type="reminder",
        entity_id="reminder-3",
    )
    log3.timestamp = now + timedelta(hours=1)
    await service.session.commit()
    await service.session.refresh(log3)

    summary = await service.get_summary(
        start_time=now - timedelta(hours=3),
        end_time=now,
    )

    assert summary.total_entries == 2


@pytest.mark.asyncio
async def test_get_summary_empty(service: AuditService) -> None:
    """Test get_summary() with no logs."""
    summary = await service.get_summary()

    assert summary.total_entries == 0
    assert summary.actions_count == {}
    assert summary.entity_types_count == {}
    assert summary.success_rate == 100.0
    assert summary.unique_users == 0
    assert summary.time_range_start is None
    assert summary.time_range_end is None


@pytest.mark.asyncio
async def test_delete_old_logs(service: AuditService) -> None:
    """Test delete_old_logs() removes old entries."""
    now = datetime.now(UTC)
    log1 = await service.log(
        action=AuditAction.CREATE,
        entity_type="reminder",
        entity_id="reminder-1",
    )
    log1.timestamp = now - timedelta(days=10)
    await service.session.commit()
    await service.session.refresh(log1)

    log2 = await service.log(
        action=AuditAction.CREATE,
        entity_type="reminder",
        entity_id="reminder-2",
    )
    log2.timestamp = now - timedelta(days=5)
    await service.session.commit()
    await service.session.refresh(log2)

    log3 = await service.log(
        action=AuditAction.CREATE,
        entity_type="reminder",
        entity_id="reminder-3",
    )
    log3.timestamp = now - timedelta(days=1)
    await service.session.commit()
    await service.session.refresh(log3)

    deleted = await service.delete_old_logs(now - timedelta(days=7))

    assert deleted == 1

    # Verify log1 was deleted
    assert await service.get_by_id(log1.id) is None

    # Verify log2 and log3 still exist
    assert await service.get_by_id(log2.id) is not None
    assert await service.get_by_id(log3.id) is not None


@pytest.mark.asyncio
async def test_delete_old_logs_with_tenant_filter(service: AuditService) -> None:
    """Test delete_old_logs() with tenant filter."""
    now = datetime.now(UTC)
    log1 = await service.log(
        action=AuditAction.CREATE,
        entity_type="reminder",
        entity_id="reminder-1",
        tenant_id="tenant-123",
    )
    log1.timestamp = now - timedelta(days=10)
    await service.session.commit()
    await service.session.refresh(log1)

    log2 = await service.log(
        action=AuditAction.CREATE,
        entity_type="reminder",
        entity_id="reminder-2",
        tenant_id="tenant-456",
    )
    log2.timestamp = now - timedelta(days=10)
    await service.session.commit()
    await service.session.refresh(log2)

    deleted = await service.delete_old_logs(now - timedelta(days=7), tenant_id="tenant-123")

    assert deleted == 1

    # Verify log1 was deleted
    assert await service.get_by_id(log1.id) is None

    # Verify log2 still exists
    assert await service.get_by_id(log2.id) is not None


@pytest.mark.asyncio
async def test_query_response_structure(service: AuditService) -> None:
    """Test that query() returns properly structured response."""
    await service.log(
        action=AuditAction.CREATE,
        entity_type="reminder",
        entity_id="reminder-1",
    )

    query = AuditLogQuery(limit=10)
    result = await service.query(query)

    assert hasattr(result, "items")
    assert hasattr(result, "total")
    assert hasattr(result, "limit")
    assert hasattr(result, "offset")
    assert hasattr(result, "has_more")
    assert isinstance(result.items, list)
    assert isinstance(result.total, int)
    assert isinstance(result.limit, int)
    assert isinstance(result.offset, int)
    assert isinstance(result.has_more, bool)


@pytest.mark.asyncio
async def test_query_with_custom_order_by(service: AuditService) -> None:
    """Test query() with custom order_by field."""
    await service.log(
        action=AuditAction.CREATE,
        entity_type="reminder",
        entity_id="reminder-1",
        user_id="user-1",
    )
    await service.log(
        action=AuditAction.CREATE,
        entity_type="reminder",
        entity_id="reminder-2",
        user_id="user-2",
    )

    # Order by user_id
    query = AuditLogQuery(order_by="user_id", order_desc=False, limit=100)
    result = await service.query(query)

    assert len(result.items) >= 2
    # Should be ordered by user_id
    user_ids = [item.user_id for item in result.items if item.user_id]
    if len(user_ids) >= 2:
        assert user_ids[0] <= user_ids[1]


@pytest.mark.asyncio
async def test_query_with_invalid_order_by_falls_back_to_timestamp(
    service: AuditService,
) -> None:
    """Test query() falls back to timestamp when order_by field doesn't exist."""
    await service.log(
        action=AuditAction.CREATE,
        entity_type="reminder",
        entity_id="reminder-1",
    )

    # Invalid order_by field
    query = AuditLogQuery(order_by="nonexistent_field", order_desc=True, limit=100)
    result = await service.query(query)

    # Should still work, falling back to timestamp
    assert len(result.items) >= 1


@pytest.mark.asyncio
async def test_get_entity_history_empty(service: AuditService) -> None:
    """Test get_entity_history() when entity has no history."""
    history = await service.get_entity_history("reminder", "nonexistent-id")

    assert history.entity_type == "reminder"
    assert history.entity_id == "nonexistent-id"
    assert len(history.entries) == 0
    assert history.created_at is None
    assert history.created_by is None
    assert history.last_modified_at is None
    assert history.last_modified_by is None
    assert history.total_changes == 0


@pytest.mark.asyncio
async def test_get_entity_history_multiple_updates(service: AuditService) -> None:
    """Test get_entity_history() with multiple updates."""
    entity_type = "reminder"
    entity_id = "reminder-123"

    # Create with user-1
    log1 = await service.log(
        action=AuditAction.CREATE,
        entity_type=entity_type,
        entity_id=entity_id,
        user_id="user-1",
    )
    log1.timestamp = datetime.now(UTC) - timedelta(hours=3)
    await service.session.commit()
    await service.session.refresh(log1)

    # Update with user-2
    log2 = await service.log(
        action=AuditAction.UPDATE,
        entity_type=entity_type,
        entity_id=entity_id,
        user_id="user-2",
    )
    log2.timestamp = datetime.now(UTC) - timedelta(hours=2)
    await service.session.commit()
    await service.session.refresh(log2)

    # Update with user-3
    log3 = await service.log(
        action=AuditAction.UPDATE,
        entity_type=entity_type,
        entity_id=entity_id,
        user_id="user-3",
    )

    history = await service.get_entity_history(entity_type, entity_id)

    assert history.created_at == log1.timestamp
    assert history.created_by == "user-1"
    assert history.last_modified_at == log3.timestamp
    assert history.last_modified_by == "user-3"
    assert history.total_changes == 3


@pytest.mark.asyncio
async def test_get_summary_with_no_logs(service: AuditService) -> None:
    """Test get_summary() with no audit logs."""
    summary = await service.get_summary()

    assert summary.total_entries == 0
    assert summary.actions_count == {}
    assert summary.entity_types_count == {}
    assert summary.success_rate == 100.0
    assert summary.unique_users == 0
    assert summary.time_range_start is None
    assert summary.time_range_end is None


@pytest.mark.asyncio
async def test_get_summary_with_only_failed_logs(service: AuditService) -> None:
    """Test get_summary() when all logs are failed."""
    for i in range(3):
        await service.log(
            action=AuditAction.CREATE,
            entity_type="reminder",
            entity_id=f"reminder-{i}",
            success=False,
            error_message="Failed",
        )

    summary = await service.get_summary()

    assert summary.total_entries == 3
    assert summary.success_rate == 0.0
    assert summary.actions_count[AuditAction.CREATE.value] == 3


@pytest.mark.asyncio
async def test_get_summary_with_mixed_success(service: AuditService) -> None:
    """Test get_summary() with mixed success and failure."""
    # 3 successful
    for i in range(3):
        await service.log(
            action=AuditAction.CREATE,
            entity_type="reminder",
            entity_id=f"reminder-{i}",
            success=True,
        )

    # 2 failed
    for i in range(3, 5):
        await service.log(
            action=AuditAction.CREATE,
            entity_type="reminder",
            entity_id=f"reminder-{i}",
            success=False,
        )

    summary = await service.get_summary()

    assert summary.total_entries == 5
    assert summary.success_rate == 60.0  # 3/5 * 100


@pytest.mark.asyncio
async def test_delete_old_logs_no_matching_logs(service: AuditService) -> None:
    """Test delete_old_logs() when no logs match criteria."""
    now = datetime.now(UTC)
    # Create recent log
    await service.log(
        action=AuditAction.CREATE,
        entity_type="reminder",
        entity_id="reminder-1",
    )

    # Try to delete logs older than 1 year ago
    deleted = await service.delete_old_logs(now - timedelta(days=365))

    assert deleted == 0


@pytest.mark.asyncio
async def test_get_audit_service_helper(service: AuditService) -> None:
    """Test get_audit_service() helper function."""
    from example_service.features.audit.service import get_audit_service_with_session

    service_from_helper = get_audit_service_with_session(service.session)

    assert isinstance(service_from_helper, AuditService)
    assert service_from_helper.session is service.session


@pytest.mark.asyncio
async def test_log_with_minimal_fields(service: AuditService) -> None:
    """Test log() with only required fields."""
    log = await service.log(
        action=AuditAction.READ,
        entity_type="reminder",
    )

    assert log.id is not None
    assert log.action == AuditAction.READ.value
    assert log.entity_type == "reminder"
    assert log.entity_id is None
    assert log.user_id is None
    assert log.tenant_id is None
    assert log.success is True


@pytest.mark.asyncio
async def test_log_with_none_values(service: AuditService) -> None:
    """Test log() handles None values correctly."""
    log = await service.log(
        action=AuditAction.CREATE,
        entity_type="reminder",
        entity_id=None,
        user_id=None,
        tenant_id=None,
        old_values=None,
        new_values=None,
        ip_address=None,
        user_agent=None,
        request_id=None,
        endpoint=None,
        method=None,
        metadata=None,
        success=True,
        error_message=None,
        duration_ms=None,
    )

    assert log.entity_id is None
    assert log.user_id is None
    assert log.tenant_id is None
    assert log.old_values is None
    assert log.new_values is None


@pytest.mark.asyncio
async def test_query_has_more_calculation(service: AuditService) -> None:
    """Test that has_more is calculated correctly in query()."""
    # Create 10 logs
    for i in range(10):
        await service.log(
            action=AuditAction.CREATE,
            entity_type="reminder",
            entity_id=f"reminder-{i}",
        )

    # First page with limit 5
    query1 = AuditLogQuery(limit=5, offset=0)
    result1 = await service.query(query1)

    assert result1.has_more is True  # 10 total, showing 5, so more exists

    # Last page
    query2 = AuditLogQuery(limit=5, offset=5)
    result2 = await service.query(query2)

    assert result2.has_more is False  # 10 total, showing last 5, no more


@pytest.mark.asyncio
async def test_query_with_all_filters_combined(service: AuditService) -> None:
    """Test query() with all possible filters combined."""
    now = datetime.now(UTC)
    log = await service.log(
        action=AuditAction.CREATE,
        entity_type="reminder",
        entity_id="reminder-123",
        user_id="user-456",
        tenant_id="tenant-789",
        request_id="req-123",
        success=True,
    )
    log.timestamp = now
    await service.session.commit()
    await service.session.refresh(log)

    # Create another log that doesn't match all filters
    await service.log(
        action=AuditAction.UPDATE,
        entity_type="task",
        entity_id="task-456",
        user_id="user-999",
        tenant_id="tenant-999",
        success=False,
    )

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

    result = await service.query(query)

    assert result.total == 1
    assert len(result.items) == 1
    assert result.items[0].id == log.id
