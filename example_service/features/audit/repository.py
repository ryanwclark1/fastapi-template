"""Audit log repository for database operations.

Provides data access layer for audit logs, separating persistence
concerns from business logic in the service layer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import delete, desc, func, select

from example_service.core.database.repository import BaseRepository, SearchResult
from example_service.infra.logging import get_lazy_logger

from .models import AuditLog

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession

    from .schemas import AuditLogQuery

_lazy = get_lazy_logger(__name__)


class AuditRepository(BaseRepository[AuditLog]):
    """Repository for AuditLog database operations.

    Provides methods for:
    - Querying audit logs with complex filters
    - Getting entity-specific audit history
    - Generating aggregated statistics
    - Bulk deletion of old logs

    Example:
        repo = AuditRepository()
        log = await repo.get(session, audit_id)
        history = await repo.get_entity_history(session, "reminder", "123")
    """

    def __init__(self) -> None:
        """Initialize audit repository."""
        super().__init__(AuditLog)

    async def query_logs(
        self,
        session: AsyncSession,
        query: AuditLogQuery,
    ) -> SearchResult[AuditLog]:
        """Query audit logs with filters.

        Args:
            session: Database session.
            query: Query parameters with filters.

        Returns:
            SearchResult with paginated logs and total count.
        """
        stmt = select(AuditLog)

        # Apply filters
        if query.entity_type:
            stmt = stmt.where(AuditLog.entity_type == query.entity_type)
        if query.entity_id:
            stmt = stmt.where(AuditLog.entity_id == query.entity_id)
        if query.user_id:
            stmt = stmt.where(AuditLog.user_id == query.user_id)
        if query.tenant_id:
            stmt = stmt.where(AuditLog.tenant_id == query.tenant_id)
        if query.action:
            stmt = stmt.where(AuditLog.action == query.action.value)
        if query.actions:
            action_values = [a.value for a in query.actions]
            stmt = stmt.where(AuditLog.action.in_(action_values))
        if query.success is not None:
            stmt = stmt.where(AuditLog.success == query.success)
        if query.request_id:
            stmt = stmt.where(AuditLog.request_id == query.request_id)
        if query.start_time:
            stmt = stmt.where(AuditLog.timestamp >= query.start_time)
        if query.end_time:
            stmt = stmt.where(AuditLog.timestamp <= query.end_time)

        # Apply sorting
        order_column = getattr(AuditLog, query.order_by, AuditLog.timestamp)
        if query.order_desc:
            stmt = stmt.order_by(desc(order_column))
        else:
            stmt = stmt.order_by(order_column)

        # Use base class search for pagination
        return await self.search(session, stmt, limit=query.limit, offset=query.offset)

    async def get_entity_history(
        self,
        session: AsyncSession,
        entity_type: str,
        entity_id: str,
        *,
        limit: int = 100,
    ) -> Sequence[AuditLog]:
        """Get audit history for a specific entity.

        Args:
            session: Database session.
            entity_type: Type of entity (e.g., "reminder").
            entity_id: Entity identifier.
            limit: Maximum entries to return.

        Returns:
            Sequence of audit logs ordered by timestamp (newest first).
        """
        stmt = (
            select(AuditLog)
            .where(
                AuditLog.entity_type == entity_type,
                AuditLog.entity_id == entity_id,
            )
            .order_by(desc(AuditLog.timestamp))
            .limit(limit)
        )

        result = await session.execute(stmt)
        logs = result.scalars().all()

        _lazy.debug(lambda: f"get_entity_history: {entity_type}/{entity_id} -> {len(logs)} entries")
        return logs

    async def get_summary_stats(
        self,
        session: AsyncSession,
        *,
        tenant_id: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> dict[str, Any]:
        """Get aggregated audit statistics.

        Args:
            session: Database session.
            tenant_id: Optional tenant filter.
            start_time: Optional start time filter.
            end_time: Optional end time filter.

        Returns:
            Dictionary with aggregated statistics:
            - total_entries: Total count of logs
            - actions_count: Count by action type
            - entity_types_count: Count by entity type
            - success_count: Count of successful actions
            - unique_users: Count of unique user IDs
            - time_range: (min_timestamp, max_timestamp)
        """
        # Build base query with filters
        base_stmt = select(AuditLog)
        if tenant_id:
            base_stmt = base_stmt.where(AuditLog.tenant_id == tenant_id)
        if start_time:
            base_stmt = base_stmt.where(AuditLog.timestamp >= start_time)
        if end_time:
            base_stmt = base_stmt.where(AuditLog.timestamp <= end_time)

        subquery = base_stmt.subquery()

        # Total entries
        total_result = await session.execute(select(func.count()).select_from(subquery))
        total_entries = total_result.scalar() or 0

        # Action counts
        action_result = await session.execute(
            select(subquery.c.action, func.count())
            .select_from(subquery)
            .group_by(subquery.c.action)
        )
        # Convert enum keys to their values for dictionary
        actions_count: dict[Any, int] = dict(action_result.all())  # type: ignore[arg-type]

        # Entity type counts
        entity_result = await session.execute(
            select(subquery.c.entity_type, func.count())
            .select_from(subquery)
            .group_by(subquery.c.entity_type)
        )
        entity_types_count: dict[str, int] = dict(entity_result.all())  # type: ignore[arg-type]

        # Success count
        success_result = await session.execute(
            select(func.count()).select_from(subquery).where(subquery.c.success == True)  # noqa: E712
        )
        success_count = success_result.scalar() or 0

        # Unique users
        users_result = await session.execute(
            select(func.count(func.distinct(subquery.c.user_id))).select_from(subquery)
        )
        unique_users = users_result.scalar() or 0

        # Time range
        time_result = await session.execute(
            select(func.min(subquery.c.timestamp), func.max(subquery.c.timestamp)).select_from(
                subquery
            )
        )
        time_row = time_result.one_or_none()
        time_range = (time_row[0], time_row[1]) if time_row else (None, None)

        _lazy.debug(lambda: f"get_summary_stats: {total_entries} entries, {unique_users} users")

        return {
            "total_entries": total_entries,
            "actions_count": actions_count,
            "entity_types_count": entity_types_count,
            "success_count": success_count,
            "unique_users": unique_users,
            "time_range": time_range,
        }

    async def delete_before(
        self,
        session: AsyncSession,
        before: datetime,
        *,
        tenant_id: str | None = None,
    ) -> int:
        """Delete audit logs older than a specified date.

        Args:
            session: Database session.
            before: Delete logs before this date.
            tenant_id: Optional tenant filter.

        Returns:
            Number of deleted entries.
        """
        stmt = delete(AuditLog).where(AuditLog.timestamp < before)
        if tenant_id:
            stmt = stmt.where(AuditLog.tenant_id == tenant_id)

        result = await session.execute(stmt)
        deleted_count: int = result.rowcount  # type: ignore[attr-defined]

        self._logger.info(
            "Deleted old audit logs",
            extra={
                "before": before.isoformat(),
                "tenant_id": tenant_id,
                "deleted_count": deleted_count,
            },
        )

        return deleted_count


# Global singleton instance
_audit_repository: AuditRepository | None = None


def get_audit_repository() -> AuditRepository:
    """Get the global AuditRepository instance.

    Returns:
        Singleton AuditRepository instance.
    """
    global _audit_repository
    if _audit_repository is None:
        _audit_repository = AuditRepository()
    return _audit_repository


__all__ = [
    "AuditRepository",
    "get_audit_repository",
]
