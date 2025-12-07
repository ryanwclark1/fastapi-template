"""Audit logging service.

Provides the main interface for recording and querying audit logs.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy import desc, func, or_, select

from example_service.infra.database.session import get_async_session

from .models import AuditAction, AuditLog
from .schemas import (
    AuditLogCreate,
    AuditLogListResponse,
    AuditLogQuery,
    AuditLogResponse,
    AuditSummary,
    DangerousActionsResponse,
    EntityAuditHistory,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class AuditService:
    """Service for managing audit logs.

    Provides methods for:
    - Recording audit log entries
    - Querying audit logs with filters
    - Getting entity history
    - Generating audit summaries

    Example:
        service = AuditService(session)

        # Log an action
        await service.log(
            action=AuditAction.CREATE,
            entity_type="reminder",
            entity_id="123",
            user_id="user-456",
            new_values={"title": "Meeting"},
        )

        # Query logs
        logs = await service.query(
            AuditLogQuery(entity_type="reminder", limit=100)
        )
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize audit service.

        Args:
            session: Async database session.
        """
        self.session = session

    async def log(
        self,
        action: AuditAction,
        entity_type: str,
        entity_id: str | None = None,
        user_id: str | None = None,
        actor_roles: list[str] | None = None,
        tenant_id: str | None = None,
        old_values: dict[str, Any] | None = None,
        new_values: dict[str, Any] | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        request_id: str | None = None,
        endpoint: str | None = None,
        method: str | None = None,
        metadata: dict[str, Any] | None = None,
        success: bool = True,
        error_message: str | None = None,
        duration_ms: int | None = None,
    ) -> AuditLog:
        """Record an audit log entry.

        Args:
            action: Type of action performed.
            entity_type: Type of entity affected.
            entity_id: ID of the affected entity.
            user_id: User who performed the action.
            actor_roles: Roles the user had at time of action.
            tenant_id: Tenant context.
            old_values: Previous state (for updates/deletes).
            new_values: New state (for creates/updates).
            ip_address: Client IP address.
            user_agent: Client user agent.
            request_id: Request correlation ID.
            endpoint: API endpoint path.
            method: HTTP method.
            metadata: Additional context data.
            success: Whether the action succeeded.
            error_message: Error details if failed.
            duration_ms: Action duration in milliseconds.

        Returns:
            Created AuditLog entry.
        """
        # Compute changes if both old and new values provided
        changes = AuditLog.compute_changes(old_values, new_values)

        audit_log = AuditLog(
            action=action.value,
            entity_type=entity_type,
            entity_id=entity_id,
            user_id=user_id,
            actor_roles=actor_roles or [],
            tenant_id=tenant_id,
            old_values=old_values,
            new_values=new_values,
            changes=changes,
            ip_address=ip_address,
            user_agent=user_agent,
            request_id=request_id,
            endpoint=endpoint,
            method=method,
            context_data=metadata,
            success=success,
            error_message=error_message,
            duration_ms=duration_ms,
        )

        self.session.add(audit_log)
        await self.session.commit()
        await self.session.refresh(audit_log)

        logger.debug(
            "Audit log created: %s on %s",
            action.value,
            entity_type,
            extra={
                "audit_id": str(audit_log.id),
                "action": action.value,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "user_id": user_id,
            },
        )

        return audit_log

    async def log_from_schema(self, data: AuditLogCreate) -> AuditLog:
        """Record an audit log entry from a schema.

        Args:
            data: Audit log creation data.

        Returns:
            Created AuditLog entry.
        """
        return await self.log(
            action=data.action,
            entity_type=data.entity_type,
            entity_id=data.entity_id,
            user_id=data.user_id,
            actor_roles=data.actor_roles,
            tenant_id=data.tenant_id,
            old_values=data.old_values,
            new_values=data.new_values,
            ip_address=data.ip_address,
            user_agent=data.user_agent,
            request_id=data.request_id,
            endpoint=data.endpoint,
            method=data.method,
            metadata=data.metadata,
            success=data.success,
            error_message=data.error_message,
            duration_ms=data.duration_ms,
        )

    async def log_bulk(
        self,
        entries: list[AuditLogCreate],
    ) -> Sequence[AuditLog]:
        """Create multiple audit entries efficiently.

        This is more efficient than calling log() multiple times as it
        uses a single database transaction for all entries.

        Args:
            entries: List of audit log creation data.

        Returns:
            Sequence of created audit log entries.

        Example:
            entries = [
                AuditLogCreate(
                    action=AuditAction.USER_CREATED,
                    entity_type="user",
                    entity_id="user-1",
                    user_id="admin-1",
                ),
                AuditLogCreate(
                    action=AuditAction.USER_CREATED,
                    entity_type="user",
                    entity_id="user-2",
                    user_id="admin-1",
                ),
            ]
            logs = await service.log_bulk(entries)
        """
        audit_logs = []
        for data in entries:
            changes = AuditLog.compute_changes(data.old_values, data.new_values)
            audit_log = AuditLog(
                action=data.action.value
                if hasattr(data.action, "value")
                else data.action,
                entity_type=data.entity_type,
                entity_id=data.entity_id,
                user_id=data.user_id,
                actor_roles=data.actor_roles or [],
                tenant_id=data.tenant_id,
                old_values=data.old_values,
                new_values=data.new_values,
                changes=changes,
                ip_address=data.ip_address,
                user_agent=data.user_agent,
                request_id=data.request_id,
                endpoint=data.endpoint,
                method=data.method,
                context_data=data.metadata,
                success=data.success,
                error_message=data.error_message,
                duration_ms=data.duration_ms,
            )
            audit_logs.append(audit_log)

        self.session.add_all(audit_logs)
        await self.session.commit()

        for audit_log in audit_logs:
            await self.session.refresh(audit_log)

        logger.debug(
            "Bulk created %s audit log entries",
            len(audit_logs),
            extra={"count": len(audit_logs)},
        )

        return audit_logs

    async def get_by_id(self, audit_id: UUID) -> AuditLog | None:
        """Get an audit log entry by ID.

        Args:
            audit_id: Audit log ID.

        Returns:
            AuditLog if found, None otherwise.
        """
        stmt = select(AuditLog).where(AuditLog.id == audit_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def query(self, query: AuditLogQuery) -> AuditLogListResponse:
        """Query audit logs with filters.

        Args:
            query: Query parameters.

        Returns:
            Paginated list of audit logs.
        """
        # Build base query
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

        # Get total count
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total_result = await self.session.execute(count_stmt)
        total = total_result.scalar() or 0

        # Apply sorting
        order_column = getattr(AuditLog, query.order_by, AuditLog.timestamp)
        if query.order_desc:
            stmt = stmt.order_by(desc(order_column))
        else:
            stmt = stmt.order_by(order_column)

        # Apply pagination
        stmt = stmt.offset(query.offset).limit(query.limit)

        # Execute query
        result = await self.session.execute(stmt)
        logs = result.scalars().all()

        return AuditLogListResponse(
            items=[AuditLogResponse.model_validate(log) for log in logs],
            total=total,
            limit=query.limit,
            offset=query.offset,
            has_more=(query.offset + len(logs)) < total,
        )

    async def get_entity_history(
        self,
        entity_type: str,
        entity_id: str,
        limit: int = 100,
    ) -> EntityAuditHistory:
        """Get complete audit history for an entity.

        Args:
            entity_type: Type of entity.
            entity_id: Entity ID.
            limit: Maximum entries to return.

        Returns:
            Entity audit history.
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

        result = await self.session.execute(stmt)
        logs = result.scalars().all()

        # Find creation and last modification
        created_at = None
        created_by = None
        last_modified_at = None
        last_modified_by = None

        for log in reversed(logs):  # Oldest first
            if log.action == AuditAction.CREATE.value:
                created_at = log.timestamp
                created_by = log.user_id
            if log.action in (AuditAction.UPDATE.value, AuditAction.CREATE.value):
                last_modified_at = log.timestamp
                last_modified_by = log.user_id

        return EntityAuditHistory(
            entity_type=entity_type,
            entity_id=entity_id,
            entries=[AuditLogResponse.model_validate(log) for log in logs],
            created_at=created_at,
            created_by=created_by,
            last_modified_at=last_modified_at,
            last_modified_by=last_modified_by,
            total_changes=len(logs),
        )

    async def get_summary(
        self,
        tenant_id: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> AuditSummary:
        """Get audit log summary statistics.

        Args:
            tenant_id: Optional tenant filter.
            start_time: Optional start time filter.
            end_time: Optional end time filter.

        Returns:
            Audit summary statistics.
        """
        # Build base query
        base_stmt = select(AuditLog)
        if tenant_id:
            base_stmt = base_stmt.where(AuditLog.tenant_id == tenant_id)
        if start_time:
            base_stmt = base_stmt.where(AuditLog.timestamp >= start_time)
        if end_time:
            base_stmt = base_stmt.where(AuditLog.timestamp <= end_time)

        subquery = base_stmt.subquery()

        # Total entries
        total_result = await self.session.execute(
            select(func.count()).select_from(subquery)
        )
        total_entries = total_result.scalar() or 0

        # Action counts
        action_result = await self.session.execute(
            select(subquery.c.action, func.count())
            .select_from(subquery)
            .group_by(subquery.c.action)
        )
        actions_count: dict[str, int] = {str(k): v for k, v in action_result.all()}

        # Entity type counts
        entity_result = await self.session.execute(
            select(subquery.c.entity_type, func.count())
            .select_from(subquery)
            .group_by(subquery.c.entity_type)
        )
        entity_types_count: dict[str, int] = dict(entity_result.all())  # type: ignore

        # Success rate
        success_result = await self.session.execute(
            select(func.count()).select_from(subquery).where(subquery.c.success == True)  # noqa: E712
        )
        success_count = success_result.scalar() or 0
        success_rate = (
            (success_count / total_entries * 100) if total_entries > 0 else 100.0
        )

        # Unique users
        users_result = await self.session.execute(
            select(func.count(func.distinct(subquery.c.user_id))).select_from(subquery)
        )
        unique_users = users_result.scalar() or 0

        # Time range
        time_result = await self.session.execute(
            select(
                func.min(subquery.c.timestamp), func.max(subquery.c.timestamp)
            ).select_from(subquery)
        )
        time_row = time_result.one_or_none()
        time_range_start = time_row[0] if time_row else None
        time_range_end = time_row[1] if time_row else None

        # Count dangerous actions
        dangerous_count = await self._count_dangerous_actions(
            tenant_id, start_time, end_time
        )

        return AuditSummary(
            total_entries=total_entries,
            actions_count=actions_count,
            entity_types_count=entity_types_count,
            success_rate=success_rate,
            unique_users=unique_users,
            dangerous_actions_count=dangerous_count,
            time_range_start=time_range_start,
            time_range_end=time_range_end,
        )

    async def _count_dangerous_actions(
        self,
        tenant_id: str | None,
        start_time: datetime | None,
        end_time: datetime | None,
    ) -> int:
        """Count dangerous actions for a time period."""
        dangerous_patterns = ["%.deleted", "%.revoked", "%.suspended", "%.disconnected"]
        dangerous_exact = ["delete", "bulk_delete", "purge"]

        action_filters = [
            AuditLog.action.like(pattern) for pattern in dangerous_patterns
        ]
        action_filters.extend([AuditLog.action == exact for exact in dangerous_exact])

        stmt = select(func.count(AuditLog.id)).where(or_(*action_filters))

        if tenant_id:
            stmt = stmt.where(AuditLog.tenant_id == tenant_id)
        if start_time:
            stmt = stmt.where(AuditLog.timestamp >= start_time)
        if end_time:
            stmt = stmt.where(AuditLog.timestamp <= end_time)

        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def list_dangerous_actions(
        self,
        tenant_id: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> DangerousActionsResponse:
        """List dangerous actions for security review.

        Dangerous actions include deletes, revokes, suspensions, and disconnections
        that could affect user access or data integrity.

        Args:
            tenant_id: Optional tenant filter.
            start_time: Optional start time filter.
            end_time: Optional end time filter.
            limit: Maximum results to return.
            offset: Number of results to skip.

        Returns:
            Response with dangerous actions and count.
        """
        dangerous_patterns = ["%.deleted", "%.revoked", "%.suspended", "%.disconnected"]
        dangerous_exact = ["delete", "bulk_delete", "purge"]

        action_filters = [
            AuditLog.action.like(pattern) for pattern in dangerous_patterns
        ]
        action_filters.extend([AuditLog.action == exact for exact in dangerous_exact])

        stmt = (
            select(AuditLog)
            .where(or_(*action_filters))
            .order_by(desc(AuditLog.timestamp))
        )

        if tenant_id:
            stmt = stmt.where(AuditLog.tenant_id == tenant_id)
        if start_time:
            stmt = stmt.where(AuditLog.timestamp >= start_time)
        if end_time:
            stmt = stmt.where(AuditLog.timestamp <= end_time)

        # Get total count
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total_result = await self.session.execute(count_stmt)
        total = total_result.scalar() or 0

        # Apply pagination
        stmt = stmt.offset(offset).limit(limit)

        result = await self.session.execute(stmt)
        logs = result.scalars().all()

        return DangerousActionsResponse(
            items=[AuditLogResponse.model_validate(log) for log in logs],
            total=total,
            limit=limit,
            offset=offset,
            has_more=(offset + len(logs)) < total,
        )

    async def delete_old_logs(
        self,
        before: datetime,
        tenant_id: str | None = None,
    ) -> int:
        """Delete audit logs older than a specified date.

        Args:
            before: Delete logs before this date.
            tenant_id: Optional tenant filter.

        Returns:
            Number of deleted entries.
        """
        from sqlalchemy import delete

        stmt = delete(AuditLog).where(AuditLog.timestamp < before)
        if tenant_id:
            stmt = stmt.where(AuditLog.tenant_id == tenant_id)

        result = await self.session.execute(stmt)
        await self.session.commit()

        deleted_count = result.rowcount  # type: ignore[attr-defined]
        logger.info(
            "Deleted %s old audit logs",
            deleted_count,
            extra={"before": before.isoformat(), "tenant_id": tenant_id},
        )

        return deleted_count  # type: ignore


async def get_audit_service() -> AuditService:
    """Get an audit service instance.

    Returns:
        AuditService with a new database session.

    Example:
        service = await get_audit_service()
        await service.log(...)
    """
    async with get_async_session() as session:
        return AuditService(session)


def get_audit_service_with_session(session: AsyncSession) -> AuditService:
    """Get an audit service instance with an existing session.

    Args:
        session: Existing database session.

    Returns:
        AuditService using the provided session.
    """
    return AuditService(session)
